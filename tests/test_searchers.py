from codebase_index.retrieval.searchers import (
    fts_candidates, path_candidates, symbol_candidates,
)


def test_fts_candidates_uniform_shape(seeded_index):
    cands = fts_candidates(seeded_index.conn, "token", limit=10)
    assert cands and all(c.source == "fts" for c in cands)
    assert all(c.content is not None and c.token_est > 0 for c in cands)


def test_symbol_candidates_exact_flagged(seeded_index):
    cands = symbol_candidates(seeded_index.conn, "refresh_access_token", limit=10)
    top = cands[0]
    assert top.symbol == "refresh_access_token"
    assert top.source == "symbol" and top.exact_symbol is True
    assert top.in_degree == 4


def test_path_candidates(seeded_index):
    cands = path_candidates(seeded_index.conn, "auth/token.py", limit=10)
    assert cands[0].path == "src/auth/token.py"
    assert cands[0].source == "path"


def test_symbol_candidates_empty_query(seeded_index):
    assert symbol_candidates(seeded_index.conn, "   ", limit=10) == []
