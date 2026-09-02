from __future__ import annotations

from codebase_index.graph.builder import build_graph
from codebase_index.graph.expand import impact_lookup, walk_impact
from codebase_index.parsers.base import Symbol
from codebase_index.storage import repo
from codebase_index.storage.db import Database


def _file(db, path: str, sha: str) -> int:
    return repo.upsert_file(
        db.conn,
        path=path,
        lang="python",
        size_bytes=1,
        sha256=sha,
        mtime_ns=1,
        git_status=None,
        parser="treesitter",
        indexed_at="t",
        is_generated=False,
    )


def _graph(db):
    target_file = _file(db, "src/target.py", "target")
    direct_file = _file(db, "src/direct.py", "direct")
    transitive_file = _file(db, "src/transitive.py", "transitive")
    repo.replace_symbols(
        db.conn,
        target_file,
        [Symbol(name="root", kind="function", line_start=1, line_end=1, qualified="root")],
    )
    direct = repo.replace_symbols(
        db.conn,
        direct_file,
        [Symbol(name="direct", kind="function", line_start=1, line_end=1, qualified="direct")],
    )[0]
    transitive = repo.replace_symbols(
        db.conn,
        transitive_file,
        [
            Symbol(
                name="transitive",
                kind="function",
                line_start=1,
                line_end=1,
                qualified="transitive",
            )
        ],
    )[0]
    repo.replace_edges(
        db.conn,
        direct_file,
        [
            {
                "edge_type": "call",
                "src_kind": "symbol",
                "src_id": direct,
                "dst_kind": None,
                "dst_id": None,
                "dst_name": "root",
                "line": 1,
                "resolved": 0,
            }
        ],
    )
    repo.replace_edges(
        db.conn,
        transitive_file,
        [
            {
                "edge_type": "call",
                "src_kind": "symbol",
                "src_id": transitive,
                "dst_kind": None,
                "dst_id": None,
                "dst_name": "direct",
                "line": 1,
                "resolved": 0,
            }
        ],
    )
    build_graph(db.conn)
    return target_file


def test_impact_decay_keeps_direct_before_transitive(tmp_path):
    db = Database(tmp_path / "index.sqlite").open()
    _graph(db)

    nodes = walk_impact(
        db.conn, "src/target.py", depth=2, direction="up", decay=0.5
    )
    assert [(node.name, node.distance) for node in nodes] == [
        ("direct", 1),
        ("transitive", 2),
    ]

    response = impact_lookup(
        db.conn, "src/target.py", depth=2, direction="up", decay=0.5
    )
    assert response.files == ["src/direct.py", "src/transitive.py"]
    db.close()


def test_impact_decay_missing_target_is_empty(tmp_path):
    db = Database(tmp_path / "index.sqlite").open()
    assert walk_impact(db.conn, "missing.py", depth=2, direction="up", decay=0.5) == []
    db.close()
