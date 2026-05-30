from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(rel: str) -> dict:
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def test_plugin_manifest_has_required_fields():
    m = _load(".claude-plugin/plugin.json")
    assert m["name"] == "codebase-index"
    assert m["version"]
    assert m["description"]


def test_marketplace_lists_plugin_from_repo_root():
    mk = _load(".claude-plugin/marketplace.json")
    assert mk["name"]
    assert "owner" in mk
    entries = {p["name"]: p for p in mk["plugins"]}
    assert "codebase-index" in entries
    assert entries["codebase-index"]["source"] == "./"


def test_plugin_version_matches_pyproject():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    ver = re.search(r'^version = "([^"]+)"', pyproject, re.MULTILINE).group(1)
    assert _load(".claude-plugin/plugin.json")["version"] == ver


def test_requirements_lock_pins_package_from_github_tag():
    # codebase-index is distributed from GitHub (not PyPI): the lock pins the
    # package to the matching release tag tarball, not a PyPI version specifier.
    version = _load(".claude-plugin/plugin.json")["version"]
    lock_text = (ROOT / "requirements.lock").read_text(encoding="utf-8")
    expected = (
        "codebase-index @ "
        f"https://github.com/denfry/codebase-index/archive/refs/tags/v{version}.tar.gz"
    )
    assert expected in lock_text.splitlines()
    assert "codebase-index==" not in lock_text  # must not fall back to PyPI


def test_requirements_lock_pins_tree_sitter_grammars():
    lock_lines = (ROOT / "requirements.lock").read_text(encoding="utf-8").splitlines()
    assert "tree-sitter==0.25.2" in lock_lines
    assert "tree-sitter-language-pack==1.8.1" in lock_lines


def test_session_start_hook_runs_bootstrap():
    hooks = _load("hooks/hooks.json")["hooks"]
    assert "SessionStart" in hooks
    cmds = [
        h["command"]
        for entry in hooks["SessionStart"]
        for h in entry["hooks"]
        if h["type"] == "command"
    ]
    assert any("bootstrap.sh" in c and "${CLAUDE_PLUGIN_ROOT}" in c for c in cmds)
