from __future__ import annotations

from pathlib import Path

from codebase_index.config import Config
from codebase_index.indexer.pipeline import build_index, update_index
from codebase_index.storage import repo
from codebase_index.storage.db import Database


def _cfg(root: Path) -> Config:
    cfg = Config()
    cfg.root = str(root)
    return cfg


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")
    (root / "src" / "b.py").write_text("def beta():\n    return 2\n", encoding="utf-8")
    return root


def test_update_skips_unchanged_files(tmp_path):
    root = _repo(tmp_path)
    cfg = _cfg(root)
    db = Database(tmp_path / "index.sqlite").open()
    build_index(cfg, db, root=root)

    stats = update_index(cfg, db, root=root)
    assert stats.indexed == 0
    assert stats.skipped == 2
    assert stats.deleted == 0
    db.close()


def test_update_reindexes_edited_file(tmp_path):
    root = _repo(tmp_path)
    cfg = _cfg(root)
    db = Database(tmp_path / "index.sqlite").open()
    build_index(cfg, db, root=root)
    before = repo.fingerprints(db.conn)["src/a.py"][2]

    (root / "src" / "a.py").write_text("def alpha():\n    return 999\n", encoding="utf-8")
    stats = update_index(cfg, db, root=root)

    assert stats.indexed == 1
    assert stats.skipped == 1
    after = repo.fingerprints(db.conn)["src/a.py"][2]
    assert after != before
    db.close()


def test_update_prunes_deleted_file(tmp_path):
    root = _repo(tmp_path)
    cfg = _cfg(root)
    db = Database(tmp_path / "index.sqlite").open()
    build_index(cfg, db, root=root)

    (root / "src" / "b.py").unlink()
    stats = update_index(cfg, db, root=root)

    assert stats.deleted == 1
    assert "src/b.py" not in repo.all_paths(db.conn)
    db.close()


def test_update_all_rehashes_even_when_mtime_matches(tmp_path):
    root = _repo(tmp_path)
    cfg = _cfg(root)
    db = Database(tmp_path / "index.sqlite").open()
    build_index(cfg, db, root=root)

    p = root / "src" / "a.py"
    stat = p.stat()
    p.write_text("def alpha():\n    return 7\n", encoding="utf-8")
    import os
    os.utime(p, ns=(stat.st_atime_ns, stat.st_mtime_ns))

    skipped = update_index(cfg, db, root=root)
    assert skipped.indexed == 0
    forced = update_index(cfg, db, root=root, all_files=True)
    assert forced.indexed == 1
    db.close()
