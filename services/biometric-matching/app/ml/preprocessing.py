"""Face preprocessing — detection, alignment, and quality estimation.

This module handles everything *before* embedding generation:

    image → face detection → landmarks → alignment → quality assessment

The output is a FaceDetectionResult containing the aligned face crop (ready for the
encoder) and quality metrics.

Current implementation: RetinaFace via the `deepface` library.
This is behind a function-level abstraction so the detector can be swapped independently
of the rest of Module 3.
"""
from __future__ import annotations

import logging
from typing import Optional

import cv2
import numpy as np

from app.domain.models import BoundingBox, FaceDetectionResult, QualityMetrics

logger = logging.getLogger(__name__)

def detect_and_align(
    image_rgb: np.ndarray,
    *,
    model: str = "retinaface",
    check_liveness: bool = False,
) -> FaceDetectionResult:
    """Detect, align, and quality-check the primary face in *image_rgb*.

    Parameters
    ----------
    image_rgb : np.ndarray
        Input image as H×W×3 RGB uint8.
    model : str
        ``"retinaface"`` or other deepface backends.
    check_liveness : bool
        If True, runs anti-spoofing model and populates liveness_score.

    Returns
    -------
    FaceDetectionResult
        Contains the aligned face crop, bounding box, and quality metrics.
        If no face is detected, ``found=False`` and ``aligned_face=None``.
    """
    from deepface import DeepFace  # type: ignore[import-untyped]

    if image_rgb.ndim != 3 or image_rgb.shape[2] != 3:
        logger.warning("Expected H×W×3 RGB image, got shape %s", image_rgb.shape)
        return FaceDetectionResult(found=False)

    h, w = image_rgb.shape[:2]

    # DeepFace expects BGR for numpy array inputs
    image_bgr = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2BGR)

    try:
        # extract_faces returns a list of dictionaries
        faces = DeepFace.extract_faces(
            img_path=image_bgr,
            detector_backend=model,
            align=True,
            enforce_detection=True,
            anti_spoofing=check_liveness
        )
    except ValueError:
        # DeepFace raises ValueError if enforce_detection=True and no face is found
        return FaceDetectionResult(found=False)
    except Exception as e:
        logger.warning(f"Face extraction failed: {e}")
        return FaceDetectionResult(found=False)

    if not faces:
        return FaceDetectionResult(found=False)

    face_count = len(faces)

    # Use the largest face when multiple are found (most likely the primary subject).
    def _area(f: dict) -> int:
        return f["facial_area"]["w"] * f["facial_area"]["h"]

    faces_sorted = sorted(faces, key=_area, reverse=True)
    best_face = faces_sorted[0]
    area = best_face["facial_area"]

    box = BoundingBox(
        top=area["y"],
        bottom=area["y"] + area["h"],
        left=area["x"],
        right=area["x"] + area["w"]
    )

    # DeepFace returns the aligned face as RGB float64 array in [0, 1] usually.
    # Convert back to uint8 [0, 255] to keep our abstraction consistent.
    aligned = best_face["face"]
    if aligned.dtype in (np.float32, np.float64):
        aligned = (aligned * 255).astype(np.uint8)

    # --- Quality ---
    # Crop the original grayscale face region for sharpness estimation
    gray = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2GRAY)
    face_gray = gray[max(0, box.top):min(h, box.bottom), max(0, box.left):min(w, box.right)]
    
    sharpness = 0.0
    if face_gray.size > 0:
        variance = cv2.Laplacian(face_gray, cv2.CV_64F).var()
        sharpness = float(min(variance / 500.0, 1.0))
        
    face_size_ratio = min(box.area / (h * w), 1.0) if (h * w) > 0 else 0.0

    quality = QualityMetrics(
        detection_confidence=float(best_face.get("confidence", 1.0)),
        sharpness=sharpness,
        face_size_ratio=face_size_ratio,
    )

    liveness_score = float(best_face["antispoof_score"]) if "antispoof_score" in best_face else None
    is_real = bool(best_face["is_real"]) if "is_real" in best_face else None

    return FaceDetectionResult(
        found=True,
        face_count=face_count,
        box=box,
        quality=quality,
        aligned_face=aligned,
        liveness_score=liveness_score,
        is_real=is_real
    )


def image_bytes_to_rgb(data: bytes) -> Optional[np.ndarray]:
    """Decode raw image bytes to an H×W×3 RGB numpy array.

    Returns None if the data cannot be decoded as an image.
    """
    arr = np.frombuffer(data, dtype=np.uint8)
    bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if bgr is None:
        return None
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
