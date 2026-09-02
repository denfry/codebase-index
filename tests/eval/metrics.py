"""Standard IR metrics for the retrieval eval harness.

All functions take a *ranked* list of retrieved item ids (best first, already
deduplicated) and a set of relevant ids. Binary relevance throughout: a file
either does or does not contain the answer. Graded relevance was considered and
rejected — assigning 0..3 grades by hand to hundreds of (query, file) pairs is
not reproducible, and binary gains keep nDCG comparable across corpora.

Every function is pure and total: an empty ranking or empty ground truth yields
0.0 rather than raising, so a query that returns nothing scores as a miss
instead of crashing the sweep.
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence


def _prefix(ranked: Sequence[str], k: int) -> Sequence[str]:
    return ranked[: max(0, k)]


def recall_at_k(ranked: Sequence[str], relevant: Iterable[str], k: int) -> float:
    """Fraction of the relevant set retrieved within the top k."""
    rel = set(relevant)
    if not rel:
        return 0.0
    return len(set(_prefix(ranked, k)) & rel) / len(rel)


def precision_at_k(ranked: Sequence[str], relevant: Iterable[str], k: int) -> float:
    """Fraction of the top k that is relevant."""
    rel = set(relevant)
    top = _prefix(ranked, k)
    if not top:
        return 0.0
    return sum(1 for item in top if item in rel) / len(top)


def hit_rate_at_k(ranked: Sequence[str], relevant: Iterable[str], k: int) -> float:
    """1.0 if any relevant item appears in the top k. The 'did it work at all' metric."""
    rel = set(relevant)
    return 1.0 if any(item in rel for item in _prefix(ranked, k)) else 0.0


def reciprocal_rank(ranked: Sequence[str], relevant: Iterable[str]) -> float:
    """1/rank of the first relevant hit; 0.0 when the ranking misses entirely.

    Averaged over a query set this is MRR — the metric that matters most for an
    agent, which reads results top-down and stops early.
    """
    rel = set(relevant)
    for i, item in enumerate(ranked, start=1):
        if item in rel:
            return 1.0 / i
    return 0.0


def average_precision(ranked: Sequence[str], relevant: Iterable[str]) -> float:
    """Mean of precision@i taken at every rank i holding a relevant item."""
    rel = set(relevant)
    if not rel:
        return 0.0
    hits = 0
    total = 0.0
    for i, item in enumerate(ranked, start=1):
        if item in rel:
            hits += 1
            total += hits / i
    return total / len(rel) if hits else 0.0


def ndcg_at_k(ranked: Sequence[str], relevant: Iterable[str], k: int) -> float:
    """Binary-gain nDCG@k with the standard log2(rank+1) discount.

    The ideal ranking places min(|relevant|, k) hits at the very top, so a query
    with a single relevant file can still reach 1.0 — nDCG is not implicitly
    penalised for small ground-truth sets.
    """
    rel = set(relevant)
    if not rel:
        return 0.0
    dcg = sum(
        1.0 / math.log2(i + 1)
        for i, item in enumerate(_prefix(ranked, k), start=1)
        if item in rel
    )
    ideal_hits = min(len(rel), max(0, k))
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, ideal_hits + 1))
    return dcg / idcg if idcg else 0.0


def useful_context_at_budget(
    returned: Sequence[tuple[str, int]],
    relevant: Iterable[str],
    budget_tokens: int,
) -> float:
    """Agent-centric metric: relevant items recovered per unit of context spent.

    `returned` is the ranked list of (item_id, token_cost) actually placed in the
    agent's context. We walk it in rank order, spending tokens until the budget is
    exhausted, and report the fraction of the relevant set that made it in.

    This is what the whole system optimises: not "is the answer somewhere in the
    ranking" but "is the answer in the context window the agent can afford".
    """
    rel = set(relevant)
    if not rel:
        return 0.0
    spent = 0
    found: set[str] = set()
    for item, cost in returned:
        cost = max(0, cost)
        if spent + cost > budget_tokens:
            continue
        spent += cost
        if item in rel:
            found.add(item)
    return len(found) / len(rel)


def percentile(values: Sequence[float], pct: float) -> float:
    """Nearest-rank percentile (no interpolation) — stable for small samples."""
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = math.ceil(pct / 100.0 * len(ordered)) - 1
    return ordered[min(max(idx, 0), len(ordered) - 1)]
