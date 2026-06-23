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
    assert data["format"] == "html"
    assert data["nodes"] >= 1
    assert out.exists()
    text = out.read_text(encoding="utf-8")
    assert "codebase-index graph" in text
    assert "graph-data" in text
    # Phase-4 enrichment: module colours + confidence legend are present.
    assert "= module" in text
    assert "inferred" in text and "ambiguous" in text


def test_graph_command_writes_graphml(sample_repo, tmp_path):
    assert runner.invoke(app, ["--root", str(sample_repo), "index"]).exit_code == 0
    out = tmp_path / "g.graphml"
    res = runner.invoke(
        app, ["--root", str(sample_repo), "--json", "graph", "--format", "graphml",
               "--output", str(out)],
    )
    assert res.exit_code == 0, res.output
    assert json.loads(res.output)["format"] == "graphml"
    text = out.read_text(encoding="utf-8")
    assert "<graphml" in text and 'attr.name="community"' in text and "edge_type" in text


def test_graph_command_writes_dot_and_neo4j(sample_repo, tmp_path):
    assert runner.invoke(app, ["--root", str(sample_repo), "index"]).exit_code == 0

    dot = tmp_path / "g.dot"
    res = runner.invoke(
        app, ["--root", str(sample_repo), "graph", "--format", "dot", "--output", str(dot)]
    )
    assert res.exit_code == 0, res.output
    assert "digraph codebase_index" in dot.read_text(encoding="utf-8")

    cy = tmp_path / "g.cypher"
    res = runner.invoke(
        app, ["--root", str(sample_repo), "graph", "--format", "neo4j", "--output", str(cy)]
    )
    assert res.exit_code == 0, res.output
    assert "MERGE" in cy.read_text(encoding="utf-8")


def test_graph_command_rejects_unknown_format(sample_repo):
    assert runner.invoke(app, ["--root", str(sample_repo), "index"]).exit_code == 0
    res = runner.invoke(app, ["--root", str(sample_repo), "graph", "--format", "svg"])
    assert res.exit_code == 2
    assert "invalid --format" in res.output
