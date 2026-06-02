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
    res = runner.invoke(app, ["--root", str(root), "init", "--target", "claude"])
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
    assert runner.invoke(app, ["--root", str(root), "init", "--target", "claude"]).exit_code == 0
    res = runner.invoke(app, ["--root", str(root), "init", "--target", "claude"])
    assert res.exit_code != 0
    assert "--force" in res.output


def test_init_force_overwrites(tmp_path):
    root = _project(tmp_path)
    runner.invoke(app, ["--root", str(root), "init", "--target", "claude"])
    res = runner.invoke(app, ["--root", str(root), "init", "--target", "claude", "--force"])
    assert res.exit_code == 0, res.output


def test_init_with_hooks_merges_settings(tmp_path):
    root = _project(tmp_path)
    res = runner.invoke(app, ["--root", str(root), "init", "--target", "claude", "--with-hooks"])
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


def test_init_codex_writes_agents_package_and_resources(tmp_path):
    root = _project(tmp_path)
    res = runner.invoke(app, ["--root", str(root), "init", "--target", "codex"])
    assert res.exit_code == 0, res.output

    agents = root / "AGENTS.md"
    assert agents.is_file()
    text = agents.read_text(encoding="utf-8")
    assert "codebase-index" in text
    assert ".codex/skills/codebase-index/SKILL.md" in text

    skill = root / ".codex" / "skills" / "codebase-index"
    assert (skill / "SKILL.md").is_file()
    assert (skill / "scripts" / "cbx").is_file()
    assert "codex" in res.output
    assert "(skill)" in res.output


def test_init_auto_installs_detected_project_cli_dirs(tmp_path, monkeypatch):
    from codebase_index import scaffold

    root = _project(tmp_path)
    (root / ".codex").mkdir()
    (root / ".opencode").mkdir()
    monkeypatch.setattr(scaffold, "detect_cli_targets", lambda _root: ["codex", "opencode"])
    monkeypatch.setattr(scaffold, "detect_mcp_targets", lambda _root: [])

    res = runner.invoke(app, ["--root", str(root), "init", "--target", "auto"])
    assert res.exit_code == 0, res.output

    assert (root / "AGENTS.md").is_file()
    assert (root / ".opencode" / "commands" / "codebase-index.md").is_file()
    assert "Detected targets: codex, opencode" in res.output
