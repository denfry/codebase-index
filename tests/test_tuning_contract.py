"""The ablation contract: every ranking signal must be independently switchable.

These tests protect the property that makes `tests/eval/run_eval.py --ablate`
meaningful. If a signal stops being individually disablable, or if `baseline()`
drifts away from the pre-1.8.0 pipeline, every published benchmark delta silently
becomes unverifiable.
"""

from __future__ import annotations

from dataclasses import fields

import pytest

from codebase_index.retrieval.pipeline import search
from codebase_index.retrieval.tuning import DEFAULT_TUNING, RetrievalTuning


def test_every_boolean_signal_is_independently_disablable():
    tuning = RetrievalTuning()
    booleans = [f.name for f in fields(tuning) if isinstance(getattr(tuning, f.name), bool)]
    assert booleans, "a tuning with no boolean signals cannot be ablated"
    for flag in booleans:
        assert getattr(tuning.without(flag), flag) is False


def test_without_rejects_unknown_and_non_boolean_fields():
    with pytest.raises(KeyError):
        RetrievalTuning().without("no_such_flag")
    # Silently "disabling" a numeric knob by setting it to False would produce a
    # nonsense ablation row rather than an error.
    with pytest.raises(TypeError):
        RetrievalTuning().without("rrf_k")


def test_baseline_disables_every_post_170_signal():
    """`baseline()` is the honest 'before' column; it must stay signal-free."""
    baseline = RetrievalTuning.baseline()
    for flag in (
        "fuzzy_symbols",
        "query_expansion",
        "graph_source",
        "soft_lexical",
        "mmr",
        "dedup",
        "source_priors",
        "file_agreement",
    ):
        assert getattr(baseline, flag) is False, flag
    # 1.7.0 took the page size verbatim; over-fetching is a later addition.
    assert baseline.candidate_pool_multiplier == 1


def test_shipped_defaults_are_the_measured_configuration():
    """Guards against a default drifting without a benchmark run behind it."""
    assert DEFAULT_TUNING.file_agreement is True
    assert DEFAULT_TUNING.file_agreement_weight == pytest.approx(0.4)
    assert DEFAULT_TUNING.candidate_pool_multiplier == 2
    assert DEFAULT_TUNING.fuzzy_fallback_min == 3
    # Signals measured as neutral-or-harmful stay off by default.
    assert DEFAULT_TUNING.graph_source is False
    assert DEFAULT_TUNING.mmr is False


def test_tuning_is_immutable_and_hashable():
    tuning = RetrievalTuning()
    with pytest.raises(Exception):
        tuning.file_agreement_weight = 0.9  # type: ignore[misc]
    assert hash(tuning) == hash(RetrievalTuning())


@pytest.mark.parametrize("multiplier", [1, 2, 5])
def test_pool_multiplier_does_not_change_the_page_size(seeded_index, multiplier):
    """Over-fetching feeds selection; it must never inflate the returned page."""
    from dataclasses import replace

    payload = search(
        seeded_index.conn,
        "token",
        mode="hybrid",
        limit=3,
        token_budget=1500,
        no_fallback=True,
        tuning=replace(RetrievalTuning(), candidate_pool_multiplier=multiplier),
    )
    assert len(payload["results"]) <= 3


def test_baseline_and_default_both_answer_a_direct_symbol_query(seeded_index):
    for tuning in (RetrievalTuning.baseline(), RetrievalTuning()):
        payload = search(
            seeded_index.conn,
            "refresh_access_token",
            mode="hybrid",
            limit=10,
            token_budget=1500,
            no_fallback=True,
            tuning=tuning,
        )
        assert payload["results"][0]["path"] == "src/auth/token.py"


@pytest.mark.parametrize(
    "query",
    [
        "",
        "   ",
        "the and of for",          # stopwords only
        "!!! ??? ***",             # punctuation only
        "\"; DROP TABLE files;--",  # would be an FTS/SQL injection if unquoted
        "a" * 512,                 # pathological identifier
        "поиск конфигурации",      # non-ASCII
        "getUserById" * 40,        # pathological camelCase run
    ],
)
def test_degenerate_queries_are_answered_without_raising(seeded_index, query):
    payload = search(
        seeded_index.conn,
        query,
        mode="hybrid",
        limit=5,
        token_budget=800,
        no_fallback=True,
    )
    assert isinstance(payload["results"], list)
    assert payload["confidence"] in {"high", "medium", "low"}


def test_ranking_is_deterministic_across_repeated_identical_queries(seeded_index):
    def run() -> list[tuple[str, int, int]]:
        payload = search(
            seeded_index.conn,
            "how does token refresh work",
            mode="hybrid",
            limit=10,
            token_budget=1500,
            no_fallback=True,
        )
        return [(r["path"], r["line_start"], r["line_end"]) for r in payload["results"]]

    assert run() == run() == run()
