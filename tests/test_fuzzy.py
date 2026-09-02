from codebase_index.retrieval.fuzzy import identifier_similarity, rank_fuzzy_symbols
from codebase_index.retrieval.types import Candidate


def test_identifier_similarity_handles_case_tokens_and_concatenation():
    assert identifier_similarity("Get_User", "getUser") == 1.0
    assert identifier_similarity("userid", "getUserById") > 0.8
    assert identifier_similarity("getUser", "getUserById") > 0.8


def test_identifier_similarity_handles_acronyms_and_edit_distance():
    assert identifier_similarity("GUBI", "getUserById") > 0.85
    assert identifier_similarity("getUsrById", "getUserById") > 0.65
    assert identifier_similarity("GUBI", "getUserByName") < 0.55


def test_identifier_similarity_short_and_empty_inputs_are_safe():
    assert identifier_similarity("", "anything") == 0.0
    assert identifier_similarity("a", "anything") == 0.0
    assert identifier_similarity("", "") == 0.0
    assert identifier_similarity("ID", "id") == 1.0


def test_rank_fuzzy_symbols_preserves_exactness_and_has_deterministic_ties():
    candidates = [
        Candidate("z.py", 1, 2, "symbol", 0.1, symbol="getUserById"),
        Candidate("a.py", 4, 5, "symbol", 0.1, symbol="getUserById"),
        Candidate("exact.py", 1, 2, "symbol", 0.0, symbol="userid", exact_symbol=True),
    ]
    ranked = rank_fuzzy_symbols("userid", candidates, threshold=0.55)
    assert ranked[0] is candidates[2]
    assert [c.path for c in ranked[1:]] == ["a.py", "z.py"]
    assert all(c.exact_symbol is (c is candidates[2]) for c in ranked)


def test_rank_fuzzy_symbols_accepts_mapping_rows_and_threshold():
    rows = [
        {"name": "getUserById", "path": "src/user.py", "line_start": 1},
        {"name": "getUserByName", "path": "src/name.py", "line_start": 1},
    ]
    ranked = rank_fuzzy_symbols("GUBI", rows, threshold=0.55)
    assert [row["name"] for row in ranked] == ["getUserById"]
