"""Materialize the bundled skill template into project CLI trees.

Pure filesystem helpers used by the `init` CLI command. The template is read from
the wheel via importlib.resources, so it works in editable and zip installs alike.
"""

from __future__ import annotations

import json
import os
import shutil
import stat
import sys
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path
from typing import Optional

from .config import Config

CLI_TARGETS = ("claude", "codex", "opencode")

# MCP clients that receive a JSON config entry (no skill files needed).
MCP_TARGETS = ("cursor", "claude-desktop", "zed", "vscode", "windsurf")

ALL_TARGETS = CLI_TARGETS + MCP_TARGETS

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


def detect_mcp_targets(root: Path) -> list[str]:
    """Detect MCP-capable clients present on this machine or in this project."""
    home = Path.home()
    found: list[str] = []

    checks = [
        ("cursor",        [root / ".cursor",      home / ".cursor"]),
        ("windsurf",      [root / ".windsurf",     home / ".windsurf"]),
        ("vscode",        [root / ".vscode"]),
        ("zed",           [root / ".zed",          home / ".config" / "zed"]),
        ("claude-desktop",[_claude_desktop_config_path()]),
    ]
    exe_checks = {
        "cursor":    ["cursor"],
        "windsurf":  ["windsurf"],
        "vscode":    ["code", "code-insiders"],
        "zed":       ["zed"],
    }
    for target, markers in checks:
        if any(m is not None and m.exists() for m in markers):
            found.append(target)
            continue
        for exe in exe_checks.get(target, []):
            if shutil.which(exe):
                found.append(target)
                break
    return found


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


# ── MCP client config helpers ──────────────────────────────────────────────────────────────────

_MCP_SERVER_NAME = "codebase-index"
_MCP_ENTRY_STDIO = {"command": "codebase-index", "args": ["mcp"]}


def _claude_desktop_config_path() -> Optional[Path]:
    """Platform-specific path to Claude Desktop's config file."""
    if sys.platform == "win32":
        appdata = Path(os.environ.get("APPDATA", Path.home() / "AppData" / "Roaming"))
        return appdata / "Claude" / "claude_desktop_config.json"
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    return Path.home() / ".config" / "Claude" / "claude_desktop_config.json"


def _load_json_file(path: Path) -> dict:
    if path.exists():
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            return {}
    return {}


def _write_json_file(path: Path, data: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _merge_mcp_servers(path: Path, entry: dict, *, force: bool) -> bool:
    """Merge {"mcpServers": {"codebase-index": entry}} into a JSON config file.

    Returns True if the file was written (new or updated), False if already present.
    """
    data = _load_json_file(path)
    servers: dict = data.setdefault("mcpServers", {})
    if _MCP_SERVER_NAME in servers and not force:
        return False
    servers[_MCP_SERVER_NAME] = entry
    _write_json_file(path, data)
    return True


def _merge_vscode_mcp(path: Path, *, force: bool) -> bool:
    """VS Code uses {"servers": {"name": {"type": "stdio", ...}}} in .vscode/mcp.json."""
    data = _load_json_file(path)
    servers: dict = data.setdefault("servers", {})
    if _MCP_SERVER_NAME in servers and not force:
        return False
    servers[_MCP_SERVER_NAME] = {"type": "stdio", **_MCP_ENTRY_STDIO}
    _write_json_file(path, data)
    return True


def _merge_zed_settings(path: Path, *, force: bool) -> bool:
    """Zed uses context_servers with a nested command object in settings.json."""
    data = _load_json_file(path)
    ctx: dict = data.setdefault("context_servers", {})
    if _MCP_SERVER_NAME in ctx and not force:
        return False
    ctx[_MCP_SERVER_NAME] = {
        "command": {
            "path": "codebase-index",
            "args": ["mcp"],
        }
    }
    _write_json_file(path, data)
    return True


def install_mcp_target(root: Path, target: str, *, force: bool = False) -> tuple[Path, bool]:
    """Write or merge the MCP server entry for `target`.

    Returns (config_path, written) where written=False means it was already present.
    Raises ValueError for unknown targets.
    """
    home = Path.home()

    if target == "cursor":
        path = root / ".cursor" / "mcp.json"
        written = _merge_mcp_servers(path, _MCP_ENTRY_STDIO, force=force)
        return path, written

    if target == "windsurf":
        path = root / ".windsurf" / "mcp.json"
        written = _merge_mcp_servers(path, _MCP_ENTRY_STDIO, force=force)
        return path, written

    if target == "vscode":
        path = root / ".vscode" / "mcp.json"
        written = _merge_vscode_mcp(path, force=force)
        return path, written

    if target == "zed":
        # prefer project-local; Zed picks it up automatically
        path = root / ".zed" / "settings.json"
        written = _merge_zed_settings(path, force=force)
        return path, written

    if target == "claude-desktop":
        path = _claude_desktop_config_path()
        if path is None:
            raise RuntimeError("Cannot determine Claude Desktop config path on this platform.")
        written = _merge_mcp_servers(path, _MCP_ENTRY_STDIO, force=force)
        return path, written

    raise ValueError(f"unknown MCP target: {target!r}. Valid: {MCP_TARGETS}")


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
