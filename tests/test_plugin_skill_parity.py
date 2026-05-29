from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_plugin_skill_matches_authored_skill():
    plugin = (ROOT / "skills" / "codebase-index" / "SKILL.md").read_text(encoding="utf-8")
    authored = (ROOT / "skill" / "SKILL.md").read_text(encoding="utf-8")
    assert plugin == authored
