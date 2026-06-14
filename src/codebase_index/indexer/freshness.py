"""Compute index freshness for the `index` block of every response.

Contract (consumed by SKILL.md step 2):
  exists -> a build has happened (meta.built_at present).
  stale  -> the working tree differs from what was indexed.
  files_changed_since_build -> how many indexable files differ.

Strategy:
  * Git fast-path: if the repo is a clean git tree AT the indexed commit, nothing
    changed -> not stale (cheap; no walk).
  * Accurate fallback (dirty tree, different commit, or no git): walk the current
    indexable set and diff (path, mtime_ns) against the `files` table. This reuses
    the discovery gates, so ignored/secret/binary files never count as changes.
"""

from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path

from ..config import Config
from ..discovery.walker import walk
from ..models import IndexFreshness
from ..storage import repo


def compute_freshness(conn, root: Path, config: Config) -> IndexFreshness:
    built_at = repo.get_meta(conn, "built_at")
    if built_at is None:
        return IndexFreshness(exists=False, stale=False)

    head = repo.get_meta(conn, "head_commit")
    root = Path(root)

    if _git_clean_at(root, head):
        changed = 0
    else:
        changed = _changed_count(conn, root, config)

    return IndexFreshness(
        exists=True,
        stale=changed > 0,
        files_changed_since_build=changed,
        built_at=built_at,
        head_commit=head,
    )


def _changed_count(conn, root: Path, config: Config) -> int:
    """Added + removed + content-modified indexable files vs. the index.

    Mirrors the incremental update's decision (indexer/pipeline.py): a file is
    unchanged when (mtime, size) match, and even when they differ it is only
    counted as changed if its sha256 differs. A bare `touch` that rewrites mtime
    without changing bytes is a no-op for update_index, so it must not register as
    stale here either.
    """
    indexed = repo.fingerprints(conn)  # path -> (mtime_ns, size_bytes, sha256)
    seen: set[str] = set()
    changed = 0
    for cand in walk(root, config):
        try:
            st = cand.path.stat()
        except OSError:
            continue
        seen.add(cand.rel_path)
        prior = indexed.get(cand.rel_path)
        if prior is None:
            changed += 1
            continue
        if prior[0] == st.st_mtime_ns and prior[1] == cand.size_bytes:
            continue
        try:
            if prior[2] == _sha256_file(cand.path):
                continue
        except OSError:
            pass
        changed += 1
    changed += sum(1 for path in indexed if path not in seen)
    return changed


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def _git_clean_at(root: Path, indexed_head: "str | None") -> bool:
    """True iff git is available, HEAD == indexed_head, and the tree has no changes."""
    if indexed_head is None or not (root / ".git").exists():
        return False
    try:
        head = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        if head.returncode != 0 or head.stdout.strip() != indexed_head:
            return False
        status = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return status.returncode == 0 and status.stdout.strip() == ""
