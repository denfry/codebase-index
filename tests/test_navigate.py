"""Tests for graph.navigate — shortest path and the describe node card."""

from __future__ import annotations

from codebase_index.graph.builder import build_graph
from codebase_index.graph.navigate import describe_payload, path_payload
from codebase_index.output import markdown
from codebase_index.parsers.base import Symbol
from codebase_index.storage import repo
from codebase_index.storage.db import Database


def _graph(tmp_path) -> Database:
    """login -> make_token, login -> run_query (bridge), run_query -> exec_stmt."""
    db = Database(tmp_path / "index.sqlite").open()
    auth = repo.upsert_file(
        db.conn, path="src/auth/token.py", lang="python", size_bytes=1, sha256="a",
        mtime_ns=1, git_status=None, parser="treesitter", indexed_at="t", is_generated=False,
    )
    dbf = repo.upsert_file(
        db.conn, path="src/db/query.py", lang="python", size_bytes=1, sha256="b",
        mtime_ns=1, git_status=None, parser="treesitter", indexed_at="t", is_generated=False,
    )
    a = repo.replace_symbols(db.conn, auth, [
        Symbol(name="make_token", kind="function", line_start=1, line_end=2),
        Symbol(name="login", kind="function", line_start=3, line_end=4),
    ])
    b = repo.replace_symbols(db.conn, dbf, [
        Symbol(name="run_query", kind="function", line_start=1, line_end=2),
        Symbol(name="exec_stmt", kind="function", line_start=3, line_end=4),
    ])
    repo.replace_edges(db.conn, auth, [
        {"edge_type": "call", "src_kind": "symbol", "src_id": a[1],
         "dst_kind": None, "dst_id": None, "dst_name": "make_token", "line": 3, "resolved": 0},
        {"edge_type": "call", "src_kind": "symbol", "src_id": a[1],
         "dst_kind": None, "dst_id": None, "dst_name": "run_query", "line": 4, "resolved": 0},
    ])
    repo.replace_edges(db.conn, dbf, [
        {"edge_type": "call", "src_kind": "symbol", "src_id": b[0],
         "dst_kind": None, "dst_id": None, "dst_name": "exec_stmt", "line": 2, "resolved": 0},
    ])
    build_graph(db.conn)
    return db


def test_path_finds_chain(tmp_path):
    db = _graph(tmp_path)
    payload = path_payload(db.conn, "login", "exec_stmt")
    assert payload["found"] is True
    names = [n["name"] for n in payload["nodes"]]
    assert names[0] == "login" and names[-1] == "exec_stmt"
    assert "run_query" in names  # the bridge node
    assert payload["hops"] == 2
    # Markdown renders without error and mentions both ends.
    md = markdown.render_path(payload)
    assert "login" in md and "exec_stmt" in md
    db.close()


def test_path_unresolved_source(tmp_path):
    db = _graph(tmp_path)
    payload = path_payload(db.conn, "no_such_symbol", "exec_stmt")
    assert payload["found"] is False
    assert "no_such_symbol" in payload["reason"]
    db.close()


def test_path_no_connection(tmp_path):
    db = _graph(tmp_path)
    # make_token is a leaf callee; nothing connects it to a fresh isolated file.
    iso = repo.upsert_file(
        db.conn, path="src/iso/lonely.py", lang="python", size_bytes=1, sha256="c",
        mtime_ns=1, git_status=None, parser="treesitter", indexed_at="t", is_generated=False,
    )
    repo.replace_symbols(db.conn, iso, [
        Symbol(name="lonely", kind="function", line_start=1, line_end=2),
    ])
    payload = path_payload(db.conn, "lonely", "exec_stmt")
    assert payload["found"] is False
    db.close()


def test_describe_symbol_card(tmp_path):
    db = _graph(tmp_path)
    payload = describe_payload(db.conn, "run_query")
    assert payload["found"] is True
    assert payload["primary"]["in_degree"] == 1   # called by login
    assert payload["primary"]["out_degree"] == 1  # calls exec_stmt
    callee_names = {c["name"] for c in payload["callees"]}
    assert "exec_stmt" in callee_names
    md = markdown.render_describe(payload)
    assert "run_query" in md and "exec_stmt" in md
    db.close()


def test_describe_unknown_symbol(tmp_path):
    db = _graph(tmp_path)
    payload = describe_payload(db.conn, "does_not_exist")
    assert payload["found"] is False
    assert "does_not_exist" in payload["reason"]
    assert "Not found" in markdown.render_describe(payload) or "No symbol" in payload["reason"]
    db.close()
