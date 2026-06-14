"""Orchestrate the hybrid retrieval pipeline (RETRIEVAL.md §1–§7).

query -> intent -> retrievers -> RRF fuse -> rerank -> budget -> payload.
Graph expansion (§5) and vector retrieval (§2 vector) are deferred to M5/M6.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Optional

from ..config import Config
from ..indexer.freshness import compute_freshness
from . import searchers
from .budget import apply_budget
from .fusion import fuse
from .intent import detect_intent
from .rerank import rerank
from .types import Confidence

_TERM_RE = re.compile(r"[A-Za-z0-9_]+")
_RRF_K = 60
# Max results kept per file before extras are pushed to the tail. Bucketed fusion
# already collapses co-located hits; this caps the long tail of one big file
# dominating the page so distinct files get surfaced.
_MAX_PER_FILE = 3
_KIND_ALIASES = {
    "method": "method",
    "methods": "method",
    "function": "function",
    "functions": "function",
    "class": "class",
    "classes": "class",
    "interface": "interface",
    "interfaces": "interface",
    "enum": "enum",
    "enums": "enum",
    "type": "type",
    "types": "type",
}


def _requested_symbol_kind(query: str) -> str | None:
    kinds = {
        _KIND_ALIASES[t.lower()]
        for t in _TERM_RE.findall(query)
        if t.lower() in _KIND_ALIASES
    }
    return next(iter(kinds)) if len(kinds) == 1 else None


def _run_retrievers(conn, query, *, mode, limit, weights, backend=None):
    lists = {}
    symbol_kind = _requested_symbol_kind(query)
    if mode in ("hybrid", "fts"):
        lists["fts"] = searchers.fts_candidates(conn, query, limit=limit)
    if mode in ("hybrid", "symbol"):
        lists["symbol"] = searchers.symbol_candidates(conn, query, limit=limit, kind=symbol_kind)
    if mode == "hybrid":
        lists["path"] = searchers.path_candidates(conn, query, limit=limit)
    if mode in ("hybrid", "vector") and backend is not None and getattr(backend, "enabled", False):
        lists["vector"] = searchers.vector_candidates(conn, query, backend, limit=limit)
    if mode != "hybrid":
        weights = {mode: 1.0}
    return lists, weights


def _confidence(ranked) -> Confidence:
    if not ranked:
        return Confidence.LOW
    top = ranked[0]
    if top.score <= 0:
        return Confidence.LOW
    if len(ranked) == 1:
        return Confidence.MEDIUM
    # Relative gap, not absolute: scale-invariant, so it stays meaningful regardless
    # of fusion's score magnitude. agreeing_sources is file-level (how many retrievers
    # surfaced the winning file at all), the signal RRF agreement is meant to capture.
    rel_gap = (top.score - ranked[1].score) / top.score
    agree = getattr(top, "agreeing_sources", 1)
    exact = getattr(top, "exact_symbol", False)
    n = len(ranked)
    # Exact symbol match always high confidence
    if exact:
        return Confidence.HIGH
    # Strong multi-source agreement with a clear score gap
    if agree >= 3 and rel_gap > 0.15:
        return Confidence.HIGH
    if agree >= 2 and rel_gap > 0.25:
        return Confidence.HIGH
    # Single source but very dominant winner
    if agree == 1 and rel_gap > 0.5:
        return Confidence.HIGH
    if agree >= 2 or rel_gap > 0.1 or n >= 5:
        return Confidence.MEDIUM
    return Confidence.LOW


def _diversify(ranked: list, *, per_file: int) -> list:
    """Stable reorder: keep the first `per_file` hits of each file in place, push
    the rest to the tail (preserving their relative order). Nothing is dropped, so
    recall is intact; the page just isn't monopolised by one file's many regions."""
    kept: list = []
    overflow: list = []
    counts: dict[str, int] = {}
    for c in ranked:
        counts[c.path] = counts.get(c.path, 0) + 1
        (kept if counts[c.path] <= per_file else overflow).append(c)
    return kept + overflow


def _fallback_suggestions(query, ranked) -> dict:
    terms = _TERM_RE.findall(query)
    if not terms:
        return {}
    longest = max(terms, key=len)
    rg = [f'rg -n "{longest}"']
    if len(terms) > 1:
        rg.append(f'rg -n "{".*".join(terms[:3])}"')
    return {"ripgrep": rg}


def search(
    conn: sqlite3.Connection,
    query: str,
    *,
    mode: str,
    limit: int,
    token_budget: int,
    no_fallback: bool,
    backend=None,
    root: Optional[Path] = None,
    config: Optional[Config] = None,
    offset: int = 0,
) -> dict:
    plan = detect_intent(query)
    if token_budget <= 0:
        token_budget = plan.token_budget
    fetch_limit = limit + offset
    lists, weights = _run_retrievers(
        conn, query, mode=mode, limit=fetch_limit, weights=plan.weights, backend=backend
    )
    fused = fuse(lists, weights=weights, k=_RRF_K)
    ranked = _diversify(rerank(fused, query=query, intent=plan.intent), per_file=_MAX_PER_FILE)
    ranked = ranked[:fetch_limit]
    confidence = _confidence(ranked)
    # Scale budget proportionally so later pages receive snippet coverage.
    scaled_budget = token_budget * fetch_limit // max(limit, 1) if offset > 0 else token_budget
    all_results, all_recommended = apply_budget(ranked, token_budget=scaled_budget)

    # Paginate: slice results and filter recommended_reads to the current page.
    paginated = all_results[offset:offset + limit]
    paginated_keys = {(r["path"], r["line_start"], r["line_end"]) for r in paginated}
    recommended = [
        r for r in all_recommended
        if (r["path"], r["line_start"], r["line_end"]) in paginated_keys
    ]
    has_more = len(all_results) > offset + limit

    fallback = {}
    if not no_fallback and confidence == Confidence.LOW:
        fallback = _fallback_suggestions(query, ranked)

    if config is not None and root is not None:
        freshness = compute_freshness(conn, root, config)
    else:
        from ..models import IndexFreshness
        from ..storage import repo
        built_at = repo.get_meta(conn, "built_at")
        freshness = IndexFreshness(
            exists=built_at is not None,
            stale=False,
            files_changed_since_build=0,
            built_at=built_at,
            head_commit=repo.get_meta(conn, "head_commit"),
        )

    payload: dict = {
        "query": query,
        "intent": plan.intent.value,
        "mode": mode,
        "index": freshness.model_dump(),
        "confidence": confidence.value,
        "results": paginated,
        "recommended_reads": recommended,
        "fallback_suggestions": fallback,
    }
    if offset > 0 or has_more:
        payload["pagination"] = {
            "offset": offset,
            "limit": limit,
            "has_more": has_more,
            "next_offset": offset + limit if has_more else None,
        }
    return payload
