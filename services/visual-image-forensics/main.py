"""Visual / Image Forensics — Module 2.

Implements POST /screen per ../../API_CONTRACT.md. Real AI-image detection, splice
forensics, and guilloché checking aren't built yet (see TODO below) — this validates
input per SECURITY.md and returns a stub result so the pipeline is wired end to end.
"""
import io
import json
import logging
import os
from typing import Optional

import httpx
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger(__name__)

app = FastAPI(title="visual-image-forensics")
# Dev CORS: the frontend calls this port directly from the browser. Restrict allow_origins
# to the real frontend origin before this ever leaves a local dev machine.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["POST"], allow_headers=["*"])

MAX_IMAGE_BYTES = 15 * 1024 * 1024
RISK_ENGINE_URL = os.environ.get("RISK_ENGINE_URL", "http://localhost:8004").rstrip("/")


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


async def _notify_risk_engine(uuid: str, hard_fail: bool, tamper_score: float, reasons: list[str]) -> None:
    """Push this module's flag + tamper score to risk-scoring-engine (see
    ../../services/risk-scoring-engine/README.md for the two-stage contract) — the "forensics"
    flag and the "tamper" score are the two pieces only this module ever sends. Best-effort:
    the risk engine being down must never break this service's own /screen response."""
    async with httpx.AsyncClient(timeout=5.0) as client:
        try:
            await client.post(
                f"{RISK_ENGINE_URL}/flag-check",
                json={"uuid": uuid, "module": "forensics", "flag": hard_fail, "reasons": reasons},
            )
            await client.post(
                f"{RISK_ENGINE_URL}/submit-score",
                json={"uuid": uuid, "module": "tamper", "tamper": {"score": tamper_score}},
            )
            logger.info("uuid=%s pushed to risk-scoring-engine (flag=%s, tamper_score=%s)", uuid, hard_fail, tamper_score)
        except httpx.HTTPError as exc:
            logger.warning("uuid=%s risk-scoring-engine unreachable, skipping push: %s", uuid, exc)


@app.post("/screen")
async def screen(
    uuid: str = Form(...),
    documents_present: str = Form(...),
    passport: Optional[UploadFile] = File(None),
    visa: Optional[UploadFile] = File(None),
    nationalId: Optional[UploadFile] = File(None),
    drivingLicence: Optional[UploadFile] = File(None),
    permit: Optional[UploadFile] = File(None),
    selfie: Optional[UploadFile] = File(None),
) -> dict:
    try:
        present: dict = json.loads(documents_present)
    except json.JSONDecodeError:
        raise HTTPException(400, "documents_present must be valid JSON")

    # selfie is excluded: it may be video, and this module only inspects document images.
    documents = {"passport": passport, "visa": visa, "nationalId": nationalId, "drivingLicence": drivingLicence, "permit": permit}
    for key, file in documents.items():
        if present.get(key) and file is None:
            raise HTTPException(400, f"documents_present says '{key}' is present but no file was sent")
        if file is not None:
            validate_image(await file.read(), key)

    logger.info("uuid=%s /screen received: docs=%s", uuid, [k for k, v in present.items() if v and k != "selfie"])

    # TODO: real AI-generated-image detection, splice/tamper forensics, and guilloché/
    # background CNN check. Stub result below keeps the contract honest (score/hard_fail/
    # reason_codes) without pretending to have run checks that don't exist yet. The score is
    # pinned to 100 (one of the risk engine's 4 recognized tamper values — see scoring.py's
    # TAMPER_REASON_MAP) rather than an arbitrary number, now that this pushes upstream too.
    score, hard_fail, reason_codes = 100, False, ["stub: real forensics checks not implemented yet"]

    logger.info("uuid=%s /screen result: score=%s hard_fail=%s", uuid, score, hard_fail)
    await _notify_risk_engine(uuid, hard_fail, score, reason_codes)
    return {"score": score, "hard_fail": hard_fail, "reason_codes": reason_codes}
