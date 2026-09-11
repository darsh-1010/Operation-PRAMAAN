"""Domain enumerations for Module 3 — Biometric Matching."""
from enum import Enum


class CheckType(str, Enum):
    """Types of biometric verification checks."""
    LIVENESS = "LIVENESS"
    DOC_TO_SELFIE = "DOC_TO_SELFIE"
    CROSS_DOCUMENT = "CROSS_DOCUMENT"


class Decision(str, Enum):
    """Outcome of a biometric check after applying thresholds."""
    PASS = "PASS"
    REVIEW = "REVIEW"
    FAIL = "FAIL"


class ReasonCode(str, Enum):
    """Machine-readable reason codes for biometric results.

    Stable identifiers — these may be mapped to officer-friendly messages downstream.
    """
    # Liveness
    LIVENESS_SPOOF_DETECTED = "LIVENESS_SPOOF_DETECTED"
    LIVENESS_REPLAY_DETECTED = "LIVENESS_REPLAY_DETECTED"
    LIVENESS_CHALLENGE_FAILED = "LIVENESS_CHALLENGE_FAILED"

    # Face detection / quality
    FACE_NOT_DETECTED = "FACE_NOT_DETECTED"
    MULTIPLE_FACES_DETECTED = "MULTIPLE_FACES_DETECTED"
    FACE_QUALITY_TOO_LOW = "FACE_QUALITY_TOO_LOW"
    FACE_OCCLUDED = "FACE_OCCLUDED"

    # Doc-to-selfie matching
    FACE_ID_STRONG_MISMATCH = "FACE_ID_STRONG_MISMATCH"
    FACE_ID_BORDERLINE_MATCH = "FACE_ID_BORDERLINE_MATCH"

    # Cross-document
    CROSS_DOCUMENT_FACE_MISMATCH = "CROSS_DOCUMENT_FACE_MISMATCH"
    CROSS_DOCUMENT_LOW_QUALITY = "CROSS_DOCUMENT_LOW_QUALITY"

    # General
    BIOMETRIC_REVIEW_REQUIRED = "BIOMETRIC_REVIEW_REQUIRED"
