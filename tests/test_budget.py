from codebase_index.retrieval.budget import apply_budget
from codebase_index.retrieval.types import Candidate


def _c(path, ls, le, content, token_est):
    c = Candidate(path=path, line_start=ls, line_end=le, source="fts",
                  score=1.0, content=content, token_est=token_est)
    c.reason = "x"
    return c


def test_snippets_stop_at_budget():
    cands = [_c(f"f{i}.py", 1, 5, "x" * 400, 100) for i in range(10)]
    results, recommended = apply_budget(cands, token_budget=250)
    with_snippet = [r for r in results if r["snippet"] is not None]
    assert sum(r["token_est"] for r in with_snippet) <= 250
    assert recommended and all("snippet" not in r for r in recommended)


def test_secrets_are_redacted():
    secret = "aws_secret = 'AKIAIOSFODNN7EXAMPLE'"
    cands = [_c("s.py", 1, 2, secret, 20)]
    results, _ = apply_budget(cands, token_budget=1000)
    assert "AKIAIOSFODNN7EXAMPLE" not in results[0]["snippet"]


def test_metadata_always_present_even_when_budget_zero():
    cands = [_c("a.py", 1, 2, "content", 50)]
    results, recommended = apply_budget(cands, token_budget=0)
    assert results[0]["path"] == "a.py" and results[0]["snippet"] is None
