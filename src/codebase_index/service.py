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
from contextlib import contextmanager
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Iterator, Optional, Sequence, Union

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
    session: Optional[str] = None,
) -> dict:
    """One search session: open the DB (vector-enabled when the backend is
    live), run retrieval, return the payload dict both surfaces serialize.

    ``raw`` forces full snippets; otherwise snippets are skeletonized when
    ``cfg.retrieval.compact_snippets`` is on (the default).

    ``session`` names one agent context for evidence reuse (docs/MEMORY.md);
    ``ValueError`` for a malformed tag. Without it the packet is the plain
    retrieval packet, plus ``stale`` on any result whose index text no longer
    matches the working tree."""
    from .retrieval.pipeline import search as run_search
    from .storage.db import Database

    compact = cfg.retrieval.compact_snippets and not raw
    tag = session_tag(session)
    enabled = memory_enabled(cfg)
    with Database(db_path) as db:
        if backend is not None and getattr(backend, "enabled", False):
            db.enable_vectors()
        with _evidence(cfg, tag, enabled, db.conn) as evidence:
            payload = run_search(
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
                evidence=evidence,
            )
    if tag is not None and not enabled:
        payload["memory"] = {"session": tag, "available": False, "reason": "memory is disabled"}
    return payload


def memory_enabled(cfg: "Config") -> bool:
    """Evidence memory is on unless the config disables it or ``CBX_MEMORY=0``."""
    if os.environ.get("CBX_MEMORY", "").strip() == "0":
        return False
    return bool(cfg.memory.enabled)


def memory_path_for(cfg: "Config") -> Path:
    """``CBX_MEMORY_PATH``, else next to a ``CBX_DB_PATH`` override, else the cache dir."""
    override = os.environ.get("CBX_MEMORY_PATH")
    if override:
        return Path(override)
    db_override = os.environ.get("CBX_DB_PATH")
    if db_override:
        return Path(db_override).with_name("memory.sqlite")
    return cache_dir_for(cfg) / "memory.sqlite"


def session_tag(session: Optional[str]) -> Optional[str]:
    """Validated session tag, or None. Sessions are only ever named explicitly."""
    if session is None or not session.strip():
        return None
    from .memory.identity import validate_session_tag

    return validate_session_tag(session)


@contextmanager
def _evidence(cfg: "Config", tag: Optional[str], enabled: bool,
              conn: sqlite3.Connection) -> Iterator[Any]:
    if not enabled:
        yield None
        return
    from .memory.session import open_evidence

    with open_evidence(
        root=Path(cfg.root), config=cfg, memory_path=memory_path_for(cfg), tag=tag,
        index_conn=conn,
    ) as processor:
        yield processor


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


def verify_payload(
    cfg: "Config", refs: Sequence[str], session: Optional[str] = None
) -> dict[str, Any]:
    """Re-check evidence references and/or everything one session was given.

    Read-only: nothing is recorded, so it is safe to run at any time and from any agent.
    References are untrusted input and are validated before any file is read.
    """
    from .discovery.gates import PathGate
    from .memory import identity as ident
    from .memory.store import MemoryStore, MemoryUnavailable
    from .memory.validate import WorkingTree, validate

    tag = session_tag(session)
    root = Path(cfg.root)
    repo_id = ident.repo_id_for(root)
    tree = WorkingTree(PathGate(root, cfg))
    enabled = memory_enabled(cfg)
    path = memory_path_for(cfg)
    store: Optional[MemoryStore] = None
    store_problem: Optional[str] = None
    if enabled and path.exists():
        try:
            store = MemoryStore.open(path)
        except MemoryUnavailable as exc:
            store_problem = str(exc)

    evidence: list[dict] = []
    errors: list[dict] = []
    session_block: Optional[dict[str, Any]] = None
    try:
        for text in refs:
            try:
                ref = ident.parse_ref(text)
            except ValueError as exc:
                errors.append({"ref": text, "error": str(exc)})
                continue
            hint = store.first_line_hint(repo_id, ref.path, ref.sha) if store else None
            evidence.append(validate(ref, tree, first_line_sha=hint).as_dict())
        if tag is not None:
            session_block = {"session": tag}
            session_id = None
            if not enabled:
                session_block.update(available=False, reason="memory is disabled")
            elif store_problem is not None:
                session_block.update(available=False, reason=store_problem)
            elif store is not None:
                session_id = store.find_session(repo_id, ident.session_key(repo_id, tag))
            session_block["found"] = session_id is not None
            if store is not None and session_id is not None:
                delivered = store.delivered(session_id)
                session_block["evidence"] = len(delivered)
                for item in delivered:
                    ref = ident.EvidenceRef(item.path, item.line_start, item.line_end,
                                            item.span_sha)
                    evidence.append(
                        validate(ref, tree, first_line_sha=item.first_line_sha).as_dict())
    finally:
        if store is not None:
            store.close()

    summary: dict[str, int] = {}
    for verdict in evidence:
        summary[verdict["state"]] = summary.get(verdict["state"], 0) + 1
    payload: dict[str, Any] = {
        "all_valid": bool(evidence) and not errors and all(v["valid"] for v in evidence),
        "summary": summary,
    }
    if session_block is not None:
        payload["session"] = session_block
    payload["evidence"] = evidence
    payload["errors"] = errors
    return payload


def memory_status_payload(cfg: "Config") -> dict[str, Any]:
    """Evidence-memory health and counters for this repository (no paths, no content)."""
    from .memory.identity import repo_id_for
    from .memory.store import MemoryStore, MemoryUnavailable

    path = memory_path_for(cfg)
    block: dict[str, Any] = {"enabled": memory_enabled(cfg), "exists": path.exists()}
    if not block["exists"]:
        return block
    try:
        with MemoryStore.open(path) as store:
            block.update(store.stats(repo_id_for(Path(cfg.root))))
            if store.recovered_from:
                block["recovered_from"] = store.recovered_from
    except MemoryUnavailable as exc:
        block.update(available=False, reason=str(exc))
    return block


def memory_gc_payload(cfg: "Config") -> dict[str, Any]:
    """Apply retention and size limits, drop orphan atoms, and compact the store."""
    from .memory.identity import repo_id_for
    from .memory.store import MemoryStore, utc_now

    path = memory_path_for(cfg)
    if not path.exists():
        return {"exists": False}
    with MemoryStore.open(path) as store:
        removed = store.gc(now=utc_now(), retention_days=cfg.memory.retention_days,
                           max_deliveries=cfg.memory.max_deliveries)
        store.vacuum()
        return {"exists": True, **removed, **store.stats(repo_id_for(Path(cfg.root)))}


def memory_clear_payload(cfg: "Config", session: Optional[str] = None) -> dict[str, Any]:
    """Forget one session, or all evidence memory for this repository."""
    from .memory import identity as ident
    from .memory.store import MemoryStore

    tag = session_tag(session)
    path = memory_path_for(cfg)
    if not path.exists():
        return {"exists": False, "removed_sessions": 0, "session": tag}
    repo_id = ident.repo_id_for(Path(cfg.root))
    with MemoryStore.open(path) as store:
        removed = store.clear(repo_id, ident.session_key(repo_id, tag) if tag else None)
        if tag is None:
            store.vacuum()
    return {"exists": True, "removed_sessions": removed, "session": tag}


def stats_payload(conn: sqlite3.Connection, cfg: Optional["Config"] = None) -> dict[str, Any]:
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
    payload: dict[str, Any] = {
        "files": repo.count_files(conn),
        "symbols": repo.count_symbols(conn),
        "built_at": repo.get_meta(conn, "built_at"),
        "head_commit": repo.get_meta(conn, "head_commit"),
        "treesitter_coverage": coverage,
        "exists": True,
    }
    if cfg is not None:
        payload["memory"] = memory_status_payload(cfg)
    return payload
