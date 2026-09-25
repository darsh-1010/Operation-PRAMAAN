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
import uuid as _uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

import requests
from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator

import anchor
import ledger
import store
from auth import authorize, caller_module, router as auth_router
from db import RiskResultDB
from ledger_routes import router as ledger_router
from schemas import (FlagCheckRequest, FlagCheckResponse, ResultResponse, SubmitScoreRequest,
                     SubmitScoreResponse)
from scoring import FORENSICS_UNAVAILABLE_REASON, decide, tamper_reasons_for

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("risk_engine")

SWEEP_INTERVAL_SECONDS = 30
OCR_CALLBACK_URL = os.environ.get("OCR_CALLBACK_URL", "").strip()

_db = RiskResultDB.get_instance()


def _persist(uuid: str, score, decision: str, reasons: list, evidence: list, timed_out: bool = False) -> None:
    """Durable copy of every finalized decision — normal, hard-fail reject, or timeout —
    alongside store.py's Redis one (see db.py for why both exist). The canonical JSON is what
    gets fingerprinted and later anchored on-chain by anchor.py; it holds no names, document
    numbers or images — only the decision and the SHA-256 of each uploaded file, so the
    encrypted evidence the modules stored can later be proven untouched (see LEDGER.md)."""
    record = {
        "v": 2,
        "result_id": str(_uuid.uuid4()),
        "uuid": uuid,
        "score": score,
        "decision": decision,
        "hard_fail": decision == "REJECTED",
        "timed_out": timed_out,
        "reasons": list(reasons),
        "evidence": sorted(set(evidence)),
        "finalized_at": datetime.now(timezone.utc).isoformat(),
    }
    canonical = ledger.canonical(record)
    _db.save_risk_result(record, canonical, ledger.leaf_hash(canonical).hex())


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
    missing = [k for k in ("flag_ocr", "flag_forensics", "ocr_score", "photo_score") if entry[k] is None]
    if entry["tamper_score"] is None and not entry["tamper_unavailable"]:
        missing.append("tamper_score")
    return missing


def _finalize(uuid: str, entry: dict, score, decision: str, reasons: list, timed_out: bool = False) -> None:
    """The one exit for every decision (normal, reject, timeout): result store, audit+ledger,
    pending cleanup, callback."""
    # Explainability: logged, persisted (see _persist), and returned via GET /result — but
    # NOT part of the {uuid, score, decision} payload pushed to OCR_CALLBACK_URL.
    logger.info("uuid=%s score=%s decision=%s", uuid, score, decision)
    for reason in reasons:
        logger.info("  - %s", reason)
    store.save_result(uuid, score, decision, timed_out=timed_out, reasons=reasons)
    _persist(uuid, score, decision, reasons, entry["evidence"], timed_out=timed_out)
    store.clear(uuid)
    _notify_ocr(uuid, score, decision)


def _try_finalize(uuid: str) -> Optional[dict]:
    """
    Checks whether this uuid is ready to be scored: both flags confirmed
    false, and all 3 scores in (forensics may instead have reported it could not assess the
    images — scoring.decide then caps the decision at MANUAL_REVIEW). Returns the final
    result dict if so, else None if we're still waiting on something.
    """
    entry = store.get(uuid)
    if _missing_pieces(entry) or entry["flag_ocr"] or entry["flag_forensics"]:
        return None

    tamper = None if entry["tamper_unavailable"] else entry["tamper_score"]
    final_score, decision = decide(entry["ocr_score"], tamper, entry["photo_score"], entry["review_required"])
    _finalize(uuid, entry, final_score, decision, entry["reasons"])
    return {"uuid": uuid, "score": final_score, "decision": decision}


def _reject(uuid: str) -> None:
    entry = store.get(uuid)
    _finalize(uuid, entry, 0, "REJECTED", entry["reasons"])


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

            missing = _missing_pieces(entry)
            if not missing:
                continue  # about to finalize normally, leave it alone

            logger.info("uuid=%s TIMEOUT after %.0fs - auto-escalating to MANUAL_REVIEW", uuid, age)
            # No numeric score is computable with pieces missing - score
            # is left as null so downstream can't mistake this for an
            # actual (e.g. 0/FAIL) result. Decision is what matters here.
            _finalize(uuid, entry, None, "MANUAL_REVIEW",
                      entry["reasons"] + [f"TIMEOUT_ESCALATION: missing={missing}"], timed_out=True)


@asynccontextmanager
async def lifespan(app: FastAPI):
    sweeper_task = asyncio.create_task(_timeout_sweeper())
    anchor_task = asyncio.create_task(anchor.run_forever(_db))
    yield
    sweeper_task.cancel()
    anchor_task.cancel()


app = FastAPI(title="Praman Risk Scoring Engine", lifespan=lifespan)
# Dev CORS: the frontend polls GET /result/{uuid} directly from the browser (see
# frontend/src/lib/riskEngine.ts). Restrict allow_origins to the real frontend origin before
# this ever leaves a local dev machine — same pattern as the other 3 services.
# POST is for /sessions only — the module-facing writes need a bearer token (auth.py).
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["GET", "POST"], allow_headers=["*"])

# Exposes /metrics (request count/latency/in-flight, per route+status) for Prometheus.
Instrumentator().instrument(app).expose(app)
app.include_router(ledger_router)
app.include_router(auth_router)


# ---------------------------------------------------------------------
# Stage 1: flags
# ---------------------------------------------------------------------

@app.post("/flag-check", response_model=FlagCheckResponse)
def flag_check(payload: FlagCheckRequest, caller: str = Depends(caller_module)) -> FlagCheckResponse:
    authorize(caller, "flag", payload.module, payload.uuid)
    logger.info("uuid=%s /flag-check received: module=%s flag=%s", payload.uuid, payload.module, payload.flag)

    # This uuid was already finalized (a prior reject, or a normal/timeout completion) and
    # its pending entry cleared — a late or duplicate call must not resurrect a fresh, never-
    # to-be-finalized phantom entry via store.get()'s auto-create. Just echo what's already decided.
    existing = store.get_result(payload.uuid)
    if existing is not None:
        return FlagCheckResponse(uuid=payload.uuid, status="DONE", score=existing["score"], decision=existing["decision"])

    store.add_evidence(payload.uuid, payload.evidence)
    if payload.flag:
        # One true flag is enough - reject now, don't wait for the other.
        # TODO: this is also where a "stop other modules" signal should
        # go out, once the other services expose an endpoint for it.
        store.update(payload.uuid, rejected=True)
        store.add_reasons(payload.uuid, payload.reasons or [f"{payload.module}_flag: TRUE"])
        _reject(payload.uuid)
        return FlagCheckResponse(uuid=payload.uuid, status="REJECTED", score=0, decision="REJECTED")

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

@app.post("/submit-score", response_model=SubmitScoreResponse)
def submit_score(payload: SubmitScoreRequest, caller: str = Depends(caller_module)) -> SubmitScoreResponse:
    authorize(caller, "score", payload.module, payload.uuid)
    body = getattr(payload, payload.module)
    if body is None:
        raise HTTPException(422, f"module '{payload.module}' requires a '{payload.module}' object")
    logger.info("uuid=%s /submit-score received: module=%s", payload.uuid, payload.module)

    # Same late/duplicate-arrival guard as /flag-check — see the comment there.
    existing = store.get_result(payload.uuid)
    if existing is not None:
        return SubmitScoreResponse(uuid=payload.uuid, status="DONE", score=existing["score"], decision=existing["decision"])

    store.add_evidence(payload.uuid, payload.evidence)
    if store.get(payload.uuid)["rejected"]:
        return SubmitScoreResponse(uuid=payload.uuid, status="REJECTED", score=0, decision="REJECTED")

    # Store the incoming score immediately - regardless of whether the
    # flags have cleared yet. A score that arrives early is never lost.
    # Reasons are stored alongside for explainability.
    if payload.module == "ocr":
        store.update(payload.uuid, ocr_score=body.score, review_required=body.review_required)
        store.add_reasons(payload.uuid, body.reasons)
    elif payload.module == "tamper":
        if body.score is None:
            store.update(payload.uuid, tamper_unavailable=True)
            store.add_reasons(payload.uuid, body.reasons + [FORENSICS_UNAVAILABLE_REASON])
        else:
            store.update(payload.uuid, tamper_score=body.score)
            store.add_reasons(payload.uuid, tamper_reasons_for(body.score))
    else:
        store.add_reasons(payload.uuid, body.reasons)
        if body.hard_fail:
            # Photo-match's own override - reject even if this arrives
            # before the flag stage has finished.
            store.update(payload.uuid, rejected=True)
            _reject(payload.uuid)
            return SubmitScoreResponse(uuid=payload.uuid, status="REJECTED", score=0, decision="REJECTED")
        store.update(payload.uuid, photo_score=body.score)

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

@app.get("/result/{uuid}", response_model=ResultResponse)
def get_result(uuid: str) -> ResultResponse:
    result = store.get_result(uuid)
    if result is None:
        raise HTTPException(status_code=404, detail="No finalized result yet for this uuid")
    return ResultResponse(**result)


@app.get("/health")
def health():
    return {"status": "ok"}
