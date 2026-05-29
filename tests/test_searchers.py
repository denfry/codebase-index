from __future__ import annotations

from codebase_index.config import Config
from codebase_index.indexer.pipeline import build_index
from codebase_index.retrieval.searchers import build_match_query, fts_response
from codebase_index.storage.db import Database


def test_build_match_query_expands_identifiers():
    q = build_match_query("refreshAccessToken")
    assert "refreshAccessToken" in q
    assert "refresh" in q and "access" in q.lower() and "token" in q.lower()
    assert "OR" in q


def test_build_match_query_handles_snake_case():
    q = build_match_query("refresh_access_token")
    assert "refresh" in q and "access" in q and "token" in q


def test_build_match_query_empty_is_empty():
    assert build_match_query("   ") == ""
    assert build_match_query("!!!") == ""


def _indexed(sample_repo, tmp_path):
    cfg = Config()
    cfg.root = str(sample_repo)
    db = Database(tmp_path / "index.sqlite").open()
    build_index(cfg, db, root=sample_repo)
    return cfg, db


def test_fts_response_finds_symbol_with_snippet(sample_repo, tmp_path):
    _, db = _indexed(sample_repo, tmp_path)
    resp = fts_response(
        db.conn,
        "refresh access token",
        limit=10,
        token_budget=1500,
        root=sample_repo,
    )
    assert resp.intent == "keyword"
    assert resp.results, "expected at least one lexical hit"
    top = resp.results[0]
    assert top.path == "src/auth/token.py"
    assert top.rank == 1
    assert top.snippet is not None
    assert resp.recommended_reads[0].path == "src/auth/token.py"
    assert resp.confidence in ("high", "medium", "low")
    db.close()


def test_fts_response_empty_query_low_confidence_with_fallback(sample_repo, tmp_path):
    _, db = _indexed(sample_repo, tmp_path)
    resp = fts_response(
        db.conn,
        "zzznotpresentzzz",
        limit=10,
        token_budget=1500,
        root=sample_repo,
    )
    assert resp.results == []
    assert resp.confidence == "low"
    assert resp.fallback_suggestions.get("ripgrep")
    db.close()
