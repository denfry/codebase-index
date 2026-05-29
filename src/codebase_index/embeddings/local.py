# src/codebase_index/embeddings/local.py
"""On-device embedding via sentence-transformers. No network at query time.

The model is an OPTIONAL dependency (`pip install codebase-index[embeddings-local]`);
it is imported lazily so the base install never pulls it in. The model loads once
on first embed and is cached on the instance.
"""

from __future__ import annotations

from typing import Optional

from .backend import EmbeddingError


class LocalBackend:
    enabled = True

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        self.name = f"local:{model_name}"
        self.model_name = model_name
        self._model = None
        self._dim: Optional[int] = None

    def _load(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:
                raise EmbeddingError(
                    "Local embeddings need the optional extra: "
                    "pip install codebase-index[embeddings-local]"
                ) from exc
            self._model = SentenceTransformer(self.model_name)
            self._dim = int(self._model.get_sentence_embedding_dimension())
        return self._model

    @property
    def dim(self) -> int:
        if self._dim is None:
            self._load()
        return int(self._dim or 0)

    def embed(self, texts: list[str]) -> list[list[float]]:
        model = self._load()
        vecs = model.encode(
            list(texts), convert_to_numpy=True, normalize_embeddings=True, show_progress_bar=False
        )
        return [[float(x) for x in row] for row in vecs]
