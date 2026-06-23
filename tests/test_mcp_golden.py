"""Golden-snapshot tests for every MCP tool output (requires the mcp extra).

Mirrors tests/test_cli_golden.py but drives the MCP server tool functions, which
wrap each payload in the stable envelope (schema_version + tool). The MCP tools
resolve the index from CBX_ROOT / CBX_DB_PATH, so we build a real index from the
shared sample_repo fixture and point the env at it.

Regenerate intentionally with:  UPDATE_GOLDEN=1 pytest tests/test_mcp_golden.py
"""
from __future__ import annotations

import json as _json
import os
import subprocess
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

try:
    from codebase_index.mcp import server as mcp_server
    MCP_AVAILABLE = True
except ImportError:
    MCP_AVAILABLE = False

pytestmark = pytest.mark.skipif(not MCP_AVAILABLE, reason="mcp extra not installed")

from codebase_index.cli import app  # noqa: E402  (after the skip guard)
from tests.golden_utils import assert_matches_golden  # noqa: E402

runner = CliRunner()


@pytest.fixture(scope="module")
def indexed_repo(tmp_path_factory):
    """A copy of sample_repo with a freshly built index, isolated from the source tree."""
    import shutil

    from tests.conftest import FIXTURE_ROOT

    dest = tmp_path_factory.mktemp("mcp_indexed") / "repo"
    shutil.copytree(FIXTURE_ROOT, dest)

    identity = ["-c", "user.name=golden", "-c", "user.email=golden@test"]
    subprocess.run(["git", "init"], cwd=dest, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=dest, capture_output=True)
    commit = subprocess.run(
        ["git", *identity, "commit", "-m", "initial"], cwd=dest, capture_output=True, text=True
    )
    assert commit.returncode == 0, commit.stderr
    assert runner.invoke(app, ["--root", str(dest), "index"]).exit_code == 0
    return dest


def _call(indexed_repo, tool_fn, **kwargs):
    """Invoke an MCP tool against the indexed fixture and parse the JSON envelope."""
    db_path = indexed_repo / ".claude" / "cache" / "codebase-index" / "index.sqlite"
    env = {"CBX_ROOT": str(indexed_repo), "CBX_DB_PATH": str(db_path)}
    with patch.dict(os.environ, env, clear=False):
        return _json.loads(tool_fn(**kwargs))


# name -> (tool function, kwargs). Queries mirror the CLI goldens for parity.
CASES = {
    "mcp_healthcheck": (lambda: mcp_server.healthcheck, {}),
    "mcp_search_code": (lambda: mcp_server.search_code, {"query": "token"}),
    "mcp_find_symbol": (lambda: mcp_server.find_symbol, {"name": "User"}),
    "mcp_find_refs": (lambda: mcp_server.find_refs, {"symbol": "refresh_access_token"}),
    "mcp_impact_of": (lambda: mcp_server.impact_of, {"target": "src/models/user.py", "direction": "up"}),
    "mcp_explain_code": (lambda: mcp_server.explain_code, {"query": "how does authentication work"}),
    "mcp_architecture": (lambda: mcp_server.architecture_overview, {}),
    "mcp_index_stats": (lambda: mcp_server.index_stats, {}),
}

# golden name -> the tool field every envelope must carry.
_EXPECTED_TOOL = {
    "mcp_healthcheck": "healthcheck",
    "mcp_search_code": "search_code",
    "mcp_find_symbol": "find_symbol",
    "mcp_find_refs": "find_refs",
    "mcp_impact_of": "impact_of",
    "mcp_explain_code": "explain_code",
    "mcp_architecture": "architecture_overview",
    "mcp_index_stats": "index_stats",
}


@pytest.mark.parametrize("name", list(CASES), ids=list(CASES))
def test_mcp_tool_matches_golden(indexed_repo, name):
    fn_factory, kwargs = CASES[name]
    payload = _call(indexed_repo, fn_factory(), **kwargs)
    # The contract values are asserted explicitly — a golden alone would happily
    # freeze a wrong schema_version. The golden then guards the rest of the shape.
    assert payload["schema_version"] == mcp_server.MCP_SCHEMA_VERSION
    assert payload["tool"] == _EXPECTED_TOOL[name]
    assert_matches_golden(name, payload, root=str(indexed_repo))
