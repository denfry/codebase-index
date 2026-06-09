"""Shared service layer for the CLI and the MCP server.

Both surfaces drive the same retrieval/storage code; this module owns the
pieces that used to be duplicated and drift apart: the cache-path formula,
db/config resolution, the explain query rewrite, vector-aware search
sessions, and the stats payload (including the per-language graph tier the
skill keys on).
"""

from __future__ import annotations

import os
import sqlite3
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional, Union

if TYPE_CHECKING:
    from .config import Config

_EXPLAIN_HINTS = ("how", "architecture", "overview")


def cache_dir_for(cfg: "Config") -> Path:
    """Per-project cache directory (index DB, graph exports, skill backups)."""
    return Path(cfg.root) / ".claude" / "cache" / "codebase-index"


def db_path_for(cfg: "Config") -> Path:
    """Index location for a resolved config; the CBX_DB_PATH env var overrides."""
    override = os.environ.get("CBX_DB_PATH")
    if override:
        return Path(override)
    return cache_dir_for(cfg) / "index.sqlite"


def resolve_db(root: Optional[Union[Path, str]] = None) -> tuple[Path, "Config"]:
    """Resolve (db_path, config) the same way on every surface.

    The config loads from *root* (CLI --root, MCP CBX_ROOT, else upward
    discovery from cwd); CBX_DB_PATH overrides only the index location.
    """
    from .config import load

    cfg = load(Path(root) if root is not None else None)
    return db_path_for(cfg), cfg


def search_backend(cfg: "Config", warn: Callable[[str], None]) -> Any:
    """Embedding backend for query-time vector search.

    Returns a NoopBackend (enabled=False) when embeddings are off, so callers
    can branch on `backend.enabled`. Network/external gating is enforced by
    resolve_backend (SECURITY.md §4).
    """
    from .embeddings.backend import resolve_backend

    return resolve_backend(cfg, warn=warn)


def normalize_explain_query(query: str) -> str:
    """Rewrite a bare topic into a how-does-X-work question for intent detection."""
    if any(w in query.lower() for w in _EXPLAIN_HINTS):
        return query
    return f"how does {query} work"


def search_payload(
    db_path: Path,
    cfg: "Config",
    query: str,
    *,
    mode: str = "hybrid",
    limit: int = 10,
    offset: int = 0,
    token_budget: int = 1500,
    no_fallback: bool = False,
    backend: Any = None,
) -> dict:
    """One search session: open the DB (vector-enabled when the backend is
    live), run retrieval, return the payload dict both surfaces serialize."""
    from .retrieval.pipeline import search as run_search
    from .storage.db import Database

    with Database(db_path) as db:
        if backend is not None and getattr(backend, "enabled", False):
            db.enable_vectors()
        return run_search(
            db.conn,
            query,
            mode=mode,
            limit=limit,
            offset=offset,
            token_budget=token_budget,
            no_fallback=no_fallback,
            backend=backend,
            root=Path(cfg.root),
            config=cfg,
        )


def stats_payload(conn: sqlite3.Connection) -> dict[str, Any]:
    """Index size, freshness, and per-language coverage with the graph tier."""
    from .parsers.languages import has_full_graph
    from .storage import repo

    coverage = [
        {
            "lang": r["lang"],
            "files": r["files"],
            "symbols": r["symbols"],
            # Tier-A languages get import/inheritance edges; Tier-B is
            # symbols-only, so refs/impact are partial for them.
            "graph": "full" if has_full_graph(r["lang"]) else "partial",
        }
        for r in repo.treesitter_coverage(conn)
    ]
    return {
        "files": repo.count_files(conn),
        "symbols": repo.count_symbols(conn),
        "built_at": repo.get_meta(conn, "built_at"),
        "head_commit": repo.get_meta(conn, "head_commit"),
        "treesitter_coverage": coverage,
        "exists": True,
    }
