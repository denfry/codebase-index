"""Evidence memory through every public surface: CLI, MCP, Markdown, stats and doctor."""

from __future__ import annotations

import json
import os
import sqlite3
from pathlib import Path
from unittest.mock import patch

import pytest
from typer.testing import CliRunner

from codebase_index.cli import app
from codebase_index.config import Config
from codebase_index.doctor import run_doctor
from codebase_index.output.markdown import render, render_verify

runner = CliRunner()

REFUND = '''def issue_refund(invoice, amount):
    """Refund part of an invoice total."""
    if amount > invoice.total:
        raise ValueError("refund exceeds invoice total")
    return invoice.total - amount
'''
QUERY = "refund exceeds invoice total"


@pytest.fixture
def indexed(tmp_path, monkeypatch):
    for name in ("CBX_DB_PATH", "CBX_MEMORY_PATH", "CBX_MEMORY", "CBX_ROOT"):
        monkeypatch.delenv(name, raising=False)
    root = tmp_path / "repo"
    (root / "billing").mkdir(parents=True)
    (root / "billing" / "refund.py").write_text(REFUND, encoding="utf-8")
    assert runner.invoke(app, ["--root", str(root), "index"]).exit_code == 0
    return root


def _cli(root: Path, *args: str):
    return runner.invoke(app, ["--root", str(root), *args])


def _json(result) -> dict:
    assert result.exit_code == 0, result.output
    return json.loads(result.output)


def test_cli_session_search_reuses_and_verify_reports_changes(indexed):
    first = _json(_cli(indexed, "search", QUERY, "--session", "cli-1", "--json"))
    assert first["memory"]["reused"] == 0
    second = _json(_cli(indexed, "search", QUERY, "--session", "cli-1", "--json"))
    assert second["memory"]["reused"] >= 1

    verdict = _json(_cli(indexed, "verify", "--session", "cli-1", "--json"))
    assert verdict["all_valid"] is True and verdict["session"]["found"] is True

    (indexed / "billing" / "refund.py").write_text(REFUND.replace(">", ">="), encoding="utf-8")
    changed = _json(_cli(indexed, "verify", "--session", "cli-1", "--json"))
    assert changed["all_valid"] is False
    assert "changed" in changed["summary"]
    ref = next(v["ref"] for v in changed["evidence"] if v["state"] == "changed")

    strict = _cli(indexed, "verify", ref, "--strict", "--json")
    assert strict.exit_code == 1
    assert json.loads(strict.output)["evidence"][0]["state"] == "changed"


def test_cli_verify_arguments_and_session_tags_are_validated(indexed):
    assert _cli(indexed, "verify").exit_code == 2
    assert _cli(indexed, "search", QUERY, "--session", "bad tag").exit_code == 2
    assert _cli(indexed, "explain", QUERY, "--session", "bad/tag").exit_code == 2
    bad = _json(_cli(indexed, "verify", "../../etc/passwd:1-2@0123456789abcdef", "--json"))
    assert bad["all_valid"] is False and bad["errors"]


def test_cli_verify_of_unknown_session_is_not_all_valid(indexed):
    payload = _json(_cli(indexed, "verify", "--session", "never-used", "--json"))
    assert payload["all_valid"] is False and payload["session"]["found"] is False


def test_cli_stats_memory_block_and_human_line(indexed):
    assert _json(_cli(indexed, "stats", "--json"))["memory"] == {"enabled": True, "exists": False}
    _json(_cli(indexed, "search", QUERY, "--session", "s", "--json"))
    _json(_cli(indexed, "search", QUERY, "--session", "s", "--json"))
    memory = _json(_cli(indexed, "stats", "--json"))["memory"]
    assert memory["sessions"] == 1 and memory["reused"] >= 1 and memory["tokens_saved"] > 0
    human = _cli(indexed, "stats")
    assert "tokens not resent" in human.output


def test_cli_memory_gc_and_clear(indexed):
    _json(_cli(indexed, "search", QUERY, "--session", "a", "--json"))
    _json(_cli(indexed, "search", QUERY, "--session", "b", "--json"))
    gc = _json(_cli(indexed, "memory", "gc", "--json"))
    assert gc["exists"] and gc["sessions"] == 2
    assert _json(_cli(indexed, "memory", "clear", "--session", "a", "--yes", "--json"))[
        "removed_sessions"] == 1
    assert _json(_cli(indexed, "memory", "clear", "--yes", "--json"))["removed_sessions"] == 1
    assert _json(_cli(indexed, "stats", "--json"))["memory"]["sessions"] == 0


def test_cli_memory_disabled_by_environment(indexed, monkeypatch):
    monkeypatch.setenv("CBX_MEMORY", "0")
    payload = _json(_cli(indexed, "search", QUERY, "--session", "s", "--json"))
    assert payload["memory"]["available"] is False
    assert not (indexed / ".claude" / "cache" / "codebase-index" / "memory.sqlite").exists()


def test_markdown_marks_reused_stale_and_invalidated():
    payload = {
        "query": "q", "intent": "keyword", "confidence": "high",
        "results": [
            {"rank": 1, "path": "a.py", "line_start": 1, "line_end": 3, "reason": "x",
             "snippet": None, "reused": True},
            {"rank": 2, "path": "b.py", "line_start": 4, "line_end": 9, "reason": "y",
             "snippet": "def b(): pass", "stale": True},
        ],
        "recommended_reads": [],
        "fallback_suggestions": {},
        "memory": {"session": "s", "reused": 1, "tokens_saved": 12,
                   "invalidated": [{"ref": "c.py:1-2@0123456789abcdef", "state": "changed"}]},
    }
    text = render(payload)
    assert "already delivered in this session" in text
    assert "index is older than the file" in text
    assert "c.py:1-2@0123456789abcdef` — changed" in text

    verdicts = render_verify({
        "all_valid": False, "summary": {"changed": 1},
        "session": {"session": "s", "found": True, "evidence": 1},
        "evidence": [{"ref": "c.py:1-2@0123456789abcdef", "state": "changed", "valid": False,
                      "line_start": None, "line_end": None, "reason": "content no longer occurs"}],
        "errors": [{"ref": "nope", "error": "not an evidence reference"}],
    })
    assert "CHANGED" in verdicts and "some evidence is not valid" in verdicts and "nope" in verdicts


try:
    from codebase_index.mcp import server as mcp_server
    MCP_AVAILABLE = True
except ImportError:  # pragma: no cover
    MCP_AVAILABLE = False


@pytest.mark.skipif(not MCP_AVAILABLE, reason="mcp extra not installed")
def test_mcp_session_reuse_and_verify_evidence(indexed):
    db_path = indexed / ".claude" / "cache" / "codebase-index" / "index.sqlite"
    env = {"CBX_ROOT": str(indexed), "CBX_DB_PATH": str(db_path)}
    with patch.dict(os.environ, env, clear=False):
        json.loads(mcp_server.search_code(query=QUERY, session="mcp-1"))
        again = json.loads(mcp_server.search_code(query=QUERY, session="mcp-1"))
        assert again["schema_version"] == 1 and again["memory"]["reused"] >= 1

        checked = json.loads(mcp_server.verify_evidence(session="mcp-1"))
        assert checked["tool"] == "verify_evidence" and checked["all_valid"] is True
        ref = checked["evidence"][0]["ref"]
        by_ref = json.loads(mcp_server.verify_evidence(refs=[ref, "garbage"]))
        assert by_ref["evidence"][0]["valid"] is True and by_ref["errors"]

        assert "error" in json.loads(mcp_server.verify_evidence())
        assert "error" in json.loads(mcp_server.search_code(query=QUERY, session="a b"))
        assert "error" in json.loads(mcp_server.explain_code(query=QUERY, session="a b"))
        health = json.loads(mcp_server.healthcheck())
        assert health["memory"]["exists"] is True


def _memory_path(root: Path) -> Path:
    return root / ".claude" / "cache" / "codebase-index" / "memory.sqlite"


def _doctor_memory(root: Path):
    cfg = Config()
    cfg.root = str(root)
    return next(f for f in run_doctor(root, cfg) if f.id == "memory_store")


def test_doctor_reports_memory_health_without_repairing(indexed):
    assert _doctor_memory(indexed).ok
    _json(_cli(indexed, "search", QUERY, "--session", "s", "--json"))
    healthy = _doctor_memory(indexed)
    assert healthy.ok and "healthy" in healthy.detail

    path = _memory_path(indexed)
    conn = sqlite3.connect(path)
    conn.execute("UPDATE meta SET value = '99' WHERE key = 'schema_version'")
    conn.commit()
    conn.close()
    newer = _doctor_memory(indexed)
    assert not newer.ok and "newer" in newer.detail

    for sidecar in path.parent.glob("memory.sqlite*"):
        sidecar.unlink()
    path.write_bytes(b"not a database" * 64)
    broken = _doctor_memory(indexed)
    assert not broken.ok and path.read_bytes().startswith(b"not a database")  # untouched
