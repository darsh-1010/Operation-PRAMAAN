"""
Praman - Risk Scoring Engine service.

Two-stage flow, because every module posts to us independently over
separate HTTP calls, in whatever order:

  Stage 1 - flags (fast, arrive first)
    OCR and visual-forensics (which also does the AI-generated-doc check
    as part of its own hard_fail) each POST /flag-check as soon as they
    know their flag. The moment EITHER flag is true, we reject right
    away - we don't wait for the other one.

  Stage 2 - scores (OCR, tampering, photo-match)
    Each POSTs /submit-score whenever its score is ready. Scores are
    stored the moment they arrive, REGARDLESS of whether the flags have
    cleared yet - a score is never dropped just because it showed up
    early. The final weighted-sum decision only fires once BOTH flags
    are confirmed false AND all 3 scores are in - whichever of those two
    conditions finishes last is what triggers it, so finalization is
    checked from both endpoints.

  Timeout safety net
    If a uuid sits incomplete for longer than RISK_ENGINE_TIMEOUT_SECONDS
    (default 300s / 5 min - one module crashed, or just never called
    back), a background sweeper auto-escalates it to MANUAL_REVIEW
    instead of leaving it stuck in memory with no decision ever reached.
    Every finalized result (normal or timed-out) is retrievable via
    GET /result/{uuid} even after the pending entry is cleared, since a
    crashed module obviously won't be the one to come collect it.

Run locally:
    uvicorn main:app --reload --port 8004
"""

import asyncio
import logging
import os
import time
from contextlib import asynccontextmanager
from typing import List, Literal, Optional

import requests
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field

import store
from scoring import band_for, tamper_reasons_for, weighted_score

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("risk_engine")

SWEEP_INTERVAL_SECONDS = 30
OCR_CALLBACK_URL = os.environ.get("OCR_CALLBACK_URL", "").strip()


def _notify_ocr(uuid: str, score, decision: str) -> None:
    """
    Pushes the final decision to OCR's callback endpoint, if one has been
    configured. Until OCR_CALLBACK_URL is set, this is a no-op - the
    result still gets saved via store.save_result() either way, so
    GET /result/{uuid} always works regardless of whether the push does.
    """
    if not OCR_CALLBACK_URL:
        return
    try:
        requests.post(
            OCR_CALLBACK_URL,
            json={"uuid": uuid, "score": score, "decision": decision},
            timeout=5,
        )
    except requests.RequestException as exc:
        # Don't let a failed push break anything - the result is already
        # saved and pollable via /result/{uuid} regardless.
        logger.warning("uuid=%s OCR callback failed: %s", uuid, exc)


def _missing_pieces(entry: dict) -> list:
    missing = []
    if entry["flag_ocr"] is None:
        missing.append("flag_ocr")
    if entry["flag_forensics"] is None:
        missing.append("flag_forensics")
    if entry["ocr_score"] is None:
        missing.append("ocr_score")
    if entry["tamper_score"] is None:
        missing.append("tamper_score")
    if entry["photo_score"] is None:
        missing.append("photo_score")
    return missing


def _try_finalize(uuid: str) -> Optional[dict]:
    """
    Checks whether this uuid is ready to be scored: both flags confirmed
    false, and all 3 scores in. Returns the final result dict if so
    (saves it to the results store and clears the pending entry), else
    None if we're still waiting on something.
    """
    entry = store.get(uuid)

    flags_clear = entry["flag_ocr"] is False and entry["flag_forensics"] is False
    scores_complete = None not in (
        entry["ocr_score"],
        entry["tamper_score"],
        entry["photo_score"],
    )

    if not (flags_clear and scores_complete):
        return None

    final_score = weighted_score(
        entry["ocr_score"], entry["tamper_score"], entry["photo_score"]
    )
    decision = band_for(final_score)

    # Explainability: printed/logged for audit purposes only - these
    # reasons are NOT part of the payload sent back for the DB update.
    logger.info("uuid=%s score=%s decision=%s", uuid, final_score, decision)
    for reason in entry["reasons"]:
        logger.info("  - %s", reason)

    store.save_result(uuid, final_score, decision)
    store.clear(uuid)
    _notify_ocr(uuid, final_score, decision)
    return {"uuid": uuid, "score": final_score, "decision": decision}


async def _timeout_sweeper():
    """Runs forever in the background - escalates anything that's been
    sitting incomplete for longer than store.TIMEOUT_SECONDS."""
    while True:
        await asyncio.sleep(SWEEP_INTERVAL_SECONDS)
        now = time.time()
        for uuid, entry in store.all_entries().items():
            if entry["rejected"]:
                continue  # already being handled by the reject path
            age = now - entry["created_at"]
            if age <= store.TIMEOUT_SECONDS:
                continue

            flags_clear = entry["flag_ocr"] is False and entry["flag_forensics"] is False
            scores_complete = None not in (
                entry["ocr_score"], entry["tamper_score"], entry["photo_score"]
            )
            if flags_clear and scores_complete:
                continue  # about to finalize normally, leave it alone

            missing = _missing_pieces(entry)
            logger.info("uuid=%s TIMEOUT after %.0fs - auto-escalating to MANUAL_REVIEW", uuid, age)
            logger.info("  - TIMEOUT_ESCALATION: missing=%s", missing)
            for reason in entry["reasons"]:
                logger.info("  - %s", reason)

            # No numeric score is computable with pieces missing - score
            # is left as null so downstream can't mistake this for an
            # actual (e.g. 0/FAIL) result. Decision is what matters here.
            store.save_result(uuid, None, "MANUAL_REVIEW", timed_out=True)
            store.clear(uuid)
            _notify_ocr(uuid, None, "MANUAL_REVIEW")


@asynccontextmanager
async def lifespan(app: FastAPI):
    sweeper_task = asyncio.create_task(_timeout_sweeper())
    yield
    sweeper_task.cancel()


app = FastAPI(title="Praman Risk Scoring Engine", lifespan=lifespan)


# ---------------------------------------------------------------------
# Stage 1: flags
# ---------------------------------------------------------------------

class FlagCheckRequest(BaseModel):
    uuid: str
    module: Literal["ocr", "forensics"]
    flag: bool


class FlagCheckResponse(BaseModel):
    uuid: str
    status: str  # "REJECTED" | "WAITING_ON_OTHER_FLAG" | "WAITING_ON_SCORES" | "DONE"
    score: Optional[float] = None
    decision: Optional[str] = None


@app.post("/flag-check", response_model=FlagCheckResponse)
def flag_check(payload: FlagCheckRequest) -> FlagCheckResponse:
    logger.info("uuid=%s /flag-check received: module=%s flag=%s", payload.uuid, payload.module, payload.flag)
    if payload.flag:
        # One true flag is enough - reject now, don't wait for the other.
        # TODO: this is also where a "stop other modules" signal should
        # go out, once the other services expose an endpoint for it.
        store.update(payload.uuid, rejected=True)
        reason = f"{payload.module}_flag: TRUE"
        logger.info("uuid=%s score=0 decision=REJECTED", payload.uuid)
        logger.info("  - %s", reason)
        store.save_result(payload.uuid, 0, "REJECTED")
        store.clear(payload.uuid)
        _notify_ocr(payload.uuid, 0, "REJECTED")
        return FlagCheckResponse(
            uuid=payload.uuid, status="REJECTED", score=0, decision="REJECTED"
        )

    field = "flag_ocr" if payload.module == "ocr" else "flag_forensics"
    entry = store.update(payload.uuid, **{field: False})

    if not (entry["flag_ocr"] is False and entry["flag_forensics"] is False):
        return FlagCheckResponse(uuid=payload.uuid, status="WAITING_ON_OTHER_FLAG")

    # Both flags are clear now - scores may already be sitting there
    # waiting (they get stored as soon as they arrive, regardless of
    # flag state), so check if we can finalize immediately.
    result = _try_finalize(payload.uuid)
    if result is not None:
        return FlagCheckResponse(status="DONE", **result)
    return FlagCheckResponse(uuid=payload.uuid, status="WAITING_ON_SCORES")


# ---------------------------------------------------------------------
# Stage 2: scores
# ---------------------------------------------------------------------

class OCRScorePayload(BaseModel):
    score: float
    reasons: List[str] = Field(default_factory=list)


class TamperScorePayload(BaseModel):
    score: float  # expected: 100, 60, 40, or 0


class PhotoScorePayload(BaseModel):
    score: float
    hard_fail: bool
    reasons: List[str] = Field(default_factory=list)


class SubmitScoreRequest(BaseModel):
    uuid: str
    module: Literal["ocr", "tamper", "photo"]
    ocr: Optional[OCRScorePayload] = None
    tamper: Optional[TamperScorePayload] = None
    photo: Optional[PhotoScorePayload] = None


class SubmitScoreResponse(BaseModel):
    uuid: str
    status: str  # "REJECTED" | "STORED_WAITING_ON_FLAGS" | "WAITING_ON_OTHER_SCORES" | "DONE"
    score: Optional[float] = None
    decision: Optional[str] = None


@app.post("/submit-score", response_model=SubmitScoreResponse)
def submit_score(payload: SubmitScoreRequest) -> SubmitScoreResponse:
    logger.info("uuid=%s /submit-score received: module=%s", payload.uuid, payload.module)
    entry = store.get(payload.uuid)

    if entry["rejected"]:
        return SubmitScoreResponse(
            uuid=payload.uuid, status="REJECTED", score=0, decision="REJECTED"
        )

    # Store the incoming score immediately - regardless of whether the
    # flags have cleared yet. A score that arrives early is never lost.
    # Reasons are stored alongside for explainability (printed at the
    # end) but never sent back in the DB-update payload.
    if payload.module == "ocr" and payload.ocr is not None:
        store.update(payload.uuid, ocr_score=payload.ocr.score)
        store.add_reasons(payload.uuid, payload.ocr.reasons)
    elif payload.module == "tamper" and payload.tamper is not None:
        store.update(payload.uuid, tamper_score=payload.tamper.score)
        store.add_reasons(payload.uuid, tamper_reasons_for(payload.tamper.score))
    elif payload.module == "photo" and payload.photo is not None:
        if payload.photo.hard_fail:
            # Photo-match's own override - reject even if this arrives
            # before the flag stage has finished.
            store.update(payload.uuid, rejected=True)
            store.add_reasons(payload.uuid, payload.photo.reasons)
            entry = store.get(payload.uuid)
            logger.info("uuid=%s score=0 decision=REJECTED", payload.uuid)
            for reason in entry["reasons"]:
                logger.info("  - %s", reason)
            store.save_result(payload.uuid, 0, "REJECTED")
            store.clear(payload.uuid)
            _notify_ocr(payload.uuid, 0, "REJECTED")
            return SubmitScoreResponse(
                uuid=payload.uuid, status="REJECTED", score=0, decision="REJECTED"
            )
        store.update(payload.uuid, photo_score=payload.photo.score)
        store.add_reasons(payload.uuid, payload.photo.reasons)

    result = _try_finalize(payload.uuid)
    if result is not None:
        return SubmitScoreResponse(status="DONE", **result)

    entry = store.get(payload.uuid)
    flags_clear = entry["flag_ocr"] is False and entry["flag_forensics"] is False
    status = "WAITING_ON_OTHER_SCORES" if flags_clear else "STORED_WAITING_ON_FLAGS"
    return SubmitScoreResponse(uuid=payload.uuid, status=status)


# ---------------------------------------------------------------------
# Result lookup (works for normal completion, reject, AND timeout)
# ---------------------------------------------------------------------

class ResultResponse(BaseModel):
    uuid: str
    score: Optional[float]
    decision: str
    timed_out: bool


@app.get("/result/{uuid}", response_model=ResultResponse)
def get_result(uuid: str) -> ResultResponse:
    result = store.get_result(uuid)
    if result is None:
        raise HTTPException(status_code=404, detail="No finalized result yet for this uuid")
    return ResultResponse(**result)


@app.get("/health")
def health():
    return {"status": "ok"}
