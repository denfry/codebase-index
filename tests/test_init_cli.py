from __future__ import annotations

import json

from typer.testing import CliRunner

from codebase_index.cli import app

runner = CliRunner()


def _project(tmp_path):
    (tmp_path / ".git").mkdir()
    return tmp_path


def test_init_scaffolds_skill_config_and_gitignore(tmp_path):
    root = _project(tmp_path)
    res = runner.invoke(app, ["--root", str(root), "init"])
    assert res.exit_code == 0, res.output

    skill = root / ".claude" / "skills" / "codebase-index"
    assert (skill / "SKILL.md").is_file()
    assert (skill / "scripts" / "cbx").is_file()
    assert (skill / "scripts" / "cbx.ps1").is_file()

    cfg = root / ".claude" / "cache" / "codebase-index" / "config.json"
    assert json.loads(cfg.read_text(encoding="utf-8"))["root"] == "."

    gitignore = (root / ".gitignore").read_text(encoding="utf-8")
    assert ".claude/cache/codebase-index/" in gitignore
    assert "codebase-index index" in res.output


def test_init_refuses_existing_without_force(tmp_path):
    root = _project(tmp_path)
    assert runner.invoke(app, ["--root", str(root), "init"]).exit_code == 0
    res = runner.invoke(app, ["--root", str(root), "init"])
    assert res.exit_code != 0
    assert "--force" in res.output


def test_init_force_overwrites(tmp_path):
    root = _project(tmp_path)
    runner.invoke(app, ["--root", str(root), "init"])
    res = runner.invoke(app, ["--root", str(root), "init", "--force"])
    assert res.exit_code == 0, res.output


def test_init_with_hooks_merges_settings(tmp_path):
    root = _project(tmp_path)
    res = runner.invoke(app, ["--root", str(root), "init", "--with-hooks"])
    assert res.exit_code == 0, res.output

    hook_example = root / ".claude" / "skills" / "codebase-index" / "examples" / "hooks" / "settings.json"
    assert hook_example.is_file()

    settings = json.loads((root / ".claude" / "settings.json").read_text(encoding="utf-8"))
    cmds = [
        hk["command"]
        for entry in settings["hooks"]["PostToolUse"]
        for hk in entry["hooks"]
    ]
    assert any("codebase-index update" in c for c in cmds)
    assert "hook" in res.output.lower()
