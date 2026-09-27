"""Domain data models for Module 3 — Biometric Matching.

Plain dataclasses — no ORM, no Pydantic dependency here. Pydantic is used only at the API
boundary (main.py). These are internal representations passed between ML components and
services.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class BoundingBox:
    """Pixel-coordinate bounding box of a detected face (top-left origin)."""
    top: int
    right: int
    bottom: int
    left: int

    @property
    def width(self) -> int:
        return self.right - self.left

    @property
    def height(self) -> int:
        return self.bottom - self.top

    @property
    def area(self) -> int:
        return self.width * self.height


@dataclass(frozen=True)
class QualityMetrics:
    """Face quality signals captured during preprocessing.

    All scores are 0..1 where 1 = best quality.  Values are optional because not every
    detector/model produces every metric — a missing value means "not assessed", which is
    different from "low quality".
    """
    detection_confidence: float = 0.0
    sharpness: Optional[float] = None       # blur estimate (1 = sharp, 0 = blurry)
    face_size_ratio: Optional[float] = None  # face area / image area
    # Pose angles in degrees (0 = frontal). None = not estimated.
    yaw: Optional[float] = None
    pitch: Optional[float] = None
    roll: Optional[float] = None

    @property
    def overall_score(self) -> float:
        """Heuristic composite quality score (0..1).

        This is a simple average of available metrics — NOT a calibrated quality model.
        It is useful for filtering/logging but should not be treated as a production
        quality gate on its own.
        """
        values: list[float] = [self.detection_confidence]
        if self.sharpness is not None:
            values.append(self.sharpness)
        if self.face_size_ratio is not None:
            # Clamp: anything above 0.5 of the image is "large enough"
            values.append(min(self.face_size_ratio * 2.0, 1.0))
        if self.yaw is not None:
            # Penalise large yaw: 0° → 1.0, ±90° → 0.0
            values.append(max(0.0, 1.0 - abs(self.yaw) / 90.0))
        return sum(values) / len(values) if values else 0.0


@dataclass(frozen=True)
class FaceDetectionResult:
    """Output of the face-detection + quality stage for one image."""
    found: bool
    face_count: int = 0
    box: Optional[BoundingBox] = None
    quality: QualityMetrics = field(default_factory=QualityMetrics)
    # Aligned face image as numpy array (H×W×3, RGB uint8). None when no face found.
    aligned_face: object = None  # typed as object to avoid numpy import at module level
    # Liveness (anti-spoofing) metrics. Only populated if check_liveness=True.
    liveness_score: Optional[float] = None
    is_real: Optional[bool] = None


@dataclass(frozen=True)
class FaceEmbedding:
    """A face embedding vector with provenance metadata."""
    vector: list[float]
    model_name: str
    model_version: str
    embedding_dimension: int

    def __post_init__(self) -> None:
        if len(self.vector) != self.embedding_dimension:
            raise ValueError(
                f"Vector length {len(self.vector)} does not match "
                f"declared dimension {self.embedding_dimension}"
            )


@dataclass(frozen=True)
class MatchResult:
    """Result of comparing two face embeddings."""
    similarity: float           # raw similarity value from the metric
    threshold: float            # threshold that was applied
    passed: bool                # similarity >= threshold
    quality_probe: float        # quality of the probe face (0..1)
    quality_ref: float          # quality of the reference face (0..1)
    model_name: str
    model_version: str
    similarity_metric: str      # e.g. "cosine", "euclidean"
