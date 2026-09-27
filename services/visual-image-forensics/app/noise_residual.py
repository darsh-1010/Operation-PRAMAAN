"""Voter 1: noise-residual consistency check.

A camera sensor leaves a roughly uniform noise signature across an entire photo. Splicing
in a region from another image (or an AI-generated patch) usually breaks that uniformity —
the pasted-in area's noise texture doesn't match its surroundings. This is the classical
steganalysis/forensics approach: pull out the high-frequency noise residual, split the image
into a patch grid, and look for patches whose residual variance is a statistical outlier
against the rest of the image.

No training data needed — pure signal processing (OpenCV + NumPy, already project deps).

ponytail: threshold constants below are a first-pass heuristic, not calibrated against a
labeled tamper dataset. Revisit OUTLIER_Z_THRESHOLD / HARD_FAIL_RATIO once real labeled
spliced-document examples are available — until then this is a real signal, not a proven one.
"""
from __future__ import annotations

import cv2
import numpy as np

from app.voters import VoterResult

VOTER_NAME = "noise_residual"

GRID = 16  # patch grid is GRID x GRID regardless of image resolution
MIN_DIM = 64  # below this, a patch grid is too coarse to mean anything
MAX_DIM = 1024  # downscale larger images before processing — this is a cheap heuristic,
                 # not pixel-perfect forensics; no need to churn through full-resolution scans
OUTLIER_Z_THRESHOLD = 3.5  # "modified z-score" (Iglewicz & Hoaglin) — standard robust-outlier cutoff
HARD_FAIL_RATIO = 0.15  # >15% of patches flagged as noise outliers -> treat as a strong signal
ZERO_SCORE_RATIO = 0.30  # outlier ratio at/above this maps to score 0


def _decode(image_bytes: bytes) -> np.ndarray | None:
    arr = np.frombuffer(image_bytes, dtype=np.uint8)
    img = cv2.imdecode(arr, cv2.IMREAD_GRAYSCALE)
    return img


def _patch_stds(gray: np.ndarray) -> np.ndarray:
    """Noise residual (image minus a denoised version of itself), then per-patch std over a
    GRID x GRID grid — cropped to a multiple of GRID so every patch is the same size."""
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    residual = gray.astype(np.float32) - blurred.astype(np.float32)

    h, w = residual.shape
    ph, pw = h // GRID, w // GRID
    cropped = residual[: ph * GRID, : pw * GRID]

    patches = cropped.reshape(GRID, ph, GRID, pw).transpose(0, 2, 1, 3).reshape(GRID * GRID, ph * pw)
    return patches.std(axis=1)


def assess(image_bytes: bytes, label: str) -> VoterResult:
    gray = _decode(image_bytes)
    if gray is None or gray.shape[0] < MIN_DIM or gray.shape[1] < MIN_DIM:
        return VoterResult(name=VOTER_NAME, score=None,
                            reason_codes=[f"{label}: NOISE_RESIDUAL_NOT_ASSESSED (image too small)"])

    if max(gray.shape) > MAX_DIM:
        scale = MAX_DIM / max(gray.shape)
        gray = cv2.resize(gray, None, fx=scale, fy=scale, interpolation=cv2.INTER_AREA)

    stds = _patch_stds(gray)
    median = np.median(stds)
    mad = np.median(np.abs(stds - median))

    if mad == 0:
        # Perfectly uniform noise (or a flat/synthetic test image) — nothing to flag.
        return VoterResult(name=VOTER_NAME, score=100.0)

    modified_z = 0.6745 * (stds - median) / mad
    outlier_ratio = float(np.mean(np.abs(modified_z) > OUTLIER_Z_THRESHOLD))

    score = round(100.0 * (1.0 - min(outlier_ratio / ZERO_SCORE_RATIO, 1.0)), 1)
    hard_fail = outlier_ratio > HARD_FAIL_RATIO
    reasons = []
    if hard_fail:
        reasons.append(f"{label}: NOISE_INCONSISTENT_REGION_DETECTED (outlier_ratio={outlier_ratio:.2f})")
    elif outlier_ratio > 0:
        reasons.append(f"{label}: NOISE_MINOR_INCONSISTENCY (outlier_ratio={outlier_ratio:.2f})")

    return VoterResult(name=VOTER_NAME, score=score, hard_fail=hard_fail, reason_codes=reasons)


def demo() -> None:
    """ponytail self-check: a flat image scores clean; a spliced-in bright block gets flagged."""
    rng = np.random.default_rng(0)

    clean = (128 + rng.normal(0, 4, (256, 256))).clip(0, 255).astype(np.uint8)
    ok, buf = cv2.imencode(".png", clean)
    assert ok
    result = assess(buf.tobytes(), "test")
    assert result.score is not None and result.score > 80, result
    assert not result.hard_fail, result

    spliced = clean.copy()
    spliced[64:192, 64:192] = 200  # a flat, noiseless block pasted into a noisy photo
    ok, buf = cv2.imencode(".png", spliced)
    assert ok
    result = assess(buf.tobytes(), "test")
    assert result.hard_fail, result
    assert result.score is not None and result.score < 50, result

    tiny = np.zeros((10, 10), dtype=np.uint8)
    ok, buf = cv2.imencode(".png", tiny)
    assert ok
    result = assess(buf.tobytes(), "test")
    assert result.score is None, result

    print("OK: noise_residual.demo")


if __name__ == "__main__":
    demo()
