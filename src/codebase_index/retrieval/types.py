"""Shared retrieval types: the uniform candidate + intent plan."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


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
    is_generated: bool = False
    exact_symbol: bool = False
    reason: str = ""
    agreeing_sources: int = 1

    def key(self) -> tuple[str, int, int]:
        return (self.path, self.line_start, self.line_end)


@dataclass
class IntentPlan:
    intent: Intent
    weights: dict[str, float]
    token_budget: int
    graph_strategy: str = "none"
    summaries_first: bool = False

    def weight(self, source: str) -> float:
        return self.weights.get(source, 0.0)
