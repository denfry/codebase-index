from codebase_index.retrieval.diversity import (
    deduplicate,
    mmr_select,
    normalize_code_tokens,
    simhash_distance,
    token_fingerprint,
)
from codebase_index.retrieval.types import Candidate


def _candidate(path: str, score: float, content: str, *, symbol: str | None = None) -> Candidate:
    return Candidate(
        path=path,
        line_start=1,
        line_end=4,
        source="fts",
        score=score,
        content=content,
        symbol=symbol,
    )


def test_deduplicate_collapses_formatting_and_comments_and_keeps_best():
    weaker = _candidate("weak.py", 0.4, "def add(a, b):\n    return a + b")
    stronger = _candidate(
        "strong.py", 0.9, "# comment\ndef add(a,b):\n\treturn a + b  # trailing comment"
    )

    result = deduplicate([weaker, stronger])

    assert result == [stronger]
    assert weaker.score == 0.4  # caller-owned candidates are not mutated


def test_deduplicate_keeps_structurally_distinct_snippets():
    left = _candidate("left.py", 0.8, "def add(a, b): return a + b")
    right = _candidate("right.py", 0.7, "def multiply(a, b): return a * b")

    assert deduplicate([left, right]) == [left, right]


def test_mmr_balances_relevance_against_redundancy():
    first = _candidate("first.py", 1.0, "def add(a, b): return a + b", symbol="add")
    near = _candidate("near.py", 0.95, "def add(a,b): return a + b", symbol="add")
    distinct = _candidate("distinct.py", 0.55, "def parse(value): return decode(value)", symbol="parse")

    assert mmr_select([first, near, distinct], 2, lambda_=1.0) == [first, near]
    assert mmr_select([first, near, distinct], 2, lambda_=0.0) == [first, distinct]


def test_selection_handles_empty_and_singleton_inputs_without_mutation():
    candidate = _candidate("one.py", 1.0, "return 1")
    assert deduplicate([]) == []
    assert mmr_select([], 3, lambda_=0.5) == []
    assert mmr_select([candidate], 3, lambda_=0.5) == [candidate]


def _reference_fingerprint(tokens: tuple[str, ...]) -> int:
    """Naive per-occurrence SimHash: the definition the fast path must match."""
    import hashlib

    if not tokens:
        return 0
    weights = [0] * 64
    for token in tokens:
        hashed = int.from_bytes(
            hashlib.blake2b(str(token).encode("utf-8"), digest_size=8).digest(), "big"
        )
        for bit in range(64):
            weights[bit] += 1 if (hashed >> bit) & 1 else -1
    fingerprint = 0
    for bit, weight in enumerate(weights):
        if weight >= 0:
            fingerprint |= 1 << bit
    return fingerprint & ((1 << 64) - 1)


def test_fingerprint_matches_per_occurrence_definition():
    """Folding duplicate tokens by count is an optimisation, not a behaviour change."""
    cases = [
        (),
        ("a",),
        ("a", "a", "a"),
        ("def", "add", "a", "b", "return", "a", "b"),
        ("ключ", "значение", "ключ"),                 # non-ASCII identifiers
        ("x" * 4096,),                                # pathological single token
        tuple(f"tok{i % 7}" for i in range(500)),     # heavy repetition
    ]
    for tokens in cases:
        assert token_fingerprint(tokens) == _reference_fingerprint(tokens), tokens


def test_fingerprint_is_stable_across_calls_and_order_sensitive_only_by_content():
    tokens = normalize_code_tokens("def add(a, b):\n    return a + b")
    assert token_fingerprint(tokens) == token_fingerprint(tokens)
    assert simhash_distance(token_fingerprint(tokens), token_fingerprint(tokens)) == 0


def test_fingerprint_handles_empty_and_none_content():
    assert token_fingerprint(None) == 0
    assert token_fingerprint("") == 0
    assert token_fingerprint(()) == 0


def test_deduplicate_keeps_untokenizable_candidates_distinct():
    """Comment-only snippets normalise to no tokens; they must not collapse together."""
    left = _candidate("a.py", 0.9, "# just a comment")
    right = _candidate("b.py", 0.8, "# another comment")
    assert deduplicate([left, right]) == [left, right]


def test_deduplicate_is_deterministic_for_identical_scores():
    first = _candidate("a.py", 0.5, "def f(): return 1")
    second = _candidate("b.py", 0.5, "def f():  return 1")
    assert deduplicate([first, second]) == deduplicate([first, second]) == [first]


def test_deduplicate_collapses_a_long_duplicate_run_to_one():
    dupes = [_candidate(f"f{i}.py", 1.0 - i / 100, "def f(a):\n    return a") for i in range(12)]
    assert deduplicate(dupes) == [dupes[0]]
