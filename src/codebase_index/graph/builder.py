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
    # Everything still unresolved that names a target is, by definition, a target we
    # could not pin to a unique node — record it as 'ambiguous' for the honesty trail.
    repo.mark_ambiguous_edges(conn)
    total_unresolved = len(repo.unresolved_edges(conn))
    # Architecture analytics (communities / god nodes / surprising bridges) are a
    # derived view of the graph. Compute once per build and cache the JSON in meta so
    # the `architecture` command and the HTML export read it instantly. Never let an
    # analysis failure fail the build — the graph itself is already written.
    try:
        from . import analysis

        analysis.refresh_analysis(conn)
    except Exception:  # pragma: no cover - defensive; analytics are best-effort
        pass
    return {"resolved": resolved, "unresolved": total_unresolved}


def resolve_edges(conn: sqlite3.Connection) -> int:
    edges = repo.unresolved_edges(conn)
    if not edges:
        return 0

    unique_symbols = repo.unique_symbol_ids_by_name(conn)
    suffix_map = _path_suffix_map(repo.all_file_ids_with_paths(conn))

    # (dst_kind, dst_id, edge_id, confidence). A repo-unique symbol name is an exact
    # hit -> 'extracted'; an import resolved only by path-suffix matching is a best-
    # effort heuristic -> 'inferred'.
    resolutions: list[tuple[str, int, int, str]] = []
    for edge in edges:
        name = edge["dst_name"]
        if edge["edge_type"] == "import":
            file_id = _module_to_file_id(suffix_map, name, lang=edge["lang"])
            if file_id is not None:
                resolutions.append(("file", file_id, edge["id"], "inferred"))
        elif edge["edge_type"] in _SYMBOL_EDGE_TYPES:
            sym_id = unique_symbols.get(name)
            if sym_id is not None:
                resolutions.append(("symbol", sym_id, edge["id"], "extracted"))

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


def _lang_suffixes(lang: Optional[str], base: str, rust_base: str, go_pkg: str) -> list[str]:
    """Import-path suffixes specific to one language, most-specific first."""
    return {
        "python": [f"{base}.py", f"{base}/__init__.py"],
        "typescript": [f"{base}.ts", f"{base}.tsx", f"{base}/index.ts", f"{base}/index.tsx"],
        "javascript": [f"{base}.js", f"{base}/index.js"],
        "java": [f"{base}.java"],
        "kotlin": [f"{base}.kt"],
        "go": [f"{go_pkg}.go"],
        "rust": [
            f"{rust_base}.rs", f"{rust_base}/mod.rs",
            f"src/{rust_base}.rs", f"src/{rust_base}/mod.rs",
        ],
        "csharp": [f"{base}.cs"],
        "ruby": [f"{base}.rb"],
        "php": [f"{base}.php"],
    }.get(lang or "", [])


def _module_to_file_id(
    suffix_map: dict[str, Optional[int]], module: str, lang: Optional[str] = None
) -> Optional[int]:
    """Resolve a module/import path to a unique file id, or None.

    Handles Python, TypeScript/JavaScript, Java/Kotlin/Scala, Rust (:: separator),
    Go (last path segment), C#, Ruby, and PHP import conventions. The importing
    file's `lang` is tried first so that, in a polyglot repo, `import './base'` from
    a .ts file resolves to base.ts rather than a same-named base.py earlier in the
    fixed fallback order. The fallback order is unchanged, so single-language repos
    and the lang-unknown path behave exactly as before.
    """
    base = module.lower().replace(".", "/").strip("/")
    rust_base = module.lower().replace("::", "/").strip("/")
    if not base:
        return None
    # Last segment used for Go package-level resolution
    go_pkg = base.rsplit("/", 1)[-1] if "/" in base else base

    fallback = (
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
    )
    for suffix in (*_lang_suffixes(lang, base, rust_base, go_pkg), *fallback):
        file_id = suffix_map.get(suffix)
        if file_id is not None:
            return file_id
    return None
