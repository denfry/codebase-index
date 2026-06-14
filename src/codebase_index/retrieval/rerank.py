"""Explainable feature reranker layered on the fused order (RETRIEVAL.md §4).

Adds a bounded bonus/penalty to the fused RRF score and produces a human-readable
`reason` per candidate. No external model. Graph centrality uses the denormalized
symbols.in_degree/out_degree; cross-node graph expansion is M5.
"""

from __future__ import annotations

import math
import re

from .types import Candidate, Intent

_TERM_RE = re.compile(r"[A-Za-z0-9_]+")

# Graph-centrality bonus. Logarithmic (not linear) so a "god class" with hundreds
# of callers cannot dominate a genuinely relevant low-degree match on a stray-term
# tie. log1p compresses the tail — in_degree 4 → 10 → 100 yields a gently rising,
# capped bonus instead of saturating the cap by in_degree 10 — and the lower cap
# keeps centrality a tiebreak rather than an override. This dampens the god-class
# over-ranking documented in tests/benchmark_honest_RESULTS.md.
_DEGREE_SCALE = 0.03
_DEGREE_CAP = 0.08


def rerank(candidates: list[Candidate], *, query: str, intent: Intent) -> list[Candidate]:
    terms = {t.lower() for t in _TERM_RE.findall(query)}
    for c in candidates:
        bonus = 0.0
        reasons: list[str] = []

        if c.source == "symbol" and c.kind in {"function", "method", "class", "interface", "type"}:
            bonus += 0.05
        if c.exact_symbol:
            bonus += 0.20
            reasons.append("exact symbol match")
        if c.symbol and c.symbol.lower() in terms:
            bonus += 0.05

        if any(t in c.path.lower() for t in terms):
            bonus += 0.05
            reasons.append(f"in {c.path.rsplit('/', 1)[0] or '.'}/")

        if c.in_degree:
            bonus += min(_DEGREE_CAP, math.log1p(c.in_degree) * _DEGREE_SCALE)
            reasons.append(f"{c.in_degree} callers")
        if intent is Intent.ARCHITECTURE and (c.in_degree + c.out_degree):
            bonus += min(_DEGREE_CAP, math.log1p(c.in_degree + c.out_degree) * (_DEGREE_SCALE / 2))

        wants_tests = "test" in terms or "tests" in terms
        if c.is_generated or (("test" in c.path.lower()) and not wants_tests):
            bonus -= 0.15
            reasons.append("generated/test demoted")

        c.score += bonus
        c.reason = " · ".join(reasons) if reasons else c.source

    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates
