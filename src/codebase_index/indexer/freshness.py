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
    """Added + removed + mtime-modified indexable files vs. the index."""
    current: dict[str, int] = {}
    for cand in walk(root, config):
        try:
            current[cand.rel_path] = cand.path.stat().st_mtime_ns
        except OSError:
            continue
    indexed = repo.path_mtimes(conn)

    changed = 0
    for path, mtime in current.items():
        if path not in indexed or indexed[path] != mtime:
            changed += 1
    for path in indexed:
        if path not in current:
            changed += 1
    return changed


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
