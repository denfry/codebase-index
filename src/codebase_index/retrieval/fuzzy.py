"""Deterministic fuzzy matching for symbol identifiers.

The module deliberately works on one identifier pair (or a caller-provided
candidate sequence).  It does not inspect the repository or perform any I/O;
searchers can therefore decide how many rows to fetch before reranking.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Mapping, Sequence
from typing import Any, TypeVar


_IDENTIFIER_PART_RE = re.compile(r"[^\W_]+", re.UNICODE)
_CAMEL_PART_RE = re.compile(
    r"[A-Z]+(?=[A-Z][a-z]|[0-9]|$)|[A-Z]?[a-z]+|[0-9]+"
)
_MAX_EDIT_INPUT = 256

T = TypeVar("T")


def _fold(value: str) -> str:
    """Return a case-folded, compatibility-normalized string."""
    return unicodedata.normalize("NFKC", value).casefold()


def _tokens(value: str) -> tuple[str, ...]:
    """Split an identifier into case-insensitive word and camel-case parts."""
    normalized = unicodedata.normalize("NFKC", value)
    parts: list[str] = []
    for segment in _IDENTIFIER_PART_RE.findall(normalized):
        camel_parts = _CAMEL_PART_RE.findall(segment)
        parts.extend(_fold(part) for part in (camel_parts or [segment]) if part)
    return tuple(parts)


def _compact(value: str) -> str:
    """Remove identifier separators while retaining Unicode letters/digits."""
    folded = _fold(value)
    return "".join(char for char in folded if char.isalnum())


def _acronym(tokens: tuple[str, ...]) -> str:
    return "".join(token[0] for token in tokens if token)


def _bounded_levenshtein_similarity(left: str, right: str, max_distance: int) -> float:
    """Compute normalized Levenshtein similarity with a bounded edit window."""
    if left == right:
        return 1.0
    if not left or not right:
        return 0.0
    longest = max(len(left), len(right))
    if longest > _MAX_EDIT_INPUT:
        # Containment and token features still work for long names, while this
        # guard prevents an accidental quadratic allocation for pathological input.
        return 0.0
    if abs(len(left) - len(right)) > max_distance:
        return 0.0

    # Keep the shorter value on the columns to reduce memory use.
    if len(left) < len(right):
        left, right = right, left
    width = len(right)
    previous = list(range(width + 1))
    infinity = max_distance + longest + 1
    for row, left_char in enumerate(left, 1):
        current = [infinity] * (width + 1)
        current[0] = row
        lo = max(1, row - max_distance)
        hi = min(width, row + max_distance)
        row_min = current[0]
        for column in range(lo, hi + 1):
            substitution = previous[column - 1] + (left_char != right[column - 1])
            insertion = current[column - 1] + 1
            deletion = previous[column] + 1
            value = min(substitution, insertion, deletion)
            current[column] = value
            row_min = min(row_min, value)
        if row_min > max_distance:
            return 0.0
        previous = current

    distance = previous[width]
    if distance > max_distance:
        return 0.0
    return max(0.0, 1.0 - distance / longest)


def _ordered_subtoken_coverage(query: str, name_tokens: tuple[str, ...]) -> tuple[float, float]:
    """Measure name subtokens found in a concatenated query.

    This is what makes ``userid`` match ``getUserById``: ``user`` and ``id``
    occur in order even though the candidate has an intervening ``by`` token.
    The second return value is the fraction of candidate subtokens covered.
    """
    if not query or not name_tokens:
        return 0.0, 0.0
    cursor = 0
    matched_chars = 0
    matched_tokens = 0
    for token in name_tokens:
        if len(token) < 2:
            continue
        position = query.find(token, cursor)
        if position < 0:
            continue
        cursor = position + len(token)
        matched_chars += len(token)
        matched_tokens += 1
    return matched_chars / len(query), matched_tokens / len(name_tokens)


def _token_overlap(query_tokens: tuple[str, ...], name_tokens: tuple[str, ...]) -> float:
    if not query_tokens or not name_tokens:
        return 0.0
    covered = 0
    for query_token in query_tokens:
        match_size = 0
        for name_token in name_tokens:
            if query_token == name_token or query_token in name_token:
                match_size = max(match_size, len(query_token))
            elif name_token in query_token:
                match_size = max(match_size, len(name_token))
        covered += match_size
    query_size = sum(len(token) for token in query_tokens)
    return covered / query_size if query_size else 0.0


def identifier_similarity(
    query: str,
    name: str,
    *,
    max_edit_distance: int = 64,
) -> float:
    """Return deterministic identifier similarity in the inclusive range [0, 1].

    The score combines case-folded/separator-insensitive equality, token and
    concatenation containment, prefixes, acronyms, and bounded edit similarity.
    A score is not an exactness claim; callers must keep their separate
    ``exact_symbol``/database exact flag unchanged.
    """
    if not isinstance(query, str) or not isinstance(name, str):
        return 0.0
    if max_edit_distance < 0:
        raise ValueError("max_edit_distance must be non-negative")

    query_tokens = _tokens(query)
    name_tokens = _tokens(name)
    query_compact = _compact(query)
    name_compact = _compact(name)
    if not query_compact or not name_compact:
        return 0.0
    if query_compact == name_compact:
        return 1.0
    # One-character identifiers are too ambiguous for non-exact matching.
    if min(len(query_compact), len(name_compact)) < 2:
        return 0.0

    score = 0.0
    name_acronym = _acronym(name_tokens)
    query_is_acronym = len(query) >= 2 and query.strip().isupper() and len(query_compact) >= 2
    if query_compact == name_acronym and len(query_compact) >= 2:
        score = max(score, 0.94)
    elif len(query_compact) >= 3 and name_acronym.startswith(query_compact):
        score = max(score, 0.77 + 0.15 * len(query_compact) / len(name_acronym))

    if query_compact in name_compact:
        ratio = len(query_compact) / len(name_compact)
        score = max(score, (0.72 if name_compact.startswith(query_compact) else 0.64) + 0.22 * ratio)
    elif name_compact in query_compact:
        ratio = len(name_compact) / len(query_compact)
        score = max(score, 0.60 + 0.22 * ratio)

    overlap = _token_overlap(query_tokens, name_tokens)
    if overlap:
        score = max(score, 0.32 + 0.34 * overlap)

    query_fit, candidate_token_ratio = _ordered_subtoken_coverage(query_compact, name_tokens)
    if query_fit >= 0.8:
        score = max(score, 0.76 + 0.15 * query_fit * candidate_token_ratio)
    elif query_fit:
        score = max(score, 0.25 + 0.55 * query_fit * candidate_token_ratio)

    edit = _bounded_levenshtein_similarity(query_compact, name_compact, max_edit_distance)
    # Edit distance alone can make a short query look deceptively close to a
    # much longer identifier merely because they share a common token.  Keep
    # useful typo matches, but dampen length-mismatched pairs; containment and
    # token features above remain responsible for those matches.
    length_ratio = min(len(query_compact), len(name_compact)) / max(
        len(query_compact), len(name_compact)
    )
    if length_ratio < 0.6:
        edit *= length_ratio / 0.6
    # An all-uppercase query is generally an acronym; near-edit matches to an
    # unrelated acronym should not pass a fuzzy threshold by edit distance alone.
    if query_is_acronym:
        edit *= 0.55
    score = max(score, edit)
    return min(1.0, max(0.0, score))


def _candidate_value(candidate: Any, key: str, default: Any = None) -> Any:
    if isinstance(candidate, Mapping):
        return candidate.get(key, default)
    try:
        return candidate[key]
    except (KeyError, IndexError, TypeError):
        return getattr(candidate, key, default)


def _candidate_exact(candidate: Any) -> bool:
    """Read either the public Candidate flag or a repository row's exact flag."""
    value = _candidate_value(candidate, "exact_symbol", None)
    if value is None:
        value = _candidate_value(candidate, "is_exact", False)
    return bool(value)


def _candidate_name(candidate: Any) -> str:
    value = _candidate_value(candidate, "symbol", None)
    if not value:
        value = _candidate_value(candidate, "name", "")
    return value if isinstance(value, str) else ""


def rank_fuzzy_symbols(
    query: str,
    candidates: Sequence[T],
    *,
    threshold: float = 0.55,
    limit: int | None = None,
    max_edit_distance: int = 64,
) -> list[T]:
    """Filter and rank a provided candidate list by identifier similarity.

    Candidates may be ``Candidate`` objects, mappings/SQLite rows with a
    ``symbol`` or ``name`` field, or small compatible records.  Returned values
    are the original objects (not copies), and their exactness flags are never
    changed.  Ties use score, pre-existing score, identifier, path, location,
    and original position to make ordering reproducible across runs.
    """
    if not math.isfinite(threshold) or not 0.0 <= threshold <= 1.0:
        raise ValueError("threshold must be finite and between 0 and 1")
    if limit is not None and limit < 0:
        raise ValueError("limit must be non-negative or None")
    if limit == 0:
        return []

    ranked: list[tuple[tuple[Any, ...], T]] = []
    for position, candidate in enumerate(candidates):
        name = _candidate_name(candidate)
        score = identifier_similarity(query, name, max_edit_distance=max_edit_distance)
        if score < threshold:
            continue
        exact = _candidate_exact(candidate)
        base_score = _candidate_value(candidate, "score", 0.0)
        try:
            base_score = float(base_score)
        except (TypeError, ValueError):
            base_score = 0.0
        path = str(_candidate_value(candidate, "path", "")).casefold()
        line_start = _candidate_value(candidate, "line_start", 0)
        line_end = _candidate_value(candidate, "line_end", 0)
        identifier = name.casefold()
        key = (-int(exact), -score, -base_score, identifier, path, line_start, line_end, position)
        ranked.append((key, candidate))

    ranked.sort(key=lambda item: item[0])
    result = [candidate for _, candidate in ranked]
    return result if limit is None else result[:limit]


__all__ = ["identifier_similarity", "rank_fuzzy_symbols"]
