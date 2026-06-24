"""Smoke tests for the CLI surface (M0). Expands per milestone in docs/ROADMAP.md."""

import json

from typer.testing import CliRunner

from codebase_index.cli import app

runner = CliRunner()


def test_help_lists_all_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for cmd in [
        "init", "index", "update", "search", "symbol", "refs",
        "impact", "graph", "explain", "stats", "doctor", "clean", "watch", "mcp",
    ]:
        assert cmd in result.output


def test_search_accepts_query_and_flags(tmp_path):
    (tmp_path / ".git").mkdir()
    result = runner.invoke(app, ["--root", str(tmp_path), "--json", "search", "auth token", "--limit", "5"])
    assert result.exit_code == 0
    assert '"exists":true' in result.output.replace(" ", "")


def test_stats_and_doctor_accept_command_json(tmp_path):
    (tmp_path / ".git").mkdir()
    stats = runner.invoke(app, ["--root", str(tmp_path), "stats", "--json"])
    assert stats.exit_code == 0, stats.output
    assert json.loads(stats.output)["exists"] is False

    doctor = runner.invoke(app, ["--root", str(tmp_path), "doctor", "--json"])
    assert doctor.exit_code == 0, doctor.output
    assert "findings" in json.loads(doctor.output)


def _strip_ansi(text: str) -> str:
    import re
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def test_search_has_raw_flag():
    result = runner.invoke(app, ["search", "--help"])
    assert result.exit_code == 0
    assert "--raw" in _strip_ansi(result.stdout)


def test_explain_has_raw_flag():
    result = runner.invoke(app, ["explain", "--help"])
    assert result.exit_code == 0
    assert "--raw" in _strip_ansi(result.stdout)
