"""Shared retrieval types: the uniform candidate + intent plan."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

# Line window used by Candidate.fuse_key to group co-located hits across retrievers.
# Wide enough to merge a symbol body and the FTS window that overlaps it, narrow
# enough to keep distinct regions of a large file separate.
_FUSE_BUCKET_LINES = 40


class Intent(str, Enum):
    LOCATE_IMPL = "locate_impl"
    HOW_IT_WORKS = "how_it_works"
    IMPACT = "impact"
    FIND_REFS = "find_refs"
    DATA_FLOW = "data_flow"
    DEBUG_ERROR = "debug_error"
    ARCHITECTURE = "architecture"
    KEYWORD = "keyword"


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class Candidate:
    """Source-agnostic retrieval hit. `source` in {"path","symbol","fts"}."""

    path: str
    line_start: int
    line_end: int
    source: str
    score: float
    kind: Optional[str] = None
    symbol: Optional[str] = None
    content: Optional[str] = None
    token_est: int = 0
    in_degree: int = 0
    out_degree: int = 0
    ref_count: int = 0
    is_generated: bool = False
    exact_symbol: bool = False
    reason: str = ""
    agreeing_sources: int = 1

    def key(self) -> tuple[str, int, int]:
        return (self.path, self.line_start, self.line_end)

    def fuse_key(self) -> tuple[str, int]:
        """Coarse locator for RRF fusion: path + line bucket.

        Different retrievers emit different granularities for the same place — a
        symbol body, an 80-line FTS window, a path hit anchored at line 1 — so an
        exact (path, start, end) key almost never coincides across sources and RRF
        degenerates into a weighted round-robin that never rewards agreement.
        Bucketing line_start collapses co-located hits onto one key so their
        per-source RRF contributions actually sum, while still separating genuinely
        distant regions of a large file.
        """
        return (self.path, (max(self.line_start, 1) - 1) // _FUSE_BUCKET_LINES)


@dataclass
class IntentPlan:
    intent: Intent
    weights: dict[str, float]
    token_budget: int
    graph_strategy: str = "none"
    summaries_first: bool = False

    def weight(self, source: str) -> float:
        return self.weights.get(source, 0.0)
