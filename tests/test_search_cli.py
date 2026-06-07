from __future__ import annotations

import json as _json
import shutil

from typer.testing import CliRunner

from codebase_index.cli import app

runner = CliRunner()


def _build(tmp_path, monkeypatch):
    from pathlib import Path

    from codebase_index.config import load
    from codebase_index.indexer.pipeline import build_index
    from codebase_index.storage.db import Database

    fixture_root = Path(__file__).parent / "fixtures" / "sample_repo"
    cfg = load(root=str(fixture_root))
    db_path = tmp_path / "index.sqlite"
    with Database(db_path) as db:
        build_index(cfg, db, root=Path(cfg.root))
    return db_path


def test_search_json_runs(tmp_path, monkeypatch):
    db_path = _build(tmp_path, monkeypatch)
    monkeypatch.setenv("CBX_DB_PATH", str(db_path))
    result = runner.invoke(app, ["search", "refresh token", "--json"])
    assert result.exit_code == 0, result.output
    payload = _json.loads(result.stdout)
    assert payload["mode"] == "hybrid"
    assert "results" in payload


def test_search_auto_indexes_when_missing(sample_repo, tmp_path):
    root = tmp_path / "copy"
    shutil.copytree(sample_repo, root)
    db_path = root / ".claude" / "cache" / "codebase-index" / "index.sqlite"
    if db_path.exists():
        db_path.unlink()

    result = runner.invoke(app, ["--root", str(root), "--json", "search", "token"])
    assert result.exit_code == 0, result.output
    payload = _json.loads(result.output)
    assert payload["index"]["exists"] is True
    assert payload["index"]["stale"] is False
    assert db_path.exists()


def test_explain_forces_intent_shape(tmp_path, monkeypatch):
    db_path = _build(tmp_path, monkeypatch)
    monkeypatch.setenv("CBX_DB_PATH", str(db_path))
    result = runner.invoke(app, ["explain", "how does token refresh work", "--json"])
    assert result.exit_code == 0, result.output
    payload = _json.loads(result.stdout)
    assert payload["intent"] in {"how_it_works", "architecture", "keyword"}


def test_vector_mode_disabled_is_clear(tmp_path, monkeypatch):
    db_path = _build(tmp_path, monkeypatch)
    monkeypatch.setenv("CBX_DB_PATH", str(db_path))
    result = runner.invoke(app, ["search", "token", "--mode", "vector"])
    assert result.exit_code == 2
    assert "embeddings" in result.output.lower()


def test_vector_mode_enabled_runs(tmp_path, monkeypatch):
    import pytest

    pytest.importorskip("sqlite_vec")
    import codebase_index.cli as cli_mod
    import codebase_index.indexer.pipeline as pipe
    from pathlib import Path

    from codebase_index.config import Config
    from codebase_index.indexer.pipeline import build_index
    from codebase_index.storage.db import Database
    from tests.conftest import FakeEmbeddingBackend

    fixture_root = Path(__file__).parent / "fixtures" / "sample_repo"
    fake = FakeEmbeddingBackend()
    monkeypatch.setattr(pipe, "resolve_backend", lambda cfg, warn=None: fake)
    cfg = Config(root=str(fixture_root))
    cfg.embeddings.enabled = True
    db_path = tmp_path / "index.sqlite"
    with Database(db_path) as db:
        build_index(cfg, db, root=fixture_root)

    monkeypatch.setenv("CBX_DB_PATH", str(db_path))
    monkeypatch.setattr(cli_mod, "_resolve_backend_for_search", lambda ctx: fake)
    result = runner.invoke(app, ["search", "renew credentials", "--mode", "vector", "--json"])
    assert result.exit_code == 0, result.output
    payload = _json.loads(result.stdout)
    assert payload["mode"] == "vector"


def test_search_reports_stale_after_edit(sample_repo, tmp_path, monkeypatch):
    import sqlite3

    from typer.testing import CliRunner

    from codebase_index.cli import app

    runner = CliRunner()
    assert runner.invoke(app, ["--root", str(sample_repo), "index"]).exit_code == 0

    res = runner.invoke(app, ["--root", str(sample_repo), "--json", "search", "token"])
    assert res.exit_code == 0, res.output
    fresh = _json.loads(res.output)
    assert fresh["index"]["exists"] is True
    assert fresh["index"]["stale"] is False

    db_path = sample_repo / ".claude" / "cache" / "codebase-index" / "index.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.execute("UPDATE files SET mtime_ns = 1")
    conn.execute("DELETE FROM meta WHERE key = 'head_commit'")
    conn.commit()
    conn.close()

    res2 = runner.invoke(app, ["--root", str(sample_repo), "--json", "search", "token"])
    stale = _json.loads(res2.output)
    assert stale["index"]["stale"] is True
    assert stale["index"]["files_changed_since_build"] >= 1


def test_explain_reports_stale_after_edit(sample_repo):
    """Regression: explain must honor the freshness contract like search.

    Before the fix, explain called the retrieval pipeline without root/config, so
    it always fell back to a hardcoded ``stale=False, files_changed_since_build=0``
    block — silently breaking the skill's freshness check for "how does X work".
    """
    import sqlite3

    assert runner.invoke(app, ["--root", str(sample_repo), "index"]).exit_code == 0

    res = runner.invoke(
        app, ["--root", str(sample_repo), "--json", "explain", "how does token refresh work"]
    )
    assert res.exit_code == 0, res.output
    fresh = _json.loads(res.output)
    assert fresh["index"]["exists"] is True
    assert fresh["index"]["stale"] is False

    db_path = sample_repo / ".claude" / "cache" / "codebase-index" / "index.sqlite"
    conn = sqlite3.connect(str(db_path))
    conn.execute("UPDATE files SET mtime_ns = 1")
    conn.execute("DELETE FROM meta WHERE key = 'head_commit'")
    conn.commit()
    conn.close()

    res2 = runner.invoke(
        app, ["--root", str(sample_repo), "--json", "explain", "how does token refresh work"]
    )
    stale = _json.loads(res2.output)
    assert stale["index"]["stale"] is True
    assert stale["index"]["files_changed_since_build"] >= 1


def test_search_kind_words_filter_symbol_kind(sample_repo):
    assert runner.invoke(app, ["--root", str(sample_repo), "index"]).exit_code == 0

    result = runner.invoke(
        app,
        [
            "--root",
            str(sample_repo),
            "--json",
            "search",
            "refresh access token function",
            "--limit",
            "3",
        ],
    )

    assert result.exit_code == 0, result.output
    payload = _json.loads(result.output)
    assert payload["results"][0]["symbols"] == ["refresh_access_token"]
