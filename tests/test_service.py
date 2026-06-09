from __future__ import annotations

from pathlib import Path

from codebase_index import service
from codebase_index.config import Config


def _cfg(tmp_path: Path) -> Config:
    cfg = Config()
    cfg.root = str(tmp_path)
    return cfg


def test_db_path_follows_cache_dir(tmp_path):
    cfg = _cfg(tmp_path)
    assert service.cache_dir_for(cfg) == tmp_path / ".claude" / "cache" / "codebase-index"
    assert service.db_path_for(cfg) == service.cache_dir_for(cfg) / "index.sqlite"


def test_db_path_env_override(tmp_path, monkeypatch):
    custom = tmp_path / "custom.sqlite"
    monkeypatch.setenv("CBX_DB_PATH", str(custom))
    assert service.db_path_for(_cfg(tmp_path)) == custom


def test_resolve_db_loads_config_from_root(tmp_path, monkeypatch):
    monkeypatch.delenv("CBX_DB_PATH", raising=False)
    (tmp_path / ".git").mkdir()
    db_path, cfg = service.resolve_db(tmp_path)
    assert Path(cfg.root) == tmp_path
    assert db_path == tmp_path / ".claude" / "cache" / "codebase-index" / "index.sqlite"


def test_normalize_explain_query():
    assert service.normalize_explain_query("auth tokens") == "how does auth tokens work"
    # Queries that already carry an explain hint pass through unchanged.
    for q in ("how does auth work", "architecture overview", "How is X structured"):
        assert service.normalize_explain_query(q) == q
