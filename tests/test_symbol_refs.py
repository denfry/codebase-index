from __future__ import annotations

from codebase_index.config import Config
from codebase_index.indexer.pipeline import build_index
from codebase_index.retrieval.searchers import refs_lookup, symbol_lookup
from codebase_index.storage.db import Database


def _indexed(sample_repo, tmp_path):
    cfg = Config()
    cfg.root = str(sample_repo)
    db = Database(tmp_path / "index.sqlite").open()
    build_index(cfg, db, root=sample_repo)
    return db


def test_symbol_lookup_exact(sample_repo, tmp_path):
    db = _indexed(sample_repo, tmp_path)
    resp = symbol_lookup(db.conn, "refresh_access_token", kind=None, exact=True)
    assert resp.symbols
    symbol = resp.symbols[0]
    assert symbol.path == "src/auth/token.py" and symbol.kind == "function"
    assert resp.index.exists is True
    db.close()


def test_symbol_lookup_kind_filter_and_prefix(sample_repo, tmp_path):
    db = _indexed(sample_repo, tmp_path)
    resp = symbol_lookup(db.conn, "User", kind="class", exact=True)
    assert any(symbol.name == "User" and symbol.kind == "class" for symbol in resp.symbols)
    db.close()


def test_refs_lookup_includes_call_and_def(sample_repo, tmp_path):
    db = _indexed(sample_repo, tmp_path)
    resp = refs_lookup(db.conn, "refresh_access_token", kind="all")
    kinds = {site.kind for site in resp.sites}
    assert "call" in kinds
    assert "definition" in kinds
    callers = refs_lookup(db.conn, "refresh_access_token", kind="callers")
    assert callers.sites and all(site.kind == "call" for site in callers.sites)
    db.close()
