"""Three retrievers, each emitting a uniform list[Candidate].

Vector retrieval (RETRIEVAL.md §2) is M6 and intentionally absent here; the
pipeline degrades to path+symbol+fts.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..models import (
    Confidence,
    IndexFreshness,
    ReadRange,
    RefSite,
    RefsResponse,
    Result,
    SearchResponse,
    SymbolDef,
    SymbolResponse,
)
from ..output.redact import redact_snippet
from ..storage import repo
from .types import Candidate as M4Candidate

_WORD_RE = re.compile(r"[A-Za-z0-9_]+")
_CAMEL_RE = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z0-9]+")
_SNIPPET_MAX_LINES = 18

# FTS5 MATCH is sensitive to punctuation; reduce a NL query to bare terms.
_TERM_RE = re.compile(r"[A-Za-z0-9_]+")


def _fts_match_query(query: str) -> str:
    terms = _TERM_RE.findall(query)
    return " OR ".join(f'"{t}"' for t in terms)


def fts_candidates(conn: sqlite3.Connection, query: str, *, limit: int) -> list[M4Candidate]:
    match = _fts_match_query(query)
    if not match:
        return []
    out: list[M4Candidate] = []
    for row in repo.fts_search(conn, match, limit=limit):
        out.append(
            M4Candidate(
                path=row["path"],
                line_start=row["line_start"],
                line_end=row["line_end"],
                source="fts",
                score=-float(row["bm25"]),
                content=row["content"],
                token_est=int(row["token_est"]),
            )
        )
    return out


def symbol_candidates(
    conn: sqlite3.Connection, query: str, *, limit: int, kind: str | None = None
) -> list[M4Candidate]:
    ids = _TERM_RE.findall(query)
    if not ids:
        return []
    name = max(ids, key=len)
    out: list[M4Candidate] = []
    rows = repo.symbol_search(conn, name, limit=limit, kind=kind)
    for rank, row in enumerate(rows):
        out.append(
            M4Candidate(
                path=row["path"],
                line_start=row["line_start"],
                line_end=row["line_end"],
                source="symbol",
                score=1.0 / (1 + rank),
                kind=row["kind"],
                symbol=row["name"],
                content=row["signature"],
                token_est=max(1, len(row["signature"] or "") // 4),
                in_degree=int(row["in_degree"]),
                out_degree=int(row["out_degree"]),
                is_generated=bool(row["is_generated"]),
                exact_symbol=bool(row["is_exact"]),
            )
        )
    return out


def path_candidates(conn: sqlite3.Connection, query: str, *, limit: int) -> list[M4Candidate]:
    out: list[M4Candidate] = []
    for rank, row in enumerate(repo.path_search(conn, query, limit=limit)):
        out.append(
            M4Candidate(
                path=row["path"],
                line_start=1,
                line_end=1,
                source="path",
                score=float(row["hits"]) / (1 + rank),
                is_generated=bool(row["is_generated"]),
            )
        )
    return out


@dataclass
class Candidate:
    chunk_id: int
    path: str
    line_start: int
    line_end: int
    content: str
    token_est: int
    bm25: float


def _subtokens(term: str) -> list[str]:
    parts: list[str] = []
    for piece in term.split("_"):
        parts.extend(m.group(0) for m in _CAMEL_RE.finditer(piece))
    return [p for p in parts if len(p) >= 2]


def build_match_query(query: str) -> str:
    groups: list[str] = []
    for term in _WORD_RE.findall(query):
        variants = {term, *_subtokens(term)}
        variants = {v for v in variants if len(v) >= 2}
        if not variants:
            continue
        ored = " OR ".join(f'"{v}"' for v in sorted(variants, key=str.lower))
        groups.append(f"({ored})" if len(variants) > 1 else ored)
    return " ".join(groups)


def fts_search(conn: sqlite3.Connection, query: str, *, limit: int) -> list[Candidate]:
    match = build_match_query(query)
    rows = repo.fts_search(conn, match, limit=limit)
    return [
        Candidate(
            chunk_id=r["chunk_id"],
            path=r["path"],
            line_start=r["line_start"],
            line_end=r["line_end"],
            content=r["content"],
            token_est=r["token_est"],
            bm25=r["bm25"],
        )
        for r in rows
    ]


def fts_response(
    conn: sqlite3.Connection,
    query: str,
    *,
    limit: int,
    token_budget: int,
    root: Path,
) -> SearchResponse:
    del root
    candidates = fts_search(conn, query, limit=limit)
    results: list[Result] = []
    recommended: list[ReadRange] = []
    spent = 0

    for rank, candidate in enumerate(candidates, start=1):
        recommended.append(
            ReadRange(
                path=candidate.path,
                line_start=candidate.line_start,
                line_end=candidate.line_end,
            )
        )
        snippet: Optional[str] = None
        if spent + candidate.token_est <= token_budget:
            snippet = redact_snippet(_trim(candidate.content))
            spent += candidate.token_est
        results.append(
            Result(
                rank=rank,
                path=candidate.path,
                line_start=candidate.line_start,
                line_end=candidate.line_end,
                symbols=[],
                score=round(1.0 / rank, 4),
                reason="lexical match (bm25)",
                snippet=snippet,
            )
        )

    confidence = _confidence(candidates)
    return SearchResponse(
        query=query,
        intent="keyword",
        index=_freshness(conn),
        confidence=confidence,
        results=results,
        recommended_reads=recommended,
        fallback_suggestions=_fallbacks(query) if confidence != "high" else {},
    )


def _trim(content: str) -> str:
    lines = content.splitlines()
    if len(lines) <= _SNIPPET_MAX_LINES:
        return content
    return "\n".join(lines[:_SNIPPET_MAX_LINES]) + "\n..."


def _confidence(candidates: list[Candidate]) -> Confidence:
    if not candidates:
        return "low"
    if len(candidates) == 1:
        return "medium"
    gap = abs(candidates[1].bm25 - candidates[0].bm25)
    return "high" if gap >= 1.0 else "medium"


def _fallbacks(query: str) -> dict[str, list[str]]:
    terms = _WORD_RE.findall(query)
    primary = terms[0] if terms else query
    return {"ripgrep": [f'rg -n "{primary}"', f'rg -ni "{primary}"']}


def _freshness(conn: sqlite3.Connection) -> IndexFreshness:
    built_at = repo.get_meta(conn, "built_at")
    head = repo.get_meta(conn, "head_commit")
    return IndexFreshness(
        exists=built_at is not None,
        stale=False,
        files_changed_since_build=0,
        built_at=built_at,
        head_commit=head,
    )


def symbol_lookup(
    conn: sqlite3.Connection, name: str, *, kind: Optional[str], exact: bool
) -> SymbolResponse:
    rows = repo.symbols_by_name(conn, name, kind=kind, exact=exact)
    symbols = [
        SymbolDef(
            name=row["name"],
            qualified=row["qualified"],
            kind=row["kind"],
            path=row["path"],
            line_start=row["line_start"],
            line_end=row["line_end"],
            signature=row["signature"],
        )
        for row in rows
    ]
    return SymbolResponse(query=name, index=_freshness(conn), symbols=symbols)


def refs_lookup(conn: sqlite3.Connection, name: str, *, kind: str) -> RefsResponse:
    sites = [
        RefSite(path=row["path"], line=row["line"], kind="call")
        for row in repo.refs_for_name(conn, name)
    ]
    if kind == "all":
        sites.extend(
            RefSite(path=row["path"], line=row["line_start"], kind="definition")
            for row in repo.symbols_by_name(conn, name, exact=True)
        )
    sites.sort(key=lambda site: (site.path, site.line, site.kind))
    return RefsResponse(query=name, index=_freshness(conn), sites=sites)
