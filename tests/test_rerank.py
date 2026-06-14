from codebase_index.retrieval.rerank import _DEGREE_CAP, rerank
from codebase_index.retrieval.types import Candidate, Intent


def _c(path, src, score, **kw):
    return Candidate(path=path, line_start=1, line_end=2, source=src, score=score, **kw)


def test_exact_symbol_outranks_equal_fts():
    fts = _c("a.py", "fts", 0.5)
    sym = _c("b.py", "symbol", 0.5, symbol="X", kind="function", exact_symbol=True, in_degree=4)
    out = rerank([fts, sym], query="find X", intent=Intent.LOCATE_IMPL)
    assert out[0].path == "b.py"


def test_generated_files_demoted():
    plain = _c("real.py", "fts", 0.5)
    gen = _c("g.generated.ts", "fts", 0.55, is_generated=True)
    out = rerank([gen, plain], query="token", intent=Intent.KEYWORD)
    assert out[0].path == "real.py"


def test_reason_string_present():
    sym = _c("b.py", "symbol", 0.5, symbol="X", kind="function", exact_symbol=True, in_degree=4)
    out = rerank([sym], query="find X", intent=Intent.LOCATE_IMPL)
    assert out[0].reason and "exact symbol" in out[0].reason


def test_in_degree_bonus_is_sublinear_and_capped():
    """The graph-centrality bonus grows logarithmically and never exceeds the cap,
    so 10x the callers is far from 10x the bonus (the old linear rule saturated by
    in_degree=10 and gave god classes the full bonus)."""
    scores = []
    for deg in (1, 10, 100, 1000):
        c = _c("x.py", "fts", 0.0, in_degree=deg)
        rerank([c], query="zzz", intent=Intent.KEYWORD)
        scores.append(c.score)
    assert scores == sorted(scores)               # monotonic non-decreasing
    assert scores[-1] <= _DEGREE_CAP + 1e-9       # capped
    assert scores[2] < 2 * scores[1]              # 100 callers nowhere near 10x of 10


def test_god_class_does_not_outrank_relevant_match_on_stray_term():
    """A high-in_degree 'god class' that matches only a stray term must not float
    above a genuinely relevant (name/path) match with a slightly lower base score.

    Tuned to fail under the old linear `min(0.10, in_degree*0.01)` rule (god wins
    0.62 > 0.60) and pass under the dampened rule (relevant wins ~0.613 > ~0.60).
    """
    relevant = _c("auth/religion.py", "fts", 0.48, symbol="Religion", in_degree=2)
    god = _c("core/newtowny.py", "fts", 0.52, symbol="NewTowny", in_degree=200)
    out = rerank([god, relevant], query="religion", intent=Intent.KEYWORD)
    assert out[0].path == "auth/religion.py"
