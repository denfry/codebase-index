from __future__ import annotations

import json
import shutil
import subprocess

from typer.testing import CliRunner

from codebase_index.cli import app

runner = CliRunner()


def _git_repo(sample_repo, tmp_path):
    root = tmp_path / "repo"
    shutil.copytree(sample_repo, root)
    subprocess.run(["git", "init", "-q", str(root)], check=True)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(
        [
            "git", "-C", str(root),
            "-c", "user.name=Tests",
            "-c", "user.email=tests@example.invalid",
            "commit", "-qm", "baseline",
        ],
        check=True,
    )
    return root


def test_diff_impact_reports_changed_and_affected_files(sample_repo, tmp_path):
    root = _git_repo(sample_repo, tmp_path)
    indexed = runner.invoke(app, ["--root", str(root), "index"])
    assert indexed.exit_code == 0, indexed.output

    changed = root / "src" / "models" / "user.py"
    changed.write_text(changed.read_text(encoding="utf-8") + "\n# changed\n", encoding="utf-8")

    result = runner.invoke(
        app,
        ["--root", str(root), "--json", "diff-impact", "--depth", "2"],
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["changed_files"] == ["src/models/user.py"]
    assert payload["changed_files_total"] == 1
    assert payload["truncated"] is False
    assert "src/api/service.py" in {
        item["path"] for item in payload["affected_files"]
    }
    assert payload["index"]["stale"] is True


def test_diff_impact_empty_worktree_is_clear(sample_repo, tmp_path):
    root = _git_repo(sample_repo, tmp_path)
    assert runner.invoke(app, ["--root", str(root), "index"]).exit_code == 0

    result = runner.invoke(app, ["--root", str(root), "diff-impact"])
    assert result.exit_code == 0, result.output
    assert "No tracked changes" in result.output


def test_diff_impact_rejects_option_like_base(sample_repo, tmp_path):
    root = _git_repo(sample_repo, tmp_path)
    assert runner.invoke(app, ["--root", str(root), "index"]).exit_code == 0

    result = runner.invoke(
        app,
        ["--root", str(root), "--json", "diff-impact", "--base=--output=/tmp/x"],
    )
    assert result.exit_code == 2
    payload = json.loads(result.output)
    assert "non-option Git revision" in payload["error"]
