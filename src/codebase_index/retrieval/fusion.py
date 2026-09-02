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
* Cross-locator agreement is scored, not merely counted. Bucketing alone does not
  rescue agreement: a symbol defined at line 40 and a lexical hit at line 120 sit
  in different buckets of the same file, so two retrievers pointing at one file
  still fused as two unrelated candidates, each carrying a single retriever's
  evidence. `file_agreement` adds the missing evidence back at a discount — a
  candidate also receives, weighted by `file_agreement_weight`, the RRF mass of
  every retriever that found its *file* somewhere else. Retrievers already
  counted at the candidate's own locator are excluded, so nothing double-counts.

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
    file_agreement: float = 0.0,
) -> list[Candidate]:
    """Fuse per-source ranked lists into one ordered candidate list.

    `file_agreement` is the discount applied to same-file, different-locator
    evidence; 0.0 reproduces plain locator-only RRF.
    """
    accum: dict[tuple, float] = {}
    rep: dict[tuple, Candidate] = {}
    seen: set[tuple] = set()
    file_sources: dict[str, set[str]] = {}
    # Best (lowest) rank each source achieved for each file, and which sources
    # already contributed at each fused locator.
    best_file_rank: dict[tuple[str, str], int] = {}
    key_sources: dict[tuple, set[str]] = {}

    for source, candidates in lists.items():
        w = weights.get(source, 0.0)
        if w <= 0.0:
            continue
        for rank, cand in enumerate(candidates):
            file_sources.setdefault(cand.path, set()).add(source)
            file_key = (source, cand.path)
            previous = best_file_rank.get(file_key)
            if previous is None or rank < previous:
                best_file_rank[file_key] = rank
            key = cand.fuse_key()
            key_sources.setdefault(key, set()).add(source)
            # One contribution per source per locator: a file matching three FTS
            # chunks in the same bucket is one lexical signal, not three.
            if (source, key) in seen:
                continue
            seen.add((source, key))
            accum[key] = accum.get(key, 0.0) + w * k / (k + rank)
            rep[key] = _richer(rep[key], cand) if key in rep else cand

    if file_agreement > 0.0:
        for key, base in accum.items():
            path = rep[key].path
            own = key_sources[key]
            extra = 0.0
            for source in file_sources.get(path, ()):
                if source in own:
                    continue
                w = weights.get(source, 0.0)
                if w <= 0.0:
                    continue
                extra += w * k / (k + best_file_rank[(source, path)])
            if extra:
                accum[key] = base + file_agreement * extra

    fused = [_replace(rep[key], score=score) for key, score in accum.items()]
    fused.sort(key=lambda c: c.score, reverse=True)
    return [_replace(c, agreeing_sources=len(file_sources[c.path])) for c in fused]
