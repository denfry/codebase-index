from __future__ import annotations

import importlib.util
import json
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

_spec = importlib.util.spec_from_file_location(
    "sync_skill_copies", REPO / "scripts" / "sync_skill_copies.py"
)
assert _spec is not None and _spec.loader is not None
sync_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(sync_mod)


def _mini_repo(tmp_path: Path, version: str = "9.9.9") -> Path:
    repo = tmp_path / "repo"
    (repo / "src/codebase_index/skill_template/scripts").mkdir(parents=True)
    (repo / "src/codebase_index/__init__.py").write_text(
        f'__version__ = "{version}"\n', encoding="utf-8"
    )
    tpl = repo / "src/codebase_index/skill_template"
    (tpl / "SKILL.md").write_text("skill body\n", encoding="utf-8")
    (tpl / "scripts" / "cbx").write_text("#!/bin/sh\n", encoding="utf-8")
    (tpl / "scripts" / "cbx.ps1").write_text("Write-Output ok\n", encoding="utf-8")
    (repo / ".claude-plugin").mkdir()
    (repo / ".claude-plugin/plugin.json").write_text(
        '{\n  "name": "codebase-index",\n  "version": "%s"\n}\n' % version, encoding="utf-8"
    )
    (repo / "requirements.lock").write_text(
        f"codebase-index @ https://github.com/x/y/archive/refs/tags/v{version}.tar.gz\n",
        encoding="utf-8",
    )
    sync_mod.sync(repo, version)
    return repo


def test_real_repo_is_in_sync():
    version = sync_mod.package_version(REPO)
    assert sync_mod.check(REPO, version) == []


def test_check_detects_drift_and_sync_repairs(tmp_path):
    repo = _mini_repo(tmp_path)
    assert sync_mod.check(repo, "9.9.9") == []

    drifted = repo / ".claude/skills/codebase-index/SKILL.md"
    drifted.write_text("locally edited\n", encoding="utf-8")
    (repo / "skills/codebase-index/SKILL.md").unlink()

    problems = sync_mod.check(repo, "9.9.9")
    assert any("differs" in p for p in problems)
    assert any("missing" in p for p in problems)

    sync_mod.sync(repo, "9.9.9")
    assert sync_mod.check(repo, "9.9.9") == []
    assert drifted.read_text(encoding="utf-8") == "skill body\n"


def test_version_bump_flows_to_all_stamps(tmp_path):
    repo = _mini_repo(tmp_path)
    (repo / "src/codebase_index/__init__.py").write_text(
        '__version__ = "9.9.10"\n', encoding="utf-8"
    )
    version = sync_mod.package_version(repo)
    assert version == "9.9.10"

    problems = sync_mod.check(repo, version)
    assert any(".skill_version" in p for p in problems)
    assert any("plugin.json" in p for p in problems)
    assert any("requirements.lock" in p for p in problems)

    sync_mod.sync(repo, version)
    assert sync_mod.check(repo, version) == []
    stamp = repo / ".claude/skills/codebase-index/.skill_version"
    assert stamp.read_text(encoding="utf-8") == "9.9.10\n"
    plugin = json.loads((repo / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
    assert plugin == {"name": "codebase-index", "version": "9.9.10"}
    assert "v9.9.10.tar.gz" in (repo / "requirements.lock").read_text(encoding="utf-8")


def test_crlf_worktree_is_not_drift(tmp_path):
    # core.autocrlf=true checks text files out with CRLF; that must not be
    # reported as drift against the LF template.
    repo = _mini_repo(tmp_path)
    skill_md = repo / ".claude/skills/codebase-index/SKILL.md"
    skill_md.write_bytes(b"skill body\r\n")
    assert sync_mod.check(repo, "9.9.9") == []
