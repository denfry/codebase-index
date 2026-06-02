"""Smoke tests for the CLI surface (M0). Expands per milestone in docs/ROADMAP.md."""

from typer.testing import CliRunner

from codebase_index.cli import app

runner = CliRunner()


def test_help_lists_all_commands():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    for cmd in [
        "init", "index", "update", "search", "symbol", "refs",
        "impact", "explain", "stats", "doctor", "clean", "watch",
    ]:
        assert cmd in result.output


def test_search_accepts_query_and_flags(tmp_path):
    (tmp_path / ".git").mkdir()
    result = runner.invoke(app, ["--root", str(tmp_path), "--json", "search", "auth token", "--limit", "5"])
    assert result.exit_code == 1
    assert "No index found" in result.output
