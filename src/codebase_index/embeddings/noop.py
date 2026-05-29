# src/codebase_index/embeddings/noop.py
"""The disabled default backend. Present so callers never branch on None."""

from __future__ import annotations

from .backend import EmbeddingError


class NoopBackend:
    enabled = False
    name = "noop"
    dim = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise EmbeddingError("Embeddings are disabled (embeddings.enabled = false).")
