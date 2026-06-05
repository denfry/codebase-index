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
    gap = top.score - (ranked[1].score if len(ranked) > 1 else 0.0)
    agree = getattr(top, "agreeing_sources", 1)
    if getattr(top, "exact_symbol", False) or (agree >= 2 and gap > 0.01):
        return Confidence.HIGH
    if top.score > 0 and (agree >= 2 or gap > 0.005):
        return Confidence.MEDIUM
    return Confidence.LOW


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
) -> dict:
    plan = detect_intent(query)
    if token_budget <= 0:
        token_budget = plan.token_budget
    lists, weights = _run_retrievers(
        conn, query, mode=mode, limit=limit, weights=plan.weights, backend=backend
    )
    fused = fuse(lists, weights=weights, k=_RRF_K)
    ranked = rerank(fused, query=query, intent=plan.intent)[:limit]
    confidence = _confidence(ranked)
    results, recommended = apply_budget(ranked, token_budget=token_budget)

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

    return {
        "query": query,
        "intent": plan.intent.value,
        "mode": mode,
        "index": freshness.model_dump(),
        "confidence": confidence.value,
        "results": results,
        "recommended_reads": recommended,
        "fallback_suggestions": fallback,
    }
