"""Contract tests for the 1.10.0 name-co-occurrence ranking signal.

The feature is one short function, but it sits in the hot path of every query and
its whole justification is a measured interaction effect. These tests pin the
properties that made it worth shipping — superlinearity, name-zone scope, role
conditioning, determinism — plus the degenerate inputs that a query string can
actually contain.
"""

from __future__ import annotations

from codebase_index.retrieval.features import (
    name_cooccurrence,
    name_zone,
    query_profile,
)
from codebase_index.retrieval.rerank import rerank
from codebase_index.retrieval.tuning import DEFAULT_TUNING, RetrievalTuning
from codebase_index.retrieval.types import Candidate, Intent


def _cooc(query: str, path: str, symbol: str | None = None) -> float:
    return name_cooccurrence(query_profile(query), name_zone(path, symbol))[1]


def _cand(path: str, **kw) -> Candidate:
    base = dict(
        path=path, line_start=1, line_end=10, source="symbol", score=1.0, kind="function"
    )
    base.update(kw)
    return Candidate(**base)  # type: ignore[arg-type]


# --- the interaction itself -------------------------------------------------


def test_query_terms_co_occurring_in_one_symbol_beat_a_single_term_match():
    """The measured failure this signal exists to fix.

    On "graph resolution + traversal accessors", 1.9.0 ranked `graph_candidates`
    (one term) above `test_graph_accessors_resolve_and_walk` (three terms in one
    name), because RRF sums per-term evidence and cannot see co-occurrence.
    """
    query = "graph resolution traversal accessors"
    one_term = _cooc(query, "src/graph/retrieval.py", "graph_candidates")
    three_terms = _cooc(query, "src/storage/repo.py", "graph_accessors_resolve")
    assert one_term == 0.0
    assert three_terms > one_term


def test_score_is_superlinear_not_additive():
    """Two terms in one name must beat one, and the first match earns nothing.

    A single matched term is already fully paid for by the retriever that
    surfaced the candidate; crediting it again here would just re-weight lexical
    matching, which is not what the benchmark showed was missing.
    """
    query = "token budget applied results"
    assert _cooc(query, "a/token.py") == 0.0
    assert 0.0 < _cooc(query, "a/token_budget.py") < _cooc(query, "a/token_budget_results.py")
    assert _cooc(query, "a/token_budget_applied_results.py") == 1.0


def test_single_term_queries_have_no_co_occurrence_to_observe():
    assert _cooc("budget", "src/retrieval/budget.py") == 0.0
    assert name_cooccurrence(query_profile("budget"), {"budget"}) == (0, 0.0)


def test_normalisation_makes_short_and_long_queries_comparable():
    """Both candidates match every salient term, so both must score 1.0."""
    assert _cooc("parse config", "a/parse_config.py") == 1.0
    assert _cooc("parse config values from disk", "a/parse_config_values_from_disk.py") == 1.0


# --- name-zone scope --------------------------------------------------------


def test_zone_is_basename_and_symbol_but_never_directories():
    """Directory components are shared by hundreds of files, so they carry no
    evidence about which file answers the query — only co-occurrence noise."""
    zone = name_zone("src/main/java/net/denfry/newtowny/items/CustomItems.java", None)
    assert zone == {"custom", "items"}
    assert "denfry" not in zone and "java" not in zone and "src" not in zone
    assert _cooc("newtowny items denfry", "src/net/denfry/newtowny/items/Foo.java") == 0.0


def test_zone_splits_camel_snake_and_kebab_identifiers():
    assert name_zone("a/getUserById.ts", None) == {"get", "user", "by", "id"}
    assert name_zone("a/refresh_access_token.py", None) == {"refresh", "access", "token"}
    assert name_zone("a/my-http-server.js", None) == {"my", "http", "server"}
    assert name_zone("a/x.py", "HTTPServerFactory") == {"x", "http", "server", "factory"}


def test_extension_is_not_part_of_the_zone():
    """Otherwise every query mentioning `py` or `ts` would fire on whole languages."""
    assert "py" not in name_zone("src/parse.py", None)
    assert "java" not in name_zone("src/Parse.java", None)
    assert _cooc("parse py files", "src/parse.py") == 0.0


def test_dotted_and_multi_suffix_names_keep_their_stem():
    assert name_zone("web/app.module.ts", None) == {"app", "module"}
    assert name_zone("a/schema.generated.ts", None) == {"schema", "generated"}


def test_windows_separators_are_normalised():
    assert name_zone(r"src\retrieval\token_budget.py", None) == {"token", "budget"}


# --- role conditioning ------------------------------------------------------


def test_descriptive_test_names_get_a_discounted_bonus():
    """Test function names are sentences, so they harvest co-occurrences that real
    identifiers never do. Discounted, not withheld: on git-derived ground truth the
    changed file often *is* the test."""
    query = "secrets redacted before output"
    impl = _cand("src/output/redact.py", symbol="redact_snippet")
    test = _cand("tests/test_budget.py", symbol="test_compactor_output_is_redacted")
    ranked = rerank([impl, test], query=query, intent=Intent.KEYWORD, tuning=DEFAULT_TUNING)
    assert [c.path for c in ranked][0] == "src/output/redact.py"

    scale = DEFAULT_TUNING.name_cooccurrence_demoted_scale
    assert 0.0 < scale < 1.0


def test_an_explicit_test_query_is_not_discounted():
    query = "tests for redacted output"
    graded = rerank(
        [_cand("tests/test_redacted_output.py", symbol="test_redacted_output")],
        query=query,
        intent=Intent.KEYWORD,
        tuning=DEFAULT_TUNING,
    )
    assert "co-occur in name" in graded[0].reason


def test_generated_sources_are_discounted_too():
    query = "schema generated types"
    plain = _cand("src/schema_generated_types.ts")
    generated = _cand("src/schema_generated_types.ts", is_generated=True)
    for c in (plain, generated):
        rerank([c], query=query, intent=Intent.KEYWORD, tuning=DEFAULT_TUNING)
    assert plain.score > generated.score


# --- ablatability and explainability ---------------------------------------


def test_signal_is_independently_ablatable():
    query = "token budget applied results"
    on = _cand("src/token_budget.py", symbol="apply_token_budget")
    off = _cand("src/token_budget.py", symbol="apply_token_budget")
    rerank([on], query=query, intent=Intent.KEYWORD, tuning=DEFAULT_TUNING)
    rerank([off], query=query, intent=Intent.KEYWORD,
           tuning=DEFAULT_TUNING.without("name_cooccurrence"))
    assert on.score > off.score
    assert "co-occur in name" in on.reason
    assert "co-occur in name" not in off.reason


def test_reason_reports_the_actual_counts():
    c = _cand("src/token_budget.py")
    rerank([c], query="token budget applied results", intent=Intent.KEYWORD,
           tuning=DEFAULT_TUNING)
    assert "2/4 query terms co-occur in name" in c.reason


def test_weight_scales_the_bonus_monotonically():
    scores = []
    for weight in (0.0, 1.0, 2.0):
        c = _cand("src/token_budget.py")
        rerank(
            [c],
            query="token budget applied results",
            intent=Intent.KEYWORD,
            tuning=RetrievalTuning(name_cooccurrence_weight=weight),
        )
        scores.append(c.score)
    assert scores[0] < scores[1] < scores[2]


# --- determinism and degenerate input ---------------------------------------


def test_ranking_is_deterministic_and_stable_on_ties():
    query = "token budget applied results"
    def run():
        cands = [
            _cand("src/token_budget.py", symbol="apply"),
            _cand("src/budget_token.py", symbol="apply"),
            _cand("src/other.py", symbol="apply"),
        ]
        return [c.path for c in rerank(cands, query=query, intent=Intent.KEYWORD,
                                       tuning=DEFAULT_TUNING)]
    first = run()
    assert all(run() == first for _ in range(5))
    # The two equally-matching files tie on score, so input order decides and the
    # sort must not reshuffle them.
    assert first[:2] == ["src/token_budget.py", "src/budget_token.py"]


def test_duplicate_candidates_score_identically():
    query = "token budget applied"
    a, b = _cand("src/token_budget.py"), _cand("src/token_budget.py")
    rerank([a, b], query=query, intent=Intent.KEYWORD, tuning=DEFAULT_TUNING)
    assert a.score == b.score


def test_empty_and_punctuation_only_queries_are_inert():
    for query in ("", "   ", "???", "!!! ... ???", "- -- ---", "/////"):
        assert query_profile(query).terms == ()
        assert _cooc(query, "src/token_budget.py") == 0.0


def test_stopword_only_query_is_inert():
    assert _cooc("how does the", "src/how_does_the.py") == 0.0


def test_punctuation_between_terms_does_not_break_matching():
    assert _cooc("token, budget; applied!", "src/token_budget.py") > 0.0


def test_unicode_identifiers_and_queries_are_handled():
    assert name_zone("src/расчёт_налога.py", None) == {"расчёт", "налога"}
    assert _cooc("расчёт налога ставка", "src/расчёт_налога.py") > 0.0
    # Mixed scripts must not raise or silently drop the ASCII half.
    assert _cooc("расчёт tax rate", "src/расчёт_tax.py") > 0.0


def test_pathological_long_query_stays_bounded_and_sane():
    query = " ".join(f"term{i}" for i in range(2000))
    profile = query_profile(query)
    assert profile.n_terms == 2000
    # One matched term out of 2000 is not evidence of anything.
    assert _cooc(query, "src/term7.py") == 0.0
    assert 0.0 < _cooc(query, "src/term7_term8_term9.py") < 0.01


def test_pathological_long_identifier_stays_bounded():
    symbol = "_".join(f"part{i}" for i in range(2000))
    score = _cooc("part7 part8 part9", "src/x.py", symbol)
    assert score == 1.0


def test_missing_and_malformed_metadata_does_not_raise():
    query = "token budget applied"
    for path in ("", ".", "/", "a/", "...", "no_extension"):
        assert 0.0 <= _cooc(query, path, None) <= 1.0
    assert _cooc(query, "src/token_budget.py", None) > 0.0
    # A candidate with no symbol, no kind and no content must still rank.
    c = Candidate(path="src/token_budget.py", line_start=0, line_end=0,
                  source="path", score=0.0)
    ranked = rerank([c], query=query, intent=Intent.KEYWORD, tuning=DEFAULT_TUNING)
    assert ranked[0].score > 0.0


def test_score_is_always_in_the_unit_interval():
    queries = ("a b", "token budget applied results", "x" * 300, "расчёт налога")
    paths = ("src/token_budget.py", "", "a/b/c/d.py", "src/" + "x" * 300 + ".py")
    for query in queries:
        for path in paths:
            assert 0.0 <= _cooc(query, path, "some_symbol_name") <= 1.0
