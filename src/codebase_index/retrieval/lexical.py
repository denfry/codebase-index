"""Safe, code-aware lexical query parsing.

The lexical retriever needs two things that a plain ``str.split`` cannot provide:
identifier-aware variants (``getUserById`` -> ``get``, ``user``, ``by``, ``id``)
and a deliberately tiny vocabulary of programming synonyms.  This module keeps
those concerns independent of SQLite/FTS so callers can apply their own ranking
and ablation policy.
"""

from __future__ import annotations

from dataclasses import dataclass
import math
import re
from types import MappingProxyType
from typing import Literal, Mapping


# A token may contain the separators used by identifiers. Other punctuation is
# a boundary, which also means arbitrary FTS operators never reach the builder.
_TOKEN_RE = re.compile(r"[^\W_]+(?:[_-][^\W_]+)*", re.UNICODE)

# Keep this list conservative: words such as ``get``, ``set`` and ``run`` can
# be real identifiers and must not be discarded from a code search.
LEXICAL_STOPWORDS = frozenset(
    {
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
        # Common query framing, not useful lexical evidence.
        "work",
        "works",
        "working",
        "function",
        "functions",
        "method",
        "methods",
        "class",
        "classes",
        "interface",
        "interfaces",
        "enum",
        "enums",
        "type",
        "types",
    }
)

# Values are tuples rather than sets to make expansion order deterministic.
# The map is intentionally explicit and small; it is not a general thesaurus.
SYNONYM_MAP: Mapping[str, tuple[str, ...]] = MappingProxyType(
    {
        "auth": ("authentication",),
        "authentication": ("auth",),
        "config": ("configuration",),
        "configuration": ("config",),
        "delete": ("remove",),
        "remove": ("delete",),
        "create": ("add", "insert"),
        "add": ("create", "insert"),
        "insert": ("create", "add"),
        "repo": ("repository",),
        "repository": ("repo",),
        "retry": ("retries",),
        "retries": ("retry",),
        "caller": ("callers",),
        "callers": ("caller",),
        "test": ("tests",),
        "tests": ("test",),
        # Small, explicit inflection bridges for natural-language questions.
        "redacted": ("redact",),
        "redaction": ("redact",),
        "secrets": ("secret",),
        "files": ("file",),
        "chosen": ("choose",),
        "produced": ("produce",),
        "raises": ("raise",),
        "parsing": ("parse",),
        "loaded": ("load",),
        "merged": ("merge", "merg"),
        "merging": ("merge", "merg"),
        "ranking": ("rank",),
    }
)
TermKind = Literal["original", "subtoken", "synonym"]


@dataclass(frozen=True, slots=True)
class WeightedTerm:
    """A lexical term variant and its relative ranking weight."""

    term: str
    weight: float
    kind: TermKind
    origin: str


@dataclass(frozen=True, slots=True)
class LexicalQuery:
    """Parsed query with original terms kept distinct from expansions.

    ``original_terms`` are salient, normalized query tokens. ``expanded_terms``
    never contains an original term and is ordered by source term, then
    subtokens before synonyms. Ranking code can use :attr:`weighted_terms` to
    preserve the stronger score of originals without parsing query strings.
    """

    original_terms: tuple[str, ...]
    expanded_terms: tuple[WeightedTerm, ...]

    @property
    def weighted_terms(self) -> tuple[WeightedTerm, ...]:
        originals = tuple(
            WeightedTerm(term=term, weight=1.0, kind="original", origin=term)
            for term in self.original_terms
        )
        return originals + self.expanded_terms

    @property
    def terms(self) -> tuple[str, ...]:
        """All terms in deterministic ranking order, originals first per source."""
        return tuple(item.term for item in self.weighted_terms)

    @property
    def weights(self) -> Mapping[str, float]:
        """Highest applicable weight per term, useful for score accumulation."""
        out: dict[str, float] = {}
        for item in self.weighted_terms:
            out[item.term] = max(out.get(item.term, 0.0), item.weight)
        return MappingProxyType(out)

    def to_fts(self, *, include_expansions: bool = True) -> str:
        return build_fts_query(self, include_expansions=include_expansions)


def _is_identifier_char(char: str) -> bool:
    # ``isalnum`` handles non-ASCII letters and decimal digits without relying
    # on locale or third-party Unicode tables.
    return char.isalnum()


def _camel_boundary(previous: str, current: str, following: str | None) -> bool:
    """Whether ``current`` starts a new camel/Pascal component."""
    if not current.isupper():
        return False
    if previous.islower() or previous.isdigit():
        return True
    # ``HTTPServer`` -> ``HTTP``, ``Server``: the S starts a word because the
    # acronym run is ending before a lowercase letter.
    return previous.isupper() and following is not None and following.islower()


def split_identifier(identifier: str) -> tuple[str, ...]:
    """Split common identifier forms into lowercase components.

    Underscores and hyphens are separators. Case transitions cover camelCase,
    PascalCase and acronym runs, while non-ASCII alphanumeric characters are
    retained. Concatenations such as ``userid`` are intentionally not guessed
    apart: without a dictionary, doing so creates noisy false positives.
    """

    if not identifier:
        return ()

    parts: list[str] = []
    current: list[str] = []

    def flush() -> None:
        if current:
            parts.append("".join(current).casefold())
            current.clear()

    for index, char in enumerate(identifier):
        if char in "_-" or not _is_identifier_char(char):
            flush()
            continue
        if current:
            previous = current[-1]
            following = identifier[index + 1] if index + 1 < len(identifier) else None
            if _camel_boundary(previous, char, following):
                flush()
        current.append(char)
    flush()
    return tuple(part for part in parts if part)


def salient_terms(query: str) -> tuple[str, ...]:
    """Return normalized, deduplicated query terms worth lexical matching."""

    out: list[str] = []
    seen: set[str] = set()
    for token in _TOKEN_RE.findall(query):
        term = token.casefold()
        if len(term) < 2 or term in LEXICAL_STOPWORDS or term in seen:
            continue
        seen.add(term)
        out.append(term)
    return tuple(out)


def _bounded_weight(value: float) -> float:
    try:
        value = float(value)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(value):
        return 0.0
    return max(0.0, min(value, 0.999999))


def build_lexical_query(
    query: str,
    *,
    synonym_weight: float = 0.35,
    subtoken_weight: float = 0.65,
    include_synonyms: bool = True,
    include_subtokens: bool = True,
    tuning: object | None = None,
) -> LexicalQuery:
    """Parse ``query`` and produce deterministic, down-weighted expansions.

    ``tuning`` is optional to avoid coupling this pure module to a config type;
    when supplied, ``query_expansion`` and ``expansion_weight`` attributes are
    honored. Callers may still explicitly disable either expansion family.
    """

    if tuning is not None:
        if hasattr(tuning, "query_expansion"):
            include_synonyms = include_synonyms and bool(tuning.query_expansion)
        if hasattr(tuning, "expansion_weight"):
            synonym_weight = float(tuning.expansion_weight)

    raw_terms: dict[str, str] = {}
    for token in _TOKEN_RE.findall(query):
        normalized = token.casefold()
        if len(normalized) >= 2 and normalized not in LEXICAL_STOPWORDS:
            raw_terms.setdefault(normalized, token)
    originals = salient_terms(query)
    original_set = set(originals)
    expanded: list[WeightedTerm] = []
    emitted: set[str] = set(original_set)
    sub_weight = _bounded_weight(subtoken_weight)
    syn_weight = _bounded_weight(synonym_weight)

    for original in originals:
        identifier = raw_terms.get(original, original)
        if include_subtokens:
            for subtoken in split_identifier(identifier):
                if subtoken in emitted or len(subtoken) < 2:
                    continue
                emitted.add(subtoken)
                expanded.append(
                    WeightedTerm(
                        term=subtoken,
                        weight=sub_weight,
                        kind="subtoken",
                        origin=original,
                    )
                )
        if include_synonyms:
            for synonym in SYNONYM_MAP.get(original, ()):
                if synonym in emitted or len(synonym) < 2:
                    continue
                emitted.add(synonym)
                expanded.append(
                    WeightedTerm(
                        term=synonym,
                        weight=syn_weight,
                        kind="synonym",
                        origin=original,
                    )
                )

    return LexicalQuery(original_terms=originals, expanded_terms=tuple(expanded))


def expansion_weights(
    query: str | LexicalQuery,
    *,
    synonym_weight: float = 0.35,
    subtoken_weight: float = 0.65,
    include_synonyms: bool = True,
    include_subtokens: bool = True,
    tuning: object | None = None,
) -> Mapping[str, float]:
    """Return the strongest relative weight for each parsed lexical term."""

    parsed = (
        query
        if isinstance(query, LexicalQuery)
        else build_lexical_query(
            query,
            synonym_weight=synonym_weight,
            subtoken_weight=subtoken_weight,
            include_synonyms=include_synonyms,
            include_subtokens=include_subtokens,
            tuning=tuning,
        )
    )
    return parsed.weights


def escape_fts_term(term: str) -> str:
    """Quote one FTS5 term so operators and quotes are treated literally."""

    # FTS5 phrase syntax escapes an embedded quote by doubling it. NUL is not a
    # valid SQLite string character in all bindings, so replace it defensively.
    return '"' + term.replace("\x00", " ").replace('"', '""') + '"'


def build_fts_query(
    query: str | LexicalQuery,
    *,
    include_expansions: bool = True,
    synonym_weight: float = 0.35,
    subtoken_weight: float = 0.65,
    include_synonyms: bool = True,
    include_subtokens: bool = True,
    tuning: object | None = None,
) -> str:
    """Build a safe FTS5 expression with originals first in each OR group.

    FTS5 MATCH itself has no portable per-term boost. The returned expression
    therefore groups each original with its variants, while
    :func:`expansion_weights` exposes graduated weights for the caller's ranker.
    Every emitted value is quoted, so input cannot inject MATCH operators.
    """

    parsed = (
        query
        if isinstance(query, LexicalQuery)
        else build_lexical_query(
            query,
            synonym_weight=synonym_weight,
            subtoken_weight=subtoken_weight,
            include_synonyms=include_synonyms,
            include_subtokens=include_subtokens,
            tuning=tuning,
        )
    )
    if not parsed.original_terms:
        return ""

    by_origin: dict[str, list[str]] = {term: [] for term in parsed.original_terms}
    if include_expansions:
        for item in parsed.expanded_terms:
            by_origin.setdefault(item.origin, []).append(item.term)

    groups: list[str] = []
    for original in parsed.original_terms:
        variants = [original, *by_origin.get(original, [])]
        quoted = [escape_fts_term(term) for term in variants]
        groups.append(quoted[0] if len(quoted) == 1 else "(" + " OR ".join(quoted) + ")")
    return " AND ".join(groups)


__all__ = [
    "LEXICAL_STOPWORDS",
    "SYNONYM_MAP",
    "LexicalQuery",
    "WeightedTerm",
    "build_fts_query",
    "build_lexical_query",
    "escape_fts_term",
    "expansion_weights",
    "salient_terms",
    "split_identifier",
]
