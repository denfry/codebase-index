# tests/test_vectors_storage.py
from __future__ import annotations

import pytest

from codebase_index.storage import repo
from codebase_index.storage.db import Database

pytest.importorskip("sqlite_vec")


def _file_and_chunk(conn, path: str, content: str) -> int:
    fid = repo.upsert_file(
        conn, path=path, lang="python", size_bytes=1, sha256=path, mtime_ns=1,
        git_status=None, parser="treesitter", indexed_at="t", is_generated=False,
    )
    conn.execute(
        "INSERT INTO chunks (file_id, line_start, line_end, kind, symbol_id, content, token_est) "
        "VALUES (?,?,?,?,NULL,?,?)",
        (fid, 1, 3, "window", content, 5),
    )
    return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])


def test_vector_roundtrip_and_knn(tmp_path):
    db = Database(tmp_path / "index.sqlite").open()
    db.enable_vectors()
    repo.ensure_vec_tables(db.conn, dim=3)
    repo.set_vec_meta(db.conn, model="fake", dim=3, built_at="t")

    c_auth = _file_and_chunk(db.conn, "src/auth/token.py", "refresh access token")
    c_user = _file_and_chunk(db.conn, "src/models/user.py", "user profile name")
    repo.upsert_chunk_vector(db.conn, c_auth, [1.0, 0.0, 0.0])
    repo.upsert_chunk_vector(db.conn, c_user, [0.0, 1.0, 0.0])
    db.conn.commit()

    assert repo.count_vectors(db.conn) == 2
    meta = repo.get_vec_meta(db.conn)
    assert meta["model"] == "fake" and meta["dim"] == 3

    rows = repo.vector_search(db.conn, [0.9, 0.1, 0.0], limit=2)
    assert rows[0]["path"] == "src/auth/token.py"
    assert rows[0]["chunk_id"] == c_auth
    assert "content" in rows[0].keys() and rows[0]["line_start"] == 1

    repo.clear_vectors(db.conn)
    assert repo.count_vectors(db.conn) == 0
    assert db.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 2
    db.close()


def test_chunks_for_embedding_lists_content(tmp_path):
    db = Database(tmp_path / "index.sqlite").open()
    cid = _file_and_chunk(db.conn, "a.py", "hello body")
    rows = repo.chunks_for_embedding(db.conn)
    assert any(r["id"] == cid and r["content"] == "hello body" for r in rows)
    db.close()
