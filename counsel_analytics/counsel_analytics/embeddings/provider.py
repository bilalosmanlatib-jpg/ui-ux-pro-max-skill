"""Pluggable embedding hook for `metrics/reargument.py`'s semantic-similarity
mode. Kept out of `metrics/reargument.py` itself so importing that module
never requires an optional ML dependency — `embedding_provider: "none"`
(the default) takes zero extra imports; `"local"`/`"api"` only import their
concrete library inside the provider class, at first use.
"""

from __future__ import annotations

import math
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from counsel_analytics.config import Settings


class EmbeddingProvider(Protocol):
    def embed(self, texts: list[str]) -> list[list[float]]: ...


def cosine_similarity(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    norm_a = math.sqrt(sum(x * x for x in a))
    norm_b = math.sqrt(sum(y * y for y in b))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


class LocalEmbeddingProvider:
    """Local embeddings via `sentence-transformers` (the `embeddings` extra)."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2"):
        from sentence_transformers import SentenceTransformer  # lazy import

        self._model = SentenceTransformer(model_name)

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [list(vec) for vec in self._model.encode(texts)]


class ApiEmbeddingProvider:
    """Placeholder for a hosted embeddings API. Anthropic's API is an LLM
    completion API, not a text-embeddings endpoint, so there is no real
    implementation to lazily import here yet — raises clearly rather than
    faking a similarity score. A real embeddings provider (e.g. Voyage AI,
    Anthropic's recommended embeddings partner) would plug in at this seam.
    """

    def __init__(self):
        raise NotImplementedError(
            "ApiEmbeddingProvider has no real backend yet — Anthropic's API "
            "does not expose text embeddings. Use embedding_provider: local "
            "(sentence-transformers) or none, or wire in a real embeddings "
            "API here."
        )

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise NotImplementedError


def build_embedding_provider(settings: "Settings") -> EmbeddingProvider | None:
    if settings.embedding_provider == "none":
        return None
    if settings.embedding_provider == "local":
        return LocalEmbeddingProvider()
    if settings.embedding_provider == "api":
        return ApiEmbeddingProvider()
    raise ValueError(f"Unknown embedding_provider: {settings.embedding_provider!r}")
