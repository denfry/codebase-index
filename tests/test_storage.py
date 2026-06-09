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


def _seed_two_files(db):
    from codebase_index.parsers.base import Symbol

    fid_a = repo.upsert_file(
        db.conn, path="src/auth/token.py", lang="python", size_bytes=1, sha256="a",
        mtime_ns=1, git_status=None, parser="treesitter", indexed_at="t", is_generated=False,
    )
    fid_b = repo.upsert_file(
        db.conn, path="src/api/service.py", lang="python", size_bytes=1, sha256="b",
        mtime_ns=1, git_status=None, parser="treesitter", indexed_at="t", is_generated=False,
    )
    a_syms = repo.replace_symbols(db.conn, fid_a, [
        Symbol(name="refresh_access_token", kind="function", line_start=1, line_end=2,
               qualified="refresh_access_token"),
    ])
    b_syms = repo.replace_symbols(db.conn, fid_b, [
        Symbol(name="renew", kind="function", line_start=5, line_end=6, qualified="renew"),
    ])
    return fid_a, fid_b, a_syms[0], b_syms[0]


def test_graph_accessors_resolve_and_walk(tmp_path):
    db = _open(tmp_path)
    fid_a, fid_b, target_id, caller_id = _seed_two_files(db)

    # one unresolved cross-file call edge + one unresolved import edge
    repo.replace_edges(db.conn, fid_b, [
        {"edge_type": "call", "src_kind": "symbol", "src_id": caller_id,
         "dst_kind": None, "dst_id": None, "dst_name": "refresh_access_token",
         "line": 6, "resolved": 0},
        {"edge_type": "import", "src_kind": "file", "src_id": fid_b,
         "dst_kind": None, "dst_id": None, "dst_name": "auth.token",
         "line": 1, "resolved": 0},
    ])

    assert len(repo.unresolved_edges(db.conn)) == 2
    assert repo.symbol_id_for_unique_name(db.conn, "refresh_access_token") == target_id
    assert repo.symbol_id_for_unique_name(db.conn, "nope") is None
    suffix_rows = repo.files_with_suffix(db.conn, "auth/token.py")
    assert [r["id"] for r in suffix_rows] == [fid_a]
    assert repo.file_by_path(db.conn, "src/api/service.py")["id"] == fid_b

    # resolve both edges, recompute degrees
    repo.resolve_edge(db.conn, repo.unresolved_edges(db.conn)[0]["id"], "symbol", target_id)
    repo.recompute_degrees(db.conn)
    assert repo.count_resolved_edges(db.conn) == 1
    rows = repo.incoming_edges(db.conn, "symbol", target_id)
    assert rows and rows[0]["src_id"] == caller_id
    out = repo.outgoing_edges(db.conn, "symbol", caller_id)
    assert out and out[0]["dst_id"] == target_id
    assert [r["id"] for r in repo.symbols_in_file(db.conn, fid_a)] == [target_id]
    db.close()


def test_path_mtimes_returns_indexed_paths(tmp_path):
    db = _open(tmp_path)
    repo.upsert_file(
        db.conn, path="src/a.py", lang="python", size_bytes=1, sha256="a",
        mtime_ns=111, git_status=None, parser="line", indexed_at="t", is_generated=False,
    )
    repo.upsert_file(
        db.conn, path="src/b.py", lang="python", size_bytes=1, sha256="b",
        mtime_ns=222, git_status=None, parser="line", indexed_at="t", is_generated=False,
    )
    mtimes = repo.path_mtimes(db.conn)
    assert mtimes == {"src/a.py": 111, "src/b.py": 222}
    db.close()


def test_fingerprints_returns_mtime_size_and_sha(tmp_path):
    db = _open(tmp_path)
    repo.upsert_file(
        db.conn, path="src/a.py", lang="python", size_bytes=10, sha256="aaa",
        mtime_ns=111, git_status=None, parser="line", indexed_at="t", is_generated=False,
    )
    repo.upsert_file(
        db.conn, path="src/b.py", lang="python", size_bytes=20, sha256="bbb",
        mtime_ns=222, git_status=None, parser="line", indexed_at="t", is_generated=False,
    )
    fps = repo.fingerprints(db.conn)
    assert fps == {
        "src/a.py": (111, 10, "aaa"),
        "src/b.py": (222, 20, "bbb"),
    }
    db.close()


def _create_vec_tables(conn):
    # Plain stand-ins matching the vec0 layout: every function under test runs
    # ordinary SQL against these tables, so the optional sqlite-vec extension
    # is not needed to exercise the cache/meta/orphan logic.
    conn.execute("CREATE TABLE vec_chunks (chunk_id INTEGER PRIMARY KEY, embedding BLOB)")
    conn.execute("CREATE TABLE vec_meta (model TEXT, dim INTEGER, built_at TEXT)")
    conn.execute(
        "CREATE TABLE vec_cache (model TEXT NOT NULL, content_sha TEXT NOT NULL, "
        "embedding BLOB NOT NULL, PRIMARY KEY (model, content_sha))"
    )


def test_vec_meta_roundtrip_replaces_previous_row(tmp_path):
    db = _open(tmp_path)
    _create_vec_tables(db.conn)
    assert repo.get_vec_meta(db.conn) is None
    repo.set_vec_meta(db.conn, model="m1", dim=4, built_at="2026-06-09T00:00:00Z")
    repo.set_vec_meta(db.conn, model="m2", dim=8, built_at="2026-06-09T01:00:00Z")
    row = repo.get_vec_meta(db.conn)
    assert (row["model"], row["dim"]) == ("m2", 8)
    db.close()


def test_embedding_cache_roundtrip_dedup_and_batching(tmp_path):
    db = _open(tmp_path)
    _create_vec_tables(db.conn)
    assert repo.cached_embeddings(db.conn, model="m", shas=[]) == {}
    items = [(f"sha{i}", f"blob{i}".encode()) for i in range(600)]
    repo.store_cached_embeddings(db.conn, model="m", items=items)
    repo.store_cached_embeddings(db.conn, model="m", items=[])  # no-op
    # 600 shas exercise the >500 IN-list chunking; duplicates collapse to one.
    shas = [sha for sha, _ in items] + ["sha0", "missing"]
    out = repo.cached_embeddings(db.conn, model="m", shas=shas)
    assert len(out) == 600
    assert out["sha0"] == b"blob0"
    # The cache is keyed by model: another model sees nothing.
    assert repo.cached_embeddings(db.conn, model="other", shas=["sha0"]) == {}
    db.close()


def test_vector_blob_upsert_count_and_clear(tmp_path):
    db = _open(tmp_path)
    _create_vec_tables(db.conn)
    repo.upsert_chunk_vector_blob(db.conn, 1, b"v1")
    repo.upsert_chunk_vector_blob(db.conn, 1, b"v2")  # replaces, no duplicate
    repo.upsert_chunk_vector_blob(db.conn, 2, b"v3")
    assert repo.count_vectors(db.conn) == 2
    assert repo.embedded_chunk_ids(db.conn) == {1, 2}
    repo.clear_vectors(db.conn)
    assert repo.count_vectors(db.conn) == 0
    db.close()


def test_vector_helpers_tolerate_missing_vec_tables(tmp_path):
    db = _open(tmp_path)
    assert repo.embedded_chunk_ids(db.conn) == set()
    assert repo.prune_orphan_vectors(db.conn) == 0
    db.close()


def test_chunks_for_embedding_and_prune_orphans(tmp_path):
    db = _open(tmp_path)
    _create_vec_tables(db.conn)
    fid = repo.upsert_file(
        db.conn, path="src/a.py", lang="python", size_bytes=1, sha256="a",
        mtime_ns=111, git_status=None, parser="line", indexed_at="t", is_generated=False,
    )
    repo.replace_chunks(
        db.conn,
        fid,
        [
            Chunk(line_start=1, line_end=5, content="def a(): ...", token_est=5),
            Chunk(line_start=6, line_end=9, content="def b(): ...", token_est=5),
        ],
    )
    rows = repo.chunks_for_embedding(db.conn)
    assert [r["content"] for r in rows] == ["def a(): ...", "def b(): ..."]

    live_ids = [int(r["id"]) for r in rows]
    for cid in live_ids:
        repo.upsert_chunk_vector_blob(db.conn, cid, b"vec")
    repo.upsert_chunk_vector_blob(db.conn, 9999, b"orphan")
    assert repo.prune_orphan_vectors(db.conn) == 1
    assert repo.embedded_chunk_ids(db.conn) == set(live_ids)
    db.close()
