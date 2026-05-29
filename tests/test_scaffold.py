from __future__ import annotations

import json

from codebase_index import scaffold


def test_materialize_skill_writes_all_template_files(tmp_path):
    written = scaffold.materialize_skill(tmp_path, force=False)
    dest = tmp_path / ".claude" / "skills" / "codebase-index"
    assert (dest / "SKILL.md").is_file()
    assert (dest / "scripts" / "cbx").is_file()
    assert (dest / "scripts" / "cbx.ps1").is_file()
    assert (dest / "SKILL.md") in written


def test_materialize_skill_refuses_existing_without_force(tmp_path):
    scaffold.materialize_skill(tmp_path, force=False)
    try:
        scaffold.materialize_skill(tmp_path, force=False)
        assert False, "expected FileExistsError"
    except FileExistsError:
        pass
    scaffold.materialize_skill(tmp_path, force=True)


def test_write_config_emits_resolved_defaults(tmp_path):
    path = scaffold.write_config(tmp_path, force=False)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["root"] == "."
    assert data["retrieval"]["default_mode"] == "hybrid"
    assert data["embeddings"]["enabled"] is False
    path.write_text('{"root": "custom"}', encoding="utf-8")
    scaffold.write_config(tmp_path, force=False)
    assert json.loads(path.read_text(encoding="utf-8"))["root"] == "custom"


def test_merge_gitignore_is_idempotent(tmp_path):
    changed_first = scaffold.merge_gitignore(tmp_path)
    text = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert ".claude/cache/codebase-index/" in text
    assert changed_first is True
    changed_second = scaffold.merge_gitignore(tmp_path)
    assert changed_second is False
    assert text.count(".claude/cache/codebase-index/") == 1


def test_write_hooks_example(tmp_path):
    path = scaffold.write_hooks_example(tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "PostToolUse" in data["hooks"]
