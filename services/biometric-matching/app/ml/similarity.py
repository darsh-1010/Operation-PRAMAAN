"""Face similarity / distance computation.

Provides the ``compare(embedding_a, embedding_b) → similarity`` abstraction specified
in the biometric module proposal.  The metric must match what the selected face model
was trained/validated with.

Current default: cosine similarity (appropriate for dlib's L2-normalized 128-D vectors).
"""
from __future__ import annotations

import math

from app.domain.models import FaceEmbedding


def cosine_similarity(a: list[float], b: list[float]) -> float:
    """Compute cosine similarity between two vectors.

    Returns a value in [-1, 1].  For L2-normalized face embeddings this is
    typically in [0, 1] for genuine pairs and [-0.5, 0.5] for impostor pairs,
    though the exact distribution depends on the model.
    """
    if len(a) != len(b):
        raise ValueError(f"Vector dimension mismatch: {len(a)} vs {len(b)}")

    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(x * x for x in b))

    if norm_a == 0.0 or norm_b == 0.0:
        return 0.0

    return dot / (norm_a * norm_b)


def euclidean_distance(a: list[float], b: list[float]) -> float:
    """Compute Euclidean distance between two vectors.

    Lower = more similar.  For dlib 128-D embeddings, typical thresholds are around 0.6
    (same person) vs >0.6 (different person), but this must be validated per model.
    """
    if len(a) != len(b):
        raise ValueError(f"Vector dimension mismatch: {len(a)} vs {len(b)}")
    return math.sqrt(sum((x - y) ** 2 for x, y in zip(a, b)))


def compare(
    embedding_a: FaceEmbedding,
    embedding_b: FaceEmbedding,
    metric: str = "cosine",
) -> float:
    """Compare two face embeddings using the specified similarity metric.

    Parameters
    ----------
    embedding_a, embedding_b : FaceEmbedding
        Must be from the same model/version (enforced here).
    metric : str
        ``"cosine"`` or ``"euclidean"``.

    Returns
    -------
    float
        Similarity score.  For cosine: higher = more similar.
        For euclidean: this returns ``1 / (1 + distance)`` to normalise into [0, 1].

    Raises
    ------
    ValueError
        If the embeddings come from incompatible models or the metric is unknown.
    """
    if embedding_a.model_name != embedding_b.model_name:
        raise ValueError(
            f"Cannot compare embeddings from different models: "
            f"{embedding_a.model_name} vs {embedding_b.model_name}"
        )
    if embedding_a.model_version != embedding_b.model_version:
        raise ValueError(
            f"Cannot compare embeddings from different model versions: "
            f"{embedding_a.model_version} vs {embedding_b.model_version}"
        )

    if metric == "cosine":
        return cosine_similarity(embedding_a.vector, embedding_b.vector)
    elif metric == "euclidean":
        dist = euclidean_distance(embedding_a.vector, embedding_b.vector)
        return 1.0 / (1.0 + dist)
    else:
        raise ValueError(f"Unknown similarity metric: {metric!r}")
