"""Visual / Image Forensics — Module 2.

Implements POST /screen per ../../API_CONTRACT.md. Real AI-image detection, splice
forensics, and guilloché checking aren't built yet (see TODO below) — this validates
input per SECURITY.md and returns a stub result so the pipeline is wired end to end.
"""
import io
import json
from typing import Optional

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from PIL import Image

app = FastAPI(title="visual-image-forensics")
# Dev CORS: the frontend calls this port directly from the browser. Restrict allow_origins
# to the real frontend origin before this ever leaves a local dev machine.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["POST"], allow_headers=["*"])

MAX_IMAGE_BYTES = 15 * 1024 * 1024


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

    # TODO: real AI-generated-image detection, splice/tamper forensics, and guilloché/
    # background CNN check. Stub result below keeps the contract honest (score/hard_fail/
    # reason_codes) without pretending to have run checks that don't exist yet.
    return {"score": 88, "hard_fail": False, "reason_codes": ["stub: real forensics checks not implemented yet"]}
