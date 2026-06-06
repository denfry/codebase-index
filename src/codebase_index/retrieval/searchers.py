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

from ..config import Config
from ..indexer.freshness import compute_freshness
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


def fts_candidates(conn: sqlite3.Connection, query: str, *, limit: int) -> list[M4Candidate]:
    match = build_match_query(query)
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


# Natural-language filler that is never a useful symbol query term. Kept deliberately small:
# anything that could plausibly be an identifier (get/set/run/...) is NOT a stopword.
_SYMBOL_STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being", "how", "does",
    "do", "did", "what", "where", "which", "who", "whom", "when", "why", "to", "of", "in",
    "on", "for", "and", "or", "with", "from", "it", "this", "that", "these", "those",
    "into", "during", "if", "via", "across", "between", "about", "their", "its",
}


def _salient_terms(query: str) -> list[str]:
    """Lower-cased query terms worth matching against symbol names (dedup, order-preserving)."""
    out: list[str] = []
    for t in _WORD_RE.findall(query):
        tl = t.lower()
        if len(tl) < 3 or tl in _SYMBOL_STOPWORDS:
            continue
        out.append(tl)
    return list(dict.fromkeys(out))


def _name_subtokens(name: str) -> set[str]:
    """camelCase + snake_case split of a symbol name, lower-cased (e.g. ReligionManager ->
    {religion, manager}; refresh_access_token -> {refresh, access, token})."""
    return {s.lower() for s in _subtokens(name)}


def symbol_candidates(
    conn: sqlite3.Connection, query: str, *, limit: int, kind: str | None = None
) -> list[M4Candidate]:
    """Symbol retriever that scores by how many query terms a symbol's name covers.

    The old behaviour searched only the single longest term, so "religion manager" matched
    the bare `Religion` class (exact) and never reached `ReligionManager`. Now every salient
    term is searched and candidates are ranked by camelCase/underscore-split *coverage* of the
    query, so the multi-word concept lands on the multi-word symbol.
    """
    terms = _salient_terms(query)
    if not terms:
        return []

    term_set = set(terms)
    joined = "".join(terms)
    rows_by_key: dict[tuple, sqlite3.Row] = {}
    for term in terms:
        for row in repo.symbol_search(conn, term, limit=limit, kind=kind):
            key = (row["path"], row["line_start"], row["name"])
            rows_by_key.setdefault(key, row)

    scored: list[tuple] = []
    for row in rows_by_key.values():
        subs = _name_subtokens(row["name"])
        name_l = (row["name"] or "").lower()
        covered = sum(1 for t in terms if t in subs or t in name_l)
        tightness = len(subs & term_set) / len(subs) if subs else 0.0
        # Exact-match precedence is for *precise* lookups only. With one salient term it's a
        # real identifier query; with many it must match the whole camelCase-joined name
        # (e.g. "religion manager" -> ReligionManager). A single shared term ("token" hitting
        # a generated `Token` type) must NOT count as exact.
        exact = (len(terms) == 1 and bool(row["is_exact"])) or (bool(joined) and name_l == joined)
        # Ranking: most query terms covered, then exact-name match, then a tighter name
        # (fewer junk subtokens), then more-referenced (in_degree), then a shorter name.
        sort_key = (covered, int(exact), tightness, int(row["in_degree"]), -len(name_l))
        score = covered + tightness + (2.0 if exact else 0.0)
        scored.append((sort_key, score, exact, row))

    scored.sort(key=lambda x: x[0], reverse=True)

    out: list[M4Candidate] = []
    for sort_key, score, exact, row in scored[:limit]:
        out.append(
            M4Candidate(
                path=row["path"],
                line_start=row["line_start"],
                line_end=row["line_end"],
                source="symbol",
                score=float(score),
                kind=row["kind"],
                symbol=row["name"],
                content=row["signature"],
                token_est=max(1, len(row["signature"] or "") // 4),
                in_degree=int(row["in_degree"]),
                out_degree=int(row["out_degree"]),
                is_generated=bool(row["is_generated"]),
                exact_symbol=exact,
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
    kind: str = "window"


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
    # FTS5 rejects implicit AND (space) when a group contains parenthesised OR
    # expressions; explicit AND is required between all groups.
    return " AND ".join(groups)


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
            kind=r.get("kind", "window"),  # type: ignore[attr-defined]
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
    config: Optional[Config] = None,
) -> SearchResponse:
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
                reason="doc match" if candidate.kind == "doc" else "lexical match (bm25)",
                snippet=snippet,
            )
        )

    confidence = _confidence(candidates)
    return SearchResponse(
        query=query,
        intent="keyword",
        index=_freshness(conn, root, config),
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
    top, second = candidates[0], candidates[1]
    gap = abs(second.bm25 - top.bm25)
    n = len(candidates)
    # Clear BM25 separation, or moderate gap with several corroborating results
    if gap >= 2.0 or (gap >= 1.0 and n >= 3):
        return "high"
    if gap >= 0.3 or n >= 3:
        return "medium"
    return "low"


def _fallbacks(query: str) -> dict[str, list[str]]:
    terms = _WORD_RE.findall(query)
    primary = terms[0] if terms else query
    return {"ripgrep": [f'rg -n "{primary}"', f'rg -ni "{primary}"']}


def _freshness(
    conn: sqlite3.Connection, root: Optional[Path] = None, config: Optional[Config] = None
) -> IndexFreshness:
    if config is not None and root is not None:
        return compute_freshness(conn, root, config)
    built_at = repo.get_meta(conn, "built_at")
    return IndexFreshness(
        exists=built_at is not None,
        stale=False,
        files_changed_since_build=0,
        built_at=built_at,
        head_commit=repo.get_meta(conn, "head_commit"),
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


def vector_candidates(
    conn: sqlite3.Connection, query: str, backend, *, limit: int
) -> list["M4Candidate"]:
    """Semantic retriever: embed the query, KNN over vec_chunks.

    `backend` must be an enabled EmbeddingBackend; callers pass None/Noop when
    embeddings are disabled and simply skip this retriever. sqlite-vec `distance`
    is smaller-is-better, so the candidate score negates it for "higher is better".
    """
    if backend is None or not getattr(backend, "enabled", False):
        return []
    query = query.strip()
    if not query:
        return []
    vec = backend.embed([query])[0]
    out: list[M4Candidate] = []
    for row in repo.vector_search(conn, vec, limit=limit):
        out.append(
            M4Candidate(
                path=row["path"],
                line_start=row["line_start"],
                line_end=row["line_end"],
                source="vector",
                score=-float(row["distance"]),
                content=row["content"],
                token_est=int(row["token_est"]),
            )
        )
    return out
