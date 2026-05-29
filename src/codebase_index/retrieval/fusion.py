"""Reciprocal Rank Fusion across per-source ranked candidate lists.

RRF(d) = Σ_r  w_r / (k + rank_r(d))   — robust to incomparable raw scores.
On merge, the candidate carrying the most signal (symbol > fts > path) is kept
as the representative so downstream rerank/snippet logic has the richest fields.
"""

from __future__ import annotations

from .types import Candidate

_SOURCE_RICHNESS = {"symbol": 3, "fts": 2, "vector": 2, "path": 1}


def _richer(a: Candidate, b: Candidate) -> Candidate:
    return a if _SOURCE_RICHNESS.get(a.source, 0) >= _SOURCE_RICHNESS.get(b.source, 0) else b


def fuse(
    lists: dict[str, list[Candidate]],
    *,
    weights: dict[str, float],
    k: int,
) -> list[Candidate]:
    accum: dict[tuple, float] = {}
    rep: dict[tuple, Candidate] = {}
    agree: dict[tuple, set[str]] = {}

    for source, candidates in lists.items():
        w = weights.get(source, 0.0)
        if w <= 0.0:
            continue
        for rank, cand in enumerate(candidates):
            key = cand.key()
            accum[key] = accum.get(key, 0.0) + w / (k + rank)
            agree.setdefault(key, set()).add(source)
            rep[key] = _richer(rep[key], cand) if key in rep else cand

    fused: list[Candidate] = []
    for key, score in accum.items():
        c = rep[key]
        c.score = score
        fused.append(c)

    fused.sort(key=lambda c: c.score, reverse=True)
    for c in fused:
        c.agreeing_sources = len(agree[c.key()])
    return fused
