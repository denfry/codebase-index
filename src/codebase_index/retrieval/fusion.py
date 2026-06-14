"""Reciprocal Rank Fusion across per-source ranked candidate lists.

RRF(d) = Σ_r  w_r · k / (k + rank_r(d))   — robust to incomparable raw scores.

Two deliberate departures from the textbook formula:

* Scaled by k. Raw RRF tops out at w/k (≈0.017 for k=60), an order of magnitude
  below the bounded bonuses the reranker layers on top, so rerank would silently
  become the primary ranker and RRF a mere tiebreak. Multiplying by k is a pure
  monotonic rescale (fusion order is identical) that lifts the top contribution to
  ≈w, putting fused scores and rerank bonuses on the same O(1) scale.
* Fused on a coarse (path, line-bucket) key, not (path, start, end). Different
  retrievers report different line ranges for the same place; an exact key almost
  never coincides across sources, so cross-source agreement — RRF's whole point —
  would never fire. `agreeing_sources` is therefore counted at file granularity.

On merge, the candidate carrying the most signal (symbol > fts > path) is kept as
the representative so downstream rerank/snippet logic has the richest fields.
"""

from __future__ import annotations

from dataclasses import replace as _replace

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
    seen: set[tuple] = set()
    file_sources: dict[str, set[str]] = {}

    for source, candidates in lists.items():
        w = weights.get(source, 0.0)
        if w <= 0.0:
            continue
        for rank, cand in enumerate(candidates):
            file_sources.setdefault(cand.path, set()).add(source)
            key = cand.fuse_key()
            # One contribution per source per locator: a file matching three FTS
            # chunks in the same bucket is one lexical signal, not three.
            if (source, key) in seen:
                continue
            seen.add((source, key))
            accum[key] = accum.get(key, 0.0) + w * k / (k + rank)
            rep[key] = _richer(rep[key], cand) if key in rep else cand

    fused = [_replace(rep[key], score=score) for key, score in accum.items()]
    fused.sort(key=lambda c: c.score, reverse=True)
    return [_replace(c, agreeing_sources=len(file_sources[c.path])) for c in fused]
