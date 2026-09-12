"""Biometric Matching — Module 3.

Implements POST /screen per ../../API_CONTRACT.md. Real liveness detection and face
matching aren't built yet (see TODO below) — this validates input per SECURITY.md and
returns a stub result so the pipeline is wired end to end.
"""
import io
import json
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image

app = FastAPI(title="biometric-matching")
# Dev CORS: the frontend calls this port directly from the browser. Restrict allow_origins
# to the real frontend origin before this ever leaves a local dev machine.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["POST"], allow_headers=["*"])

MAX_IMAGE_BYTES = 15 * 1024 * 1024
MAX_VIDEO_BYTES = 50 * 1024 * 1024


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


def validate_selfie(data: bytes) -> None:
    """The selfie may be an image or a short video. Pillow can only decode the image case,
    so a video is accepted on size alone here — real video validation (a decodable container,
    duration/frame checks) belongs to the eventual liveness-detection implementation, not this
    stub's job of proving the pipeline is wired."""
    if not data:
        raise HTTPException(400, "selfie: empty file")
    if len(data) > MAX_VIDEO_BYTES:
        raise HTTPException(400, f"selfie: exceeds {MAX_VIDEO_BYTES // (1024 * 1024)}MB limit")
    try:
        Image.open(io.BytesIO(data)).verify()
    except Exception:
        pass  # not a still image — assume video, real check comes with real liveness detection


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

    documents = {"passport": passport, "visa": visa, "nationalId": nationalId, "drivingLicence": drivingLicence, "permit": permit}
    for key, file in documents.items():
        if present.get(key) and file is None:
            raise HTTPException(400, f"documents_present says '{key}' is present but no file was sent")
        if file is not None:
            validate_image(await file.read(), key)  # needed for doc-to-selfie face matching

    if present.get("selfie") and selfie is None:
        raise HTTPException(400, "documents_present says 'selfie' is present but no file was sent")
    if selfie is not None:
        validate_selfie(await selfie.read())

    # TODO: real liveness detection, doc-to-selfie face matching, and cross-document face
    # consistency. Stub result below keeps the contract honest (score/hard_fail/reason_codes)
    # without pretending to have run checks that don't exist yet.
    return {"score": 90, "hard_fail": False, "reason_codes": ["stub: real liveness/face-match checks not implemented yet"]}
