"""Materialize the bundled skill template into project CLI trees.

Pure filesystem helpers used by the `init` CLI command. The template is read from
the wheel via importlib.resources, so it works in editable and zip installs alike.
"""

from __future__ import annotations

import json
import shutil
import stat
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path

from .config import Config

CLI_TARGETS = ("claude", "codex", "opencode")

CLAUDE_SKILL_REL = Path(".claude") / "skills" / "codebase-index"
CODEX_SKILL_REL = Path(".codex") / "skills" / "codebase-index"
OPENCODE_SKILL_REL = Path(".opencode") / "skills" / "codebase-index"
OPENCODE_COMMAND_REL = Path(".opencode") / "commands" / "codebase-index.md"
OPENCODE_AGENT_REL = Path(".opencode") / "agents" / "codebase-index.md"

SKILL_REL = CLAUDE_SKILL_REL
CACHE_REL = Path(".claude") / "cache" / "codebase-index"
_CACHE_IGNORE_LINE = ".claude/cache/codebase-index/"
_GITIGNORE_BLOCK = (
    "\n# codebase-index cache (machine-local; do not commit)\n"
    f"{_CACHE_IGNORE_LINE}\n"
)
_MANAGED_START = "<!-- >>> codebase-index managed >>> -->"
_MANAGED_END = "<!-- <<< codebase-index managed <<< -->"


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


def skill_rel_for_target(target: str) -> Path:
    if target == "claude":
        return CLAUDE_SKILL_REL
    if target == "codex":
        return CODEX_SKILL_REL
    if target == "opencode":
        return OPENCODE_SKILL_REL
    raise ValueError(f"unknown CLI target: {target}")


def detect_cli_targets(root: Path) -> list[str]:
    """Detect usable local CLI targets for a project install."""
    home = Path.home()
    checks = (
        ("claude", "claude", root / ".claude", home / ".claude"),
        ("codex", "codex", root / ".codex", home / ".codex"),
        ("opencode", "opencode", root / ".opencode", home / ".config" / "opencode"),
    )
    return [
        target
        for target, command, project_marker, home_marker in checks
        if project_marker.exists() or shutil.which(command) or home_marker.exists()
    ]


def materialize_skill(root: Path, *, force: bool, target: str = "claude") -> list[Path]:
    """Copy the whole skill template to the target's project resource directory."""
    dest = root / skill_rel_for_target(target)
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


def _managed_block(content: str) -> str:
    return f"{_MANAGED_START}\n{content.rstrip()}\n{_MANAGED_END}\n"


def _upsert_managed_block(path: Path, content: str) -> Path:
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    block = _managed_block(content)
    if _MANAGED_START in existing and _MANAGED_END in existing:
        before, rest = existing.split(_MANAGED_START, 1)
        _, after = rest.split(_MANAGED_END, 1)
        new_text = before.rstrip() + "\n\n" + block + after.lstrip()
    else:
        sep = "" if existing in ("", "\n") else "\n\n"
        new_text = existing.rstrip() + sep + block
    path.write_text(new_text, encoding="utf-8")
    return path


def write_codex_agents(root: Path) -> Path:
    rel = CODEX_SKILL_REL / "SKILL.md"
    content = f"""# codebase-index

Use the local codebase index before scanning repository files.

Skill resources: `{rel.as_posix()}`

Run `codebase-index search "<query>" --json` for general questions, or use
`symbol`, `refs`, and `impact` for symbol lookup, references, and change impact.
If the index is missing, run `codebase-index index` first.
"""
    return _upsert_managed_block(root / "AGENTS.md", content)


def write_opencode_files(root: Path) -> list[Path]:
    command = root / OPENCODE_COMMAND_REL
    agent = root / OPENCODE_AGENT_REL
    command.parent.mkdir(parents=True, exist_ok=True)
    agent.parent.mkdir(parents=True, exist_ok=True)
    command.write_text(
        """---
description: Search this repository with codebase-index before reading files.
---

Run:

```bash
codebase-index search "$ARGUMENTS" --json
```

Use `symbol <name>`, `refs <name>`, or `impact <file|symbol>` when those match
the request. If the index is missing, run `codebase-index index` first.
""",
        encoding="utf-8",
    )
    src = _template_root() / "SKILL.md"
    agent.write_bytes(src.read_bytes())
    return [command, agent]


def install_target(root: Path, target: str, *, force: bool) -> list[Path]:
    written = materialize_skill(root, force=force, target=target)
    if target == "codex":
        written.append(write_codex_agents(root))
    elif target == "opencode":
        written.extend(write_opencode_files(root))
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
