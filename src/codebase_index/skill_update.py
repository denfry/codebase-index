"""Skill auto-update and rollback helpers.

Auto-update flow:
  1. On any CLI invocation, compare the installed skill's .skill_version stamp
     against the running package version.
  2. If they differ, re-materialize the skill template silently and stamp the new
     version.  A backup is saved first so the user can roll back.

Manual commands exposed via cli.py:
  codebase-index skill-update   -- force refresh all/one installed targets
  codebase-index skill-rollback -- restore the last backup
"""

from __future__ import annotations

import shutil
import sys
from pathlib import Path

VERSION_FILE = ".skill_version"
_CACHE_BACKUP_REL = ".claude/cache/codebase-index/skill-backups"


# ---------------------------------------------------------------------------
# version helpers
# ---------------------------------------------------------------------------

def _package_version() -> str:
    try:
        from importlib.metadata import version
        return version("codebase-index")
    except Exception:
        return "unknown"


def _installed_version(skill_dir: Path) -> str:
    vf = skill_dir / VERSION_FILE
    return vf.read_text(encoding="utf-8").strip() if vf.exists() else ""


def _write_version(skill_dir: Path, ver: str) -> None:
    (skill_dir / VERSION_FILE).write_text(ver + "\n", encoding="utf-8")


def needs_update(skill_dir: Path) -> bool:
    """True when the installed skill stamp differs from the running package version."""
    return _installed_version(skill_dir) != _package_version()


# ---------------------------------------------------------------------------
# backup helpers
# ---------------------------------------------------------------------------

def _backup_dir(root: Path, target: str) -> Path:
    """Backup lives in the cache, not next to the skill (avoids polluting skill namespaces)."""
    return root / _CACHE_BACKUP_REL / target


def _make_backup(root: Path, skill_dir: Path, target: str) -> bool:
    """Copy skill_dir to the cache backup location.  Returns True if a backup was written."""
    if not skill_dir.exists():
        return False
    bak = _backup_dir(root, target)
    if bak.exists():
        shutil.rmtree(bak)
    bak.parent.mkdir(parents=True, exist_ok=True)
    shutil.copytree(skill_dir, bak)
    return True


# ---------------------------------------------------------------------------
# public API
# ---------------------------------------------------------------------------

def update_skill(root: Path, target: str, *, backup: bool = True) -> dict:
    """Re-materialize the bundled skill template for *target*.

    Returns a result dict:
      - updated (bool)
      - backed_up (bool)
      - target (str)
      - old_version (str)
      - new_version (str)
    """
    from . import scaffold

    skill_dir = root / scaffold.skill_rel_for_target(target)
    pkg_ver = _package_version()
    old_ver = _installed_version(skill_dir)

    backed_up = _make_backup(root, skill_dir, target) if backup else False

    scaffold.materialize_skill(root, force=True, target=target)
    _write_version(skill_dir, pkg_ver)

    return {
        "target": target,
        "old_version": old_ver,
        "new_version": pkg_ver,
        "backed_up": backed_up,
        "updated": True,
    }


def rollback_skill(root: Path, target: str) -> dict:
    """Restore the backed-up skill for *target*.

    Returns a result dict:
      - target (str)
      - rolled_back (bool)
      - reason (str, only when rolled_back=False)
    """
    from . import scaffold

    skill_dir = root / scaffold.skill_rel_for_target(target)
    bak = _backup_dir(root, target)

    if not bak.exists():
        return {"target": target, "rolled_back": False, "reason": "no backup found"}

    if skill_dir.exists():
        shutil.rmtree(skill_dir)
    shutil.copytree(bak, skill_dir)
    return {"target": target, "rolled_back": True}


def auto_update_if_needed(root: Path, target: str) -> bool:
    """Silently update *target* skill if the installed version is outdated.

    Returns True when an update was applied.  Never raises — failures are swallowed
    because a broken auto-update must never crash the user's real command.
    """
    try:
        from . import scaffold

        skill_dir = root / scaffold.skill_rel_for_target(target)
        if not skill_dir.exists():
            return False
        if not needs_update(skill_dir):
            return False

        update_skill(root, target, backup=True)
        return True
    except Exception as exc:
        print(
            f"[codebase-index] skill auto-update for '{target}' failed "
            f"({type(exc).__name__}: {exc}); run `codebase-index skill-update`.",
            file=sys.stderr,
        )
        return False
