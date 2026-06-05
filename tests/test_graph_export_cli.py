from __future__ import annotations

import json

from typer.testing import CliRunner

from codebase_index.cli import app

runner = CliRunner()


def test_graph_command_writes_html(sample_repo, tmp_path):
    assert runner.invoke(app, ["--root", str(sample_repo), "index"]).exit_code == 0
    out = tmp_path / "graph.html"

    res = runner.invoke(
        app,
        [
            "--root",
            str(sample_repo),
            "--json",
            "graph",
            "src/models/user.py",
            "--direction",
            "up",
            "--output",
            str(out),
        ],
    )

    assert res.exit_code == 0, res.output
    data = json.loads(res.output)
    assert data["path"] == str(out)
    assert data["nodes"] >= 1
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "codebase-index graph" in text
    assert "graph-data" in text
