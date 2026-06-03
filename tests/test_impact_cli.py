from __future__ import annotations

import json

from typer.testing import CliRunner

from codebase_index.cli import app

runner = CliRunner()


def _index(sample_repo):
    assert runner.invoke(app, ["--root", str(sample_repo), "index"]).exit_code == 0


def test_impact_command_json_up(sample_repo):
    _index(sample_repo)
    res = runner.invoke(
        app,
        ["--root", str(sample_repo), "--json", "impact", "src/models/user.py",
         "--direction", "up", "--depth", "2"],
    )
    assert res.exit_code == 0, res.output
    data = json.loads(res.output)
    assert data["direction"] == "up"
    assert "src/api/service.py" in data["files"]


def test_impact_command_markdown(sample_repo):
    _index(sample_repo)
    res = runner.invoke(
        app, ["--root", str(sample_repo), "impact", "refresh_access_token", "--direction", "up"]
    )
    assert res.exit_code == 0, res.output
    assert "impact:" in res.output and "refresh_access_token" in res.output


def test_impact_missing_index(tmp_path):
    empty = tmp_path / "empty"
    (empty / ".git").mkdir(parents=True)
    res = runner.invoke(app, ["--root", str(empty), "--json", "impact", "anything"])
    assert res.exit_code == 0
    data = json.loads(res.output)
    assert data["index"]["exists"] is True and data["files"] == []
