import sqlite3

from codebase_index.graph.retrieval import graph_candidates
from codebase_index.retrieval.types import Candidate


def _graph(*, confidence=True):
    conn = sqlite3.connect(":memory:")
    conn.row_factory = sqlite3.Row
    confidence_col = ", confidence TEXT" if confidence else ""
    conn.executescript(
        f"""
        CREATE TABLE files (
            id INTEGER PRIMARY KEY, path TEXT UNIQUE NOT NULL,
            is_generated INTEGER DEFAULT 0, summary TEXT
        );
        CREATE TABLE symbols (
            id INTEGER PRIMARY KEY, file_id INTEGER, name TEXT, kind TEXT,
            line_start INTEGER, line_end INTEGER, signature TEXT
        );
        CREATE TABLE edges (
            id INTEGER PRIMARY KEY, edge_type TEXT, src_kind TEXT, src_id INTEGER,
            dst_kind TEXT, dst_id INTEGER, dst_name TEXT, file_id INTEGER,
            line INTEGER, resolved INTEGER{confidence_col}
        );
        CREATE INDEX idx_edges_src ON edges(src_kind, src_id);
        CREATE INDEX idx_edges_dst ON edges(dst_kind, dst_id);
        """
    )
    conn.executemany(
        "INSERT INTO files(id, path, summary) VALUES (?, ?, ?)",
        [(1, "src/a.py", "A"), (2, "src/b.py", "B"), (3, "src/c.py", "C")],
    )
    conn.executemany(
        "INSERT INTO symbols VALUES (?, ?, ?, ?, ?, ?, ?)",
        [(10, 1, "alpha", "function", 2, 4, "def alpha()"),
         (20, 2, "beta", "function", 3, 5, "def beta()"),
         (30, 3, "gamma", "function", 7, 9, "def gamma()")],
    )
    if confidence:
        conn.executemany(
            "INSERT INTO edges VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(1, "call", "symbol", 10, "symbol", 20, "beta", 1, 3, 1, "extracted"),
             (2, "call", "symbol", 20, "symbol", 30, "gamma", 2, 4, 1, "inferred")],
        )
    else:
        conn.executemany(
            "INSERT INTO edges VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            [(1, "call", "symbol", 10, "symbol", 20, "beta", 1, 3, 1),
             (2, "call", "symbol", 20, "symbol", 30, "gamma", 2, 4, 1)],
        )
    return conn


def test_graph_candidates_are_bounded_and_keep_provenance():
    conn = _graph()
    seed = Candidate("src/a.py", 2, 4, "symbol", 1.0, symbol="alpha")
    result = graph_candidates(conn, [seed], depth=2, node_cap=1, iterations=8)
    assert len(result) == 1
    assert result[0].symbol == "beta"
    assert "confidence=extracted" in result[0].reason
    assert "graph provenance" in (result[0].content or "")
    assert result[0].key() != seed.key()


def test_graph_candidates_are_deterministic_and_support_old_edges():
    seed = Candidate("src/a.py", 2, 4, "symbol", 1.0, symbol="alpha")
    first = graph_candidates(_graph(confidence=False), [seed], depth=2, node_cap=5, iterations=5)
    second = graph_candidates(_graph(confidence=False), [seed], depth=2, node_cap=5, iterations=5)
    assert [(c.path, c.line_start, c.score) for c in first] == [
        (c.path, c.line_start, c.score) for c in second
    ]
    assert first and "confidence=unknown" in first[0].reason



def test_graph_candidates_honor_direction():
    down = graph_candidates(
        _graph(),
        [Candidate("src/a.py", 2, 4, "symbol", 1.0, symbol="alpha")],
        depth=2,
        node_cap=5,
        direction="down",
    )
    assert [candidate.symbol for candidate in down] == ["beta", "gamma"]

    up = graph_candidates(
        _graph(),
        [Candidate("src/b.py", 3, 5, "symbol", 1.0, symbol="beta")],
        depth=2,
        node_cap=5,
        direction="up",
    )
    assert [candidate.symbol for candidate in up] == ["alpha"]

def test_graph_candidates_tolerate_empty_or_partial_graphs():
    assert graph_candidates(sqlite3.connect(":memory:"), [], depth=2, node_cap=5) == []
    conn = sqlite3.connect(":memory:")
    conn.execute("CREATE TABLE files(id INTEGER PRIMARY KEY, path TEXT)")
    assert graph_candidates(conn, [Candidate("missing.py", 1, 1, "path", 1.0)]) == []
