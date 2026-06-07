"""Regression: refs/impact must flag partial graph coverage for Tier-B languages.

Import/inheritance edges are only extracted for the hand-tuned (Tier-A) languages.
A symbol or file in a Tier-B language (generic tree-sitter walk, e.g. Lua) gets
symbols and best-effort call sites but no dependency edges, so an empty/short
refs or impact result is inconclusive — the response must say so rather than let
an agent read "no references" as proof.
"""

from __future__ import annotations

from pathlib import Path

from codebase_index.config import load
from codebase_index.graph.expand import impact_lookup
from codebase_index.indexer.pipeline import build_index
from codebase_index.models import GraphCoverage
from codebase_index.retrieval.searchers import refs_lookup
from codebase_index.storage.db import Database

_LUA = (
    "local function greet(name)\n  return name\nend\n\n"
    "local function main()\n  return greet('x')\nend\n"
)
_PY = "def helper():\n    return 1\n\n\ndef caller():\n    return helper()\n"


def _index(repo: Path) -> Path:
    (repo / "mod.lua").write_text(_LUA, encoding="utf-8")
    (repo / "mod.py").write_text(_PY, encoding="utf-8")
    cfg = load(root=str(repo))
    db_path = repo / "index.sqlite"
    with Database(db_path) as db:
        build_index(cfg, db, root=Path(cfg.root))
    return db_path


def test_coverage_for_paths_unit():
    assert GraphCoverage.for_paths(["a.py", "b.go"]).partial is False
    partial = GraphCoverage.for_paths(["x.lua"])
    assert partial.partial is True
    assert partial.languages == ["lua"]
    assert partial.reason and "lua" in partial.reason


def test_refs_flags_partial_for_tier_b_symbol(tmp_path):
    db_path = _index(tmp_path)
    with Database(db_path) as db:
        lua_refs = refs_lookup(db.conn, "greet", kind="all")
        py_refs = refs_lookup(db.conn, "helper", kind="all")

    assert lua_refs.coverage.partial is True
    assert "lua" in lua_refs.coverage.languages
    # Tier-A symbol: fully analyzed, no warning.
    assert py_refs.coverage.partial is False


def test_impact_flags_partial_for_tier_b_file(tmp_path):
    db_path = _index(tmp_path)
    with Database(db_path) as db:
        lua_impact = impact_lookup(db.conn, "mod.lua", depth=2, direction="both")
        py_impact = impact_lookup(db.conn, "mod.py", depth=2, direction="both")

    assert lua_impact.coverage.partial is True
    assert "lua" in lua_impact.coverage.languages
    assert py_impact.coverage.partial is False
