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
