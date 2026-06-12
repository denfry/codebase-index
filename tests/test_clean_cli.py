"""`clean` resets the local index (documented in README/FAQ/ARCHITECTURE §5).

Until 1.3.x it was a stub; these lock in the real reset behavior and the
"never touch the installed skill" guarantee.
"""

from __future__ import annotations

import json

from typer.testing import CliRunner

from codebase_index.cli import app

runner = CliRunner()


def _make_project(tmp_path):
    (tmp_path / ".git").mkdir()
    src = tmp_path / "src"
    src.mkdir()
    (src / "app.py").write_text("def greet(name):\n    return f'hi {name}'\n", encoding="utf-8")
    return tmp_path


def _cache_dir(root):
    return root / ".claude" / "cache" / "codebase-index"


def test_clean_removes_index_db_but_keeps_cache_dir(tmp_path):
    root = _make_project(tmp_path)
    assert runner.invoke(app, ["--root", str(root), "index"]).exit_code == 0

    db = _cache_dir(root) / "index.sqlite"
    assert db.exists()

    result = runner.invoke(app, ["--root", str(root), "clean", "--yes", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["existed"] is True
    assert any("index.sqlite" in p for p in payload["removed"])
    assert not db.exists()
    # default clean is a DB reset, not a cache wipe
    assert _cache_dir(root).exists()


def test_clean_all_wipes_cache_dir(tmp_path):
    root = _make_project(tmp_path)
    assert runner.invoke(app, ["--root", str(root), "index"]).exit_code == 0
    assert _cache_dir(root).exists()

    result = runner.invoke(app, ["--root", str(root), "clean", "--all", "--yes", "--json"])
    assert result.exit_code == 0, result.output
    assert json.loads(result.output)["existed"] is True
    assert not _cache_dir(root).exists()


def test_clean_never_removes_installed_skill(tmp_path):
    root = _make_project(tmp_path)
    assert runner.invoke(app, ["--root", str(root), "init", "--target", "claude"]).exit_code == 0
    assert runner.invoke(app, ["--root", str(root), "index"]).exit_code == 0

    skill = root / ".claude" / "skills" / "codebase-index" / "SKILL.md"
    assert skill.is_file()

    assert runner.invoke(app, ["--root", str(root), "clean", "--all", "--yes"]).exit_code == 0
    assert skill.is_file(), "clean must keep the installed skill"


def test_clean_is_a_noop_when_nothing_to_clean(tmp_path):
    root = _make_project(tmp_path)
    result = runner.invoke(app, ["--root", str(root), "clean", "--yes", "--json"])
    assert result.exit_code == 0, result.output
    payload = json.loads(result.output)
    assert payload["existed"] is False
    assert payload["removed"] == []


def test_clean_rebuild_cycle(tmp_path):
    root = _make_project(tmp_path)
    assert runner.invoke(app, ["--root", str(root), "index"]).exit_code == 0
    assert runner.invoke(app, ["--root", str(root), "clean", "--yes"]).exit_code == 0

    db = _cache_dir(root) / "index.sqlite"
    assert not db.exists()
    assert runner.invoke(app, ["--root", str(root), "index"]).exit_code == 0
    assert db.exists()
