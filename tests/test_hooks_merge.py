from __future__ import annotations

import json

from codebase_index import scaffold


def test_merge_hook_settings_creates_settings(tmp_path):
    changed = scaffold.merge_hook_settings(tmp_path)
    assert changed is True
    data = json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    matchers = [h["matcher"] for h in data["hooks"]["PostToolUse"]]
    assert any("Edit" in m for m in matchers)
    cmds = [
        hk["command"]
        for entry in data["hooks"]["PostToolUse"]
        for hk in entry["hooks"]
    ]
    assert any("codebase-index update" in c for c in cmds)


def test_merge_hook_settings_is_idempotent(tmp_path):
    assert scaffold.merge_hook_settings(tmp_path) is True
    assert scaffold.merge_hook_settings(tmp_path) is False  # already present
    data = json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    cmds = [
        hk["command"]
        for entry in data["hooks"]["PostToolUse"]
        for hk in entry["hooks"]
    ]
    assert sum("codebase-index update" in c for c in cmds) == 1  # not duplicated


def test_merge_hook_settings_preserves_existing(tmp_path):
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"model": "opus", "hooks": {"Stop": []}}), encoding="utf-8")

    scaffold.merge_hook_settings(tmp_path)
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["model"] == "opus"          # unrelated keys preserved
    assert "Stop" in data["hooks"]          # unrelated hook groups preserved
    assert "PostToolUse" in data["hooks"]


def test_enabled_hooks_detects_our_hook(tmp_path):
    assert scaffold.enabled_hooks(tmp_path) == []
    scaffold.merge_hook_settings(tmp_path)
    found = scaffold.enabled_hooks(tmp_path)
    assert any("codebase-index update" in c for c in found)
