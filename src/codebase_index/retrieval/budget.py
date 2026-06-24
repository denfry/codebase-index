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

from typing import Callable, Optional

from ..output.redact import redact_snippet
from .skeleton import Compacted
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
    candidates: list[Candidate],
    *,
    token_budget: int,
    compactor: Optional[Callable[[Candidate], Compacted]] = None,
) -> tuple[list[dict], list[dict]]:
    results: list[dict] = []
    recommended: list[dict] = []
    spent = 0

    for rank, c in enumerate(candidates, start=1):
        meta = _meta(c)
        meta["rank"] = rank
        meta["skeletonized"] = False
        meta["elided_lines"] = 0

        # Resolve the snippet text + cost. A compactor only changes anything
        # when it returns a real skeleton; otherwise we keep today's raw path
        # byte-for-byte (uses c.content / c.token_est).
        text = c.content
        cost = c.token_est
        if compactor is not None and c.content:
            comp = compactor(c)
            if comp.skeletonized:
                text = comp.text
                cost = comp.token_est
                meta["skeletonized"] = True
                meta["elided_lines"] = comp.elided_lines

        snippet = None
        snippet_is_useful = False
        if text and spent + cost <= token_budget:
            snippet = redact_snippet(text)
            spent += cost
            meta["token_est"] = cost
            snippet_is_useful = cost >= _MIN_USEFUL_TOKENS

        if not snippet_is_useful:
            recommended.append(
                {"path": c.path, "line_start": c.line_start, "line_end": c.line_end}
            )
        meta["snippet"] = snippet
        results.append(meta)

    return results, recommended
