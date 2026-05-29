"""Materialize the bundled skill template into a project's `.claude/` tree.

Pure filesystem helpers used by the `init` CLI command. The template is read from
the wheel via importlib.resources, so it works in editable and zip installs alike.
"""

from __future__ import annotations

import json
import stat
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path

from .config import Config

SKILL_REL = Path(".claude") / "skills" / "codebase-index"
CACHE_REL = Path(".claude") / "cache" / "codebase-index"
_CACHE_IGNORE_LINE = ".claude/cache/codebase-index/"
_GITIGNORE_BLOCK = (
    "\n# codebase-index cache (machine-local; do not commit)\n"
    f"{_CACHE_IGNORE_LINE}\n"
)


def _template_root() -> Traversable:
    return resources.files("codebase_index") / "skill_template"


def _iter_template(node: Traversable, prefix: str = "") -> "list[tuple[str, Traversable]]":
    """Depth-first list of (relative-posix-path, file) under a template dir."""
    out: list[tuple[str, Traversable]] = []
    for child in node.iterdir():
        rel = f"{prefix}{child.name}"
        if child.is_dir():
            out.extend(_iter_template(child, prefix=f"{rel}/"))
        else:
            out.append((rel, child))
    return out


def materialize_skill(root: Path, *, force: bool) -> list[Path]:
    """Copy the whole skill template to `<root>/.claude/skills/codebase-index/`."""
    dest = root / SKILL_REL
    if dest.exists() and not force:
        raise FileExistsError(dest)

    written: list[Path] = []
    for rel, node in _iter_template(_template_root()):
        target = dest / Path(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(node.read_bytes())
        if rel == "scripts/cbx":
            target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        written.append(target)
    return written


def write_config(root: Path, *, force: bool) -> Path:
    """Write resolved defaults to `<root>/.claude/cache/codebase-index/config.json`."""
    path = root / CACHE_REL / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not force:
        return path
    cfg = Config()
    path.write_text(cfg.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path


def merge_gitignore(root: Path) -> bool:
    """Append the cache-ignore block to `<root>/.gitignore` if absent. Returns True if changed."""
    path = root / ".gitignore"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if _CACHE_IGNORE_LINE in existing:
        return False
    sep = "" if existing.endswith("\n") or existing == "" else "\n"
    path.write_text(existing + sep + _GITIGNORE_BLOCK, encoding="utf-8")
    return True


def write_hooks_example(root: Path) -> Path:
    """Copy the hooks example next to the installed skill (for manual `--with-hooks` review)."""
    src = _template_root() / "examples" / "hooks" / "settings.json"
    path = root / SKILL_REL / "examples" / "hooks" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(src.read_bytes())
    return path


SETTINGS_REL = Path(".claude") / "settings.json"
_HOOK_MARKER = "codebase-index update"


def _template_hook_entries() -> "list[dict]":
    src = _template_root() / "examples" / "hooks" / "settings.json"
    data = json.loads(src.read_text(encoding="utf-8"))
    return data["hooks"]["PostToolUse"]


def _has_our_hook(settings: dict) -> bool:
    for entry in settings.get("hooks", {}).get("PostToolUse", []):
        for hk in entry.get("hooks", []):
            if _HOOK_MARKER in hk.get("command", ""):
                return True
    return False


def merge_hook_settings(root: Path) -> bool:
    path = root / SETTINGS_REL
    settings: dict = {}
    if path.exists():
        settings = json.loads(path.read_text(encoding="utf-8"))
    if _has_our_hook(settings):
        return False

    hooks = settings.setdefault("hooks", {})
    post = hooks.setdefault("PostToolUse", [])
    post.extend(_template_hook_entries())

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    return True


def enabled_hooks(root: Path) -> list[str]:
    path = root / SETTINGS_REL
    if not path.exists():
        return []
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [
        hk.get("command", "")
        for entry in settings.get("hooks", {}).get("PostToolUse", [])
        for hk in entry.get("hooks", [])
        if _HOOK_MARKER in hk.get("command", "")
    ]
