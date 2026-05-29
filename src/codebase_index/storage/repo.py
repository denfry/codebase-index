"""Typed read/write accessors. All SQL lives here."""

from __future__ import annotations

import re
import sqlite3
from typing import Any, Iterable, Optional, Sequence

from ..parsers.base import Chunk, Symbol


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
    conn: sqlite3.Connection,
    file_id: int,
    chunks: Sequence[Chunk],
    symbol_ids: Optional[Sequence[int]] = None,
) -> int:
    conn.execute("DELETE FROM chunks WHERE file_id = ?", (file_id,))

    def _symbol_id(chunk: Chunk) -> Optional[int]:
        if chunk.symbol_index is not None and symbol_ids is not None:
            return symbol_ids[chunk.symbol_index]
        return None

    conn.executemany(
        """
        INSERT INTO chunks
            (file_id, line_start, line_end, kind, symbol_id, content, token_est)
        VALUES
            (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (
                file_id,
                c.line_start,
                c.line_end,
                c.kind,
                _symbol_id(c),
                c.content,
                c.token_est,
            )
            for c in chunks
        ],
    )
    return len(chunks)


def append_chunks(
    conn: sqlite3.Connection,
    file_id: int,
    chunks: Sequence[Chunk],
) -> int:
    """Append chunks without deleting existing ones (for doc chunks)."""
    conn.executemany(
        """
        INSERT INTO chunks
            (file_id, line_start, line_end, kind, symbol_id, content, token_est)
        VALUES
            (?, ?, ?, ?, NULL, ?, ?)
        """,
        [
            (
                file_id,
                c.line_start,
                c.line_end,
                c.kind,
                c.content,
                c.token_est,
            )
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


def replace_symbols(
    conn: sqlite3.Connection, file_id: int, symbols: Sequence[Symbol]
) -> list[int]:
    conn.execute("DELETE FROM symbols WHERE file_id = ?", (file_id,))
    ids: list[int] = []
    for symbol in symbols:
        cur = conn.execute(
            """
            INSERT INTO symbols
                (file_id, name, qualified, kind, line_start, line_end, signature,
                 parent_id, docstring, in_degree, out_degree)
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, 0, 0)
            """,
            (
                file_id,
                symbol.name,
                symbol.qualified,
                symbol.kind,
                symbol.line_start,
                symbol.line_end,
                symbol.signature,
                symbol.docstring,
            ),
        )
        assert cur.lastrowid is not None
        ids.append(int(cur.lastrowid))
    for symbol, symbol_id in zip(symbols, ids):
        if symbol.parent_index is not None:
            conn.execute(
                "UPDATE symbols SET parent_id = ? WHERE id = ?",
                (ids[symbol.parent_index], symbol_id),
            )
    return ids


def symbols_by_name(
    conn: sqlite3.Connection,
    name: str,
    *,
    kind: Optional[str] = None,
    exact: bool = True,
) -> list[sqlite3.Row]:
    sql = """
        SELECT s.*, f.path AS path
        FROM symbols s JOIN files f ON f.id = s.file_id
        WHERE s.name {op} ?
    """.format(op="=" if exact else "LIKE")
    params: list[Any] = [name if exact else f"{name}%"]
    if kind:
        sql += " AND s.kind = ?"
        params.append(kind)
    sql += " ORDER BY s.name, f.path, s.line_start"
    return conn.execute(sql, params).fetchall()


def count_symbols(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0])


def replace_edges(
    conn: sqlite3.Connection, file_id: int, edges: Sequence[dict[str, Any]]
) -> int:
    conn.execute("DELETE FROM edges WHERE file_id = ?", (file_id,))
    conn.executemany(
        """
        INSERT INTO edges
            (edge_type, src_kind, src_id, dst_kind, dst_id, dst_name, file_id, line, resolved)
        VALUES
            (:edge_type, :src_kind, :src_id, :dst_kind, :dst_id, :dst_name, :file_id, :line, :resolved)
        """,
        [{**edge, "file_id": file_id} for edge in edges],
    )
    return len(edges)


def count_edges(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0])


def refs_for_name(conn: sqlite3.Connection, name: str) -> list[sqlite3.Row]:
    return conn.execute(
        """
        SELECT e.line AS line, f.path AS path, e.edge_type AS edge_type,
               e.resolved AS resolved, e.src_id AS src_id, e.src_kind AS src_kind,
               src.name AS src_name, src.qualified AS src_qualified
        FROM edges e
        JOIN files f ON f.id = e.file_id
        LEFT JOIN symbols src ON src.id = e.src_id AND e.src_kind = 'symbol'
        WHERE e.dst_name = ? AND e.edge_type = 'call'
        ORDER BY f.path, e.line
        """,
        (name,),
    ).fetchall()


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
               bm25(fts_chunks) AS bm25,
               c.kind           AS kind
        FROM fts_chunks
        JOIN chunks c ON c.id = fts_chunks.rowid
        JOIN files f ON f.id = c.file_id
        WHERE fts_chunks MATCH ?
        ORDER BY bm25(fts_chunks)
        LIMIT ?
        """,
        (match_query, limit),
    ).fetchall()


def path_search(
    conn: sqlite3.Connection, query: str, *, limit: int
) -> list[sqlite3.Row]:
    """Match files whose path contains query tokens. Score = number of tokens hit."""
    tokens = [t for t in re.split(r"[\s/.\\]+", query.strip()) if t]
    if not tokens:
        return []
    score_expr = " + ".join(["(path LIKE ?)"] * len(tokens))
    like_args = [f"%{t}%" for t in tokens]
    return conn.execute(
        f"""
        SELECT id AS file_id, path, mtime_ns, is_generated,
               ({score_expr}) AS hits
        FROM files
        WHERE {' OR '.join(['path LIKE ?'] * len(tokens))}
        ORDER BY hits DESC, length(path) ASC
        LIMIT ?
        """,
        (*like_args, *like_args, limit),
    ).fetchall()


def symbol_search(
    conn: sqlite3.Connection,
    name: str,
    *,
    limit: int,
    kind: Optional[str] = None,
    exact: bool = False,
) -> list[sqlite3.Row]:
    """Symbol lookup: exact name first, then prefix, then substring (fuzzy)."""
    name = name.strip()
    if not name:
        return []
    kind_clause = "AND s.kind = :kind" if kind else ""
    name_clause = "s.name = :exact COLLATE NOCASE" if exact else (
        "(s.name = :exact COLLATE NOCASE "
        "OR s.name LIKE :prefix COLLATE NOCASE "
        "OR s.name LIKE :sub COLLATE NOCASE)"
    )
    return conn.execute(
        f"""
        SELECT s.name, s.kind, s.signature, s.line_start, s.line_end,
               s.in_degree, s.out_degree, f.path, f.mtime_ns, f.is_generated,
               (s.name = :exact COLLATE NOCASE) AS is_exact
        FROM symbols s
        JOIN files f ON f.id = s.file_id
        WHERE {name_clause} {kind_clause}
        ORDER BY is_exact DESC,
                 (s.name LIKE :prefix COLLATE NOCASE) DESC,
                 s.in_degree DESC
        LIMIT :limit
        """,
        {
            "exact": name,
            "prefix": f"{name}%",
            "sub": f"%{name}%",
            "kind": kind,
            "limit": limit,
        },
    ).fetchall()


def unresolved_edges(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id, edge_type, dst_name FROM edges "
        "WHERE resolved = 0 AND dst_name IS NOT NULL ORDER BY id"
    ).fetchall()


def resolve_edge(conn: sqlite3.Connection, edge_id: int, dst_kind: str, dst_id: int) -> None:
    conn.execute(
        "UPDATE edges SET dst_kind = ?, dst_id = ?, resolved = 1 WHERE id = ?",
        (dst_kind, dst_id, edge_id),
    )


def symbol_id_for_unique_name(conn: sqlite3.Connection, name: str) -> Optional[int]:
    rows = conn.execute(
        "SELECT id FROM symbols WHERE name = ? LIMIT 2", (name,)
    ).fetchall()
    return int(rows[0]["id"]) if len(rows) == 1 else None


def files_with_suffix(conn: sqlite3.Connection, suffix: str) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id, path FROM files WHERE path = ? OR path LIKE ? ORDER BY length(path), path",
        (suffix, f"%/{suffix}"),
    ).fetchall()


def file_by_path(conn: sqlite3.Connection, path: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT id, path FROM files WHERE path = ?", (path,)).fetchone()


def symbols_in_file(conn: sqlite3.Connection, file_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id, name, kind, line_start, in_degree FROM symbols "
        "WHERE file_id = ? ORDER BY line_start",
        (file_id,),
    ).fetchall()


def incoming_edges(conn: sqlite3.Connection, kind: str, node_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id, edge_type, src_kind, src_id, file_id, line FROM edges "
        "WHERE resolved = 1 AND dst_kind = ? AND dst_id = ?",
        (kind, node_id),
    ).fetchall()


def outgoing_edges(conn: sqlite3.Connection, kind: str, node_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id, edge_type, dst_kind, dst_id, file_id, line FROM edges "
        "WHERE resolved = 1 AND src_kind = ? AND src_id = ?",
        (kind, node_id),
    ).fetchall()


def recompute_degrees(conn: sqlite3.Connection) -> None:
    conn.execute(
        "UPDATE symbols SET "
        "out_degree = (SELECT COUNT(*) FROM edges "
        "  WHERE resolved = 1 AND src_kind = 'symbol' AND src_id = symbols.id), "
        "in_degree = (SELECT COUNT(*) FROM edges "
        "  WHERE resolved = 1 AND dst_kind = 'symbol' AND dst_id = symbols.id)"
    )


def count_resolved_edges(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM edges WHERE resolved = 1").fetchone()[0])


def ensure_vec_tables(conn: sqlite3.Connection, *, dim: int) -> None:
    """Create vec_chunks (sqlite-vec) + vec_meta if absent. dim is fixed per build."""
    dim = int(dim)
    conn.execute(
        f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0("
        f"chunk_id INTEGER PRIMARY KEY, embedding FLOAT[{dim}])"
    )
    conn.execute("CREATE TABLE IF NOT EXISTS vec_meta (model TEXT, dim INTEGER, built_at TEXT)")


def set_vec_meta(conn: sqlite3.Connection, *, model: str, dim: int, built_at: str) -> None:
    conn.execute("DELETE FROM vec_meta")
    conn.execute(
        "INSERT INTO vec_meta (model, dim, built_at) VALUES (?,?,?)", (model, int(dim), built_at)
    )


def get_vec_meta(conn: sqlite3.Connection) -> "Optional[sqlite3.Row]":
    return conn.execute("SELECT model, dim, built_at FROM vec_meta LIMIT 1").fetchone()


def chunks_for_embedding(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT id, content FROM chunks ORDER BY id").fetchall()


def upsert_chunk_vector(
    conn: sqlite3.Connection, chunk_id: int, embedding: list[float]
) -> None:
    import sqlite_vec  # type: ignore[import-untyped]

    conn.execute("DELETE FROM vec_chunks WHERE chunk_id = ?", (int(chunk_id),))
    conn.execute(
        "INSERT INTO vec_chunks (chunk_id, embedding) VALUES (?, ?)",
        (int(chunk_id), sqlite_vec.serialize_float32(embedding)),
    )


def clear_vectors(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM vec_chunks")


def count_vectors(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM vec_chunks").fetchone()[0])


def path_mtimes(conn: sqlite3.Connection) -> dict[str, int]:
    """Map every indexed file's repo-relative path to its stored mtime_ns."""
    return {
        row["path"]: int(row["mtime_ns"])
        for row in conn.execute("SELECT path, mtime_ns FROM files").fetchall()
    }


def fingerprints(conn: sqlite3.Connection) -> dict[str, tuple[int, int, str]]:
    """Map every indexed path to its (mtime_ns, size_bytes, sha256) for incremental update."""
    return {
        row["path"]: (int(row["mtime_ns"]), int(row["size_bytes"]), row["sha256"])
        for row in conn.execute(
            "SELECT path, mtime_ns, size_bytes, sha256 FROM files"
        ).fetchall()
    }


def vector_search(
    conn: sqlite3.Connection, query_embedding: list[float], *, limit: int
) -> list[sqlite3.Row]:
    """KNN over vec_chunks; joins back to chunks/files for a uniform result row."""
    import sqlite_vec  # type: ignore[import-untyped]

    return conn.execute(
        "SELECT v.chunk_id AS chunk_id, v.distance AS distance, f.path AS path, "
        "       c.line_start AS line_start, c.line_end AS line_end, "
        "       c.content AS content, c.token_est AS token_est "
        "FROM vec_chunks v "
        "JOIN chunks c ON c.id = v.chunk_id "
        "JOIN files f ON f.id = c.file_id "
        "WHERE v.embedding MATCH ? AND k = ? "
        "ORDER BY v.distance",
        (sqlite_vec.serialize_float32(query_embedding), int(limit)),
    ).fetchall()
