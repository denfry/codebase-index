from __future__ import annotations

import json as _json

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
    from pathlib import Path
    import conftest

    from codebase_index.config import Config
    from codebase_index.indexer.pipeline import build_index
    from codebase_index.storage.db import Database
    import codebase_index.indexer.pipeline as pipe

    fixture_root = Path(__file__).parent / "fixtures" / "sample_repo"
    fake = conftest.FakeEmbeddingBackend()
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
