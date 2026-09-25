"""Visual / Image Forensics — Module 2.

Implements POST /screen per ../../API_CONTRACT.md. Real AI-image detection, splice
forensics, and guilloché checking aren't built yet (see TODO below) — this validates
input per SECURITY.md and reports honestly that it assessed nothing: score null, which the
risk engine turns into "decision capped at MANUAL_REVIEW". (It used to report a perfect 100,
handing every forged document 40% of the final score for free.)
"""
import io
import json
import logging
import os
from typing import Optional

import httpx
from aiobreaker import CircuitBreakerError
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image
from prometheus_fastapi_instrumentator import Instrumentator
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from rate_limit import SCREEN_RATE_LIMIT, limiter
from risk_engine_breaker import RISK_ENGINE_BREAKER

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="visual-image-forensics")
# Dev CORS: the frontend calls this port directly from the browser. Restrict allow_origins
# to the real frontend origin before this ever leaves a local dev machine.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["POST"], allow_headers=["*"])

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

# Exposes /metrics (request count/latency/in-flight, per route+status) for Prometheus.
Instrumentator().instrument(app).expose(app)

MAX_IMAGE_BYTES = 15 * 1024 * 1024
RISK_ENGINE_URL = os.environ.get("RISK_ENGINE_URL", "http://localhost:8004").rstrip("/")
# Must equal risk-scoring-engine's RISK_TOKEN_FORENSICS.
RISK_ENGINE_TOKEN = os.environ.get("RISK_ENGINE_TOKEN", "").strip()
NOT_ASSESSED = "FORENSICS_NOT_IMPLEMENTED: tamper/AI-image/guilloche checks not built — no assessment made"


def validate_image(data: bytes, field: str) -> None:
    """SECURITY.md #1-2: re-check independently of the client, decode+verify rather than
    trust magic bytes alone — Image.verify() raises on anything Pillow can't actually parse
    as the image format it claims to be."""
    if not data:
        raise HTTPException(400, f"{field}: empty file")
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(400, f"{field}: exceeds {MAX_IMAGE_BYTES // (1024 * 1024)}MB limit")
    try:
        Image.open(io.BytesIO(data)).verify()
    except Exception:
        raise HTTPException(400, f"{field}: not a decodable image")


@RISK_ENGINE_BREAKER
async def _push_to_risk_engine(uuid: str, hard_fail: bool, tamper_score: Optional[float], reasons: list[str]) -> list[str]:
    """Returns the requests the risk engine refused (4xx). Only 5xx/network errors raise, so
    only they count towards the breaker — a flood of bad ids must not block real screenings."""
    calls = [("/flag-check", {"uuid": uuid, "module": "forensics", "flag": hard_fail, "reasons": reasons}),
             ("/submit-score", {"uuid": uuid, "module": "tamper", "tamper": {"score": tamper_score, "reasons": reasons}})]
    refused = []
    async with httpx.AsyncClient(timeout=5.0, headers={"Authorization": f"Bearer {RISK_ENGINE_TOKEN}"}) as client:
        for path, body in calls:
            resp = await client.post(RISK_ENGINE_URL + path, json=body)
            if resp.status_code >= 500:
                resp.raise_for_status()
            if resp.status_code >= 400:
                refused.append(f"{path} -> {resp.status_code} {resp.text[:200]}")
    return refused


async def _notify_risk_engine(uuid: str, hard_fail: bool, tamper_score: Optional[float], reasons: list[str]) -> None:
    """Push this module's flag + tamper score to risk-scoring-engine (see
    ../../services/risk-scoring-engine/README.md for the two-stage contract) — the "forensics"
    flag and the "tamper" score are the two pieces only this module ever sends. Best-effort:
    the risk engine being down must never break this service's own /screen response.
    Circuit-breaker-backed (see risk_engine_breaker.py) so a down risk-scoring-engine fails
    fast instead of costing a full httpx timeout on every single request."""
    if not RISK_ENGINE_TOKEN:
        logger.error("uuid=%s RISK_ENGINE_TOKEN not set — result NOT sent to risk-scoring-engine", uuid)
        return
    try:
        refused = await _push_to_risk_engine(uuid, hard_fail, tamper_score, reasons)
        for problem in refused:
            logger.error("uuid=%s risk-scoring-engine refused forensics result: %s", uuid, problem)
    except CircuitBreakerError:
        logger.warning("uuid=%s risk-scoring-engine circuit open, skipping push", uuid)
    except httpx.HTTPError as exc:
        logger.warning("uuid=%s risk-scoring-engine unreachable, skipping push: %s", uuid, exc)


@app.post("/screen")
@limiter.limit(SCREEN_RATE_LIMIT)
async def screen(
    request: Request,
    uuid: str = Form(...),
    documents_present: str = Form(...),
    passport: Optional[UploadFile] = File(None),
    visa: Optional[UploadFile] = File(None),
    nationalId: Optional[UploadFile] = File(None),
    drivingLicence: Optional[UploadFile] = File(None),
    permit: Optional[UploadFile] = File(None),
    voterId: Optional[UploadFile] = File(None),
    citizenship: Optional[UploadFile] = File(None),
    selfie: Optional[UploadFile] = File(None),
) -> dict:
    try:
        present: dict = json.loads(documents_present)
    except json.JSONDecodeError:
        raise HTTPException(400, "documents_present must be valid JSON")

    # selfie is excluded: it may be video, and this module only inspects document images.
    documents = {"passport": passport, "visa": visa, "nationalId": nationalId, "drivingLicence": drivingLicence,
                 "permit": permit, "voterId": voterId, "citizenship": citizenship}
    for key, file in documents.items():
        if present.get(key) and file is None:
            raise HTTPException(400, f"documents_present says '{key}' is present but no file was sent")
        if file is not None:
            validate_image(await file.read(), key)

    logger.info("uuid=%s /screen received: docs=%s", uuid, [k for k, v in present.items() if v and k != "selfie"])

    # TODO: real AI-generated-image detection, splice/tamper forensics, and guilloché/
    # background CNN check. Until then: score None = "not assessed" (API_CONTRACT.md), never a
    # made-up number. hard_fail stays False — we found nothing, because we looked at nothing.
    score, hard_fail, reason_codes = None, False, [NOT_ASSESSED]

    logger.info("uuid=%s /screen result: score=%s hard_fail=%s", uuid, score, hard_fail)
    await _notify_risk_engine(uuid, hard_fail, score, reason_codes)
    return {"score": score, "hard_fail": hard_fail, "reason_codes": reason_codes}
