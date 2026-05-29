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
    assert s1.vectors == s2.vectors
    db.close()
