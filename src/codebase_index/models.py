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
