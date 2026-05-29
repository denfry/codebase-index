"""Global graph pass: resolve unresolved edges against the whole repo and
denormalize symbol degrees.

Runs once after all files are indexed (it needs the complete symbol/file tables).
Symbol-target edges (call/reference/extends/implements) resolve only on an
UNAMBIGUOUS name match — if two definitions share a name, the edge is left
unresolved rather than guessed. Import edges resolve their module path to a file
by POSIX path-suffix match (e.g. 'auth.token' -> '%/auth/token.py').
"""

from __future__ import annotations

import sqlite3
from typing import Optional

from ..storage import repo

_SYMBOL_EDGE_TYPES = {"call", "reference", "extends", "implements"}


def build_graph(conn: sqlite3.Connection) -> dict[str, int]:
    resolved = resolve_edges(conn)
    repo.recompute_degrees(conn)
    total_unresolved = len(repo.unresolved_edges(conn))
    return {"resolved": resolved, "unresolved": total_unresolved}


def resolve_edges(conn: sqlite3.Connection) -> int:
    resolved = 0
    for edge in repo.unresolved_edges(conn):
        name = edge["dst_name"]
        if edge["edge_type"] == "import":
            file_id = _module_to_file_id(conn, name)
            if file_id is not None:
                repo.resolve_edge(conn, edge["id"], "file", file_id)
                resolved += 1
        elif edge["edge_type"] in _SYMBOL_EDGE_TYPES:
            sym_id = repo.symbol_id_for_unique_name(conn, name)
            if sym_id is not None:
                repo.resolve_edge(conn, edge["id"], "symbol", sym_id)
                resolved += 1
    return resolved


def _module_to_file_id(conn: sqlite3.Connection, module: str) -> Optional[int]:
    """Resolve a dotted/slashed module path to a unique file id, or None."""
    base = module.replace(".", "/").strip("/")
    if not base:
        return None
    for suffix in (f"{base}.py", f"{base}.ts", f"{base}.js",
                   f"{base}/__init__.py", f"{base}/index.ts", f"{base}/index.js"):
        rows = repo.files_with_suffix(conn, suffix)
        if len(rows) == 1:
            return int(rows[0]["id"])
    return None
