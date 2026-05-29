from __future__ import annotations

import json
import subprocess

from typer.testing import CliRunner

from codebase_index.cli import app

runner = CliRunner()


def _git_repo(tmp_path):
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(root), "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-q", "-m", "init"],
        check=True,
    )
    return root


def test_update_no_index_reports_clearly(tmp_path):
    res = runner.invoke(app, ["--root", str(tmp_path), "update"])
    assert res.exit_code == 0
    assert "index" in res.output.lower()


def test_update_json_reports_counts(tmp_path):
    root = _git_repo(tmp_path)
    assert runner.invoke(app, ["--root", str(root), "index"]).exit_code == 0

    (root / "src" / "a.py").write_text("def alpha():\n    return 42\n", encoding="utf-8")
    res = runner.invoke(app, ["--root", str(root), "--json", "update"])
    assert res.exit_code == 0, res.output
    data = json.loads(res.output)
    assert data["indexed"] == 1
    assert data["deleted"] == 0


def test_update_refreshes_freshness(tmp_path):
    root = _git_repo(tmp_path)
    assert runner.invoke(app, ["--root", str(root), "index"]).exit_code == 0
    (root / "src" / "a.py").write_text("def alpha():\n    return 5\n", encoding="utf-8")

    # stale before update
    stale = json.loads(
        runner.invoke(app, ["--root", str(root), "--json", "search", "alpha"]).output
    )
    assert stale["index"]["stale"] is True

    assert runner.invoke(app, ["--root", str(root), "update"]).exit_code == 0
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(root), "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-q", "-m", "edit"],
        check=True,
    )
    fresh = json.loads(
        runner.invoke(app, ["--root", str(root), "--json", "search", "alpha"]).output
    )
    assert fresh["index"]["stale"] is False
