from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from codebase_index.storage.db import Database

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "sample_repo"


@pytest.fixture
def sample_repo() -> Path:
    assert FIXTURE_ROOT.is_dir(), "run the M1 fixture-build steps first"
    return FIXTURE_ROOT


def _insert_file(conn: sqlite3.Connection, *, path: str, lang: str, mtime_ns: int,
                 is_generated: bool = False, parser: str = "treesitter") -> int:
    conn.execute(
        "INSERT INTO files (path, lang, size_bytes, sha256, mtime_ns, git_status, "
        "parser, indexed_at, is_generated) VALUES (?,?,?,?,?,?,?,?,?)",
        (path, lang, 100, "deadbeef", mtime_ns, "clean", parser, "2026-05-29T00:00:00Z",
         1 if is_generated else 0),
    )
    return int(conn.execute("SELECT id FROM files WHERE path = ?", (path,)).fetchone()[0])


def _insert_chunk(conn: sqlite3.Connection, file_id: int, *, line_start: int,
                  line_end: int, content: str, kind: str = "window") -> int:
    token_est = max(1, len(content) // 4)
    conn.execute(
        "INSERT INTO chunks (file_id, line_start, line_end, kind, symbol_id, content, "
        "token_est) VALUES (?,?,?,?,NULL,?,?)",
        (file_id, line_start, line_end, kind, content, token_est),
    )
    return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])


def _insert_symbol(conn: sqlite3.Connection, file_id: int, *, name: str, kind: str,
                   line_start: int, line_end: int, signature: str,
                   in_degree: int = 0, out_degree: int = 0) -> None:
    conn.execute(
        "INSERT INTO symbols (file_id, name, qualified, kind, line_start, line_end, "
        "signature, parent_id, docstring, in_degree, out_degree) "
        "VALUES (?,?,?,?,?,?,?,NULL,NULL,?,?)",
        (file_id, name, name, kind, line_start, line_end, signature, in_degree, out_degree),
    )


@pytest.fixture
def seeded_index(tmp_path) -> Database:
    """Deterministic in-tree index: files + chunks (+fts via triggers) + symbols.

    Retrieval logic is tested against this, not the indexer, so symbol coverage
    is independent of M3 pipeline wiring.
    """
    db = Database(tmp_path / "index.sqlite")
    db.open()
    conn = db.conn

    auth = _insert_file(conn, path="src/auth/token.py", lang="python", mtime_ns=5000)
    _insert_chunk(conn, auth, line_start=1, line_end=6,
                  content="def refresh_access_token(refresh_token):\n"
                          "    # exchange a refresh token for a new access token\n"
                          "    return mint(refresh_token)\n", kind="symbol_body")
    _insert_symbol(conn, auth, name="refresh_access_token", kind="function",
                   line_start=1, line_end=6,
                   signature="def refresh_access_token(refresh_token)", in_degree=4)

    user = _insert_file(conn, path="src/models/user.py", lang="python", mtime_ns=4000)
    _insert_chunk(conn, user, line_start=1, line_end=4,
                  content="class User:\n    def __init__(self, name):\n        self.name = name\n",
                  kind="symbol_body")
    _insert_symbol(conn, user, name="User", kind="class", line_start=1, line_end=4,
                   signature="class User", in_degree=9)

    notes = _insert_file(conn, path="docs/notes.md", lang="markdown", mtime_ns=3000)
    _insert_chunk(conn, notes, line_start=1, line_end=3,
                  content="token token token refresh token access token notes about token\n")
    _insert_chunk(conn, notes, line_start=4, line_end=6,
                  content="refresh refresh refresh access access access token token token\n")
    _insert_chunk(conn, notes, line_start=7, line_end=9,
                  content="token refresh access token refresh access token refresh access\n")

    gen = _insert_file(conn, path="src/schema.generated.ts", lang="typescript",
                       mtime_ns=6000, is_generated=True)
    _insert_chunk(conn, gen, line_start=1, line_end=2,
                  content="export type Token = { refresh_access_token: string }\n")
    _insert_symbol(conn, gen, name="Token", kind="type", line_start=1, line_end=2,
                   signature="type Token")

    conn.commit()
    yield db
    db.close()