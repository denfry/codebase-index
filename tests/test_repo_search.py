from codebase_index.storage import repo


def test_path_search_matches_path_tokens(seeded_index):
    rows = repo.path_search(seeded_index.conn, "auth/token.py", limit=10)
    assert rows[0]["path"] == "src/auth/token.py"


def test_symbol_search_exact_beats_other(seeded_index):
    rows = repo.symbol_search(seeded_index.conn, "refresh_access_token", limit=10)
    assert rows[0]["name"] == "refresh_access_token"
    assert rows[0]["is_exact"] == 1


def test_symbol_search_prefix(seeded_index):
    rows = repo.symbol_search(seeded_index.conn, "refresh_acc", limit=10)
    assert any(r["name"] == "refresh_access_token" for r in rows)


def test_symbol_search_kind_filter(seeded_index):
    rows = repo.symbol_search(seeded_index.conn, "User", limit=10, kind="class")
    assert all(r["kind"] == "class" for r in rows)
    assert any(r["name"] == "User" for r in rows)
