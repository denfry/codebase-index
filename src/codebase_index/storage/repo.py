"""Typed read/write accessors. All SQL lives here."""

from __future__ import annotations

import sqlite3
from typing import Iterable, Optional, Sequence

from ..parsers.base import Chunk


def upsert_file(
    conn: sqlite3.Connection,
    *,
    path: str,
    lang: Optional[str],
    size_bytes: int,
    sha256: str,
    mtime_ns: int,
    git_status: Optional[str],
    parser: str,
    indexed_at: str,
    is_generated: bool,
) -> int:
    """Insert or update a file row keyed by repo-relative path."""
    conn.execute(
        """
        INSERT INTO files
            (path, lang, size_bytes, sha256, mtime_ns, git_status, parser, indexed_at, is_generated)
        VALUES
            (:path, :lang, :size_bytes, :sha256, :mtime_ns, :git_status, :parser, :indexed_at, :is_generated)
        ON CONFLICT(path) DO UPDATE SET
            lang = excluded.lang,
            size_bytes = excluded.size_bytes,
            sha256 = excluded.sha256,
            mtime_ns = excluded.mtime_ns,
            git_status = excluded.git_status,
            parser = excluded.parser,
            indexed_at = excluded.indexed_at,
            is_generated = excluded.is_generated
        """,
        {
            "path": path,
            "lang": lang,
            "size_bytes": size_bytes,
            "sha256": sha256,
            "mtime_ns": mtime_ns,
            "git_status": git_status,
            "parser": parser,
            "indexed_at": indexed_at,
            "is_generated": 1 if is_generated else 0,
        },
    )
    row = conn.execute("SELECT id FROM files WHERE path = ?", (path,)).fetchone()
    return int(row[0])


def get_file(conn: sqlite3.Connection, path: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM files WHERE path = ?", (path,)).fetchone()


def all_paths(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT path FROM files")}


def delete_files(conn: sqlite3.Connection, paths: Iterable[str]) -> int:
    paths = list(paths)
    if not paths:
        return 0
    before = conn.total_changes
    conn.executemany("DELETE FROM files WHERE path = ?", [(p,) for p in paths])
    return conn.total_changes - before


def count_files(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM files").fetchone()[0])


def get_meta(conn: sqlite3.Connection, key: str) -> Optional[str]:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )


def replace_chunks(
    conn: sqlite3.Connection, file_id: int, chunks: Sequence[Chunk]
) -> int:
    conn.execute("DELETE FROM chunks WHERE file_id = ?", (file_id,))
    conn.executemany(
        """
        INSERT INTO chunks
            (file_id, line_start, line_end, kind, symbol_id, content, token_est)
        VALUES
            (?, ?, ?, ?, NULL, ?, ?)
        """,
        [
            (file_id, c.line_start, c.line_end, c.kind, c.content, c.token_est)
            for c in chunks
        ],
    )
    return len(chunks)


def chunks_for_file(conn: sqlite3.Connection, file_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM chunks WHERE file_id = ? ORDER BY line_start", (file_id,)
    ).fetchall()


def count_chunks(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])


def fts_search(
    conn: sqlite3.Connection, match_query: str, *, limit: int
) -> list[sqlite3.Row]:
    if not match_query.strip():
        return []
    return conn.execute(
        """
        SELECT c.id             AS chunk_id,
               f.path           AS path,
               c.line_start     AS line_start,
               c.line_end       AS line_end,
               c.content        AS content,
               c.token_est      AS token_est,
               bm25(fts_chunks) AS bm25
        FROM fts_chunks
        JOIN chunks c ON c.id = fts_chunks.rowid
        JOIN files f ON f.id = c.file_id
        WHERE fts_chunks MATCH ?
        ORDER BY bm25(fts_chunks)
        LIMIT ?
        """,
        (match_query, limit),
    ).fetchall()
