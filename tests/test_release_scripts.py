"""Unit tests for the release/CI hygiene scripts under scripts/."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]


def _load(name: str):
    spec = importlib.util.spec_from_file_location(name, REPO / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


release_notes = _load("release_notes")
check_versions = _load("check_versions")
check_links = _load("check_links")


CHANGELOG = """# Changelog

## [Unreleased]

## [1.9.0] - 2026-09-02

### Added

- Thing one → arrow.

## [1.8.0] - 2026-09-02

### Changed

- Older thing.

## [1.7.0] - 2026-07-29

[Unreleased]: https://github.com/denfry/codebase-index/compare/v1.8.0...HEAD
[1.8.0]: https://github.com/denfry/codebase-index/compare/v1.7.0...v1.8.0
"""


# --- release_notes -----------------------------------------------------------
def test_release_notes_extracts_section_and_synthesizes_compare_link():
    out = release_notes.render(CHANGELOG, "1.9.0")
    assert "Thing one" in out
    assert "Older thing" not in out
    assert "pip install codebase-index==1.9.0" in out
    # No link definition for 1.9.0 -> derived from the previous heading.
    assert "compare/v1.8.0...v1.9.0" in out


def test_release_notes_prefers_existing_link_definition():
    out = release_notes.render(CHANGELOG, "1.8.0")
    assert "compare/v1.7.0...v1.8.0" in out
    assert "[1.8.0]:" not in out  # link defs are stripped from the body


def test_release_notes_fails_on_empty_or_missing_section():
    with pytest.raises(SystemExit):
        release_notes.render(CHANGELOG, "1.7.0")  # heading present, body empty
    with pytest.raises(KeyError):
        release_notes.render(CHANGELOG, "9.9.9")


def test_release_notes_cli_writes_file(tmp_path):
    changelog = tmp_path / "CHANGELOG.md"
    changelog.write_text(CHANGELOG, encoding="utf-8")
    out = tmp_path / "notes.md"
    rc = release_notes.main(["1.9.0", "--changelog", str(changelog), "--out", str(out)])
    assert rc == 0
    assert "Thing one" in out.read_text(encoding="utf-8")
    assert release_notes.main(["9.9.9", "--changelog", str(changelog)]) == 1


# --- check_versions ----------------------------------------------------------
def _fake_repo(tmp_path: Path, version: str, *, plugin=None, lock=None, stamps=None,
               changelog=CHANGELOG) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    (tmp_path / "src/codebase_index").mkdir(parents=True)
    (tmp_path / "src/codebase_index/__init__.py").write_text(
        f'__version__ = "{version}"\n', encoding="utf-8"
    )
    (tmp_path / ".claude-plugin").mkdir()
    (tmp_path / ".claude-plugin/plugin.json").write_text(
        json.dumps({"version": plugin or version}), encoding="utf-8"
    )
    (tmp_path / "requirements.lock").write_text(
        f"codebase-index @ https://github.com/denfry/codebase-index/archive/refs/tags/"
        f"v{lock or version}.tar.gz\n",
        encoding="utf-8",
    )
    for rel in check_versions.STAMPS:
        (tmp_path / rel).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / rel).write_text(f"{stamps or version}\n", encoding="utf-8")
    (tmp_path / "CHANGELOG.md").write_text(changelog, encoding="utf-8")
    return tmp_path


def test_check_versions_consistent(tmp_path):
    assert check_versions.check(_fake_repo(tmp_path, "1.9.0")) == []


def test_check_versions_reports_every_mismatch(tmp_path):
    repo = _fake_repo(tmp_path, "1.9.0", plugin="1.8.0", lock="1.8.0", stamps="1.8.0")
    problems = check_versions.check(repo)
    assert any("plugin.json" in p for p in problems)
    assert any("requirements.lock" in p for p in problems)
    assert sum(".skill_version" in p for p in problems) == 3


def test_check_versions_allows_bumped_version_with_unreleased(tmp_path):
    # main between releases: version ahead of the newest heading, notes under Unreleased.
    assert check_versions.check(_fake_repo(tmp_path / "ahead", "1.10.0")) == []
    # but a version that is neither released nor newer is a mistake
    problems = check_versions.check(_fake_repo(tmp_path / "behind", "1.8.5"))
    assert any("CHANGELOG" in p for p in problems)


def test_check_versions_real_repo_is_consistent():
    assert check_versions.check(REPO) == []


# --- check_links -------------------------------------------------------------
def test_check_links_detects_broken_and_ignores_external(tmp_path, monkeypatch):
    docs = tmp_path / "docs"
    docs.mkdir()
    (docs / "ok.md").write_text("target\n", encoding="utf-8")
    (tmp_path / "img.png").write_bytes(b"\x89PNG")
    md = tmp_path / "README.md"
    md.write_text(
        "\n".join([
            "[good](docs/ok.md#section)",
            "[external](https://example.com/x.md)",
            "[mail](mailto:a@b.c)",
            "[anchor](#top)",
            '<img src="img.png" width="10">',
            "![shot](assets/missing.png)",
            "[bad](docs/nope.md)",
            "```",
            "[fenced](docs/not-checked.md)",
            "```",
        ]),
        encoding="utf-8",
    )
    monkeypatch.setattr(check_links, "REPO", tmp_path)
    broken = check_links.find_broken(md, tmp_path)
    assert [t for _, t in broken] == ["assets/missing.png", "docs/nope.md"]
    assert broken[0][0] == 6 and broken[1][0] == 7


def test_check_links_cli_exit_codes(tmp_path, monkeypatch, capsys):
    (tmp_path / "a.md").write_text("[x](b.md)\n", encoding="utf-8")
    monkeypatch.setattr(check_links, "REPO", tmp_path)
    assert check_links.main([str(tmp_path)]) == 1
    assert "a.md:1: b.md" in capsys.readouterr().out
    (tmp_path / "b.md").write_text("ok\n", encoding="utf-8")
    assert check_links.main([str(tmp_path)]) == 0


def test_check_links_skips_venv(tmp_path, monkeypatch):
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv/x.md").write_text("[x](missing.md)\n", encoding="utf-8")
    monkeypatch.setattr(check_links, "REPO", tmp_path)
    assert list(check_links.iter_markdown([tmp_path], tmp_path)) == []
