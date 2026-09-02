"""Deterministic diversity helpers for retrieval candidates.

The module deliberately has no index, model, or repository dependencies. Code
snippets are reduced to lexical tokens, making formatting and comments
irrelevant to near-duplicate detection. MMR uses the same compact lexical
features when no caller-provided similarity function is supplied.
"""

from __future__ import annotations

import hashlib
import math
from collections import Counter
from collections.abc import Callable, Iterable, Sequence
from functools import lru_cache

from .types import Candidate

_MASK64 = (1 << 64) - 1


def normalize_code_tokens(content: str | None) -> tuple[str, ...]:
    """Return normalized code tokens, omitting whitespace and comments."""
    if not content:
        return ()

    tokens: list[str] = []
    length = len(content)
    index = 0
    operators = (
        "===", "!==", ">>>=", "**=", "...", "=>", "->", "::", "==", "!=", "<=", ">=",
        "&&", "||", "++", "--", "+=", "-=", "*=", "/=", "%=", "<<", ">>", "**", "??",
    )

    while index < length:
        char = content[index]
        if char.isspace():
            index += 1
            continue
        if content.startswith("//", index) or char == "#":
            newline = content.find("\n", index + (2 if content.startswith("//", index) else 1))
            index = length if newline < 0 else newline + 1
            continue
        if content.startswith("/*", index):
            end = content.find("*/", index + 2)
            index = length if end < 0 else end + 2
            continue

        if char in "'\"`":
            quote = char
            triple = content.startswith(char * 3, index)
            width = 3 if triple else 1
            cursor = index + width
            while cursor < length:
                if content[cursor] == "\\":
                    cursor += 2
                    continue
                if content.startswith(quote * width, cursor):
                    cursor += width
                    break
                cursor += 1
            tokens.append("str:" + content[index + width : max(index + width, cursor - width)])
            index = cursor
            continue

        if char.isalpha() or char == "_" or ord(char) >= 128:
            cursor = index + 1
            while cursor < length and (
                content[cursor].isalnum() or content[cursor] == "_" or ord(content[cursor]) >= 128
            ):
                cursor += 1
            tokens.append(content[index:cursor].lower())
            index = cursor
            continue

        if char.isdigit():
            cursor = index + 1
            while cursor < length and (content[cursor].isalnum() or content[cursor] in "._"):
                cursor += 1
            tokens.append(content[index:cursor].lower())
            index = cursor
            continue

        operator = next((candidate for candidate in operators if content.startswith(candidate, index)), None)
        if operator is not None:
            tokens.append(operator)
            index += len(operator)
        else:
            tokens.append(char)
            index += 1

    return tuple(tokens)


@lru_cache(maxsize=1 << 16)
def _token_digest(token: str) -> int:
    """64-bit blake2b digest of one token. Pure, so caching is safe and bounded.

    Source chunks repeat identifiers and keywords heavily both inside a chunk and
    across the candidate pool, and hashing dominated fingerprint cost.
    """
    return int.from_bytes(
        hashlib.blake2b(token.encode("utf-8"), digest_size=8).digest(), "big", signed=False
    )


def token_fingerprint(tokens: Iterable[str] | str | None) -> int:
    """Compute a stable unsigned 64-bit SimHash for tokens or source content."""
    if tokens is None:
        return 0
    if isinstance(tokens, str):
        tokens = normalize_code_tokens(tokens)
    values = tuple(tokens)
    if not values:
        return 0

    # Weighting distinct tokens by multiplicity is arithmetically identical to
    # summing each occurrence, and collapses the per-occurrence hash and 64-bit
    # accumulation loop to per-distinct-token work. Output is bit-for-bit unchanged.
    weights = [0] * 64
    for token, count in Counter(str(value) for value in values).items():
        hashed = _token_digest(token)
        for bit in range(64):
            weights[bit] += count if (hashed >> bit) & 1 else -count

    fingerprint = 0
    for bit, weight in enumerate(weights):
        if weight >= 0:
            fingerprint |= 1 << bit
    return fingerprint & _MASK64


simhash = token_fingerprint


def simhash_distance(left: int, right: int) -> int:
    """Return the Hamming distance between two 64-bit fingerprints."""
    return ((int(left) ^ int(right)) & _MASK64).bit_count()


def _features(candidate: Candidate) -> tuple[tuple[str, ...], frozenset[str], int | None]:
    tokens = normalize_code_tokens(candidate.content)
    return tokens, frozenset(tokens), token_fingerprint(tokens) if tokens else None


def _score_value(candidate: Candidate) -> float:
    score = float(candidate.score)
    return score if math.isfinite(score) else float("-inf")


def _same_or_better(left: Candidate, right: Candidate) -> bool:
    """Whether `left` (the incumbent) should stay the representative.

    Ties favor the incumbent, i.e. input order. Candidates arrive sorted by score,
    so a later duplicate is never strictly better; deciding ties by ">" instead
    handed the slot to whichever equal-scoring copy happened to arrive last, making
    the retained snippet depend on retriever emission order.
    """
    return _score_value(left) >= _score_value(right)


def deduplicate(candidates: Sequence[Candidate], hamming_distance: int = 3) -> list[Candidate]:
    """Suppress near-identical snippets, retaining the highest-scoring hit."""
    if not candidates:
        return []
    threshold = max(0, min(64, int(hamming_distance)))
    representatives: list[Candidate] = []
    fingerprints: list[int | None] = []

    for candidate in candidates:
        # Only the fingerprint is needed here; building the token set as well
        # doubled the per-candidate cost of the pipeline's hottest stage. "No
        # fingerprint" means "no tokens", never "fingerprint happened to be 0".
        tokens = normalize_code_tokens(candidate.content)
        fingerprint = token_fingerprint(tokens) if tokens else None
        if fingerprint is None:
            representatives.append(candidate)
            fingerprints.append(None)
            continue

        # Carry each match's fingerprint alongside its index: it is known non-None
        # by construction here, and re-reading it from the list later would lose
        # that guarantee.
        matches = [
            (index, existing)
            for index, existing in enumerate(fingerprints)
            if existing is not None and simhash_distance(fingerprint, existing) <= threshold
        ]
        if not matches:
            representatives.append(candidate)
            fingerprints.append(fingerprint)
            continue

        indices = [index for index, _ in matches]
        first = indices[0]
        winner = candidate
        # The winner is either this candidate or an incumbent, and both
        # fingerprints are already known — recomputing one from content was pure
        # duplicated work.
        winner_fingerprint = fingerprint
        for index, existing in matches:
            incumbent = representatives[index]
            if _same_or_better(incumbent, winner):
                winner = incumbent
                winner_fingerprint = existing
        for index in reversed(indices):
            representatives.pop(index)
            fingerprints.pop(index)
        representatives.insert(first, winner)
        fingerprints.insert(first, winner_fingerprint)

    return representatives


def _normalized_relevance(candidates: Sequence[Candidate]) -> list[float]:
    scores = [_score_value(candidate) for candidate in candidates]
    finite = [score for score in scores if math.isfinite(score)]
    if not finite:
        return [0.0] * len(candidates)
    low, high = min(finite), max(finite)
    if high <= low:
        return [1.0 if math.isfinite(score) else 0.0 for score in scores]
    return [
        max(0.0, min(1.0, (score - low) / (high - low))) if math.isfinite(score) else 0.0
        for score in scores
    ]


def _similarity_from_features(
    left: Candidate,
    right: Candidate,
    left_features: tuple[tuple[str, ...], frozenset[str], int | None],
    right_features: tuple[tuple[str, ...], frozenset[str], int | None],
) -> float:
    _, left_set, left_hash = left_features
    _, right_set, right_hash = right_features
    if left_set or right_set:
        union = left_set | right_set
        lexical = len(left_set & right_set) / len(union) if union else 0.0
        sim = 1.0 - simhash_distance(left_hash or 0, right_hash or 0) / 64.0
        value = 0.75 * lexical + 0.25 * sim
    else:
        value = 0.0

    if left.path == right.path:
        value = max(value, 0.35)
    if left.symbol and right.symbol and left.symbol == right.symbol:
        value = max(value, 0.45)
    return max(0.0, min(1.0, value))


def candidate_similarity(left: Candidate, right: Candidate) -> float:
    """Fallback similarity from lexical Jaccard/SimHash plus structure."""
    return _similarity_from_features(left, right, _features(left), _features(right))


def mmr_select(
    candidates: Sequence[Candidate],
    limit: int,
    lambda_: float,
    *,
    similarity: Callable[[Candidate, Candidate], float] | None = None,
) -> list[Candidate]:
    """Select up to ``limit`` candidates with maximal marginal relevance."""
    if not candidates or limit <= 0:
        return []
    count = min(int(limit), len(candidates))
    weight = float(lambda_)
    weight = 0.5 if not math.isfinite(weight) else max(0.0, min(1.0, weight))
    relevance = _normalized_relevance(candidates)
    feature_cache = [_features(candidate) for candidate in candidates]
    compare = similarity
    remaining = set(range(len(candidates)))
    selected: list[int] = []

    while remaining and len(selected) < count:
        best_index: int | None = None
        best_key: tuple[float, float, int] | None = None
        for index in sorted(remaining):
            if compare is None:
                redundancy = max(
                    (
                        _similarity_from_features(
                            candidates[index],
                            candidates[chosen],
                            feature_cache[index],
                            feature_cache[chosen],
                        )
                        for chosen in selected
                    ),
                    default=0.0,
                )
            else:
                redundancy = max(
                    (
                        max(
                            0.0,
                            min(1.0, float(compare(candidates[index], candidates[chosen]))),
                        )
                        for chosen in selected
                    ),
                    default=0.0,
                )
            utility = weight * relevance[index] - (1.0 - weight) * redundancy
            key = (utility, relevance[index], -index)
            if best_key is None or key > best_key:
                best_key = key
                best_index = index
        assert best_index is not None
        remaining.remove(best_index)
        selected.append(best_index)

    return [candidates[index] for index in selected]


__all__ = [
    "candidate_similarity",
    "deduplicate",
    "mmr_select",
    "normalize_code_tokens",
    "simhash",
    "simhash_distance",
    "token_fingerprint",
]
