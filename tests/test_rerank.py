from codebase_index.retrieval.rerank import rerank
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
