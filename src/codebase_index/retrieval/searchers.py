"""Three retrievers, each emitting a uniform list[Candidate].

Vector retrieval is optional and supplied by the configured embedding backend;
without it the pipeline degrades cleanly to path, symbol, and FTS retrieval.
"""

from __future__ import annotations

import math
import re
import sqlite3
from pathlib import Path
from typing import Optional, Sequence

from ..config import Config
from ..discovery.classify import detect_language, is_test_path
from ..parsers.languages import CONTAINER_KINDS
from ..graph.builder import language_family
from ..parsers.base import names_a_type
from ..indexer.freshness import compute_freshness
from ..models import (
    GraphCoverage,
    IndexFreshness,
    RefSite,
    RefsResponse,
    SymbolDef,
    SymbolResponse,
    unmatched_coverage,
)
from ..storage import repo
from .fuzzy import identifier_similarity
from .lexical import (
    LexicalQuery,
    build_fts_query,
    build_lexical_query,
    escape_fts_term,
    salient_terms as lexical_salient_terms,
)
from .tuning import DEFAULT_TUNING
from .types import Candidate as M4Candidate

_WORD_RE = re.compile(r"[A-Za-z0-9_]+")
_CAMEL_RE = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z0-9]+")


def _soft_match_query(parsed: LexicalQuery) -> str:
    """OR lexical groups so Python can rank by group coverage.

    FTS5 cannot express per-term boosts portably. Each original term is grouped
    with its down-weighted variants, then groups are OR-ed. Candidate scoring
    below restores coverage and original-term precedence.
    """
    by_origin: dict[str, list[str]] = {term: [] for term in parsed.original_terms}
    for item in parsed.expanded_terms:
        by_origin.setdefault(item.origin, []).append(item.term)
    groups: list[str] = []
    for original in parsed.original_terms:
        variants = [original, *by_origin.get(original, [])]
        quoted = [escape_fts_term(term) for term in variants]
        groups.append(quoted[0] if len(quoted) == 1 else "(" + " OR ".join(quoted) + ")")
    return " OR ".join(groups)


def _fts_coverage(content: str | None, parsed: LexicalQuery) -> tuple[int, float]:
    text = (content or "").casefold()
    matched = 0
    weighted = 0.0
    weights = parsed.weights
    for original in parsed.original_terms:
        variants = [
            original,
            *(item.term for item in parsed.expanded_terms if item.origin == original),
        ]
        # Longer code terms are safe and much cheaper as substring probes.
        # Two-character terms need token boundaries to avoid `id` matching
        # every `grid`/`identifier` occurrence.
        found = next(
            (
                term
                for term in variants
                if (
                    term.casefold() in text
                    if len(term) > 2
                    else bool(
                        re.search(
                            rf"(?<![A-Za-z0-9_]){re.escape(term.casefold())}"
                            r"(?![A-Za-z0-9_])",
                            text,
                        )
                    )
                )
            ),
            None,
        )
        if found is not None:
            matched += 1
            weighted += weights.get(found, 1.0)
    return matched, weighted


def fts_candidates(
    conn: sqlite3.Connection, query: str, *, limit: int, tuning=DEFAULT_TUNING
) -> list[M4Candidate]:
    parsed = build_lexical_query(
        query,
        include_synonyms=bool(tuning.query_expansion),
        include_subtokens=True,
        tuning=tuning,
    )
    match = build_match_query(query, tuning=tuning)
    if not match:
        return []
    # Soft OR queries need a wider first-stage pool; ranking by coverage happens
    # locally after FTS. The multiplier is bounded so long natural-language
    # questions do not turn into an unbounded scan.
    fetch_limit = max(limit, limit * min(5, max(2, len(parsed.original_terms))))
    rows = repo.fts_search(conn, match, limit=fetch_limit)
    if not rows:
        return []

    scored_rows: list[tuple[float, int, float, sqlite3.Row]] = []
    for row in rows:
        if tuning.soft_lexical and parsed.original_terms:
            matched, weighted = _fts_coverage(row["content"], parsed)
            required = max(1, math.ceil(len(parsed.original_terms) * tuning.min_term_coverage))
            if matched < required:
                continue
            coverage = matched / len(parsed.original_terms)
            score = coverage * 2.0 + weighted / len(parsed.original_terms) * 0.35
        else:
            score = 0.0
            matched = 0
            weighted = 0.0
        # BM25 is an additional tie-break, never the dominant signal in soft mode.
        bm25 = max(0.0, -float(row["bm25"]))
        score += min(bm25, 4.0) * (0.08 if tuning.soft_lexical else 1.0)
        scored_rows.append((score, matched, bm25, row))

    # If coverage threshold was too strict for an unusual query, retain FTS
    # recall rather than returning an empty list.
    if tuning.soft_lexical and not scored_rows:
        scored_rows = [
            (
                max(0.0, -float(row["bm25"])),
                0,
                max(0.0, -float(row["bm25"])),
                row,
            )
            for row in rows
        ]
    scored_rows.sort(
        key=lambda item: (-item[0], -item[1], -item[2], item[3]["path"], item[3]["line_start"])
    )
    out: list[M4Candidate] = []
    for score, matched, _, row in scored_rows[:limit]:
        reason = (
            f"lexical coverage {matched}/{len(parsed.original_terms)}"
            if tuning.soft_lexical and parsed.original_terms
            else "fts bm25"
        )
        out.append(
            M4Candidate(
                path=row["path"],
                line_start=row["line_start"],
                line_end=row["line_end"],
                source="fts",
                score=score,
                content=row["content"],
                token_est=int(row["token_est"]),
                reason=reason,
            )
        )
    return out


# Natural-language filler that is never a useful symbol query term. Kept deliberately small:
# anything that could plausibly be an identifier (get/set/run/...) is NOT a stopword.
_SYMBOL_STOPWORDS = {
    "the",
    "a",
    "an",
    "is",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "how",
    "does",
    "do",
    "did",
    "what",
    "where",
    "which",
    "who",
    "whom",
    "when",
    "why",
    "to",
    "of",
    "in",
    "on",
    "for",
    "and",
    "or",
    "with",
    "from",
    "it",
    "this",
    "that",
    "these",
    "those",
    "into",
    "during",
    "if",
    "via",
    "across",
    "between",
    "about",
    "their",
    "its",
    "find",
    "locate",
    "show",
    "me",
    "implemented",
    "implementation",
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


def _fuzzy_symbol_rows(
    conn: sqlite3.Connection, query: str, *, limit: int, kind: str | None
) -> list[sqlite3.Row]:
    """Fetch a small lexical neighborhood for fuzzy symbol scoring.

    The symbol table has a name index but no trigram index. Query terms, their
    four-character prefixes, and acronym initials provide a bounded candidate
    pool without scanning every symbol; identifier_similarity does the precise
    comparison locally.
    """
    raw_terms = [t for t in _WORD_RE.findall(query) if len(t) >= 2]
    needles: set[str] = set()
    for term in raw_terms:
        needles.add(term)
        if len(term) >= 4:
            needles.add(term[:4])
        if len(term) >= 2 and term.isupper():
            needles.add(term[:1])
    rows_by_key: dict[tuple, sqlite3.Row] = {}
    per_query = max(limit, min(limit * 2, 40))
    for needle in sorted(needles, key=lambda item: (len(item), item.casefold())):
        for row in repo.symbol_search(conn, needle, limit=per_query, kind=kind):
            rows_by_key.setdefault((row["path"], row["line_start"], row["name"]), row)
    return list(rows_by_key.values())


def symbol_candidates(
    conn: sqlite3.Connection,
    query: str,
    *,
    limit: int,
    kind: str | None = None,
    tuning=DEFAULT_TUNING,
) -> list[M4Candidate]:
    """Return symbols ranked by name coverage, exactness, and optional fuzziness."""
    terms = (
        [term for term in lexical_salient_terms(query) if term not in _SYMBOL_STOPWORDS]
        if tuning.query_expansion
        else _salient_terms(query)
    )
    expanded_terms = []
    if tuning.query_expansion:
        parsed = build_lexical_query(query, tuning=tuning)
        expanded_terms = [
            item.term
            for item in parsed.expanded_terms
            if item.kind == "synonym" and item.term not in terms
        ]
    symbol_terms = list(dict.fromkeys((*terms, *expanded_terms)))
    if not terms:
        return []
    term_set = set(terms)
    joined = "".join(terms)

    # Precise lookup first (exact -> prefix -> substring). It answers most real
    # queries on its own, and knowing its yield is what lets fuzzy matching stay
    # off the hot path.
    rows_by_key: dict[tuple, sqlite3.Row] = {}
    for needle in symbol_terms:
        for row in repo.symbol_search(conn, needle, limit=limit, kind=kind):
            rows_by_key.setdefault((row["path"], row["line_start"], row["name"]), row)

    fuzzy_enabled = tuning.fuzzy_symbols and (
        len(terms) <= 3 or any(char.isupper() for char in query)
    )
    if fuzzy_enabled and tuning.fuzzy_fallback_min > 0:
        # Bounded edit distance over a lexical neighborhood is the single most
        # expensive step in the pipeline. Spend it only when the precise lookup
        # came up short: naming a real symbol, or simply returning enough
        # candidates, means the query spelled its identifier well enough that
        # fuzzing adds cost and noise rather than recall.
        original_names = {term.casefold() for term in terms}
        named_a_symbol = any(
            (row["name"] or "").casefold() in original_names for row in rows_by_key.values()
        )
        fuzzy_enabled = not (
            named_a_symbol or len(rows_by_key) >= tuning.fuzzy_fallback_min
        )
    if fuzzy_enabled:
        for row in _fuzzy_symbol_rows(conn, query, limit=limit, kind=kind):
            rows_by_key.setdefault((row["path"], row["line_start"], row["name"]), row)

    # A constructor shares its class's name, and its `new X()` callers give it the
    # higher in-degree, so it used to take the file's one slot on the page with a
    # one-line body while the class it constructs never appeared. Keep the class.
    types_found = {
        (row["path"], row["name"]) for row in rows_by_key.values()
        if row["kind"] in CONTAINER_KINDS
    }
    rows_by_key = {
        key: row for key, row in rows_by_key.items()
        if not (
            row["kind"] == "method"
            and (row["path"], row["name"]) in types_found
            and (row["qualified"] or "").endswith(f"{row['name']}.{row['name']}")
        )
    }

    scored: list[tuple] = []
    for row in rows_by_key.values():
        subs = _name_subtokens(row["name"])
        name_l = (row["name"] or "").casefold()
        covered = sum(1 for t in terms if t in subs or t.casefold() in name_l)
        expanded_covered = sum(1 for t in expanded_terms if t in subs or t.casefold() in name_l)
        tightness = len(subs & term_set) / len(subs) if subs else 0.0
        # Exactness is judged against the user's own terms, never against an
        # expansion. `row["is_exact"]` is relative to whichever needle happened to
        # retrieve the row, so a synonym needle ("config" for "configuration") used
        # to mark a merely-related symbol as an exact match — worth +0.20 at rerank
        # and HIGH confidence. Comparing names locally is needle-independent.
        exact = (len(terms) == 1 and name_l == terms[0].casefold()) or (
            bool(joined) and name_l == joined.casefold()
        )
        fuzzy = 0.0
        if fuzzy_enabled:
            fuzzy = max(
                identifier_similarity(term, row["name"]) for term in (*terms, joined) if term
            )
            if (
                not exact
                and covered == 0
                and expanded_covered == 0
                and fuzzy < tuning.fuzzy_threshold
            ):
                continue
        sort_key = (
            int(exact),
            covered,
            expanded_covered,
            tightness,
            int(row["in_degree"]),
            -len(name_l),
            name_l,
            row["path"],
            int(row["line_start"]),
        )
        score = (
            covered
            + 0.35 * expanded_covered
            + tightness
            + (2.0 if exact else 0.0)
            + fuzzy * (0.65 if fuzzy_enabled else 0.0)
        )
        scored.append((sort_key, score, exact, row))

    scored.sort(key=lambda item: item[0], reverse=True)
    out: list[M4Candidate] = []
    for _, score, exact, row in scored[:limit]:
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

    zero_deg = [c.symbol for c in out if not c.in_degree and c.symbol]
    if zero_deg:
        counts = repo.name_ref_counts(conn, zero_deg)
        for c in out:
            if not c.in_degree and c.symbol:
                c.ref_count = counts.get(c.symbol, 0)
    return out


def path_candidates(
    conn: sqlite3.Connection,
    query: str,
    *,
    limit: int,
    tuning=DEFAULT_TUNING,
) -> list[M4Candidate]:
    if tuning.query_expansion:
        parsed = build_lexical_query(
            query,
            include_synonyms=True,
            include_subtokens=False,
            tuning=tuning,
        )
        variants = [
            *parsed.original_terms,
            *(item.term for item in parsed.expanded_terms if item.kind == "synonym"),
        ]
        path_query = " ".join(dict.fromkeys(variants))
    else:
        path_query = query
    out: list[M4Candidate] = []
    for rank, row in enumerate(repo.path_search(conn, path_query, limit=limit)):
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


def _subtokens(term: str) -> list[str]:
    parts: list[str] = []
    for piece in term.split("_"):
        parts.extend(m.group(0) for m in _CAMEL_RE.finditer(piece))
    return [p for p in parts if len(p) >= 2]


def build_match_query(query: str, *, tuning=None) -> str:
    """Build a safe FTS5 MATCH expression.

    Calls without ``tuning`` preserve the 1.7 public helper exactly (including
    its deliberate retention of identifier-like words such as ``work``).
    Tuned retrieval uses the lexical parser: soft mode ORs term groups so
    coverage can be ranked in Python; hard mode keeps groups AND-ed.
    """
    if tuning is None:
        groups: list[str] = []
        salient: list[str] = []
        for term in _WORD_RE.findall(query):
            variants = {term, *_subtokens(term)}
            variants = {v for v in variants if len(v) >= 2}
            if not variants:
                continue
            ored = " OR ".join(f'"{v}"' for v in sorted(variants, key=str.lower))
            group = f"({ored})" if len(variants) > 1 else ored
            groups.append(group)
            if term.lower() not in _SYMBOL_STOPWORDS:
                salient.append(group)
        return " AND ".join(salient or groups)

    parsed = build_lexical_query(
        query,
        include_synonyms=bool(tuning.query_expansion),
        include_subtokens=True,
        tuning=tuning,
    )
    if not parsed.original_terms:
        return ""
    if tuning.soft_lexical:
        return _soft_match_query(parsed)
    return build_fts_query(parsed, include_expansions=bool(tuning.query_expansion))


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
    rows = repo.symbols_by_name(conn, name, kind=kind, exact=True)
    more = 0
    if not exact:
        prefixed = repo.symbols_by_name(conn, name, kind=kind, exact=False)
        if rows:
            # An exact hit is what was asked for; twenty `TreasuryX` prefix matches
            # around it cost tokens and bury it.
            more = len(prefixed) - len(rows)
        else:
            rows = prefixed
    member = repo.split_member(name) if not rows else None
    if member is not None:
        rows = [r for r in repo.symbols_by_owner(conn, *member) if not kind or r["kind"] == kind]
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
    return SymbolResponse(
        query=name, index=_freshness(conn), symbols=symbols, more_prefix_matches=more
    )


def refs_lookup(
    conn: sqlite3.Connection,
    name: str,
    *,
    kind: str,
    exclude_tests: bool = False,
    paths: Sequence[str] = (),
) -> RefsResponse:
    """Definitions, calls and references of `name` (a bare or `Owner.member` name).

    `exclude_tests` drops sites in test files; `paths` keeps only sites under one of
    the given path prefixes. Both filter what is reported, including the count of
    possible calls behind `coverage.partial`.
    """
    defs, member = repo.symbols_for_target(conn, name)
    possible: list[sqlite3.Row] = []
    if member is None:
        rows = repo.refs_for_name(conn, name)
    else:
        # `Owner.member`: calls resolved to one of Owner's definitions, plus
        # unresolved calls made on a receiver literally named Owner.
        owner, short = member
        def_ids = {int(row["id"]) for row in defs}
        rows, possible = [], []
        for row in repo.refs_for_name(conn, short):
            if row["dst_id"] in def_ids or (row["dst_id"] is None and row["receiver"] == owner):
                rows.append(row)
            elif defs and row["edge_type"] == "call" and _may_call_member(row, defs):
                possible.append(row)
    if kind == "callers":
        rows = [row for row in rows if row["edge_type"] == "call"]
    keep = _site_filter(exclude_tests, paths)
    rows = [row for row in rows if keep(row["path"])]
    possible = [row for row in possible if keep(row["path"])]
    sites = [_ref_site(row, row["edge_type"]) for row in rows]
    sites += [_ref_site(row, "possible_call") for row in possible]
    if kind == "all":
        sites.extend(
            # A definition is the symbol itself — exact by construction.
            RefSite(
                path=row["path"], line=row["line_start"], kind="definition",
                target=row["qualified"] or row["name"],
            )
            for row in defs
            if keep(row["path"])
        )
    def_paths = [row["path"] for row in defs]
    # Known sites by location; possible ones after them, nearest to a definition first.
    sites.sort(key=lambda site: (
        site.kind == "possible_call",
        -_shared_dirs(site.path, def_paths) if site.kind == "possible_call" else 0,
        site.path, site.line, site.kind,
    ))
    # Coverage is judged by the symbol's defining language(s); fall back to the
    # call-site files when the symbol has no indexed definition.
    if not (defs or sites):
        coverage = unmatched_coverage(name)
    else:
        coverage = GraphCoverage.for_paths(def_paths or [s.path for s in sites])
    if possible:
        coverage = GraphCoverage(
            partial=True,
            languages=coverage.languages,
            reason=(
                f"{len(possible)} call(s) to `{member[1] if member else name}` have a "
                "receiver the index cannot type (a variable or an expression such as "
                "`chest.holdings()`), so any of them may call this. They are listed as "
                "`possible_call`, nearest to the definition first; read the ones that "
                "matter to confirm."
            ),
        )
    return RefsResponse(query=name, index=_freshness(conn), sites=sites, coverage=coverage)


def _site_filter(exclude_tests: bool, paths: Sequence[str]):
    prefixes = tuple(p.replace("\\", "/").strip("/") + "/" for p in paths if p.strip("/\\"))

    def keep(path: str) -> bool:
        if exclude_tests and is_test_path(path):
            return False
        return not prefixes or any((path + "/").startswith(p) for p in prefixes)

    return keep


def _ref_site(row: sqlite3.Row, kind: str) -> RefSite:
    return RefSite(
        path=row["path"],
        line=row["line"],
        kind=kind,
        confidence=row["confidence"] if "confidence" in row.keys() else "extracted",
        target=row["target"],
        receiver=row["receiver"],
        caller=row["src_qualified"] or row["src_name"],
    )


def _may_call_member(row: sqlite3.Row, defs: list[sqlite3.Row]) -> bool:
    """An unresolved same-named call that could still land on one of `defs`.

    A receiver naming another type (`ApprenticeService.take`) cannot; a variable,
    constant or expression receiver might. Only calls written in a
    language one of the definitions is written in are considered.
    """
    if row["dst_id"] is not None:
        return False
    if names_a_type(row["receiver"]):
        return False
    families = {language_family(detect_language(d["path"])) for d in defs}
    return language_family(detect_language(row["path"])) in families


def _shared_dirs(path: str, others: list[str]) -> int:
    """Longest run of leading directories `path` shares with any of `others`."""
    parts = path.split("/")[:-1]
    best = 0
    for other in others:
        shared = 0
        for a, b in zip(parts, other.split("/")[:-1]):
            if a != b:
                break
            shared += 1
        best = max(best, shared)
    return best


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
