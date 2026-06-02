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
    assert tools == {"search_code", "find_symbol", "find_refs", "impact_of", "explain_code", "index_stats"}


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


# ── run entry point ───────────────────────────────────────────────────────────

def test_run_function_exists():
    assert callable(mcp_server.run)
