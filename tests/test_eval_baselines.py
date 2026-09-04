"""Unit checks for the baseline models in tests/eval/baselines.py.

These pin the read model the public baseline benchmark relies on, so a change to
salient-term extraction or map packing cannot silently move a logged number.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from eval import baselines  # noqa: E402
from eval.harness import EvalQuery  # noqa: E402


def test_salient_terms_drop_stopwords_and_keep_identifiers():
    terms = baselines.salient_terms("fix how the SessionInterface saves a cookie when not set")
    assert "SessionInterface" in terms
    assert "cookie" in terms
    assert not {"fix", "how", "the", "when", "not", "set"} & {t.lower() for t in terms}


def test_salient_terms_are_bounded_and_longest_first():
    terms = baselines.salient_terms("alpha betagamma de epsilonzeta eta theta iota kappa", max_terms=3)
    assert len(terms) == 3
    assert terms[0] == "epsilonzeta"


def test_tokens_for_reads_merges_overlapping_ranges(tmp_path):
    (tmp_path / "a.py").write_text("\n".join(f"line {i}" for i in range(1, 101)), encoding="utf-8")
    corpus = baselines.Corpus(tmp_path)
    once = baselines.tokens_for_reads(corpus, {"a.py": [(1, 50)]})
    twice = baselines.tokens_for_reads(corpus, {"a.py": [(1, 50), (10, 40)]})
    assert once == twice, "overlapping windows must be charged once"
    assert baselines.tokens_for_reads(corpus, {"a.py": [(500, 600)]}) == 0


def test_pack_repo_map_respects_budget_and_query_awareness():
    entries = [
        baselines.MapEntry("a.py", "a.py:\n  def alpha()", 10, degree=5, names=frozenset({"alpha"})),
        baselines.MapEntry("b.py", "b.py:\n  def beta()", 10, degree=50, names=frozenset({"beta"})),
        baselines.MapEntry("c.py", "c.py:\n  def gamma()", 10, degree=1, names=frozenset({"gamma"})),
    ]
    chosen, used = baselines.pack_repo_map(entries, budget=20)
    assert chosen == ["b.py", "a.py"] and used == 20
    chosen, _ = baselines.pack_repo_map(entries, budget=20, query_terms=["gamma"])
    assert chosen[0] == "c.py"


def test_score_ranked_and_present_only():
    q = EvalQuery(query="x", category="c", expected_files=("b.py",))
    out = baselines.BaselineOutcome(["a.py", "b.py"], tokens=0, packet_tokens=0, latency_ms=0)
    assert baselines.score(out, q) == {"hit@3": 1.0, "recall@5": 1.0, "MRR": 0.5}
    assert baselines.score(out, q, present_only=True)["present"] == 1.0


@pytest.mark.skipif(baselines.RG is None, reason="ripgrep not available")
def test_rg_window_ranks_by_density(tmp_path):
    (tmp_path / "dense.py").write_text("token\n" * 30, encoding="utf-8")
    (tmp_path / "sparse.py").write_text("token\n" + "x\n" * 30, encoding="utf-8")
    corpus = baselines.Corpus(tmp_path)
    out = baselines.run_rg_window(corpus, EvalQuery("find the token handling", "c", ("dense.py",)))
    assert out.ranked_files[0] == "dense.py"
    assert out.tokens > out.packet_tokens > 0
