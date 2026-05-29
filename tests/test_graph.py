from __future__ import annotations

from codebase_index.config import Config
from codebase_index.graph.builder import build_graph
from codebase_index.graph.expand import impact_lookup, walk_impact
from codebase_index.parsers.base import Symbol
from codebase_index.indexer.pipeline import build_index
from codebase_index.storage import repo
from codebase_index.storage.db import Database


def _db(tmp_path):
    return Database(tmp_path / "index.sqlite").open()


def _seed(db):
    fid_a = repo.upsert_file(
        db.conn, path="src/auth/token.py", lang="python", size_bytes=1, sha256="a",
        mtime_ns=1, git_status=None, parser="treesitter", indexed_at="t", is_generated=False,
    )
    fid_b = repo.upsert_file(
        db.conn, path="src/api/service.py", lang="python", size_bytes=1, sha256="b",
        mtime_ns=1, git_status=None, parser="treesitter", indexed_at="t", is_generated=False,
    )
    a = repo.replace_symbols(db.conn, fid_a, [
        Symbol(name="refresh_access_token", kind="function", line_start=1, line_end=2,
               qualified="refresh_access_token"),
    ])
    b = repo.replace_symbols(db.conn, fid_b, [
        Symbol(name="renew", kind="function", line_start=5, line_end=6, qualified="renew"),
    ])
    repo.replace_edges(db.conn, fid_b, [
        {"edge_type": "call", "src_kind": "symbol", "src_id": b[0],
         "dst_kind": None, "dst_id": None, "dst_name": "refresh_access_token",
         "line": 6, "resolved": 0},
        {"edge_type": "import", "src_kind": "file", "src_id": fid_b,
         "dst_kind": None, "dst_id": None, "dst_name": "auth.token",
         "line": 1, "resolved": 0},
        {"edge_type": "call", "src_kind": "symbol", "src_id": b[0],
         "dst_kind": None, "dst_id": None, "dst_name": "does_not_exist",
         "line": 7, "resolved": 0},
    ])
    return fid_a, fid_b, a[0], b[0]


def test_build_graph_resolves_symbol_and_import_edges(tmp_path):
    db = _db(tmp_path)
    fid_a, fid_b, target_id, caller_id = _seed(db)
    res = build_graph(db.conn)

    assert res["resolved"] == 2
    assert res["unresolved"] == 1

    inc = repo.incoming_edges(db.conn, "symbol", target_id)
    assert any(r["src_id"] == caller_id and r["edge_type"] == "call" for r in inc)
    finc = repo.incoming_edges(db.conn, "file", fid_a)
    assert any(r["src_id"] == fid_b and r["edge_type"] == "import" for r in finc)

    target = db.conn.execute(
        "SELECT in_degree, out_degree FROM symbols WHERE id = ?", (target_id,)
    ).fetchone()
    assert target["in_degree"] == 1 and target["out_degree"] == 0
    db.close()


def _indexed(sample_repo, tmp_path):
    cfg = Config()
    cfg.root = str(sample_repo)
    db = Database(tmp_path / "index.sqlite").open()
    build_index(cfg, db, root=sample_repo)
    return db


def test_impact_up_of_file_finds_importer_and_subclass(sample_repo, tmp_path):
    db = _indexed(sample_repo, tmp_path)
    resp = impact_lookup(db.conn, "src/models/user.py", depth=2, direction="up")
    assert resp.direction == "up" and resp.index.exists is True
    assert "src/api/service.py" in resp.files
    assert any(n.via_edge == "import" for n in resp.nodes)
    db.close()


def test_impact_up_of_symbol_finds_caller(sample_repo, tmp_path):
    db = _indexed(sample_repo, tmp_path)
    resp = impact_lookup(db.conn, "refresh_access_token", depth=2, direction="up")
    assert "src/api/service.py" in resp.files
    assert any(n.name == "renew" and n.via_edge == "call" for n in resp.nodes)
    db.close()


def test_impact_down_of_symbol_lists_dependencies(sample_repo, tmp_path):
    db = _indexed(sample_repo, tmp_path)
    resp = impact_lookup(db.conn, "renew", depth=1, direction="down")
    assert any(n.name == "refresh_access_token" for n in resp.nodes)
    db.close()


def test_depth_bounds_traversal(sample_repo, tmp_path):
    db = _indexed(sample_repo, tmp_path)
    deep = walk_impact(db.conn, "src/models/user.py", depth=2, direction="up")
    shallow = walk_impact(db.conn, "src/models/user.py", depth=1, direction="up")
    assert all(n.distance <= 1 for n in shallow)
    assert all(n.distance <= 2 for n in deep)
    db.close()


def test_impact_missing_target_returns_empty(sample_repo, tmp_path):
    db = _indexed(sample_repo, tmp_path)
    resp = impact_lookup(db.conn, "no_such_thing", depth=2, direction="both")
    assert resp.nodes == [] and resp.files == []
    db.close()
