"""Explainable feature reranker layered on the fused order (RETRIEVAL.md §4).

Adds a bounded bonus/penalty to the fused RRF score and produces a human-readable
`reason` per candidate. No external model. Graph centrality uses the denormalized
symbols.in_degree/out_degree; cross-node graph expansion is M5.
"""

from __future__ import annotations

import math
import re

from ..discovery.classify import is_test_path
from .features import name_cooccurrence, name_zone, query_profile
from .priors import source_role_prior
from .tuning import DEFAULT_TUNING, RetrievalTuning
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


def _stem(path: str) -> str:
    name = path.rsplit("/", 1)[-1]
    return name.split(".", 1)[0].lower()


def rerank(
    candidates: list[Candidate],
    *,
    query: str,
    intent: Intent,
    tuning: RetrievalTuning = DEFAULT_TUNING,
) -> list[Candidate]:
    terms = {t.lower() for t in _TERM_RE.findall(query)}
    wants_tests = "test" in terms or "tests" in terms
    profile = query_profile(query) if tuning.name_cooccurrence else None
    for c in candidates:
        bonus = 0.0
        reasons: list[str] = []
        # Computed before the bonuses because the name-co-occurrence signal is
        # conditioned on it, not merely penalised after the fact.
        demoted = c.is_generated or (is_test_path(c.path) and not wants_tests)

        # Name co-occurrence is *discounted*, not withheld, for sources the ranker
        # is unwilling to promote. Test symbol names are descriptive sentences
        # (`test_compactor_output_is_redacted`), so they harvest query-term
        # co-occurrences that real identifiers never do, and a bonus reaching
        # +`name_cooccurrence_weight` is not counterbalanced by a flat -0.15
        # demotion calibrated when the largest name bonus was +0.05. Withholding it
        # outright over-corrects: on git-derived ground truth the changed file often
        # *is* the test, and zeroing the bonus cost -0.017 MRR across eight
        # repositories. The discount keeps a strongly-matching test ahead of a
        # barely-matching implementation while restoring the intended role ordering
        # when both match comparably.
        if profile is not None:
            matched, cooccurrence = name_cooccurrence(profile, name_zone(c.path, c.symbol))
            if cooccurrence:
                if demoted:
                    cooccurrence *= tuning.name_cooccurrence_demoted_scale
                bonus += tuning.name_cooccurrence_weight * cooccurrence
                reasons.append(f"{matched}/{profile.n_terms} query terms co-occur in name")

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
        if tuning.stem_match and not demoted and _stem(c.path) in terms:
            bonus += tuning.stem_match_weight
            reasons.append("file named after a query term")

        if c.in_degree:
            bonus += min(_DEGREE_CAP, math.log1p(c.in_degree) * _DEGREE_SCALE)
            reasons.append(f"{c.in_degree} callers")
        elif c.ref_count:
            # Precise in_degree is only computed for globally-unique symbol names
            # (ambiguous names never resolve), so common names like `run`/`handle`
            # always score 0. Fall back to a damped name-reference count — half the
            # scale and cap — so centrality still breaks ties without overriding the
            # precise signal where it exists.
            bonus += min(_DEGREE_CAP / 2, math.log1p(c.ref_count) * (_DEGREE_SCALE / 2))
            reasons.append(f"~{c.ref_count} refs by name")
        if intent is Intent.ARCHITECTURE and (c.in_degree + c.out_degree):
            bonus += min(_DEGREE_CAP, math.log1p(c.in_degree + c.out_degree) * (_DEGREE_SCALE / 2))

        if tuning.source_priors and ("/" in c.path or "\\" in c.path):
            prior = source_role_prior(
                c.path, query=query, intent=intent, extended=tuning.resource_priors
            )
            if prior:
                bonus += prior
                reasons.append(f"source prior {prior:+.2f}")

        if demoted:
            bonus -= 0.15
            reasons.append("generated/test demoted")

        c.score += bonus
        c.reason = " · ".join(reasons) if reasons else c.source

    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates
