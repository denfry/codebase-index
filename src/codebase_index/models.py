"""Shared result models (pydantic). The same shapes feed both JSON and Markdown renderers.

Mirrors the payload documented in docs/RETRIEVAL.md §8.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel

Intent = Literal[
    "locate_impl", "how_it_works", "impact", "find_refs",
    "data_flow", "debug_error", "architecture", "keyword",
]
Confidence = Literal["high", "medium", "low"]


class IndexFreshness(BaseModel):
    exists: bool
    stale: bool
    files_changed_since_build: int = 0
    built_at: Optional[str] = None
    head_commit: Optional[str] = None


class ReadRange(BaseModel):
    path: str
    line_start: int
    line_end: int


class Result(BaseModel):
    rank: int
    path: str
    line_start: int
    line_end: int
    symbols: list[str] = []
    score: float
    reason: str
    snippet: Optional[str] = None


class SearchResponse(BaseModel):
    query: str
    intent: Intent
    index: IndexFreshness
    confidence: Confidence
    results: list[Result] = []
    recommended_reads: list[ReadRange] = []
    fallback_suggestions: dict[str, list[str]] = {}


class SymbolDef(BaseModel):
    name: str
    qualified: Optional[str] = None
    kind: str
    path: str
    line_start: int
    line_end: int
    signature: Optional[str] = None


class SymbolResponse(BaseModel):
    query: str
    index: IndexFreshness
    symbols: list[SymbolDef] = []


class RefSite(BaseModel):
    path: str
    line: int
    kind: str


class RefsResponse(BaseModel):
    query: str
    index: IndexFreshness
    sites: list[RefSite] = []


class ImpactNode(BaseModel):
    kind: str                       # 'file' | 'symbol'
    path: str
    name: Optional[str] = None      # symbol name (None for file nodes)
    line_start: Optional[int] = None
    distance: int                   # BFS hops from the target (1 = direct)
    via_edge: Optional[str] = None  # edge_type that linked it (import|call|extends|...)


class ImpactResponse(BaseModel):
    target: str
    direction: str                  # 'up' | 'down' | 'both'
    depth: int
    index: IndexFreshness
    nodes: list[ImpactNode] = []
    files: list[str] = []           # distinct affected files, ranked
