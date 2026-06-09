"""Global graph pass: resolve unresolved edges against the whole repo and
denormalize symbol degrees.

Runs once after all files are indexed (it needs the complete symbol/file tables).
Symbol-target edges (call/reference/extends/implements) resolve only on an
UNAMBIGUOUS name match — if two definitions share a name, the edge is left
unresolved rather than guessed. Import edges resolve their module path to a file
by POSIX path-suffix match (e.g. 'auth.token' -> '%/auth/token.py').

The pass is batched: one query for globally-unique symbol names, one for file
paths (expanded into an in-memory suffix map), one executemany for the updates.
The per-edge variant did an indexed lookup per symbol edge and up to ~20
full-table LIKE scans per import edge, which dominated large builds.
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
    edges = repo.unresolved_edges(conn)
    if not edges:
        return 0

    unique_symbols = repo.unique_symbol_ids_by_name(conn)
    suffix_map = _path_suffix_map(repo.all_file_ids_with_paths(conn))

    resolutions: list[tuple[str, int, int]] = []
    for edge in edges:
        name = edge["dst_name"]
        if edge["edge_type"] == "import":
            file_id = _module_to_file_id(suffix_map, name)
            if file_id is not None:
                resolutions.append(("file", file_id, edge["id"]))
        elif edge["edge_type"] in _SYMBOL_EDGE_TYPES:
            sym_id = unique_symbols.get(name)
            if sym_id is not None:
                resolutions.append(("symbol", sym_id, edge["id"]))

    repo.resolve_edges_bulk(conn, resolutions)
    return len(resolutions)


def _path_suffix_map(rows: list[sqlite3.Row]) -> dict[str, Optional[int]]:
    """Map every '/'-aligned path suffix to its file id, or None when ambiguous.

    Mirrors files_with_suffix(path = suffix OR path LIKE '%/suffix') semantics:
    a suffix shared by several files resolves to None (like a multi-row result),
    and matching is case-insensitive the way SQLite LIKE folds ASCII.
    """
    mapping: dict[str, Optional[int]] = {}
    for row in rows:
        parts = row["path"].lower().split("/")
        for i in range(len(parts)):
            suffix = "/".join(parts[i:])
            mapping[suffix] = None if suffix in mapping else int(row["id"])
    return mapping


def _module_to_file_id(
    suffix_map: dict[str, Optional[int]], module: str
) -> Optional[int]:
    """Resolve a module/import path to a unique file id, or None.

    Handles Python, TypeScript/JavaScript, Java/Kotlin/Scala, Rust (:: separator),
    Go (last path segment), C#, Ruby, and PHP import conventions.
    """
    base = module.lower().replace(".", "/").strip("/")
    rust_base = module.lower().replace("::", "/").strip("/")
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
        file_id = suffix_map.get(suffix)
        if file_id is not None:
            return file_id
    return None
