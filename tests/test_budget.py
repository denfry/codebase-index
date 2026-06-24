from codebase_index.retrieval.budget import apply_budget
from codebase_index.retrieval.skeleton import Compacted
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


def test_compactor_lets_more_results_fit_budget():
    cands = [_c(f"f{i}.py", 1, 50, "x" * 4000, 1000) for i in range(5)]

    def fake_compactor(c):
        return Compacted(text="sig\n... 49 lines elided (read 2-50)",
                         token_est=10, elided_lines=49, skeletonized=True)

    no_comp, _ = apply_budget(cands, token_budget=1500)
    with_comp, _ = apply_budget(cands, token_budget=1500, compactor=fake_compactor)
    fit_no = sum(1 for r in no_comp if r["snippet"] is not None)
    fit_yes = sum(1 for r in with_comp if r["snippet"] is not None)
    assert fit_yes > fit_no
    assert all(r["skeletonized"] for r in with_comp if r["snippet"])
    assert all(r["elided_lines"] == 49 for r in with_comp if r["snippet"])


def test_compactor_output_is_still_redacted():
    secret = "key = 'AKIAIOSFODNN7EXAMPLE'\nbody line\nbody line"
    cand = _c("s.py", 1, 3, secret, 50)

    def fake_compactor(c):
        return Compacted(text=secret, token_est=50, elided_lines=0, skeletonized=True)

    results, _ = apply_budget([cand], token_budget=1000, compactor=fake_compactor)
    assert "AKIAIOSFODNN7EXAMPLE" not in results[0]["snippet"]


def test_none_compactor_is_unchanged_behavior():
    cands = [_c("a.py", 1, 5, "y" * 400, 100)]
    results, _ = apply_budget(cands, token_budget=1000, compactor=None)
    assert results[0]["skeletonized"] is False
    assert results[0]["elided_lines"] == 0
    assert results[0]["token_est"] == 100        # original, untouched
