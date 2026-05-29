from __future__ import annotations

import json

from typer.testing import CliRunner

from codebase_index.cli import app

runner = CliRunner()


def test_index_then_stats_json(sample_repo):
    r1 = runner.invoke(app, ["--root", str(sample_repo), "--json", "index"])
    assert r1.exit_code == 0, r1.output
    payload = json.loads(r1.output)
    assert payload["indexed"] >= 4
    assert payload["deleted"] == 0

    r2 = runner.invoke(app, ["--root", str(sample_repo), "--json", "stats"])
    assert r2.exit_code == 0, r2.output
    stats = json.loads(r2.output)
    assert stats["files"] == payload["indexed"]
    assert stats["built_at"] is not None


def test_index_excludes_secrets_end_to_end(sample_repo):
    r = runner.invoke(app, ["--root", str(sample_repo), "--json", "index"])
    assert r.exit_code == 0
    from codebase_index.config import find_root
    from codebase_index.storage import repo
    from codebase_index.storage.db import Database

    db_path = find_root(sample_repo) / ".claude" / "cache" / "codebase-index" / "index.sqlite"
    with Database(db_path) as db:
        paths = repo.all_paths(db.conn)
    assert ".env" not in paths and "secrets.pem" not in paths