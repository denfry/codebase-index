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
import subprocess
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
    raw: bool = False,
) -> dict:
    """One search session: open the DB (vector-enabled when the backend is
    live), run retrieval, return the payload dict both surfaces serialize.

    ``raw`` forces full snippets; otherwise snippets are skeletonized when
    ``cfg.retrieval.compact_snippets`` is on (the default)."""
    from .retrieval.pipeline import search as run_search
    from .storage.db import Database

    compact = cfg.retrieval.compact_snippets and not raw
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
            compact=compact,
            compact_min_reduction=cfg.retrieval.compact_min_reduction,
        )


def diff_impact_payload(
    db_path: Path,
    cfg: "Config",
    *,
    base_ref: str = "HEAD",
    depth: int = 2,
    direction: str = "up",
    max_files: int = 200,
) -> dict[str, Any]:
    """Aggregate graph impact for files changed relative to a Git commit.

    Git is invoked with argument arrays and a verified commit SHA; no shell is
    involved. The file cap bounds worst-case graph work on very large diffs.
    """
    from .graph.expand import impact_lookup
    from .indexer.freshness import compute_freshness
    from .storage.db import Database

    if direction not in {"up", "down", "both"}:
        raise ValueError("direction must be one of: up, down, both")
    if depth < 1:
        raise ValueError("depth must be >= 1")
    if max_files < 1:
        raise ValueError("max_files must be >= 1")
    if not base_ref or base_ref.startswith("-") or "\x00" in base_ref:
        raise ValueError("base_ref must be a non-option Git revision")

    root = Path(cfg.root).resolve()
    resolved = subprocess.run(
        ["git", "-C", str(root), "rev-parse", "--verify", "--end-of-options",
         f"{base_ref}^{{commit}}"],
        capture_output=True,
        text=True,
        timeout=10,
        check=False,
    )
    if resolved.returncode != 0:
        detail = (resolved.stderr or resolved.stdout).strip()
        raise ValueError(f"cannot resolve Git base {base_ref!r}: {detail or 'unknown revision'}")
    base_commit = resolved.stdout.strip()

    changed = subprocess.run(
        ["git", "-C", str(root), "diff", "--name-only", "--diff-filter=ACDMR",
         base_commit, "--"],
        capture_output=True,
        text=True,
        timeout=20,
        check=False,
    )
    if changed.returncode != 0:
        detail = (changed.stderr or changed.stdout).strip()
        raise RuntimeError(f"git diff failed: {detail or 'unknown error'}")

    normalized_changed = list(dict.fromkeys(
        line.strip().replace("\\", "/")
        for line in changed.stdout.splitlines()
        if line.strip()
    ))
    try:
        own_cache = cache_dir_for(cfg).resolve().relative_to(root).as_posix()
    except ValueError:
        own_cache = ""
    all_changed = [
        path for path in normalized_changed
        if not own_cache
        or (path != own_cache and not path.startswith(f"{own_cache}/"))
    ]
    truncated = len(all_changed) > max_files
    targets = all_changed[:max_files]

    affected: dict[str, dict[str, Any]] = {}
    unresolved: list[str] = []
    coverage_languages: set[str] = set()
    coverage_reasons: list[str] = []

    with Database(db_path) as db:
        freshness = compute_freshness(db.conn, root, cfg).model_dump()
        for target in targets:
            impact = impact_lookup(
                db.conn, target, depth=depth, direction=direction
            )
            if not impact.nodes and not impact.files:
                # A tracked file can be new, deleted after the last update, or
                # excluded by the security/discovery gates.
                from .storage import repo
                if repo.file_by_path(db.conn, target) is None:
                    unresolved.append(target)
            if impact.coverage.partial:
                coverage_languages.update(impact.coverage.languages)
                if impact.coverage.reason:
                    coverage_reasons.append(impact.coverage.reason)
            for node in impact.nodes:
                current = affected.get(node.path)
                candidate = {
                    "path": node.path,
                    "distance": node.distance,
                    "changed_by": [target],
                    "via_edge": node.via_edge,
                    "via_confidence": node.via_confidence,
                }
                if current is None:
                    affected[node.path] = candidate
                else:
                    if target not in current["changed_by"]:
                        current["changed_by"].append(target)
                    if node.distance < current["distance"]:
                        current.update({
                            "distance": node.distance,
                            "via_edge": node.via_edge,
                            "via_confidence": node.via_confidence,
                        })

    ranked = sorted(
        affected.values(),
        key=lambda item: (item["distance"], item["path"]),
    )
    return {
        "base_ref": base_ref,
        "base_commit": base_commit,
        "direction": direction,
        "depth": depth,
        "index": freshness,
        "changed_files": targets,
        "changed_files_total": len(all_changed),
        "truncated": truncated,
        "unresolved_files": unresolved,
        "affected_files": ranked,
        "coverage": {
            "partial": bool(coverage_languages),
            "languages": sorted(coverage_languages),
            "reason": " ".join(dict.fromkeys(coverage_reasons)) or None,
        },
    }


def architecture_payload(db_path: Path, cfg: "Config") -> dict[str, Any]:
    """The cached architecture analytics (communities / god nodes / surprising /
    questions) plus index freshness — the payload both CLI and MCP serialize.

    Returns ``available: False`` when no analysis is cached (an index built before
    this feature, or an empty graph); the caller tells the user to reindex.
    """
    from .graph import analysis
    from .indexer.freshness import compute_freshness
    from .storage.db import Database

    with Database(db_path) as db:
        fresh = compute_freshness(db.conn, Path(cfg.root), cfg)
        summary = analysis.load_analysis(db.conn)
        if summary is None:
            return {
                "exists": True,
                "available": False,
                "reason": (
                    "No architecture analysis cached. Rebuild the index "
                    "(`codebase-index index`) to compute it."
                ),
                "index": fresh.model_dump(),
            }
        return {"exists": True, "available": True, "index": fresh.model_dump(), **summary}


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
