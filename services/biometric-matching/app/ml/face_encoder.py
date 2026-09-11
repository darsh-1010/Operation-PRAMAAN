"""Face encoder abstraction — model-agnostic embedding generation.

Conceptual pipeline:

    aligned_face → FaceEncoder.generate_embedding() → FaceEmbedding

The rest of Module 3 uses only:

    embedding = encoder.generate_embedding(aligned_face)

and does not depend on whether the encoder internally uses dlib, a Siamese CNN,
a transformer, or any future model.

Current concrete implementation: DlibFaceEncoder (face_recognition library,
dlib ResNet, 128-D embeddings).
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

    Subclass this to add a new face model.  The system should be able to swap
    from ``DlibFaceEncoder`` to a future ``InceptionResNetEncoder`` (or any other)
    by changing configuration — no business logic rewrites needed.
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
            None if the encoder cannot produce a valid embedding (e.g. no face
            re-detected in the aligned crop — rare but possible with aggressive crops).
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


class DlibFaceEncoder(FaceEncoder):
    """Concrete encoder using dlib's ResNet face recognition model (128-D).

    This wraps ``face_recognition.face_encodings()`` behind the ``FaceEncoder``
    abstraction.  The dlib model produces 128-dimensional L2-normalized embeddings
    that work well with both cosine similarity and Euclidean distance.

    Status: initial model provider (placeholder).  The 128-D dlib model has not been
    calibrated against the application's genuine/impostor distribution.  Thresholds
    are configuration-driven and must be validated before production use.
    """

    def __init__(self, config: Optional[FaceModelConfig] = None) -> None:
        self._config = config or FaceModelConfig()

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
        import face_recognition  # type: ignore[import-untyped]

        if aligned_face is None or aligned_face.size == 0:
            return None

        # face_recognition.face_encodings expects a full image and re-detects faces.
        # We pass known_face_locations so it uses our pre-detected/aligned crop directly.
        h, w = aligned_face.shape[:2]
        known_locations = [(0, w, h, 0)]  # (top, right, bottom, left) covering the entire crop

        encodings = face_recognition.face_encodings(aligned_face, known_face_locations=known_locations)
        if not encodings:
            logger.warning("Encoder produced no embeddings from aligned face crop")
            return None

        vector = encodings[0].tolist()

        return FaceEmbedding(
            vector=vector,
            model_name=self.model_name,
            model_version=self.model_version,
            embedding_dimension=len(vector),
        )
