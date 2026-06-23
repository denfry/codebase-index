"""Tests for graph.analysis — communities / god nodes / surprising bridges.

The pure-Python graph functions are deterministic, so the assertions pin exact
structure (two cliques joined by one bridge → two communities + one surprising
link) rather than fuzzy thresholds.
"""

from __future__ import annotations

from codebase_index.config import Config
from codebase_index.graph import analysis
from codebase_index.indexer.pipeline import build_index
from codebase_index.parsers.base import Symbol
from codebase_index.storage import repo
from codebase_index.storage.db import Database


# --- pure-Python graph algorithms (no DB) -------------------------------------

def _two_cliques_with_bridge():
    """Two triangles (A0-A1-A2) and (B0-B1-B2) joined by a single A0-B0 edge."""
    edges = []

    def edge(s, d):
        return {"src_kind": "symbol", "src_id": s, "dst_kind": "symbol", "dst_id": d}

    # clique A: ids 0,1,2 ; clique B: ids 10,11,12
    for a, b in [(0, 1), (1, 2), (0, 2)]:
        edges.append(edge(a, b))
    for a, b in [(10, 11), (11, 12), (10, 12)]:
        edges.append(edge(a, b))
    edges.append(edge(0, 10))  # the bridge
    return edges


def test_detect_communities_splits_two_cliques():
    adj, _ = analysis.build_adjacency(_two_cliques_with_bridge())
    comm = analysis.detect_communities(adj)
    # All of clique A share one label; all of clique B share another; they differ.
    a_labels = {comm[("symbol", i)] for i in (0, 1, 2)}
    b_labels = {comm[("symbol", i)] for i in (10, 11, 12)}
    assert len(a_labels) == 1
    assert len(b_labels) == 1
    assert a_labels != b_labels


def test_modularity_is_positive_for_clear_structure():
    adj, _ = analysis.build_adjacency(_two_cliques_with_bridge())
    comm = analysis.detect_communities(adj)
    assert analysis.modularity(adj, comm) > 0.0


def test_god_nodes_rank_by_degree():
    # Make node 0 a hub: connect it to many leaves.
    edges = [
        {"src_kind": "symbol", "src_id": 0, "dst_kind": "symbol", "dst_id": leaf}
        for leaf in range(1, 6)
    ]
    adj, _ = analysis.build_adjacency(edges)
    comm = analysis.detect_communities(adj)
    node_index = {
        ("symbol", i): {"kind": "symbol", "name": f"sym{i}", "path": "src/x.py"}
        for i in range(6)
    }
    gods = analysis.god_nodes(adj, comm, node_index, limit=3)
    assert gods[0]["name"] == "sym0"
    assert gods[0]["degree"] == 5


def test_surprising_connection_finds_the_bridge():
    adj, edge_weight = analysis.build_adjacency(_two_cliques_with_bridge())
    comm = analysis.detect_communities(adj)
    node_index = {
        ("symbol", i): {"kind": "symbol", "name": f"sym{i}", "path": "src/a.py"}
        for i in (0, 1, 2)
    }
    node_index.update(
        {
            ("symbol", i): {"kind": "symbol", "name": f"sym{i}", "path": "src/b.py"}
            for i in (10, 11, 12)
        }
    )
    surprising = analysis.surprising_connections(edge_weight, comm, node_index)
    assert len(surprising) == 1
    names = {surprising[0]["from"]["name"], surprising[0]["to"]["name"]}
    assert names == {"sym0", "sym10"}
    assert surprising[0]["edge_count"] == 1


def test_label_community_uses_dominant_directory():
    node_index = {
        ("symbol", 1): {"kind": "symbol", "name": "a", "path": "src/auth/token.py"},
        ("symbol", 2): {"kind": "symbol", "name": "b", "path": "src/auth/login.py"},
        ("symbol", 3): {"kind": "symbol", "name": "c", "path": "src/db/conn.py"},
    }
    label = analysis.label_community([("symbol", 1), ("symbol", 2), ("symbol", 3)], node_index)
    assert label == "src/auth"


def test_label_community_discounts_test_paths():
    # Two production symbols in src/storage and three test files that exercise them:
    # tests outnumber prod, but the module should still be named for the prod code.
    node_index = {
        ("symbol", 1): {"kind": "symbol", "name": "a", "path": "src/storage/db.py"},
        ("symbol", 2): {"kind": "symbol", "name": "b", "path": "src/storage/repo.py"},
        ("symbol", 3): {"kind": "symbol", "name": "t1", "path": "tests/test_db.py"},
        ("symbol", 4): {"kind": "symbol", "name": "t2", "path": "tests/test_repo.py"},
        ("symbol", 5): {"kind": "symbol", "name": "t3", "path": "tests/test_x.py"},
    }
    members = [("symbol", i) for i in range(1, 6)]
    assert analysis.label_community(members, node_index) == "src/storage"
    # A community that is *only* tests still gets named for them.
    only_tests = [("symbol", i) for i in (3, 4, 5)]
    assert analysis.label_community(only_tests, node_index) == "tests"


def test_suggest_questions_seeds_from_structure():
    gods = [{"kind": "symbol", "name": "Engine", "path": "x", "degree": 9, "community": 0}]
    surprising = [
        {
            "from": {"kind": "symbol", "name": "a", "path": "x"},
            "to": {"kind": "symbol", "name": "b", "path": "y"},
            "from_community": 0,
            "to_community": 1,
            "edge_count": 1,
        }
    ]
    qs = analysis.suggest_questions(gods, surprising, {0: "core", 1: "io"})
    assert any("Engine" in q for q in qs)
    assert any("core" in q and "io" in q for q in qs)


# --- integration against a real built index -----------------------------------

def _seed_two_modules(db: Database) -> None:
    """auth module (token<-login) and db module (query<-exec), bridged login->query."""
    auth = repo.upsert_file(
        db.conn, path="src/auth/token.py", lang="python", size_bytes=1, sha256="a",
        mtime_ns=1, git_status=None, parser="treesitter", indexed_at="t", is_generated=False,
    )
    db_f = repo.upsert_file(
        db.conn, path="src/db/query.py", lang="python", size_bytes=1, sha256="b",
        mtime_ns=1, git_status=None, parser="treesitter", indexed_at="t", is_generated=False,
    )
    a = repo.replace_symbols(db.conn, auth, [
        Symbol(name="make_token", kind="function", line_start=1, line_end=2),
        Symbol(name="login", kind="function", line_start=3, line_end=4),
    ])
    b = repo.replace_symbols(db.conn, db_f, [
        Symbol(name="run_query", kind="function", line_start=1, line_end=2),
        Symbol(name="exec_stmt", kind="function", line_start=3, line_end=4),
    ])
    repo.replace_edges(db.conn, auth, [
        {"edge_type": "call", "src_kind": "symbol", "src_id": a[1],
         "dst_kind": None, "dst_id": None, "dst_name": "make_token", "line": 3, "resolved": 0},
        {"edge_type": "call", "src_kind": "symbol", "src_id": a[1],
         "dst_kind": None, "dst_id": None, "dst_name": "run_query", "line": 4, "resolved": 0},
    ])
    repo.replace_edges(db.conn, db_f, [
        {"edge_type": "call", "src_kind": "symbol", "src_id": b[0],
         "dst_kind": None, "dst_id": None, "dst_name": "exec_stmt", "line": 2, "resolved": 0},
    ])


def test_analyze_and_cache_roundtrip(tmp_path):
    from codebase_index.graph.builder import build_graph

    db = Database(tmp_path / "index.sqlite").open()
    _seed_two_modules(db)
    build_graph(db.conn)  # resolves edges + refresh_analysis caches the summary

    cached = analysis.load_analysis(db.conn)
    assert cached is not None
    assert cached["node_count"] > 0
    assert cached["god_nodes"], "expected at least one god node"
    # Recomputing directly matches the cached summary's headline numbers.
    fresh = analysis.analyze(db.conn)
    assert fresh["node_count"] == cached["node_count"]
    assert fresh["edge_count"] == cached["edge_count"]
    db.close()


def test_analyze_on_sample_repo(sample_repo, tmp_path):
    cfg = Config()
    cfg.root = str(sample_repo)
    db = Database(tmp_path / "index.sqlite").open()
    build_index(cfg, db, root=sample_repo)

    summary = analysis.load_analysis(db.conn)
    assert summary is not None
    assert summary["node_count"] >= 1
    assert isinstance(summary["communities"], list)
    assert isinstance(summary["questions"], list)
    db.close()
