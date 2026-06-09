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


def test_build_resolves_cross_file_edges_and_degrees(sample_repo, tmp_path):
    cfg = Config()
    cfg.root = str(sample_repo)
    db = Database(tmp_path / "index.sqlite").open()
    stats = build_index(cfg, db, root=sample_repo)

    assert stats.edges_resolved > 0
    assert repo.count_resolved_edges(db.conn) >= stats.edges_resolved

    target = repo.symbol_id_for_unique_name(db.conn, "refresh_access_token")
    assert target is not None
    inc = repo.incoming_edges(db.conn, "symbol", target)
    assert any(r["edge_type"] == "call" for r in inc)

    user_id = repo.symbol_id_for_unique_name(db.conn, "User")
    deg = db.conn.execute(
        "SELECT in_degree FROM symbols WHERE id = ?", (user_id,)
    ).fetchone()["in_degree"]
    assert deg >= 1

    user_file = repo.file_by_path(db.conn, "src/models/user.py")
    fimp = repo.incoming_edges(db.conn, "file", user_file["id"])
    assert any(r["edge_type"] == "import" for r in fimp)
    db.close()


def test_reindex_graph_idempotent(sample_repo, tmp_path):
    cfg = Config()
    cfg.root = str(sample_repo)
    db = Database(tmp_path / "index.sqlite").open()
    s1 = build_index(cfg, db, root=sample_repo)
    s2 = build_index(cfg, db, root=sample_repo)
    assert s1.edges == s2.edges and s1.edges_resolved == s2.edges_resolved
    db.close()


def test_parse_all_falls_back_sequentially_with_warning(tmp_path, monkeypatch, capsys):
    from codebase_index.discovery.walker import walk
    from codebase_index.indexer import pipeline

    (tmp_path / "a.py").write_text("def a(): ...\n", encoding="utf-8")
    (tmp_path / "b.py").write_text("def b(): ...\n", encoding="utf-8")
    cfg = Config()
    cfg.root = str(tmp_path)
    candidates = list(walk(tmp_path, cfg))
    assert candidates

    class BrokenPool:
        def __init__(self, *args, **kwargs):
            raise RuntimeError("no pool for you")

    monkeypatch.setattr(pipeline, "_MIN_PARALLEL_FILES", 1)
    monkeypatch.setattr(pipeline, "ProcessPoolExecutor", BrokenPool)

    results = pipeline._parse_all(candidates, cfg)
    assert len(results) == len(candidates)
    # The degradation must be visible, not silent.
    assert "falling back to sequential" in capsys.readouterr().err
