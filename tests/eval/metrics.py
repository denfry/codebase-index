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
import random
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


# --- oracle / headroom ------------------------------------------------------
#
# MRR alone cannot tell "the retrievers never found it" apart from "the ranker had
# it and buried it", yet those two failures have nothing in common: one is fixed by
# widening recall, the other by reranking. The pair below splits them, and the split
# is what justified spending 1.10.0 on the ranker rather than on new retrievers.


def oracle_reciprocal_rank(pool: Sequence[str], relevant: Iterable[str]) -> float:
    """Reciprocal rank a *perfect* reranker would achieve over this candidate pool.

    A perfect reranker puts a relevant candidate first, so the answer is binary:
    1.0 when the pool contains any relevant item, 0.0 when retrieval never
    surfaced one. Averaged over a query set this is the ceiling MRR can reach
    without touching candidate generation, and `1 - oracle` is the share of the
    query set that only better *recall* can ever fix.
    """
    rel = set(relevant)
    return 1.0 if any(item in rel for item in pool) else 0.0


def rerank_efficiency(mrr: float, oracle_mrr: float) -> float:
    """Fraction of the achievable ranking quality the ranker actually delivers.

    1.0 means every answer the retrievers found is ranked first; 0.0 means none
    are. This is the number 1.10.0 set out to move: at 1.9.0 it was 0.64, so a
    third of the answers already in the pool were being ranked below something
    else — an error mode roughly three times larger than the remaining recall gap.
    """
    return mrr / oracle_mrr if oracle_mrr else 0.0


def percentile(values: Sequence[float], pct: float) -> float:
    """Nearest-rank percentile (no interpolation) — stable for small samples."""
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = math.ceil(pct / 100.0 * len(ordered)) - 1
    return ordered[min(max(idx, 0), len(ordered) - 1)]


# --- significance -----------------------------------------------------------
#
# A 36-query set cannot distinguish a +0.03 MRR improvement from noise, and eyeballing
# a delta column is how ranking systems accumulate changes that never actually helped.
# Both routines below are paired (same queries, two systems) and seeded, so a reported
# interval is reproducible rather than a different number on every run.

_BOOTSTRAP_SEED = 20260902


def paired_bootstrap_ci(
    deltas: Sequence[float],
    *,
    resamples: int = 5000,
    confidence: float = 0.95,
    seed: int = _BOOTSTRAP_SEED,
) -> tuple[float, float, float]:
    """Return (mean delta, lower, upper) for a per-query difference vector.

    Resampling queries — not scores — is what makes the interval answer the
    question we care about: would this improvement survive a different, equally
    plausible sample of user questions?
    """
    values = list(deltas)
    n = len(values)
    if n == 0:
        return 0.0, 0.0, 0.0
    observed = math.fsum(values) / n
    if n == 1:
        return observed, observed, observed

    rng = random.Random(seed)
    means = []
    for _ in range(max(1, resamples)):
        total = 0.0
        for _ in range(n):
            total += values[rng.randrange(n)]
        means.append(total / n)
    means.sort()
    tail = (1.0 - confidence) / 2.0
    lo = means[min(len(means) - 1, int(tail * len(means)))]
    hi = means[min(len(means) - 1, int((1.0 - tail) * len(means)))]
    return observed, lo, hi


def paired_permutation_p(
    deltas: Sequence[float],
    *,
    resamples: int = 5000,
    seed: int = _BOOTSTRAP_SEED,
) -> float:
    """Two-sided paired permutation test on a per-query difference vector.

    Under the null the two systems are interchangeable on each query, so flipping
    the sign of any subset of deltas is equally likely. Reports the fraction of
    sign-flipped resamples at least as extreme as what we measured.
    """
    values = list(deltas)
    n = len(values)
    if n == 0:
        return 1.0
    observed = abs(math.fsum(values) / n)
    if observed == 0.0:
        return 1.0

    rng = random.Random(seed + 1)
    extreme = 0
    trials = max(1, resamples)
    for _ in range(trials):
        total = 0.0
        for value in values:
            total += value if rng.getrandbits(1) else -value
        if abs(total / n) >= observed - 1e-12:
            extreme += 1
    return extreme / trials
