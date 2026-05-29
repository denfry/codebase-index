from __future__ import annotations

import json

from typer.testing import CliRunner

from codebase_index.cli import app

runner = CliRunner()


def test_search_fts_json_after_index(sample_repo):
    idx = runner.invoke(app, ["--root", str(sample_repo), "--json", "index"])
    assert idx.exit_code == 0, idx.output

    res = runner.invoke(
        app,
        [
            "--root",
            str(sample_repo),
            "--json",
            "search",
            "refresh access token",
            "--mode",
            "fts",
        ],
    )
    assert res.exit_code == 0, res.output
    data = json.loads(res.output)
    assert data["intent"] == "keyword"
    assert any(r["path"] == "src/auth/token.py" for r in data["results"])


def test_search_without_index_reports_missing(tmp_path):
    empty = tmp_path / "empty"
    (empty / ".git").mkdir(parents=True)
    res = runner.invoke(app, ["--root", str(empty), "--json", "search", "anything"])
    assert res.exit_code == 0
    data = json.loads(res.output)
    assert data["index"]["exists"] is False
    assert data["results"] == []


def test_search_markdown_default(sample_repo):
    runner.invoke(app, ["--root", str(sample_repo), "index"])
    res = runner.invoke(
        app, ["--root", str(sample_repo), "search", "bootstrap", "--mode", "fts"]
    )
    assert res.exit_code == 0
    assert "web/app.ts" in res.output
