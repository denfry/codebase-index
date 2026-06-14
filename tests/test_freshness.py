from __future__ import annotations

from codebase_index.config import Config
from codebase_index.indexer.freshness import compute_freshness
from codebase_index.indexer.pipeline import build_index
from codebase_index.storage.db import Database


def _indexed(sample_repo, tmp_path):
    cfg = Config()
    cfg.root = str(sample_repo)
    db = Database(tmp_path / "index.sqlite").open()
    build_index(cfg, db, root=sample_repo)
    return cfg, db


def test_missing_index_is_not_fresh(tmp_path):
    db = Database(tmp_path / "index.sqlite").open()
    fr = compute_freshness(db.conn, tmp_path, Config())
    assert fr.exists is False and fr.stale is False
    db.close()


def test_freshly_built_index_is_not_stale(sample_repo, tmp_path):
    cfg, db = _indexed(sample_repo, tmp_path)
    fr = compute_freshness(db.conn, sample_repo, cfg)
    assert fr.exists is True
    assert fr.stale is False
    assert fr.files_changed_since_build == 0
    db.close()


def test_edited_file_content_makes_index_stale(sample_repo, tmp_path):
    """A file whose indexed content (sha256) no longer matches disk is stale."""
    cfg, db = _indexed(sample_repo, tmp_path)

    from codebase_index.storage import repo
    indexed = repo.fingerprints(db.conn)
    a_path = next(iter(indexed))
    repo.set_meta(db.conn, "head_commit", "deadbeef")  # force the accurate (non-git) path
    # Corrupt the stored fingerprint so the on-disk content hashes differently;
    # mtime is bumped so the (mtime,size) fast-equal check can't short-circuit.
    db.conn.execute(
        "UPDATE files SET mtime_ns = 1, sha256 = 'stale-sha' WHERE path = ?", (a_path,)
    )
    db.conn.commit()

    fr = compute_freshness(db.conn, sample_repo, cfg)
    assert fr.stale is True
    assert fr.files_changed_since_build >= 1
    db.close()


def test_touch_without_content_change_is_not_stale(sample_repo, tmp_path):
    """A bare mtime bump with unchanged bytes is a no-op for update_index, so
    freshness must not flag it as stale (it mirrors the sha-based decision)."""
    cfg, db = _indexed(sample_repo, tmp_path)

    from codebase_index.storage import repo
    indexed = repo.fingerprints(db.conn)
    a_path = next(iter(indexed))
    repo.set_meta(db.conn, "head_commit", "deadbeef")  # force the accurate (non-git) path
    db.conn.execute("UPDATE files SET mtime_ns = 1 WHERE path = ?", (a_path,))
    db.conn.commit()

    fr = compute_freshness(db.conn, sample_repo, cfg)
    assert fr.stale is False
    assert fr.files_changed_since_build == 0
    db.close()
