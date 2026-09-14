#!/usr/bin/env python3
"""Build one persistent index per corpus, shared by every experiment.

Rebuilding per variant would make ablation deltas measure indexing variance
instead of retrieval, and re-indexing 2k-file Java repos for each of a dozen
configurations is the difference between a benchmark that runs and one that does
not. The exclude list is taken verbatim from the shipped eval harness so the
research runs grade themselves on exactly the corpus the product's own benchmark
uses.
"""

from __future__ import annotations

import argparse
import time
from pathlib import Path

from codebase_index.config import Config
from codebase_index.indexer.pipeline import build_index
from codebase_index.storage.db import Database

from tests.eval.harness import CORPUS_EXCLUDES

INDEX_DIR = Path(__file__).parent / "data" / "index"


def build(name: str, root: Path, *, force: bool = False) -> tuple[int, float]:
    INDEX_DIR.mkdir(parents=True, exist_ok=True)
    db_path = INDEX_DIR / f"{name}.sqlite"
    if db_path.exists() and not force:
        db = Database(db_path).open()
        n = db.conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        db.close()
        return n, 0.0
    for suffix in ("", "-wal", "-shm"):
        p = Path(str(db_path) + suffix)
        if p.exists():
            p.unlink()
    cfg = Config()
    cfg.root = str(root)
    cfg.embeddings.enabled = False
    cfg.extra_ignore = [*cfg.extra_ignore, *CORPUS_EXCLUDES]
    start = time.perf_counter()
    db = Database(db_path).open()
    build_index(cfg, db, root=root)
    elapsed = time.perf_counter() - start
    n = db.conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
    sym = db.conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
    edg = db.conn.execute("SELECT COUNT(*) FROM edges WHERE resolved = 1").fetchone()[0]
    db.close()
    print(f"  {name}: {n} files, {sym} symbols, {edg} resolved edges, {elapsed:.1f}s")
    return n, elapsed


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", action="append", required=True, help="name:repo_path")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    for spec in args.corpus:
        name, root = spec.split(":", 1)
        print(f"[{name}] indexing {root}")
        build(name, Path(root).resolve(), force=args.force)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
