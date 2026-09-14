"""Deterministic query<->candidate ranking features.

The fused RRF score answers "how many retrievers liked this candidate, and how
much". It cannot answer "does this candidate's *name* actually talk about the
thing the query asked for", because every retriever scores each query term
independently and RRF only ever sums those independent verdicts.

That gap is a measured failure mode, not a hypothetical one. Two examples from
the benchmark, both ranked wrong by 1.9.0:

    "graph resolution + traversal accessors"
        won by  graph/retrieval.py            (`graph`  — one term)
        beating test_graph_accessors_...      (`graph` + `accessors` + `resolve`)

    "greedy token budgeting with redaction"
        won by  output/redact.py              (`redact` — one term)
        beating retrieval/budget.py           (`budget` + `token`)

The winner in each pair matched *one* query term very well. The correct answer
matched *several* terms in a single name. Summing per-term evidence cannot tell
those apart, so the signal has to be an interaction: credit terms for occurring
*together* in one name, over and above their individual matches.

Design constraints, all of which the eval harness enforces:

  * Bounded. Cost is O(len(path) + len(symbol) + len(terms)) per candidate, with
    no corpus statistics, no posting-list scan, and no second query.
  * Deterministic. Set membership over identifier components; no floating-point
    accumulation order dependence, no randomness, no I/O.
  * Explainable. The score reduces to a count the reranker can print verbatim.

Feature variants that were measured and rejected are recorded in
`docs/RETRIEVAL.md`; the short version is that idf weighting (pool-local or
corpus-wide), substring matching, proximity, ordered-subsequence matching, and
body-text coverage all failed to beat this one feature on held-out repositories.
"""

from __future__ import annotations

from dataclasses import dataclass

from .lexical import salient_terms, split_identifier


def _components(text: str) -> set[str]:
    """Lowercase identifier components of *text* (camelCase and snake_case aware).

    `split_identifier` is applied to the whole string rather than to regex-matched
    words first: it already treats `_`, `-` and every non-alphanumeric character as
    a separator, and it decides "alphanumeric" with `str.isalnum`. Pre-splitting on
    an ASCII word pattern would silently reduce `расчёт_налога` to nothing, so
    non-ASCII identifiers could never earn this bonus while the query side — which
    parses Unicode correctly — happily produced the matching terms.
    """
    return set(split_identifier(text))


def name_zone(path: str, symbol: str | None) -> set[str]:
    """Identifier components of a candidate's *name*: file basename + symbol.

    Directories are excluded deliberately. A path prefix such as
    ``src/main/java/net/denfry/newtowny/`` is shared by hundreds of files, so its
    components carry no evidence about which of them answers the query while
    adding co-occurrence noise to all of them. Measured on eight repositories,
    including the parent directory was worth -0.001 MRR: indistinguishable from
    noise, for strictly more code.
    """
    basename = path.replace("\\", "/").rsplit("/", 1)[-1]
    stem = basename[: basename.rfind(".")] if "." in basename else basename
    zone = _components(stem)
    if symbol:
        zone |= _components(symbol)
    return zone


@dataclass(frozen=True, slots=True)
class QueryProfile:
    """Query terms worth matching against a candidate name, computed once per query.

    Built from :func:`lexical.salient_terms`, so stopword policy stays in one
    place and the reranker cannot drift from the retrievers' idea of a term.
    """

    terms: tuple[str, ...]

    @property
    def n_terms(self) -> int:
        return len(self.terms)


def query_profile(query: str) -> QueryProfile:
    return QueryProfile(terms=salient_terms(query))


def name_cooccurrence(profile: QueryProfile, zone: set[str]) -> tuple[int, float]:
    """Return (terms matched in *zone*, co-occurrence score in [0, 1]).

    The score credits only the query terms *beyond the first*:

        score = max(0, matched - 1) / (n_terms - 1)

    A candidate whose name matches one query term scores 0 — it has shown no
    interaction, and its single match is already fully paid for by the retriever
    that surfaced it. The second matched term is what distinguishes
    ``test_graph_accessors_resolve_and_walk`` from ``graph_candidates`` on the
    query "graph resolution + traversal accessors", so that is where the credit
    starts. Normalising by ``n_terms - 1`` keeps the feature comparable between a
    two-term and a nine-term query.

    Single-term queries return 0.0: there is no co-occurrence to observe, and the
    exact-name machinery in the symbol retriever already handles them.
    """
    n = profile.n_terms
    if n < 2 or not zone:
        return 0, 0.0
    matched = sum(1 for term in profile.terms if term in zone)
    if matched < 2:
        return matched, 0.0
    return matched, (matched - 1) / (n - 1)
