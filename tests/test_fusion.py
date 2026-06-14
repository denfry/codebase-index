from codebase_index.retrieval.fusion import fuse
from codebase_index.retrieval.types import Candidate


def _c(path, src, score):
    return Candidate(path=path, line_start=1, line_end=2, source=src, score=score)


def test_fuse_merges_same_location_across_sources():
    fts = [_c("a.py", "fts", 0.9), _c("b.py", "fts", 0.5)]
    sym = [_c("a.py", "symbol", 0.8)]
    fused = fuse({"fts": fts, "symbol": sym}, weights={"fts": 1.0, "symbol": 1.0}, k=60)
    a = next(c for c in fused if c.path == "a.py")
    b = next(c for c in fused if c.path == "b.py")
    assert a.score > b.score


def test_weights_change_order():
    fts = [_c("doc.md", "fts", 0.9)]
    sym = [_c("code.py", "symbol", 0.9)]
    lists = {"fts": fts, "symbol": sym}
    fts_heavy = fuse(lists, weights={"fts": 1.0, "symbol": 0.1}, k=60)
    sym_heavy = fuse(lists, weights={"fts": 0.1, "symbol": 1.0}, k=60)
    assert fts_heavy[0].path == "doc.md"
    assert sym_heavy[0].path == "code.py"


def test_zero_weight_source_excluded():
    fused = fuse({"fts": [_c("a.py", "fts", 1.0)]}, weights={"fts": 0.0}, k=60)
    assert fused == []


def test_vector_source_participates_in_fusion():
    vec = [Candidate(path="v.py", line_start=1, line_end=2, source="vector", score=0.9)]
    fused = fuse({"vector": vec}, weights={"vector": 1.0}, k=60)
    assert fused and fused[0].path == "v.py"


def test_fuse_merges_co_located_hits_across_line_ranges():
    """Different retrievers report different line ranges for the same place; fusion
    buckets line_start so co-located cross-source hits still reinforce each other."""
    fts = [Candidate(path="a.py", line_start=10, line_end=80, source="fts", score=0.9)]
    sym = [Candidate(path="a.py", line_start=12, line_end=20, source="symbol", score=0.8)]
    fused = fuse({"fts": fts, "symbol": sym}, weights={"fts": 1.0, "symbol": 1.0}, k=60)
    assert len(fused) == 1                       # merged despite differing ranges
    assert fused[0].agreeing_sources == 2        # file-level agreement counted


def test_fuse_scores_are_order_one():
    """RRF is rescaled by k so the top contribution is ~weight (≈1), not ~w/k (≈0.017),
    keeping fused scores on the same scale as the reranker's bounded bonuses."""
    fts = [Candidate(path="a.py", line_start=1, line_end=2, source="fts", score=0.9)]
    fused = fuse({"fts": fts}, weights={"fts": 1.0}, k=60)
    assert 0.9 < fused[0].score <= 1.0


def test_fuse_dedupes_repeated_source_hits_in_one_bucket():
    """Three FTS chunks of the same file/bucket are one lexical signal, not three."""
    fts = [
        Candidate(path="a.py", line_start=1, line_end=10, source="fts", score=0.9),
        Candidate(path="a.py", line_start=11, line_end=20, source="fts", score=0.8),
        Candidate(path="a.py", line_start=21, line_end=30, source="fts", score=0.7),
    ]
    fused = fuse({"fts": fts}, weights={"fts": 1.0}, k=60)
    assert len(fused) == 1
    assert fused[0].score <= 1.0  # single best-rank contribution, not summed 3x
