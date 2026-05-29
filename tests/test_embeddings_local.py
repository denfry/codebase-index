# tests/test_embeddings_local.py
from __future__ import annotations

import builtins

import pytest

from codebase_index.embeddings.backend import EmbeddingError
from codebase_index.embeddings.local import LocalBackend


def test_missing_extra_gives_actionable_error(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "sentence_transformers" or name.startswith("sentence_transformers."):
            raise ImportError("no module")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    backend = LocalBackend(model_name="all-MiniLM-L6-v2")
    with pytest.raises(EmbeddingError, match="embeddings-local"):
        backend.embed(["hello"])


def test_real_local_embed_shape():
    pytest.importorskip("sentence_transformers")
    backend = LocalBackend(model_name="all-MiniLM-L6-v2")
    vecs = backend.embed(["hello world", "goodbye"])
    assert len(vecs) == 2
    assert backend.dim > 0 and all(len(v) == backend.dim for v in vecs)
