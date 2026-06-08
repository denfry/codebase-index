# tests/test_pipeline_vectors.py
from __future__ import annotations

import pytest

from codebase_index.config import Config
from codebase_index.indexer.pipeline import build_index
from codebase_index.storage import repo
from codebase_index.storage.db import Database

pytest.importorskip("sqlite_vec")


def test_index_disabled_creates_no_vectors(sample_repo, tmp_path):
    cfg = Config()
    cfg.root = str(sample_repo)
    db = Database(tmp_path / "index.sqlite").open()
    stats = build_index(cfg, db, root=sample_repo)
    assert stats.vectors == 0
    tbl = db.conn.execute(
        "SELECT name FROM sqlite_master WHERE name = 'vec_chunks'"
    ).fetchone()
    assert tbl is None
    db.close()


def test_index_enabled_embeds_and_stores(sample_repo, tmp_path, fake_backend, monkeypatch):
    import codebase_index.indexer.pipeline as pipe

    monkeypatch.setattr(pipe, "resolve_backend", lambda cfg, warn=None: fake_backend)
    cfg = Config()
    cfg.root = str(sample_repo)
    cfg.embeddings.enabled = True
    cfg.embeddings.backend = "local"
    db = Database(tmp_path / "index.sqlite").open()
    stats = build_index(cfg, db, root=sample_repo)

    assert stats.vectors > 0
    assert repo.count_vectors(db.conn) == stats.vectors
    meta = repo.get_vec_meta(db.conn)
    assert meta["dim"] == fake_backend.dim
    db.close()


def test_reindex_vectors_idempotent(sample_repo, tmp_path, fake_backend, monkeypatch):
    import codebase_index.indexer.pipeline as pipe

    monkeypatch.setattr(pipe, "resolve_backend", lambda cfg, warn=None: fake_backend)
    cfg = Config()
    cfg.root = str(sample_repo)
    cfg.embeddings.enabled = True
    db = Database(tmp_path / "index.sqlite").open()
    s1 = build_index(cfg, db, root=sample_repo)
    s2 = build_index(cfg, db, root=sample_repo)
    # Incremental: second build embeds 0 new chunks, total in DB unchanged
    assert s2.vectors == 0
    assert repo.count_vectors(db.conn) == s1.vectors
    db.close()


class _CountingBackend:
    """Wraps an embedding backend to record how many texts it is asked to embed."""

    enabled = True
    name = "fake"

    def __init__(self, inner):
        self._inner = inner
        self.dim = inner.dim
        self.calls = 0
        self.embedded = 0

    def embed(self, texts):
        self.calls += 1
        self.embedded += len(texts)
        return self._inner.embed(texts)


def test_reindex_does_not_recompute_unchanged_embeddings(
    sample_repo, tmp_path, fake_backend, monkeypatch
):
    """A full rebuild must reuse cached vectors for unchanged content, never re-embed it."""
    import codebase_index.indexer.pipeline as pipe

    backend = _CountingBackend(fake_backend)
    monkeypatch.setattr(pipe, "resolve_backend", lambda cfg, warn=None: backend)
    cfg = Config()
    cfg.root = str(sample_repo)
    cfg.embeddings.enabled = True
    db = Database(tmp_path / "index.sqlite").open()

    build_index(cfg, db, root=sample_repo)
    first_pass = backend.embedded
    assert first_pass > 0

    build_index(cfg, db, root=sample_repo)
    # Chunk ids churn across rebuilds, but content is identical -> cache hit, no backend work.
    assert backend.embedded == first_pass
    db.close()


def test_changed_file_only_embeds_new_content(
    sample_repo, tmp_path, fake_backend, monkeypatch
):
    """Editing one file embeds only its new chunks; the rest come from the cache."""
    import shutil

    import codebase_index.indexer.pipeline as pipe

    # Copy the fixture so the edit below never mutates the shared, committed sample repo.
    repo_copy = tmp_path / "repo"
    shutil.copytree(sample_repo, repo_copy)

    backend = _CountingBackend(fake_backend)
    monkeypatch.setattr(pipe, "resolve_backend", lambda cfg, warn=None: backend)
    cfg = Config()
    cfg.root = str(repo_copy)
    cfg.embeddings.enabled = True
    db = Database(tmp_path / "index.sqlite").open()

    build_index(cfg, db, root=repo_copy)
    baseline = backend.embedded

    target = repo_copy / "src" / "auth" / "token.py"
    target.write_text(
        target.read_text(encoding="utf-8") + "\n\ndef brand_new_helper():\n    return 42\n",
        encoding="utf-8",
    )
    s2 = build_index(cfg, db, root=repo_copy)

    # Some new chunks were embedded, but far fewer than a full re-embed of the repo.
    assert s2.vectors > 0
    assert backend.embedded - baseline < baseline
    db.close()
