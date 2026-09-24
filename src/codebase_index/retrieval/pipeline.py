"""Orchestrate the hybrid retrieval pipeline (RETRIEVAL.md §1–§7).

query -> intent -> retrievers -> RRF fuse -> rerank -> budget -> payload.
Graph expansion is bounded and opt-in; vector retrieval remains optional.
"""

from __future__ import annotations

import re
import sqlite3
from pathlib import Path
from typing import Callable, Optional

from ..config import Config
from ..indexer.freshness import compute_freshness
from . import searchers
from ..output.redact import redact_snippet
from .budget import apply_budget
from .diversity import deduplicate, mmr_select
from .fusion import fuse
from .intent import detect_intent, is_question
from .lexical import salient_terms
from .rerank import rerank
from .tuning import DEFAULT_TUNING, RetrievalTuning
from .types import Confidence
from ..graph.retrieval import graph_candidates

_TERM_RE = re.compile(r"[A-Za-z0-9_]+")
# rrf_k / max_per_file now live on RetrievalTuning so they are ablatable.
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


def _run_retrievers(
    conn, query, *, mode, limit, weights, backend=None, tuning=DEFAULT_TUNING,
    graph_depth: int = 2, graph_node_cap: int = 40, graph_strategy: str = "none",
):
    lists = {}
    symbol_kind = _requested_symbol_kind(query)
    if mode in ("hybrid", "fts"):
        lists["fts"] = searchers.fts_candidates(conn, query, limit=limit, tuning=tuning)
    if mode in ("hybrid", "symbol"):
        lists["symbol"] = searchers.symbol_candidates(
            conn, query, limit=limit, kind=symbol_kind, tuning=tuning
        )
    if mode == "hybrid":
        lists["path"] = searchers.path_candidates(
            conn, query, limit=limit, tuning=tuning
        )
    if mode in ("hybrid", "vector") and backend is not None and getattr(backend, "enabled", False):
        lists["vector"] = searchers.vector_candidates(conn, query, backend, limit=limit)

    if mode != "hybrid":
        weights = {mode: 1.0}
    elif tuning.graph_source and graph_strategy != "none":
        seeds = [candidate for candidates in lists.values() for candidate in candidates]
        related = graph_candidates(
            conn,
            seeds,
            depth=graph_depth,
            node_cap=graph_node_cap,
            damping=tuning.graph_damping,
            iterations=tuning.graph_iterations,
            direction={"up": "up", "down": "down", "refs": "up", "both": "both"}.get(
                graph_strategy, "both"
            ),
        )
        if related:
            lists["graph"] = related
            weights = {**weights, "graph": tuning.graph_weight}
    return lists, weights

def _confidence(ranked) -> Confidence:
    if not ranked:
        return Confidence.LOW
    top = ranked[0]
    if top.score <= 0:
        return Confidence.LOW
    exact = getattr(top, "exact_symbol", False)
    # Exact symbol matches are high confidence even when they are the sole hit.
    if exact:
        return Confidence.HIGH
    if len(ranked) == 1:
        return Confidence.MEDIUM
    # Relative gap, not absolute: scale-invariant, so it stays meaningful regardless
    # of fusion's score magnitude. agreeing_sources is file-level (how many retrievers
    # surfaced the winning file at all), the signal RRF agreement is meant to capture.
    rel_gap = (top.score - ranked[1].score) / top.score
    agree = getattr(top, "agreeing_sources", 1)
    n = len(ranked)
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


def _pool_entry(rank: int, c) -> dict:
    """One pre-rerank candidate, as the ranking-diagnostics view of it.

    Recorded before rerank mutates `score`/`reason` in place, so the fused order
    stays comparable with the final order. Only built when `explain` is set: the
    default query path allocates nothing.
    """
    return {
        "rank": rank,
        "path": c.path,
        "line_start": c.line_start,
        "line_end": c.line_end,
        "source": c.source,
        "symbol": c.symbol,
        "kind": c.kind,
        "fused_score": round(c.score, 4),
        "agreeing_sources": c.agreeing_sources,
        "exact_symbol": c.exact_symbol,
    }


def _bounded_read(entry: dict, max_lines: int) -> dict:
    """Cap one read-plan entry to `max_lines`, keeping the original span visible.

    Symbol-aligned chunks can span an entire class. Handing the agent
    ``line_start..line_end`` verbatim then bills it for the whole body when the
    definition head is usually what it needs first; the capped entry points at
    the head and records the full extent so the agent can read on deliberately.
    Additive fields only (`truncated`, `line_end_full`): schema unchanged.
    """
    span = entry["line_end"] - entry["line_start"] + 1
    if max_lines <= 0 or span <= max_lines:
        return entry
    return {
        **entry,
        "line_end": entry["line_start"] + max_lines - 1,
        "line_end_full": entry["line_end"],
        "truncated": True,
    }


_MAX_HIT_LINES = 8
_MAX_HIT_CHARS = 180


_SUFFIXES = ("ing", "ed", "es", "s")


def _display_stem(term: str) -> str:
    for suffix in _SUFFIXES:
        if term.endswith(suffix) and len(term) - len(suffix) >= 4:
            return term[: -len(suffix)]
    return term


def _range_lines(conn: sqlite3.Connection, cand) -> tuple[int, list[str]]:
    """(first line number, lines) of the candidate's full range.

    A symbol-retriever candidate carries only its signature as `content`; the body
    is in the chunk that covers it.
    """
    content = getattr(cand, "content", None) or ""
    start, end = int(cand.line_start), int(cand.line_end)
    lines = content.splitlines()
    if len(lines) >= end - start + 1:
        return start, lines
    row = conn.execute(
        "SELECT c.content, c.line_start FROM chunks c JOIN files f ON f.id = c.file_id "
        "WHERE f.path = ? AND c.line_start <= ? AND c.line_end >= ? "
        "ORDER BY c.line_end - c.line_start LIMIT 1",
        (cand.path, start, end),
    ).fetchone()
    if row is None:
        return start, lines
    chunk = row[0].splitlines()
    offset = start - int(row[1])
    return start, chunk[offset:offset + (end - start + 1)]


def _hit_lines(conn: sqlite3.Connection, cand, terms: tuple[str, ...]) -> list[list]:
    """The candidate's lines an agent would cite, numbered: `[[line, text], ...]`.

    What `grep -n` gives, restricted to a ranked candidate: its first line (the
    signature or declaration) and the lines that contain a query term, rarer terms
    weighing more, then back in file order. A snippet
    without line numbers sends an agent back to grep for them before it can cite.
    """
    start, lines = _range_lines(conn, cand)
    if not lines:
        return []
    lowered = [line.casefold() for line in lines]
    # Display only, never ranking: "persisted" should light up `persist()`.
    terms = tuple(dict.fromkeys(_display_stem(t) for t in terms if len(t) >= 3))
    # A term on every other line ("town" in a town module) says little about
    # which lines matter; weight each by how rarely it occurs in this range.
    weight = {t: 1.0 / max(1, sum(t in low for low in lowered)) for t in terms}
    scored: list[tuple[float, int]] = []
    for i, low in enumerate(lowered):
        score = sum(weight[t] for t in terms if t in low)
        if score:
            scored.append((score, i))
    first = next((i for i, line in enumerate(lines) if line.strip()), 0)
    picked = {first}
    for _score, i in sorted(scored, key=lambda s: (-s[0], s[1])):
        if len(picked) >= _MAX_HIT_LINES:
            break
        picked.add(i)
    out = []
    for i in sorted(picked):
        text = redact_snippet(lines[i].strip())
        if len(text) > _MAX_HIT_CHARS:
            text = text[: _MAX_HIT_CHARS - 1] + "…"
        out.append([start + i, text])
    return out


def search(
    conn: sqlite3.Connection,
    query: str,
    *,
    mode: str,
    limit: int,
    token_budget: int,
    no_fallback: bool,
    backend=None,
    tuning: Optional[RetrievalTuning] = None,
    root: Optional[Path] = None,
    config: Optional[Config] = None,
    offset: int = 0,
    compact: bool = True,
    compact_min_reduction: float = 0.25,
    explain: bool = False,
    evidence: Optional[Callable[[dict, list], None]] = None,
    max_read_lines: int = 120,
    hit_lines: bool = False,
) -> dict:
    tuning = tuning or DEFAULT_TUNING
    plan = detect_intent(query)
    if token_budget <= 0:
        token_budget = plan.token_budget
    fetch_limit = limit + offset
    # Selection (dedup / MMR / per-file diversification) removes candidates, so the
    # pool is over-fetched. The multiplier is explicit rather than a side effect of
    # which selection flags happen to be on. A widened pool also carries a floor so
    # a tiny `limit` still leaves selection something to choose between; multiplier
    # 1 means "no over-fetch at all" and takes the page size verbatim.
    pool_mult = max(1, tuning.candidate_pool_multiplier)
    floor = tuning.candidate_pool_floor
    if tuning.question_pool_floor and is_question(query):
        floor = max(floor, tuning.question_pool_floor)
    pool_limit = fetch_limit if pool_mult == 1 else max(fetch_limit * pool_mult, floor)
    lists, weights = _run_retrievers(
        conn,
        query,
        mode=mode,
        limit=pool_limit,
        weights=plan.weights,
        backend=backend,
        tuning=tuning,
        graph_depth=tuning.graph_depth,
        graph_node_cap=tuning.graph_node_cap,
        graph_strategy=plan.graph_strategy,
    )
    fused = fuse(
        lists,
        weights=weights,
        k=tuning.rrf_k,
        file_agreement=tuning.file_agreement_weight if tuning.file_agreement else 0.0,
    )
    pool = [_pool_entry(rank, c) for rank, c in enumerate(fused, start=1)] if explain else []
    ranked = rerank(fused, query=query, intent=plan.intent, tuning=tuning)
    if tuning.dedup:
        ranked = deduplicate(ranked, hamming_distance=tuning.dedup_hamming)
    if tuning.mmr:
        ranked = mmr_select(ranked, fetch_limit, tuning.mmr_lambda)
    else:
        ranked = _diversify(ranked, per_file=tuning.max_per_file)
    ranked = ranked[:fetch_limit]
    confidence = _confidence(ranked)
    # Scale budget proportionally so later pages receive snippet coverage.
    scaled_budget = token_budget * fetch_limit // max(limit, 1) if offset > 0 else token_budget
    from .skeleton import make_compactor

    compactor = make_compactor(
        intent=plan.intent, query=query,
        enabled=compact, min_reduction=compact_min_reduction,
    )
    all_results, all_recommended = apply_budget(
        ranked, token_budget=scaled_budget, compactor=compactor
    )
    if hit_lines:
        terms = salient_terms(query)
        for result, cand in zip(all_results, ranked):
            result["hits"] = _hit_lines(conn, cand, terms)

    # Paginate: slice results and filter recommended_reads to the current page.
    paginated = all_results[offset:offset + limit]
    paginated_keys = {(r["path"], r["line_start"], r["line_end"]) for r in paginated}
    recommended = [
        _bounded_read(r, max_read_lines) for r in all_recommended
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
    if explain:
        payload["diagnostics"] = {
            "weights": plan.weights,
            "pool_size": len(pool),
            "pool": pool,
            "ranked": [
                {
                    "rank": rank,
                    "path": c.path,
                    "line_start": c.line_start,
                    "line_end": c.line_end,
                    "source": c.source,
                    "symbol": c.symbol,
                    "score": round(c.score, 4),
                    "reason": c.reason,
                    "agreeing_sources": c.agreeing_sources,
                    "exact_symbol": c.exact_symbol,
                }
                for rank, c in enumerate(ranked, start=1)
            ],
        }
    if evidence is not None:
        # Evidence memory (memory/session.py) sees the delivered page and the candidates
        # behind it only after ranking, budgeting and pagination are final, so it cannot
        # change which results are returned or which carry snippets.
        evidence(payload, ranked[offset:offset + limit])
    return payload
