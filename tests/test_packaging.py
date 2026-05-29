from __future__ import annotations

from importlib import resources
from pathlib import Path


def _template():
    return resources.files("codebase_index") / "skill_template"


def test_packaged_template_has_skill_and_scripts():
    root = _template()
    assert (root / "SKILL.md").is_file()
    assert (root / "scripts" / "cbx").is_file()
    assert (root / "scripts" / "cbx.ps1").is_file()
    assert (root / "examples" / "hooks" / "settings.json").is_file()


def test_packaged_skill_matches_dev_copy():
    """The wheel-shipped SKILL.md must not drift from the authored skill/SKILL.md."""
    packaged = (_template() / "SKILL.md").read_text(encoding="utf-8")
    dev = Path("skill/SKILL.md").read_text(encoding="utf-8")
    assert packaged == dev


def test_packaged_skill_defines_research_discipline():
    skill = (_template() / "SKILL.md").read_text(encoding="utf-8")

    assert "## Research modes" in skill
    assert "## Confidence handling" in skill
    assert "## Coverage gate" in skill
    assert "question-specific evidence" in skill
    assert "Do not optimize for a benchmark repository" in skill
    # The skill must surface the tool's own intent classification and the
    # per-subcommand response shapes, not assume every query returns confidence.
    assert "## Response shapes by subcommand" in skill
    assert "the tool's own classification of the question" in skill


def test_packaged_cbx_whitelists_safe_subcommands_only():
    cbx = (_template() / "scripts" / "cbx").read_text(encoding="utf-8")
    assert 'ALLOWED="search explain symbol refs impact stats update index"' in cbx
    for forbidden in ("clean", "init", "watch"):
        assert f" {forbidden} " not in f' {cbx.split("ALLOWED=")[1].splitlines()[0]} '
