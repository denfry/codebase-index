"""Greedy token budgeting (RETRIEVAL.md §6).

Metadata for every result is always emitted (cheap). Snippets are attached to the
highest-ranked results until the budget is hit; the remainder become
recommended_reads. All snippet text is secret-redacted before emission.

A result is added to recommended_reads when:
  - it has no snippet (budget exceeded or no content), OR
  - its snippet is below _MIN_USEFUL_TOKENS (e.g. a bare function signature).
    Claude still gets the short preview but also receives the read plan.
"""

from __future__ import annotations

from ..output.redact import redact_snippet
from .types import Candidate

# Snippets shorter than this threshold are treated as previews only; the result
# is still added to recommended_reads so Claude knows where to read the full body.
_MIN_USEFUL_TOKENS = 40


def _meta(c: Candidate) -> dict:
    return {
        "path": c.path,
        "line_start": c.line_start,
        "line_end": c.line_end,
        "symbols": [c.symbol] if c.symbol else [],
        "score": round(c.score, 4),
        "reason": c.reason if c.reason else c.source,
        "token_est": c.token_est,
    }


def apply_budget(
    candidates: list[Candidate], *, token_budget: int
) -> tuple[list[dict], list[dict]]:
    results: list[dict] = []
    recommended: list[dict] = []
    spent = 0

    for rank, c in enumerate(candidates, start=1):
        meta = _meta(c)
        meta["rank"] = rank
        snippet = None
        snippet_is_useful = False

        if c.content and spent + c.token_est <= token_budget:
            snippet = redact_snippet(c.content)
            spent += c.token_est
            snippet_is_useful = c.token_est >= _MIN_USEFUL_TOKENS

        if not snippet_is_useful:
            recommended.append(
                {"path": c.path, "line_start": c.line_start, "line_end": c.line_end}
            )
        meta["snippet"] = snippet
        results.append(meta)

    return results, recommended
