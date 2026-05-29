from codebase_index.retrieval.types import Candidate, Intent, IntentPlan, Confidence


def test_candidate_dedup_key_ignores_source_and_score():
    a = Candidate(path="a.py", line_start=1, line_end=9, source="fts", score=0.5)
    b = Candidate(path="a.py", line_start=1, line_end=9, source="symbol", score=0.9)
    assert a.key() == b.key()


def test_intent_plan_weight_defaults_to_zero_for_missing_source():
    plan = IntentPlan(intent=Intent.KEYWORD, weights={"fts": 1.0}, token_budget=1500)
    assert plan.weight("symbol") == 0.0
    assert plan.weight("fts") == 1.0


def test_confidence_is_ordered():
    assert Confidence.HIGH.value == "high"
    assert {c.value for c in Confidence} == {"high", "medium", "low"}
