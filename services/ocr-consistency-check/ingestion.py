"""Document Ingestion Module.

Handles upload and conversion of PDF and image files (JPEG, PNG, WEBP)
into high-resolution numpy image arrays for downstream OCR processing.
Calculates SHA-256 hash for document audit logging and deduplication.
"""

from __future__ import annotations
import hashlib
import io
import logging
from dataclasses import dataclass
from typing import List, Tuple

import numpy as np
from PIL import Image

logger = logging.getLogger("ingestion")

SUPPORTED_MIME_TYPES = {
    "image/jpeg": "JPEG",
    "image/jpg": "JPEG",
    "image/png": "PNG",
    "image/webp": "WEBP",
    "application/pdf": "PDF",
}


@dataclass
class IngestedDocument:
    """Represents an ingested document file ready for OCR."""
    images: List[np.ndarray]  # RGB numpy arrays
    sha256: str
    mime_type: str
    width_px: int
    height_px: int
    page_count: int


def calculate_sha256(data: bytes) -> str:
    """Compute SHA-256 hexadecimal hash from raw file bytes."""
    return hashlib.sha256(data).hexdigest()


def detect_mime_type(data: bytes, filename: str = "") -> str:
    """Detect MIME type from magic bytes with filename extension fallback."""
    if data.startswith(b"%PDF"):
        return "application/pdf"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"RIFF") and len(data) >= 12 and data[8:12] == b"WEBP":
        return "image/webp"

    lower_name = filename.lower()
    if lower_name.endswith(".pdf"):
        return "application/pdf"
    if lower_name.endswith((".jpg", ".jpeg")):
        return "image/jpeg"
    if lower_name.endswith(".png"):
        return "image/png"
    if lower_name.endswith(".webp"):
        return "image/webp"

    raise ValueError("Unsupported document format. Please upload PDF, JPG, PNG, or WEBP.")


def render_pdf_to_images(pdf_bytes: bytes, dpi: int = 200) -> List[np.ndarray]:
    """Render each page of a PDF into an RGB numpy array using pypdfium2."""
    try:
        import pypdfium2 as pdfium
    except ImportError as err:
        raise RuntimeError("pypdfium2 is required for PDF ingestion.") from err

    pdf = pdfium.PdfDocument(pdf_bytes)
    rendered_pages: List[np.ndarray] = []
    scale = dpi / 72.0  # 72 points per inch in PDF

    for page_idx in range(len(pdf)):
        page = pdf[page_idx]
        pil_image = page.render(scale=scale).to_pil()
        rgb_image = pil_image.convert("RGB")
        rendered_pages.append(np.array(rgb_image))

    if not rendered_pages:
        raise ValueError("PDF document contains no renderable pages.")
    return rendered_pages


def load_image_bytes(image_bytes: bytes) -> np.ndarray:
    """Decode raw image bytes to an RGB numpy array."""
    try:
        pil_image = Image.open(io.BytesIO(image_bytes))
        rgb_image = pil_image.convert("RGB")
        return np.array(rgb_image)
    except Exception as err:
        raise ValueError(f"Failed to decode image: {err}") from err


def ingest_file(file_bytes: bytes, filename: str = "") -> IngestedDocument:
    """Validate, hash, and ingest an uploaded document file into RGB image arrays."""
    if not file_bytes:
        raise ValueError("Uploaded file payload is empty.")

    mime_type = detect_mime_type(file_bytes, filename)
    file_hash = calculate_sha256(file_bytes)

    if mime_type == "application/pdf":
        images = render_pdf_to_images(file_bytes)
    else:
        images = [load_image_bytes(file_bytes)]

    first_image = images[0]
    height, width = first_image.shape[0], first_image.shape[1]

    logger.info(
        "Ingested '%s' (%s, sha256=%s, pages=%d, %dx%d).",
        filename or "<unnamed>", mime_type, file_hash[:12], len(images), width, height,
    )

    return IngestedDocument(
        images=images,
        sha256=file_hash,
        mime_type=mime_type,
        width_px=width,
        height_px=height,
        page_count=len(images),
    )

