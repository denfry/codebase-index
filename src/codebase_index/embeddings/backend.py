# src/codebase_index/embeddings/backend.py
"""Embedding backend protocol + the single gating factory.

`resolve_backend` is the ONLY place a backend is constructed. It enforces
SECURITY.md §4: external backends are refused unless `allow_external = true`,
an API key is present in the environment, AND a warning naming the endpoint is
emitted. When embeddings are disabled the factory returns a NoopBackend and
imports no optional dependency.
"""

from __future__ import annotations

import os
from typing import Callable, Protocol, runtime_checkable

API_KEY_ENV = "CBX_EMBEDDINGS_API_KEY"


class EmbeddingError(RuntimeError):
    """Raised when embeddings are misconfigured, refused, or a backend is unusable."""


@runtime_checkable
class EmbeddingBackend(Protocol):
    enabled: bool
    name: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one vector (length == `dim`) per input text."""
        ...


def resolve_backend(cfg, warn: Callable[[str], None] = lambda _m: None) -> "EmbeddingBackend":
    """Construct the configured backend, applying all security gates."""
    emb = cfg.embeddings
    if not emb.enabled or emb.backend == "noop":
        from .noop import NoopBackend

        return NoopBackend()

    if emb.backend == "local":
        from .local import LocalBackend

        return LocalBackend(model_name=emb.model)

    if emb.backend == "external":
        if not emb.allow_external:
            raise EmbeddingError(
                "External embeddings require embeddings.allow_external = true (SECURITY.md §4)."
            )
        api_key = os.environ.get(API_KEY_ENV)
        if not api_key:
            raise EmbeddingError(
                f"External embeddings require an API key in ${API_KEY_ENV} (SECURITY.md §4)."
            )
        if not emb.endpoint:
            raise EmbeddingError("External embeddings require embeddings.endpoint to be set.")
        warn(
            f"[codebase-index] EXTERNAL EMBEDDINGS ENABLED — chunk text will be sent to "
            f"{emb.endpoint}. Disable with embeddings.backend=local|noop."
        )
        from .external import ExternalBackend

        return ExternalBackend(endpoint=emb.endpoint, api_key=api_key, model_name=emb.model)

    raise EmbeddingError(f"Unknown embeddings.backend: {emb.backend!r}")
