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

    from tests.conftest import FIXTURE_ROOT

    cfg = load(root=str(FIXTURE_ROOT))
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
