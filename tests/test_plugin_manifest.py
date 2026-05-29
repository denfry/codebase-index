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


def test_requirements_lock_pins_package_version():
    version = _load(".claude-plugin/plugin.json")["version"]
    lock = (ROOT / "requirements.lock").read_text(encoding="utf-8").strip()
    assert lock == f"codebase-index=={version}"


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
