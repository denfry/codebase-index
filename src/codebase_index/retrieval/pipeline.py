"""Orchestrate the hybrid retrieval pipeline (RETRIEVAL.md §1–§7).

query -> intent -> retrievers -> RRF fuse -> rerank -> budget -> payload.
Graph expansion (§5) and vector retrieval (§2 vector) are deferred to M5/M6.
"""

from __future__ import annotations

import re
import sqlite3

from . import searchers
from .budget import apply_budget
from .fusion import fuse
from .intent import detect_intent
from .rerank import rerank
from .types import Confidence

_TERM_RE = re.compile(r"[A-Za-z0-9_]+")
_RRF_K = 60


def _run_retrievers(conn, query, *, mode, limit, weights):
    lists = {}
    if mode in ("hybrid", "fts"):
        lists["fts"] = searchers.fts_candidates(conn, query, limit=limit)
    if mode in ("hybrid", "symbol"):
        lists["symbol"] = searchers.symbol_candidates(conn, query, limit=limit)
    if mode == "hybrid":
        lists["path"] = searchers.path_candidates(conn, query, limit=limit)
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
) -> dict:
    plan = detect_intent(query)
    lists, weights = _run_retrievers(
        conn, query, mode=mode, limit=limit, weights=plan.weights
    )
    fused = fuse(lists, weights=weights, k=_RRF_K)
    ranked = rerank(fused, query=query, intent=plan.intent)[:limit]
    confidence = _confidence(ranked)
    results, recommended = apply_budget(ranked, token_budget=token_budget)

    fallback = {}
    if not no_fallback and confidence == Confidence.LOW:
        fallback = _fallback_suggestions(query, ranked)

    return {
        "query": query,
        "intent": plan.intent.value,
        "mode": mode,
        "confidence": confidence.value,
        "results": results,
        "recommended_reads": recommended,
        "fallback_suggestions": fallback,
    }
