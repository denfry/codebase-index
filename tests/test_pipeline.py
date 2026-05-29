from __future__ import annotations

from codebase_index.config import Config
from codebase_index.indexer.pipeline import build_index
from codebase_index.storage import repo
from codebase_index.storage.db import Database


def _index(sample_repo, tmp_path):
    cfg = Config()
    cfg.root = str(sample_repo)
    db = Database(tmp_path / "index.sqlite").open()
    stats = build_index(cfg, db, root=sample_repo)
    return cfg, db, stats


def test_build_populates_files_and_excludes_unsafe(sample_repo, tmp_path):
    cfg, db, stats = _index(sample_repo, tmp_path)
    paths = repo.all_paths(db.conn)

    assert "src/auth/token.py" in paths
    assert ".env" not in paths and "logo.png" not in paths and "huge.json" not in paths
    assert not any(p.startswith("node_modules/") for p in paths)

    assert stats.indexed == repo.count_files(db.conn)
    assert stats.indexed >= 4
    assert repo.get_meta(db.conn, "built_at") is not None
    assert repo.get_meta(db.conn, "config_hash") == cfg.config_hash()
    db.close()


def test_rebuild_prunes_deleted_files(sample_repo, tmp_path):
    cfg, db, _ = _index(sample_repo, tmp_path)
    repo.upsert_file(
        db.conn,
        path="ghost/old.py",
        lang="python",
        size_bytes=1,
        sha256="z",
        mtime_ns=1,
        git_status=None,
        parser="line",
        indexed_at="t",
        is_generated=False,
    )
    assert "ghost/old.py" in repo.all_paths(db.conn)
    stats = build_index(cfg, db, root=sample_repo)
    assert "ghost/old.py" not in repo.all_paths(db.conn)
    assert stats.deleted >= 1
    db.close()


def test_file_row_has_hash_and_parser(sample_repo, tmp_path):
    _, db, _ = _index(sample_repo, tmp_path)
    row = repo.get_file(db.conn, "src/auth/token.py")
    assert row["parser"] == "treesitter"
    assert len(row["sha256"]) == 64
    db.close()


def test_build_populates_chunks_and_fts(sample_repo, tmp_path):
    cfg = Config()
    cfg.root = str(sample_repo)
    db = Database(tmp_path / "index.sqlite").open()
    stats = build_index(cfg, db, root=sample_repo)

    assert stats.chunks > 0
    assert repo.count_chunks(db.conn) == stats.chunks

    rows = repo.fts_search(db.conn, "refresh_access_token", limit=10)
    assert any(r["path"] == "src/auth/token.py" for r in rows)
    db.close()


def test_reindex_replaces_chunks_not_duplicates(sample_repo, tmp_path):
    cfg = Config()
    cfg.root = str(sample_repo)
    db = Database(tmp_path / "index.sqlite").open()
    s1 = build_index(cfg, db, root=sample_repo)
    s2 = build_index(cfg, db, root=sample_repo)
    assert s1.chunks == s2.chunks
    db.close()


def test_build_populates_symbols_and_edges(sample_repo, tmp_path):
    cfg = Config()
    cfg.root = str(sample_repo)
    db = Database(tmp_path / "index.sqlite").open()
    stats = build_index(cfg, db, root=sample_repo)

    assert stats.symbols > 0
    assert repo.count_symbols(db.conn) == stats.symbols
    defs = repo.symbols_by_name(db.conn, "refresh_access_token")
    assert any(r["kind"] == "function" and r["path"] == "src/auth/token.py" for r in defs)
    sites = repo.refs_for_name(db.conn, "refresh_access_token")
    assert any(s["path"] == "src/auth/token.py" and s["resolved"] == 1 for s in sites)
    db.close()


def test_symbol_body_chunks_linked(sample_repo, tmp_path):
    cfg = Config()
    cfg.root = str(sample_repo)
    db = Database(tmp_path / "index.sqlite").open()
    build_index(cfg, db, root=sample_repo)
    linked = db.conn.execute(
        "SELECT COUNT(*) FROM chunks WHERE symbol_id IS NOT NULL"
    ).fetchone()[0]
    assert linked > 0
    db.close()


def test_reindex_symbols_idempotent(sample_repo, tmp_path):
    cfg = Config()
    cfg.root = str(sample_repo)
    db = Database(tmp_path / "index.sqlite").open()
    s1 = build_index(cfg, db, root=sample_repo)
    s2 = build_index(cfg, db, root=sample_repo)
    assert s1.symbols == s2.symbols and s1.chunks == s2.chunks
    db.close()
