from codebase_index.storage import repo


def test_seeded_index_has_files_chunks_symbols(seeded_index):
    conn = seeded_index.conn
    assert repo.count_files(conn) >= 3
    assert repo.count_chunks(conn) >= 3
    rows = repo.fts_search(conn, "token", limit=10)
    assert any("token.py" in r["path"] for r in rows)
    syms = conn.execute("SELECT name FROM symbols").fetchall()
    names = {r[0] for r in syms}
    assert {"refresh_access_token", "User"} <= names
