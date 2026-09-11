"""Configuration loader for Module 3 — Biometric Matching.

Loads thresholds and model metadata from configs/thresholds.yaml.  Falls back to
hard-coded defaults (identical to the YAML shipped in the repo) so the service can
start even when the file is missing — but logs a warning.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)

_CONFIG_DIR = Path(__file__).resolve().parent.parent / "configs"
_DEFAULT_PATH = _CONFIG_DIR / "thresholds.yaml"


@dataclass
class FaceModelConfig:
    name: str = "ArcFace"
    version: str = "deepface-1.0"
    embedding_dimension: int = 512
    similarity_metric: str = "cosine"
    preprocessing_version: str = "retinaface-v1"


@dataclass
class LivenessThresholds:
    review_threshold: float = 0.80
    hard_fail_threshold: float = 0.20


@dataclass
class DocToSelfieThresholds:
    accept_threshold: float = 0.60
    review_threshold: float = 0.45
    hard_fail_threshold: float = 0.30


@dataclass
class CrossDocumentThresholds:
    accept_threshold: float = 0.70
    review_threshold: float = 0.55


@dataclass
class FusionConfig:
    liveness_weight: float = 0.35
    doc_match_weight: float = 0.45
    cross_document_weight: float = 0.20
    accept_threshold: float = 0.85
    review_threshold: float = 0.65


@dataclass
class QualityConfig:
    min_reliable_quality: float = 0.40
    low_quality_floor: float = 0.25


@dataclass
class BiometricConfig:
    face_model: FaceModelConfig = field(default_factory=FaceModelConfig)
    liveness: LivenessThresholds = field(default_factory=LivenessThresholds)
    doc_to_selfie: DocToSelfieThresholds = field(default_factory=DocToSelfieThresholds)
    cross_document: CrossDocumentThresholds = field(default_factory=CrossDocumentThresholds)
    fusion: FusionConfig = field(default_factory=FusionConfig)
    quality: QualityConfig = field(default_factory=QualityConfig)


def _apply_section(target: object, data: dict[str, Any]) -> None:
    """Set attributes on *target* from *data*, ignoring unknown keys."""
    for key, value in data.items():
        if hasattr(target, key):
            setattr(target, key, value)


def load_config(path: str | Path | None = None) -> BiometricConfig:
    """Load configuration, with env-var override for the path.

    Priority: explicit *path* argument > BIOMETRIC_CONFIG_PATH env var > default file.
    """
    if path is None:
        path = os.environ.get("BIOMETRIC_CONFIG_PATH", str(_DEFAULT_PATH))
    path = Path(path)

    cfg = BiometricConfig()

    if not path.exists():
        logger.warning("Config file %s not found — using built-in defaults", path)
        return cfg

    with open(path) as f:
        raw: dict[str, Any] = yaml.safe_load(f) or {}

    if "face_model" in raw:
        _apply_section(cfg.face_model, raw["face_model"])
    if "liveness" in raw:
        _apply_section(cfg.liveness, raw["liveness"])
    if "doc_to_selfie" in raw:
        _apply_section(cfg.doc_to_selfie, raw["doc_to_selfie"])
    if "cross_document" in raw:
        _apply_section(cfg.cross_document, raw["cross_document"])
    if "fusion" in raw:
        _apply_section(cfg.fusion, raw["fusion"])
    if "quality" in raw:
        _apply_section(cfg.quality, raw["quality"])

    logger.info("Loaded biometric config from %s", path)
    return cfg
