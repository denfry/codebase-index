from __future__ import annotations

import pytest

from codebase_index.parsers.base import Chunk, Symbol
from codebase_index.storage.db import Database, SCHEMA_VERSION
from codebase_index.storage import repo


def test_open_creates_schema_and_sets_pragmas(tmp_path):
    db_path = tmp_path / "index.sqlite"
    with Database(db_path) as db:
        assert db.conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert db.conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        tables = {
            r[0]
            for r in db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {"files", "chunks", "symbols", "edges", "modules", "meta"} <= tables
        assert db.get_schema_version() == SCHEMA_VERSION
    assert db_path.exists()


def test_reopen_is_idempotent_and_keeps_version(tmp_path):
    db_path = tmp_path / "index.sqlite"
    with Database(db_path) as db:
        db.conn.execute("INSERT INTO meta(key, value) VALUES ('probe', '1')")
    with Database(db_path) as db:
        assert db.get_schema_version() == SCHEMA_VERSION
        assert db.conn.execute("SELECT value FROM meta WHERE key='probe'").fetchone()[0] == "1"


def test_future_schema_version_raises(tmp_path):
    db_path = tmp_path / "index.sqlite"
    with Database(db_path) as db:
        db.conn.execute(
            "UPDATE meta SET value = ? WHERE key = 'schema_version'",
            (str(SCHEMA_VERSION + 1),),
        )
    with pytest.raises(RuntimeError, match="rebuild"):
        with Database(db_path):
            pass


def _open(tmp_path):
    return Database(tmp_path / "index.sqlite").open()


def test_upsert_and_get_file(tmp_path):
    db = _open(tmp_path)
    fid = repo.upsert_file(
        db.conn,
        path="src/a.py",
        lang="python",
        size_bytes=10,
        sha256="aaa",
        mtime_ns=123,
        git_status=None,
        parser="treesitter",
        indexed_at="2026-05-29T00:00:00Z",
        is_generated=False,
    )
    assert fid > 0
    row = repo.get_file(db.conn, "src/a.py")
    assert row is not None and row["sha256"] == "aaa" and row["lang"] == "python"

    fid2 = repo.upsert_file(
        db.conn,
        path="src/a.py",
        lang="python",
        size_bytes=11,
        sha256="bbb",
        mtime_ns=456,
        git_status=None,
        parser="treesitter",
        indexed_at="2026-05-29T00:01:00Z",
        is_generated=False,
    )
    assert fid2 == fid
    assert repo.get_file(db.conn, "src/a.py")["sha256"] == "bbb"
    assert repo.count_files(db.conn) == 1
    db.close()


def test_all_paths_and_prune(tmp_path):
    db = _open(tmp_path)
    for p in ("a.py", "b.py", "c.py"):
        repo.upsert_file(
            db.conn,
            path=p,
            lang="python",
            size_bytes=1,
            sha256="x",
            mtime_ns=1,
            git_status=None,
            parser="line",
            indexed_at="t",
            is_generated=False,
        )
    assert repo.all_paths(db.conn) == {"a.py", "b.py", "c.py"}
    deleted = repo.delete_files(db.conn, ["b.py", "c.py"])
    assert deleted == 2
    assert repo.all_paths(db.conn) == {"a.py"}
    db.close()


def test_meta_get_set(tmp_path):
    db = _open(tmp_path)
    assert repo.get_meta(db.conn, "missing") is None
    repo.set_meta(db.conn, "head_commit", "abc123")
    repo.set_meta(db.conn, "head_commit", "def456")
    assert repo.get_meta(db.conn, "head_commit") == "def456"
    db.close()


def test_replace_chunks_syncs_fts(tmp_path):
    db = _open(tmp_path)
    fid = repo.upsert_file(
        db.conn,
        path="src/a.py",
        lang="python",
        size_bytes=10,
        sha256="h",
        mtime_ns=1,
        git_status=None,
        parser="line",
        indexed_at="t",
        is_generated=False,
    )
    repo.replace_chunks(
        db.conn,
        fid,
        [
            Chunk(
                line_start=1,
                line_end=3,
                content="def refresh_token():\n    pass",
                token_est=8,
            ),
        ],
    )
    assert repo.count_chunks(db.conn) == 1
    hit = db.conn.execute(
        "SELECT rowid FROM fts_chunks WHERE fts_chunks MATCH 'refresh_token'"
    ).fetchall()
    assert len(hit) == 1

    repo.replace_chunks(
        db.conn,
        fid,
        [Chunk(line_start=1, line_end=1, content="x = 1", token_est=2)],
    )
    assert repo.count_chunks(db.conn) == 1
    none = db.conn.execute(
        "SELECT rowid FROM fts_chunks WHERE fts_chunks MATCH 'refresh_token'"
    ).fetchall()
    assert none == []
    db.close()


def test_fts_search_returns_path_and_lines(tmp_path):
    db = _open(tmp_path)
    fid = repo.upsert_file(
        db.conn,
        path="src/auth/token.py",
        lang="python",
        size_bytes=10,
        sha256="h",
        mtime_ns=1,
        git_status=None,
        parser="line",
        indexed_at="t",
        is_generated=False,
    )
    repo.replace_chunks(
        db.conn,
        fid,
        [
            Chunk(
                line_start=5,
                line_end=9,
                content="def bootstrap():\n    return 1",
                token_est=6,
            ),
        ],
    )
    rows = repo.fts_search(db.conn, "bootstrap", limit=10)
    assert len(rows) == 1
    r = rows[0]
    assert r["path"] == "src/auth/token.py"
    assert r["line_start"] == 5 and r["line_end"] == 9
    assert "bootstrap" in r["content"]
    db.close()


def test_replace_symbols_resolves_parents(tmp_path):
    db = _open(tmp_path)
    fid = repo.upsert_file(
        db.conn,
        path="m.py",
        lang="python",
        size_bytes=1,
        sha256="h",
        mtime_ns=1,
        git_status=None,
        parser="treesitter",
        indexed_at="t",
        is_generated=False,
    )
    ids = repo.replace_symbols(
        db.conn,
        fid,
        [
            Symbol(name="User", kind="class", line_start=1, line_end=10, qualified="User"),
            Symbol(
                name="__init__",
                kind="method",
                line_start=2,
                line_end=4,
                qualified="User.__init__",
                parent_index=0,
            ),
        ],
    )
    assert len(ids) == 2
    rows = {r["name"]: r for r in repo.symbols_by_name(db.conn, "__init__")}
    assert rows["__init__"]["parent_id"] == ids[0]
    assert repo.count_symbols(db.conn) == 2
    db.close()


def test_replace_chunks_with_symbol_ids(tmp_path):
    db = _open(tmp_path)
    fid = repo.upsert_file(
        db.conn,
        path="m.py",
        lang="python",
        size_bytes=1,
        sha256="h",
        mtime_ns=1,
        git_status=None,
        parser="treesitter",
        indexed_at="t",
        is_generated=False,
    )
    sids = repo.replace_symbols(
        db.conn,
        fid,
        [Symbol(name="a", kind="function", line_start=1, line_end=2, qualified="a")],
    )
    repo.replace_chunks(
        db.conn,
        fid,
        [
            Chunk(
                line_start=1,
                line_end=2,
                content="def a(): pass",
                token_est=3,
                kind="symbol_body",
                symbol_index=0,
            ),
        ],
        symbol_ids=sids,
    )
    row = repo.chunks_for_file(db.conn, fid)[0]
    assert row["symbol_id"] == sids[0]
    assert row["kind"] == "symbol_body"
    db.close()


def test_replace_edges_and_refs_for_name(tmp_path):
    db = _open(tmp_path)
    fid = repo.upsert_file(
        db.conn,
        path="m.py",
        lang="python",
        size_bytes=1,
        sha256="h",
        mtime_ns=1,
        git_status=None,
        parser="treesitter",
        indexed_at="t",
        is_generated=False,
    )
    sids = repo.replace_symbols(
        db.conn,
        fid,
        [
            Symbol(name="target", kind="function", line_start=1, line_end=2, qualified="target"),
            Symbol(name="caller", kind="function", line_start=4, line_end=6, qualified="caller"),
        ],
    )
    repo.replace_edges(
        db.conn,
        fid,
        [
            {
                "edge_type": "call",
                "src_kind": "symbol",
                "src_id": sids[1],
                "dst_kind": "symbol",
                "dst_id": sids[0],
                "dst_name": "target",
                "line": 5,
                "resolved": 1,
            },
        ],
    )
    assert repo.count_edges(db.conn) == 1
    sites = repo.refs_for_name(db.conn, "target")
    assert len(sites) == 1 and sites[0]["line"] == 5 and sites[0]["path"] == "m.py"
    db.close()
