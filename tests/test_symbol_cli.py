from __future__ import annotations

import json

from typer.testing import CliRunner

from codebase_index.cli import app

runner = CliRunner()


def _index(sample_repo):
    assert runner.invoke(app, ["--root", str(sample_repo), "index"]).exit_code == 0


def test_symbol_command_json(sample_repo):
    _index(sample_repo)
    res = runner.invoke(
        app, ["--root", str(sample_repo), "--json", "symbol", "refresh_access_token"]
    )
    assert res.exit_code == 0, res.output
    data = json.loads(res.output)
    assert any(symbol["path"] == "src/auth/token.py" for symbol in data["symbols"])


def test_refs_command_callers(sample_repo):
    _index(sample_repo)
    res = runner.invoke(
        app,
        [
            "--root",
            str(sample_repo),
            "--json",
            "refs",
            "refresh_access_token",
            "--kind",
            "callers",
        ],
    )
    assert res.exit_code == 0, res.output
    data = json.loads(res.output)
    assert data["sites"] and all(site["kind"] == "call" for site in data["sites"])


def test_symbol_missing_index(tmp_path):
    empty = tmp_path / "empty"
    (empty / ".git").mkdir(parents=True)
    res = runner.invoke(app, ["--root", str(empty), "--json", "symbol", "anything"])
    assert res.exit_code == 0
    data = json.loads(res.output)
    assert data["index"]["exists"] is False and data["symbols"] == []
