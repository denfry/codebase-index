from __future__ import annotations

from pathlib import Path

import pytest

from codebase_index import scaffold, skill_update


def _install(root: Path, target: str = "claude") -> Path:
    scaffold.materialize_skill(root, force=False, target=target)
    return root / scaffold.skill_rel_for_target(target)


def test_fresh_install_needs_no_update(tmp_path):
    skill_dir = _install(tmp_path)
    assert (skill_dir / skill_update.VERSION_FILE).is_file()
    assert skill_update.needs_update(skill_dir) is False


def test_needs_update_when_stamp_differs_or_missing(tmp_path):
    skill_dir = _install(tmp_path)
    (skill_dir / skill_update.VERSION_FILE).write_text("0.0.1\n", encoding="utf-8")
    assert skill_update.needs_update(skill_dir) is True
    (skill_dir / skill_update.VERSION_FILE).unlink()
    assert skill_update.needs_update(skill_dir) is True


def test_package_version_unknown_when_metadata_missing(monkeypatch):
    def boom(_name):
        raise RuntimeError("no metadata")

    monkeypatch.setattr("importlib.metadata.version", boom)
    assert skill_update._package_version() == "unknown"


def test_update_skill_refreshes_stamps_and_backs_up(tmp_path):
    skill_dir = _install(tmp_path)
    template_text = (skill_dir / "SKILL.md").read_text(encoding="utf-8")
    (skill_dir / "SKILL.md").write_text("locally edited\n", encoding="utf-8")
    (skill_dir / skill_update.VERSION_FILE).write_text("0.0.1\n", encoding="utf-8")

    result = skill_update.update_skill(tmp_path, "claude")

    assert result["updated"] is True
    assert result["backed_up"] is True
    assert result["old_version"] == "0.0.1"
    assert result["new_version"] == skill_update._package_version()
    # Skill content is re-materialized from the template...
    assert (skill_dir / "SKILL.md").read_text(encoding="utf-8") == template_text
    assert skill_update._installed_version(skill_dir) == result["new_version"]
    # ...and the pre-update state is preserved in the cache backup.
    bak = skill_update._backup_dir(tmp_path, "claude")
    assert (bak / "SKILL.md").read_text(encoding="utf-8") == "locally edited\n"


def test_update_skill_without_backup(tmp_path):
    _install(tmp_path)
    result = skill_update.update_skill(tmp_path, "claude", backup=False)
    assert result["backed_up"] is False
    assert not skill_update._backup_dir(tmp_path, "claude").exists()


def test_update_skill_on_missing_dir_writes_no_backup(tmp_path):
    result = skill_update.update_skill(tmp_path, "claude")
    assert result["updated"] is True
    assert result["backed_up"] is False
    assert result["old_version"] == ""


def test_rollback_restores_previous_skill(tmp_path):
    skill_dir = _install(tmp_path)
    (skill_dir / "SKILL.md").write_text("pre-update state\n", encoding="utf-8")
    skill_update.update_skill(tmp_path, "claude")

    result = skill_update.rollback_skill(tmp_path, "claude")

    assert result == {"target": "claude", "rolled_back": True}
    assert (skill_dir / "SKILL.md").read_text(encoding="utf-8") == "pre-update state\n"


def test_rollback_without_backup_reports_reason(tmp_path):
    result = skill_update.rollback_skill(tmp_path, "claude")
    assert result["rolled_back"] is False
    assert result["reason"] == "no backup found"


def test_auto_update_skips_missing_skill_dir(tmp_path):
    assert skill_update.auto_update_if_needed(tmp_path, "claude") is False


def test_auto_update_skips_when_current(tmp_path):
    _install(tmp_path)
    assert skill_update.auto_update_if_needed(tmp_path, "claude") is False


def test_auto_update_applies_when_outdated(tmp_path):
    skill_dir = _install(tmp_path)
    (skill_dir / skill_update.VERSION_FILE).write_text("0.0.1\n", encoding="utf-8")
    assert skill_update.auto_update_if_needed(tmp_path, "claude") is True
    assert skill_update.needs_update(skill_dir) is False


def test_auto_update_swallows_failures(tmp_path, monkeypatch):
    skill_dir = _install(tmp_path)
    (skill_dir / skill_update.VERSION_FILE).write_text("0.0.1\n", encoding="utf-8")

    def boom(*args, **kwargs):
        raise RuntimeError("materialize failed")

    monkeypatch.setattr(scaffold, "materialize_skill", boom)
    assert skill_update.auto_update_if_needed(tmp_path, "claude") is False


def test_cli_auto_update_respects_disable_env(tmp_path, monkeypatch):
    from codebase_index import cli

    skill_dir = _install(tmp_path)
    (skill_dir / skill_update.VERSION_FILE).write_text("0.0.1\n", encoding="utf-8")

    monkeypatch.setenv("CBX_NO_SKILL_AUTO_UPDATE", "1")
    cli._try_auto_update_skills(tmp_path)
    assert skill_update._installed_version(skill_dir) == "0.0.1"  # untouched

    monkeypatch.delenv("CBX_NO_SKILL_AUTO_UPDATE")
    cli._try_auto_update_skills(tmp_path)
    assert skill_update.needs_update(skill_dir) is False


@pytest.mark.parametrize("target", ["claude", "codex", "opencode"])
def test_update_skill_supports_all_targets(tmp_path, target):
    result = skill_update.update_skill(tmp_path, target)
    assert result["updated"] is True
    skill_dir = tmp_path / scaffold.skill_rel_for_target(target)
    assert (skill_dir / "SKILL.md").is_file()
    assert skill_update.needs_update(skill_dir) is False
