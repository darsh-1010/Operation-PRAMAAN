"""Visual / Image Forensics — Module 2.

Implements POST /screen per ../../API_CONTRACT.md. Three independent voters each assess the
same document images and report their own score — never as input features to one another
(see app/fusion.py for why, and app/voters.py for the shared shape). Two of the three
(reconstruction, tamper_model) aren't built yet and report honestly that they assessed
nothing: score null, never a made-up number. (This module used to report a flat 100 when it
hadn't assessed anything at all, handing every forged document 40% of the final score for
free — see app/fusion.py's docstring for how the fused result avoids repeating that.)
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

from app import noise_residual, reconstruction, tamper_model
from app.fusion import fuse, reduce_per_image
from app.voters import VoterResult
from rate_limit import SCREEN_RATE_LIMIT, limiter
from risk_engine_breaker import RISK_ENGINE_BREAKER

VOTERS = [noise_residual, reconstruction, tamper_model]

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
    doc_data: dict[str, bytes] = {}
    for key, file in documents.items():
        if present.get(key) and file is None:
            raise HTTPException(400, f"documents_present says '{key}' is present but no file was sent")
        if file is not None:
            data = await file.read()
            validate_image(data, key)
            doc_data[key] = data

    logger.info("uuid=%s /screen received: docs=%s", uuid, list(doc_data.keys()))

    # Each voter assesses every present document image independently, worst-image-wins per
    # voter (app/fusion.py's reduce_per_image), then the voters themselves are fused.
    voter_results: list[VoterResult] = [
        reduce_per_image(voter.VOTER_NAME, [voter.assess(data, label) for label, data in doc_data.items()])
        for voter in VOTERS
    ] if doc_data else []

    fused = fuse(voter_results)
    score, hard_fail, reason_codes = fused.score, fused.hard_fail, fused.reason_codes

    logger.info("uuid=%s /screen result: score=%s hard_fail=%s", uuid, score, hard_fail)
    await _notify_risk_engine(uuid, hard_fail, score, reason_codes)
    return {"score": score, "hard_fail": hard_fail, "reason_codes": reason_codes}
