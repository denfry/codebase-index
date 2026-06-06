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
    """Resolve a module/import path to a unique file id, or None.

    Handles Python, TypeScript/JavaScript, Java/Kotlin/Scala, Rust (:: separator),
    Go (last path segment), C#, Ruby, and PHP import conventions.
    """
    base = module.replace(".", "/").strip("/")
    rust_base = module.replace("::", "/").strip("/")
    if not base:
        return None
    # Last segment used for Go package-level resolution
    go_pkg = base.rsplit("/", 1)[-1] if "/" in base else base

    for suffix in (
        # Python
        f"{base}.py",
        f"{base}/__init__.py",
        # TypeScript / JavaScript
        f"{base}.ts",
        f"{base}.tsx",
        f"{base}.js",
        f"{base}/index.ts",
        f"{base}/index.tsx",
        f"{base}/index.js",
        # Java / Kotlin / Scala (dot-to-slash already done above)
        f"{base}.java",
        f"{base}.kt",
        f"{base}.scala",
        # Go: resolve last path segment to a .go file of the same name
        f"{go_pkg}.go",
        # Rust: :: separator mapped to /; also try under src/
        f"{rust_base}.rs",
        f"{rust_base}/mod.rs",
        f"src/{rust_base}.rs",
        f"src/{rust_base}/mod.rs",
        # C#
        f"{base}.cs",
        # Ruby
        f"{base}.rb",
        # PHP
        f"{base}.php",
    ):
        rows = repo.files_with_suffix(conn, suffix)
        if len(rows) == 1:
            return int(rows[0]["id"])
    return None
