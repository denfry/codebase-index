"""Tests for the MCP server module (requires mcp extra)."""
from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

try:
    from codebase_index.mcp import server as mcp_server
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False

pytestmark = pytest.mark.skipif(not MCP_AVAILABLE, reason="mcp extra not installed")


# ── helpers ──────────────────────────────────────────────────────────────────

def _call(tool_fn, **kwargs):
    """Call a tool function and parse the JSON result."""
    return json.loads(tool_fn(**kwargs))


# ── tool registration ─────────────────────────────────────────────────────────

def test_mcp_server_has_expected_tools():
    tools = {t.name for t in mcp_server.mcp._tool_manager.list_tools()}
    assert tools == {
        "healthcheck",
        "search_code",
        "find_symbol",
        "find_refs",
        "impact_of",
        "explain_code",
        "index_stats",
    }


def test_mcp_server_name():
    assert mcp_server.mcp.name == "codebase-index"


# ── no-index error path ───────────────────────────────────────────────────────

def _with_missing_db(fn):
    """Run fn with CBX_DB_PATH pointing to a non-existent file."""
    with tempfile.TemporaryDirectory() as tmp:
        missing = Path(tmp) / "no_index.sqlite"
        with patch.dict(os.environ, {"CBX_DB_PATH": str(missing)}):
            return fn()


def test_search_code_no_index():
    result = _with_missing_db(lambda: _call(mcp_server.search_code, query="foo"))
    assert "error" in result
    assert "index" in result["error"].lower()


# ── schema envelope (schema_version + tool on every payload, incl. errors) ─────

_ENVELOPE_CALLS = {
    "healthcheck": lambda: _call(mcp_server.healthcheck),
    "search_code": lambda: _call(mcp_server.search_code, query="foo"),
    "find_symbol": lambda: _call(mcp_server.find_symbol, name="Foo"),
    "find_refs": lambda: _call(mcp_server.find_refs, symbol="foo"),
    "impact_of": lambda: _call(mcp_server.impact_of, target="foo.py"),
    "explain_code": lambda: _call(mcp_server.explain_code, query="how does foo work"),
    "index_stats": lambda: _call(mcp_server.index_stats),
}


@pytest.mark.parametrize("tool,call", list(_ENVELOPE_CALLS.items()), ids=list(_ENVELOPE_CALLS))
def test_every_tool_payload_carries_schema_envelope(tool, call):
    """Even the no-index error path is wrapped in the stable envelope."""
    result = _with_missing_db(call)
    assert result["schema_version"] == mcp_server.MCP_SCHEMA_VERSION
    assert result["tool"] == tool


def test_healthcheck_no_index():
    result = _with_missing_db(lambda: _call(mcp_server.healthcheck))
    assert result["package_version"]
    assert result["index"]["exists"] is False


def test_find_symbol_no_index():
    result = _with_missing_db(lambda: _call(mcp_server.find_symbol, name="Foo"))
    assert "error" in result


def test_find_refs_no_index():
    result = _with_missing_db(lambda: _call(mcp_server.find_refs, symbol="foo"))
    assert "error" in result


def test_impact_of_no_index():
    result = _with_missing_db(lambda: _call(mcp_server.impact_of, target="foo.py"))
    assert "error" in result


def test_explain_code_no_index():
    result = _with_missing_db(lambda: _call(mcp_server.explain_code, query="how does foo work"))
    assert "error" in result


def test_index_stats_no_index():
    result = _with_missing_db(lambda: _call(mcp_server.index_stats))
    assert result["exists"] is False
    assert "error" in result


# ── CBX_ROOT resolution ───────────────────────────────────────────────────────

def test_resolve_db_uses_cbx_root(tmp_path):
    """CBX_ROOT env var is respected when resolving the db path."""
    (tmp_path / ".git").mkdir()
    with patch.dict(os.environ, {"CBX_ROOT": str(tmp_path)}, clear=False):
        if "CBX_DB_PATH" in os.environ:
            del os.environ["CBX_DB_PATH"]
        db_path, cfg = mcp_server._resolve_db()
    expected = tmp_path / ".claude" / "cache" / "codebase-index" / "index.sqlite"
    assert db_path == expected


def test_resolve_db_uses_cbx_db_path(tmp_path):
    """CBX_DB_PATH env var overrides normal discovery."""
    custom = tmp_path / "custom.sqlite"
    env = {"CBX_DB_PATH": str(custom)}
    if "CBX_ROOT" in os.environ:
        env["CBX_ROOT"] = os.environ["CBX_ROOT"]
    with patch.dict(os.environ, env):
        db_path, _ = mcp_server._resolve_db()
    assert db_path == custom


# ── pagination ───────────────────────────────────────────────────────────────

def test_search_code_accepts_offset_parameter():
    """search_code accepts offset without raising TypeError."""
    result = _with_missing_db(lambda: _call(mcp_server.search_code, query="foo", offset=5))
    assert "error" in result  # no-index error, but offset was accepted


def test_explain_code_accepts_offset_parameter():
    """explain_code accepts offset without raising TypeError."""
    result = _with_missing_db(lambda: _call(mcp_server.explain_code, query="how does auth work", offset=5))
    assert "error" in result


def test_search_code_pagination_with_real_index(tmp_path):
    """Pagination returns disjoint result pages from a real index."""
    pytest.importorskip("codebase_index.mcp.server")
    from tests.benchmark_public import build_public_fixture
    from codebase_index.config import Config
    from codebase_index.indexer.pipeline import build_index
    from codebase_index.storage.db import Database as DB

    fixture = build_public_fixture(tmp_path / "repo", filler_files=50)
    db_path = fixture / ".claude" / "cache" / "codebase-index" / "index.sqlite"
    cfg = Config()
    cfg.root = str(fixture)
    cfg.embeddings.enabled = False
    with DB(db_path) as db:
        build_index(cfg, db, root=fixture)

    env = {"CBX_DB_PATH": str(db_path)}
    with patch.dict(os.environ, env, clear=False):
        page0 = _call(mcp_server.search_code, query="auth token", limit=3, offset=0)
        page1 = _call(mcp_server.search_code, query="auth token", limit=3, offset=3)

    assert "results" in page0
    # Pages don't overlap by (path, line_start, line_end) triple.
    if page0["results"] and page1["results"]:
        page0_keys = {(r["path"], r["line_start"], r["line_end"]) for r in page0["results"]}
        page1_keys = {(r["path"], r["line_start"], r["line_end"]) for r in page1["results"]}
        assert page0_keys.isdisjoint(page1_keys), "page0 and page1 share identical result chunks"

    if page1.get("pagination"):
        assert page1["pagination"]["offset"] == 3
        assert page1["pagination"]["limit"] == 3


# ── run entry point ───────────────────────────────────────────────────────────

def test_run_function_exists():
    assert callable(mcp_server.run)
