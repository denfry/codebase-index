import pytest

from codebase_index.retrieval.intent import detect_intent
from codebase_index.retrieval.types import Intent


@pytest.mark.parametrize(
    "query,expected",
    [
        ("where is refresh_access_token implemented", Intent.LOCATE_IMPL),
        ("find the User class", Intent.LOCATE_IMPL),
        ("how does token refresh work", Intent.HOW_IT_WORKS),
        ("what breaks if I change User", Intent.IMPACT),
        ("who calls refresh_access_token", Intent.FIND_REFS),
        ("find references to User", Intent.FIND_REFS),
        ("trace data flow of refresh_token", Intent.DATA_FLOW),
        ("Traceback (most recent call last): KeyError", Intent.DEBUG_ERROR),
        ("explain the architecture", Intent.ARCHITECTURE),
        ("leftpad", Intent.KEYWORD),
    ],
)
def test_detect_intent(query, expected):
    assert detect_intent(query).intent is expected


def test_locate_impl_favors_symbol_over_fts():
    plan = detect_intent("where is refresh_access_token implemented")
    assert plan.weight("symbol") > plan.weight("fts")


def test_architecture_returns_summaries_first():
    assert detect_intent("explain the architecture").summaries_first is True


def test_every_plan_has_positive_budget():
    assert detect_intent("anything").token_budget > 0


def test_semantic_intents_have_vector_weight():
    for q in ["how does token refresh work", "leftpad", "trace data flow of refresh_token"]:
        assert detect_intent(q).weight("vector") > 0.0


def test_locate_impl_still_favors_symbol_over_vector():
    plan = detect_intent("where is refresh_access_token implemented")
    assert plan.weight("symbol") > plan.weight("vector")
