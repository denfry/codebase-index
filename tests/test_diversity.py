from codebase_index.retrieval.diversity import deduplicate, mmr_select
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
