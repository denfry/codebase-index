"""Upgrading from 1.x: a real 1.10.0 index keeps working, and memory attaches beside it.

`tests/fixtures/index-1.10.0/index.sqlite` was built by the released 1.10.0 code (commit
abb67df) over `tests/fixtures/sample_repo`, not synthesised by 2.0, so these tests check the
upgrade path users actually take. 2.0 leaves the index schema at version 3; evidence memory
lives in its own `memory.sqlite`, so no reindex is needed.
"""

from __future__ import annotations

import json
import shutil
import sqlite3
from pathlib import Path

import pytest
from typer.testing import CliRunner

from codebase_index.cli import app
from codebase_index.config import load
from codebase_index.storage.db import SCHEMA_VERSION, peek_schema_version

FIXTURES = Path(__file__).parent / "fixtures"
runner = CliRunner()


@pytest.fixture
def upgraded(tmp_path, monkeypatch):
    for name in ("CBX_DB_PATH", "CBX_MEMORY_PATH", "CBX_MEMORY", "CBX_ROOT"):
        monkeypatch.delenv(name, raising=False)
    root = tmp_path / "repo"
    # Other tests index sample_repo in place; never carry their runtime cache along.
    shutil.copytree(FIXTURES / "sample_repo", root, ignore=shutil.ignore_patterns(".claude"))
    cache = root / ".claude" / "cache" / "codebase-index"
    cache.mkdir(parents=True, exist_ok=True)
    shutil.copy(FIXTURES / "index-1.10.0" / "index.sqlite", cache / "index.sqlite")
    # The config 1.10.0 `init` writes: every section 2.0 knows, except `memory`.
    (cache / "config.json").write_text(json.dumps({
        "root": ".", "languages": "auto", "max_file_bytes": 1048576,
        "ignore_files": [".gitignore", ".cursorignore", ".claudeignore", ".codeindexignore"],
        "extra_ignore": [], "chunk": {"window_lines": 80, "overlap_lines": 10},
        "retrieval": {"default_mode": "hybrid", "rrf_k": 60, "token_budget": 1500, "limit": 10,
                      "compact_snippets": True, "compact_min_reduction": 0.25},
        "embeddings": {"backend": "noop", "enabled": False, "model": "all-MiniLM-L6-v2",
                       "allow_external": False, "endpoint": None},
        "graph": {"max_depth": 2, "node_cap": 40}, "redaction": {"enabled": True},
    }), encoding="utf-8")
    return root, cache / "index.sqlite"


def _meta(db: Path, key: str):
    conn = sqlite3.connect(db)
    try:
        row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def _cli_json(root: Path, *args: str) -> dict:
    result = runner.invoke(app, ["--root", str(root), *args])
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def test_fixture_is_a_real_1_10_index_on_the_current_schema(upgraded):
    _root, db = upgraded
    assert peek_schema_version(db) == 3 == SCHEMA_VERSION
    conn = sqlite3.connect(db)
    try:
        assert conn.execute("SELECT COUNT(*) FROM files").fetchone()[0] == 6
    finally:
        conn.close()


def test_1x_index_is_used_in_place_without_a_rebuild(upgraded):
    root, db = upgraded
    built_at = _meta(db, "built_at")
    search = _cli_json(root, "search", "token", "--json")
    assert search["results"] and "memory" not in search
    update = _cli_json(root, "--json", "update")
    assert update["indexed"] == 0 and update["deleted"] == 0   # same bytes: nothing reparsed
    assert _meta(db, "built_at") == built_at                     # the 1.x database survived
    assert peek_schema_version(db) == 3


def test_memory_attaches_to_an_upgraded_project(upgraded):
    root, db = upgraded
    assert load(root).memory.enabled is True                      # 1.x config, 2.0 defaults
    first = _cli_json(root, "search", "token", "--session", "upgrade", "--json")
    second = _cli_json(root, "search", "token", "--session", "upgrade", "--json")
    assert first["memory"]["reused"] == 0 and second["memory"]["reused"] >= 1
    assert (db.parent / "memory.sqlite").is_file()
    assert _cli_json(root, "verify", "--session", "upgrade", "--json")["all_valid"] is True
    stats = _cli_json(root, "stats", "--json")
    assert stats["memory"]["sessions"] == 1 and stats["files"] == 6


def test_clean_removes_the_index_but_keeps_memory(upgraded):
    root, db = upgraded
    _cli_json(root, "search", "token", "--session", "keep", "--json")
    result = runner.invoke(app, ["--root", str(root), "clean", "--yes", "--json"])
    assert result.exit_code == 0, result.output
    assert not db.exists() and (db.parent / "memory.sqlite").is_file()
