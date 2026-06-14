from codebase_index.retrieval.searchers import (
    build_match_query, fts_candidates, path_candidates, symbol_candidates,
)


def test_build_match_query_drops_stopwords():
    # Natural-language filler must not be AND-ed into the match (it kills recall).
    q = build_match_query("how does authentication work")
    assert "how" not in q.lower() and "does" not in q.lower()
    assert "authentication" in q.lower() and "work" in q.lower()
    assert " AND " in q  # salient terms are still AND-ed together


def test_build_match_query_falls_back_when_all_stopwords():
    # If every term is a stopword we must still emit a (non-empty) match, not "".
    q = build_match_query("how does it")
    assert q.strip() != ""


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
