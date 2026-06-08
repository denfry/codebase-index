"""Shared result models (pydantic). The same shapes feed both JSON and Markdown renderers.

Mirrors the payload documented in docs/RETRIEVAL.md §8.
"""

from __future__ import annotations

from typing import Iterable, Literal, Optional

from pydantic import BaseModel, Field

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


class GraphCoverage(BaseModel):
    """Honesty signal for graph-derived answers (refs/impact).

    Dependency edges (imports / inheritance) are only extracted for the fully
    supported (Tier-A) languages. A symbol or file in a Tier-B language (generic
    tree-sitter walk) yields symbols and best-effort call sites but no
    import/extends/implements edges, so refs/impact can undercount. When
    ``partial`` is true an *empty or short* result does not prove there are no
    references — it may just be unanalyzed; confirm with Grep.
    """

    partial: bool = False
    languages: list[str] = []
    reason: Optional[str] = None

    @classmethod
    def for_paths(cls, paths: Iterable[str]) -> "GraphCoverage":
        from .discovery.classify import detect_language, parser_for
        from .parsers.languages import spec_for

        tier_b = sorted(
            {
                lang
                for p in paths
                if (lang := detect_language(p)) is not None
                and parser_for(lang) == "treesitter"
                and spec_for(lang) is None
            }
        )
        if not tier_b:
            return cls()
        return cls(
            partial=True,
            languages=tier_b,
            reason=(
                "Import/inheritance edges are not extracted for "
                f"{', '.join(tier_b)} (best-effort symbols only). An empty or short "
                "result is inconclusive — confirm with a Grep over the codebase."
            ),
        )


class RefSite(BaseModel):
    path: str
    line: int
    kind: str


class RefsResponse(BaseModel):
    query: str
    index: IndexFreshness
    sites: list[RefSite] = []
    coverage: GraphCoverage = Field(default_factory=GraphCoverage)


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
    coverage: GraphCoverage = Field(default_factory=GraphCoverage)
