"""Face encoder abstraction — model-agnostic embedding generation.

Conceptual pipeline:

    aligned_face → FaceEncoder.generate_embedding() → FaceEmbedding

The rest of Module 3 uses only:

    embedding = encoder.generate_embedding(aligned_face)

Current concrete implementation: ArcFaceEncoder (using DeepFace, 512-D embeddings).
"""
from __future__ import annotations

import abc
import logging
from typing import Optional

import numpy as np

from app.config import FaceModelConfig
from app.domain.models import FaceEmbedding

logger = logging.getLogger(__name__)


class FaceEncoder(abc.ABC):
    """Model-agnostic interface for face embedding generation.

    Subclass this to add a new face model.
    """

    @abc.abstractmethod
    def generate_embedding(self, aligned_face: np.ndarray) -> Optional[FaceEmbedding]:
        """Generate an embedding vector from an aligned face crop.

        Parameters
        ----------
        aligned_face : np.ndarray
            RGB H×W×3 uint8 array, already face-detected and aligned.

        Returns
        -------
        FaceEmbedding or None
            None if the encoder cannot produce a valid embedding.
        """

    @property
    @abc.abstractmethod
    def model_name(self) -> str:
        """Identifier for the underlying model (persisted with every verification)."""

    @property
    @abc.abstractmethod
    def model_version(self) -> str:
        """Version string for the underlying model."""

    @property
    @abc.abstractmethod
    def embedding_dimension(self) -> int:
        """Dimensionality of the embedding vector."""


class ArcFaceEncoder(FaceEncoder):
    """Concrete encoder using ArcFace (via deepface).

    Produces 512-dimensional embeddings.
    """

    def __init__(self, config: Optional[FaceModelConfig] = None) -> None:
        self._config = config or FaceModelConfig(
            name="ArcFace",
            version="deepface-1.0",
            embedding_dimension=512,
            similarity_metric="cosine",
            preprocessing_version="retinaface-v1"
        )

    @property
    def model_name(self) -> str:
        return self._config.name

    @property
    def model_version(self) -> str:
        return self._config.version

    @property
    def embedding_dimension(self) -> int:
        return self._config.embedding_dimension

    def generate_embedding(self, aligned_face: np.ndarray) -> Optional[FaceEmbedding]:
        from deepface import DeepFace  # type: ignore[import-untyped]
        import cv2

        if aligned_face is None or aligned_face.size == 0:
            return None

        # DeepFace expects BGR format when passed a numpy array
        bgr = cv2.cvtColor(aligned_face, cv2.COLOR_RGB2BGR)

        try:
            # We already detected and aligned the face, so skip detection here
            representations = DeepFace.represent(
                img_path=bgr,
                model_name=self.model_name,
                detector_backend="skip",
                enforce_detection=False
            )
        except Exception as e:
            logger.warning(f"ArcFace encoding failed: {e}")
            return None

        if not representations:
            return None

        vector = representations[0]["embedding"]

        return FaceEmbedding(
            vector=vector,
            model_name=self.model_name,
            model_version=self.model_version,
            embedding_dimension=len(vector),
        )
