# tests/test_embeddings_backend.py
from __future__ import annotations

import pytest

from codebase_index.config import Config
from codebase_index.embeddings.backend import (
    EmbeddingBackend,
    EmbeddingError,
    resolve_backend,
)
from codebase_index.embeddings.noop import NoopBackend


def test_default_config_resolves_to_noop():
    backend = resolve_backend(Config())
    assert isinstance(backend, NoopBackend)
    assert backend.enabled is False


def test_noop_embed_raises():
    with pytest.raises(EmbeddingError):
        NoopBackend().embed(["anything"])


def test_external_refused_without_allow_external(monkeypatch):
    monkeypatch.setenv("CBX_EMBEDDINGS_API_KEY", "sk-test")
    cfg = Config()
    cfg.embeddings.enabled = True
    cfg.embeddings.backend = "external"
    cfg.embeddings.endpoint = "https://example.test/embed"
    cfg.embeddings.allow_external = False
    with pytest.raises(EmbeddingError, match="allow_external"):
        resolve_backend(cfg)


def test_external_refused_without_api_key(monkeypatch):
    monkeypatch.delenv("CBX_EMBEDDINGS_API_KEY", raising=False)
    cfg = Config()
    cfg.embeddings.enabled = True
    cfg.embeddings.backend = "external"
    cfg.embeddings.endpoint = "https://example.test/embed"
    cfg.embeddings.allow_external = True
    with pytest.raises(EmbeddingError, match="API key"):
        resolve_backend(cfg)


def test_external_allowed_emits_warning_naming_endpoint(monkeypatch):
    monkeypatch.setenv("CBX_EMBEDDINGS_API_KEY", "sk-test")
    cfg = Config()
    cfg.embeddings.enabled = True
    cfg.embeddings.backend = "external"
    cfg.embeddings.endpoint = "https://example.test/embed"
    cfg.embeddings.allow_external = True
    warnings: list[str] = []
    backend = resolve_backend(cfg, warn=warnings.append)
    assert isinstance(backend, EmbeddingBackend)
    assert any("example.test" in w for w in warnings)


def test_disabled_config_with_local_backend_is_still_noop():
    cfg = Config()
    cfg.embeddings.backend = "local"
    cfg.embeddings.enabled = False
    assert isinstance(resolve_backend(cfg), NoopBackend)
