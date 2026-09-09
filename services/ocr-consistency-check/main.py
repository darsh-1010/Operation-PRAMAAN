"""OCR, Extraction & Watchlist — Module 1.

Implements POST /screen per ../../API_CONTRACT.md. Real MRZ/OCR/watchlist logic isn't
built yet (see TODO below) — this validates input per SECURITY.md and returns a stub
result so the frontend <-> module pipeline is fully wired end to end.
"""
import json
from typing import Optional

import cv2
import numpy as np
from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="ocr-consistency-check")
# Dev CORS: the frontend calls this port directly from the browser. Restrict allow_origins
# to the real frontend origin before this ever leaves a local dev machine.
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["POST"], allow_headers=["*"])

MAX_IMAGE_BYTES = 15 * 1024 * 1024


def validate_image(data: bytes, field: str) -> None:
    """SECURITY.md #1-2: re-check independently of the client, decode rather than trust
    magic bytes alone. cv2.imdecode returns None for anything it can't actually decode as
    an image, which is what catches a renamed non-image file that slipped past a naive check."""
    if not data:
        raise HTTPException(400, f"{field}: empty file")
    if len(data) > MAX_IMAGE_BYTES:
        raise HTTPException(400, f"{field}: exceeds {MAX_IMAGE_BYTES // (1024 * 1024)}MB limit")
    arr = np.frombuffer(data, dtype=np.uint8)
    if cv2.imdecode(arr, cv2.IMREAD_UNCHANGED) is None:
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

    # selfie is excluded: it may be video, and this module only reads documents.
    documents = {"passport": passport, "visa": visa, "nationalId": nationalId, "drivingLicence": drivingLicence, "permit": permit}
    for key, file in documents.items():
        if present.get(key) and file is None:
            raise HTTPException(400, f"documents_present says '{key}' is present but no file was sent")
        if file is not None:
            validate_image(await file.read(), key)

    # TODO: real MRZ OCR, barcode decode, checksum/field-format validation, and fuzzy
    # watchlist matching. Stub result below keeps the contract honest (score/hard_fail/
    # reason_codes) without pretending to have run checks that don't exist yet.
    return {"score": 85, "hard_fail": False, "reason_codes": ["stub: real OCR/watchlist checks not implemented yet"]}
