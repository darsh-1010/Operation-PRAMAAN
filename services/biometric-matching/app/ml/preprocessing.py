"""Face preprocessing — detection, alignment, and quality estimation.

This module handles everything *before* embedding generation:

    image → face detection → landmarks → alignment → quality assessment

The output is a FaceDetectionResult containing the aligned face crop (ready for the
encoder) and quality metrics.

Current implementation: dlib via the `face_recognition` library.
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

# Target size for aligned face crops fed to the embedding model.
# dlib's face_recognition model expects 150×150, but we use a slightly larger crop
# and let the encoder handle final resizing — this preserves more information for
# quality assessment.
ALIGNED_FACE_SIZE = (160, 160)


def _estimate_sharpness(gray: np.ndarray) -> float:
    """Laplacian-variance blur estimate.  Higher = sharper.

    Returns a 0..1 score by clamping the raw variance into a practical range.
    The mapping is heuristic, not calibrated.
    """
    variance = cv2.Laplacian(gray, cv2.CV_64F).var()
    # Typical range: <50 = very blurry, >500 = sharp.  Clamp to 0..1.
    return float(min(variance / 500.0, 1.0))


def _face_size_ratio(box: BoundingBox, image_height: int, image_width: int) -> float:
    """Fraction of the image area occupied by the face bounding box."""
    image_area = image_height * image_width
    if image_area == 0:
        return 0.0
    return min(box.area / image_area, 1.0)


def detect_and_align(
    image_rgb: np.ndarray,
    *,
    model: str = "hog",
) -> FaceDetectionResult:
    """Detect, align, and quality-check the primary face in *image_rgb*.

    Parameters
    ----------
    image_rgb : np.ndarray
        Input image as H×W×3 RGB uint8 (the format returned by ``face_recognition.load_image_file``
        and by ``cv2.cvtColor(..., cv2.COLOR_BGR2RGB)``).
    model : str
        ``"hog"`` (fast, CPU) or ``"cnn"`` (slower, GPU-capable).  Passed through to
        ``face_recognition.face_locations``.

    Returns
    -------
    FaceDetectionResult
        Contains the aligned face crop, bounding box, and quality metrics.
        If no face is detected, ``found=False`` and ``aligned_face=None``.
    """
    # Import here so the rest of the codebase can be tested without face_recognition
    # installed (e.g. the existing test_main.py stub tests).
    import face_recognition  # type: ignore[import-untyped]

    if image_rgb.ndim != 3 or image_rgb.shape[2] != 3:
        logger.warning("Expected H×W×3 RGB image, got shape %s", image_rgb.shape)
        return FaceDetectionResult(found=False)

    h, w = image_rgb.shape[:2]

    # --- Detection ---
    locations = face_recognition.face_locations(image_rgb, model=model)
    face_count = len(locations)

    if face_count == 0:
        return FaceDetectionResult(found=False, face_count=0)

    # Use the largest face when multiple are found (most likely the primary subject).
    def _area(loc: tuple[int, int, int, int]) -> int:
        top, right, bottom, left = loc
        return (bottom - top) * (right - left)

    locations_sorted = sorted(locations, key=_area, reverse=True)
    top, right, bottom, left = locations_sorted[0]
    box = BoundingBox(top=top, right=right, bottom=bottom, left=left)

    # --- Landmarks (for alignment) ---
    landmarks_list = face_recognition.face_landmarks(image_rgb, [locations_sorted[0]])
    aligned = _align_face(image_rgb, landmarks_list[0] if landmarks_list else None, box)

    # --- Quality ---
    gray = cv2.cvtColor(image_rgb, cv2.COLOR_RGB2GRAY)
    # Crop the face region for sharpness estimation
    face_gray = gray[max(0, top):min(h, bottom), max(0, left):min(w, right)]
    sharpness = _estimate_sharpness(face_gray) if face_gray.size > 0 else 0.0

    quality = QualityMetrics(
        detection_confidence=1.0,  # face_recognition doesn't expose a confidence score for HOG
        sharpness=sharpness,
        face_size_ratio=_face_size_ratio(box, h, w),
    )

    return FaceDetectionResult(
        found=True,
        face_count=face_count,
        box=box,
        quality=quality,
        aligned_face=aligned,
    )


def _align_face(
    image_rgb: np.ndarray,
    landmarks: Optional[dict[str, list[tuple[int, int]]]],
    box: BoundingBox,
) -> np.ndarray:
    """Align a face crop using eye landmarks (similarity transform).

    If landmarks are unavailable, falls back to a simple crop + resize.
    """
    h, w = image_rgb.shape[:2]

    if landmarks and "left_eye" in landmarks and "right_eye" in landmarks:
        left_eye = np.mean(landmarks["left_eye"], axis=0)
        right_eye = np.mean(landmarks["right_eye"], axis=0)

        # Angle between eyes
        dy = right_eye[1] - left_eye[1]
        dx = right_eye[0] - left_eye[0]
        angle = float(np.degrees(np.arctan2(dy, dx)))

        # Center of the face
        cx = (box.left + box.right) // 2
        cy = (box.top + box.bottom) // 2

        # Rotation matrix around face center
        M = cv2.getRotationMatrix2D((float(cx), float(cy)), angle, 1.0)
        rotated = cv2.warpAffine(image_rgb, M, (w, h), flags=cv2.INTER_LINEAR)

        # Crop aligned face with a small margin
        margin = int(max(box.width, box.height) * 0.15)
        t = max(0, box.top - margin)
        b = min(h, box.bottom + margin)
        l = max(0, box.left - margin)
        r = min(w, box.right + margin)
        face_crop = rotated[t:b, l:r]
    else:
        # Fallback: simple crop without rotation
        margin = int(max(box.width, box.height) * 0.15)
        t = max(0, box.top - margin)
        b = min(h, box.bottom + margin)
        l = max(0, box.left - margin)
        r = min(w, box.right + margin)
        face_crop = image_rgb[t:b, l:r]

    if face_crop.size == 0:
        # Degenerate bounding box — return a black placeholder
        return np.zeros((*ALIGNED_FACE_SIZE, 3), dtype=np.uint8)

    aligned = cv2.resize(face_crop, ALIGNED_FACE_SIZE, interpolation=cv2.INTER_LINEAR)
    return aligned


def image_bytes_to_rgb(data: bytes) -> Optional[np.ndarray]:
    """Decode raw image bytes to an H×W×3 RGB numpy array.

    Returns None if the data cannot be decoded as an image.
    """
    arr = np.frombuffer(data, dtype=np.uint8)
    bgr = cv2.imdecode(arr, cv2.IMREAD_COLOR)
    if bgr is None:
        return None
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB)
