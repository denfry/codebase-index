"""Cheap rule-first intent classifier (regex/keyword heuristics).

Each intent maps to retriever weights over {"path","symbol","fts"}, a default
token budget, and a graph strategy (consumed later by M5).
"""

from __future__ import annotations

import re

from .types import Intent, IntentPlan

_RULES: list[tuple[re.Pattern[str], Intent]] = [
    (re.compile(r"traceback|stack ?trace|error:|exception|why does .* fail", re.I), Intent.DEBUG_ERROR),
    (re.compile(r"\b(who calls|find references|references to|callers of)\b", re.I), Intent.FIND_REFS),
    (re.compile(r"\b(what breaks|what depends on|impact of|affected if)\b", re.I), Intent.IMPACT),
    (re.compile(r"\b(data ?flow|where does .* get set|trace .* flow)\b", re.I), Intent.DATA_FLOW),
    (re.compile(r"\b(architecture|high-?level|overview|structure of)\b", re.I), Intent.ARCHITECTURE),
    (re.compile(r"\b(how does|how do|explain how|how .* works?)\b", re.I), Intent.HOW_IT_WORKS),
    (re.compile(r"\b(where is|find the|locate|implementation of|defined)\b", re.I), Intent.LOCATE_IMPL),
]

_PLANS: dict[Intent, IntentPlan] = {
    Intent.LOCATE_IMPL: IntentPlan(Intent.LOCATE_IMPL, {"symbol": 1.0, "path": 0.7, "fts": 0.4, "vector": 0.2}, 1500),
    Intent.HOW_IT_WORKS: IntentPlan(Intent.HOW_IT_WORKS, {"fts": 1.0, "symbol": 0.7, "path": 0.3, "vector": 0.8}, 2200, graph_strategy="down"),
    Intent.IMPACT: IntentPlan(Intent.IMPACT, {"symbol": 1.0, "path": 0.6, "fts": 0.3, "vector": 0.3}, 1800, graph_strategy="up"),
    Intent.FIND_REFS: IntentPlan(Intent.FIND_REFS, {"symbol": 1.0, "fts": 0.3, "path": 0.2, "vector": 0.2}, 1500, graph_strategy="refs"),
    Intent.DATA_FLOW: IntentPlan(Intent.DATA_FLOW, {"symbol": 0.9, "fts": 0.8, "path": 0.3, "vector": 0.6}, 2000, graph_strategy="both"),
    Intent.DEBUG_ERROR: IntentPlan(Intent.DEBUG_ERROR, {"fts": 1.0, "symbol": 0.6, "path": 0.3, "vector": 0.4}, 1800),
    Intent.ARCHITECTURE: IntentPlan(Intent.ARCHITECTURE, {"fts": 0.6, "symbol": 0.4, "path": 0.5, "vector": 0.5}, 2500, summaries_first=True),
    Intent.KEYWORD: IntentPlan(Intent.KEYWORD, {"fts": 1.0, "symbol": 0.6, "path": 0.5, "vector": 0.7}, 1500),
}


def detect_intent(query: str) -> IntentPlan:
    for pattern, intent in _RULES:
        if pattern.search(query):
            return _PLANS[intent]
    return _PLANS[Intent.KEYWORD]
