"""Symbol-aware ranking for natural-language queries (recall@3 follow-up).

A query like "religion manager belief and faith" should surface the file that defines
`ReligionManager`, not the loosely-related `Religion` class. The symbol retriever must:
  * use ALL salient query terms, not just the single longest one, and
  * rank a symbol by how many query terms its camelCase/underscore-split name covers,
so that `ReligionManager` (covers religion+manager) beats `Religion` (covers religion).
"""

from __future__ import annotations

from codebase_index.retrieval.searchers import symbol_candidates
from codebase_index.storage.db import Database


def _insert_file(conn, *, path, lang, mtime_ns):
    conn.execute(
        "INSERT INTO files (path, lang, size_bytes, sha256, mtime_ns, git_status, "
        "parser, indexed_at, is_generated) VALUES (?,?,?,?,?,?,?,?,?)",
        (path, lang, 100, "deadbeef", mtime_ns, "clean", "treesitter", "2026-05-29T00:00:00Z", 0),
    )
    return int(conn.execute("SELECT id FROM files WHERE path = ?", (path,)).fetchone()[0])


def _insert_symbol(conn, file_id, *, name, kind, line_start, line_end, signature, in_degree=0):
    conn.execute(
        "INSERT INTO symbols (file_id, name, qualified, kind, line_start, line_end, "
        "signature, parent_id, docstring, in_degree, out_degree) "
        "VALUES (?,?,?,?,?,?,?,NULL,NULL,?,0)",
        (file_id, name, name, kind, line_start, line_end, signature, in_degree),
    )


def _db(tmp_path) -> Database:
    db = Database(tmp_path / "index.sqlite").open()
    return db


def test_multiterm_camelcase_coverage_outranks_single_term(tmp_path):
    db = _db(tmp_path)
    conn = db.conn
    rel = _insert_file(conn, path="src/Religion.java", lang="java", mtime_ns=1)
    _insert_symbol(conn, rel, name="Religion", kind="class",
                   line_start=1, line_end=9, signature="class Religion", in_degree=3)
    mgr = _insert_file(conn, path="src/managers/ReligionManager.java", lang="java", mtime_ns=2)
    _insert_symbol(conn, mgr, name="ReligionManager", kind="class",
                   line_start=1, line_end=99, signature="class ReligionManager", in_degree=5)
    conn.commit()

    cands = symbol_candidates(conn, "religion manager belief and faith handling", limit=10)
    names = [c.symbol for c in cands]
    db.close()

    assert "ReligionManager" in names and "Religion" in names
    # covers 2 query terms (religion + manager) vs 1 (religion)
    assert names.index("ReligionManager") < names.index("Religion")
    assert cands[0].symbol == "ReligionManager"


def test_exact_single_identifier_still_wins(tmp_path):
    """Regression guard: a precise identifier query keeps exact-match precedence."""
    db = _db(tmp_path)
    conn = db.conn
    rel = _insert_file(conn, path="src/Religion.java", lang="java", mtime_ns=1)
    _insert_symbol(conn, rel, name="Religion", kind="class",
                   line_start=1, line_end=9, signature="class Religion")
    mgr = _insert_file(conn, path="src/managers/ReligionManager.java", lang="java", mtime_ns=2)
    _insert_symbol(conn, mgr, name="ReligionManager", kind="class",
                   line_start=1, line_end=99, signature="class ReligionManager")
    conn.commit()

    cands = symbol_candidates(conn, "Religion", limit=10)
    db.close()
    assert cands[0].symbol == "Religion"
    assert cands[0].exact_symbol is True


def test_underscore_names_also_covered(tmp_path):
    db = _db(tmp_path)
    conn = db.conn
    f = _insert_file(conn, path="auth/token.py", lang="python", mtime_ns=1)
    _insert_symbol(conn, f, name="refresh_access_token", kind="function",
                   line_start=1, line_end=6, signature="def refresh_access_token()")
    _insert_symbol(conn, f, name="refresh", kind="function",
                   line_start=8, line_end=9, signature="def refresh()")
    conn.commit()

    cands = symbol_candidates(conn, "how does refresh access token work", limit=10)
    names = [c.symbol for c in cands]
    db.close()
    assert names.index("refresh_access_token") < names.index("refresh")
