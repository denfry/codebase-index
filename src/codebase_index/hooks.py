"""Claude Code hooks that make the index the default way to search code.

Two events, both no-ops outside a repository that has an index:

- ``session-start`` adds one short note to the session context: this repository
  is indexed, and which commands answer code questions.
- ``guard`` (PreToolUse on Grep and Bash) intercepts a code search the first time
  in a session, before any ``codebase-index`` command has run, and names the
  index command to use instead. It is a nudge, not a wall: repeating the same
  call lets it through, the first ``codebase-index`` command in the session turns
  the guard off, and searches over docs, logs or config are never intercepted.

Measured on a 5.9k-file monorepo, an agent spent 19% fewer tokens with the index
than with grep (tests/eval/results/2026-09-24-agent-pilot.md), but agents reach
for Grep out of habit. The guard runs on every Bash call, so this module imports
only the standard library and does no index work beyond one small SQLite read.

Entry point: ``codebase-index-hook <event>`` reads the hook JSON on stdin and
prints the hook JSON reply (or nothing). ``CBX_GUARD=0`` disables the guard.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import sys
import time
from pathlib import Path
from typing import Any, Optional

INDEX_REL = Path(".claude") / "cache" / "codebase-index" / "index.sqlite"
_STATE_DIR = "hook-sessions"
_STATE_TTL_S = 2 * 24 * 3600

# A shell segment that searches file contents: the first command of the segment
# (after `&&`, `||`, `;` or the start), so `ps aux | grep x` is not a repo search.
_SEARCH_CMD = re.compile(
    r"(?:^|&&|\|\||;)\s*(?:cd\s+\S+\s*&&\s*)?"
    r"(?P<cmd>git\s+grep|grep|egrep|fgrep|rg|ag|ack|findstr|Select-String)\b(?P<args>[^|;&]*)",
    re.IGNORECASE,
)
_INDEX_CMD = re.compile(r"(?:^|[\s;&|/\\\"'])(?:codebase-index|cbx)(?:\.exe|\.ps1)?\s+\w")
# Searches over prose, logs and config are what grep is for; leave them alone.
_NON_CODE = re.compile(
    r"\.(?:md|mdx|rst|txt|log|ya?ml|json|toml|ini|cfg|conf|csv|xml|properties|lock|env|html?)\b"
    r"|--include=\*?\.(?:md|txt|log|ya?ml|json|toml)",
    re.IGNORECASE,
)
_NON_CODE_TYPES = {"md", "markdown", "txt", "log", "yaml", "yml", "json", "toml", "xml",
                   "csv", "ini", "config"}


def main(argv: Optional[list[str]] = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    event = args[0] if args else ""
    try:
        payload = json.loads(sys.stdin.read() or "{}")
    except (ValueError, OSError):
        return 0
    try:
        reply = {"guard": guard, "session-start": session_start}.get(event, _none)(payload)
    except Exception:  # a hook must never break the session it runs in
        return 0
    if reply:
        sys.stdout.write(json.dumps(reply))
    return 0


def _none(_payload: dict) -> Optional[dict]:
    return None


def find_index_root(start: Path) -> Optional[Path]:
    """The nearest directory at or above `start` that holds an index."""
    for path in (start, *start.parents):
        if (path / INDEX_REL).is_file():
            return path
    return None


def _cwd(payload: dict) -> Path:
    raw = str(payload.get("cwd") or os.getcwd())
    # Git Bash hands out MSYS paths (/c/Projects/x); Python on Windows needs C:/.
    msys = re.match(r"^/([a-zA-Z])(/.*)?$", raw)
    if os.name == "nt" and msys:
        raw = f"{msys.group(1)}:{msys.group(2) or '/'}"
    return Path(raw)


# --- session-start ------------------------------------------------------------------


def session_start(payload: dict) -> Optional[dict]:
    root = find_index_root(_cwd(payload))
    if root is None:
        return None
    files = _indexed_files(root)
    size = f" ({files} files)" if files else ""
    note = (
        f"This repository has a codebase-index index{size}. For questions about the "
        "code (where something is, how it works, who calls it, what a change breaks) "
        "use the codebase-index skill before Grep or Read: "
        '`codebase-index search "<question>" --compact`, '
        '`codebase-index refs "Owner.member" --compact`, '
        '`codebase-index impact "Owner.member" --compact`. '
        "Output lines are numbered; cite them as file:line."
    )
    return {"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": note}}


def _indexed_files(root: Path) -> Optional[int]:
    try:
        conn = sqlite3.connect(f"file:{root / INDEX_REL}?mode=ro", uri=True, timeout=0.5)
        try:
            return int(conn.execute("SELECT COUNT(*) FROM files").fetchone()[0])
        finally:
            conn.close()
    except sqlite3.Error:
        return None


# --- guard ------------------------------------------------------------------------------


def guard(payload: dict) -> Optional[dict]:
    if os.environ.get("CBX_GUARD", "").strip() == "0":
        return None
    tool = payload.get("tool_name") or ""
    tool_input = payload.get("tool_input") or {}
    if tool not in ("Grep", "Bash"):
        return None
    root = find_index_root(_cwd(payload))
    if root is None:
        return None
    session = str(payload.get("session_id") or "default")
    state = _State(root, session)

    if tool == "Bash":
        command = str(tool_input.get("command") or "")
        if _INDEX_CMD.search(command):
            state.mark_used()
            return None
        pattern = _shell_search_pattern(command)
        if pattern is None:
            return None
    else:
        if _grep_targets_non_code(tool_input):
            return None
        pattern = str(tool_input.get("pattern") or "")

    if state.used:
        return None
    fingerprint = hashlib.sha1(
        (tool + json.dumps(tool_input, sort_keys=True, default=str)).encode("utf-8")
    ).hexdigest()
    if state.was_denied(fingerprint):
        return None  # the retry after a nudge: the agent decided grep is right
    state.deny(fingerprint)
    return {
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": _reason(pattern),
        }
    }


def _shell_search_pattern(command: str) -> Optional[str]:
    """The search term of a content search in `command`, or None if there is none."""
    for match in _SEARCH_CMD.finditer(command):
        args = match.group("args")
        if _NON_CODE.search(args):
            continue
        quoted = re.search(r"""(['"])(.+?)\1""", args)
        if quoted:
            return quoted.group(2)
        words = [w for w in args.split() if not w.startswith("-")]
        return words[0] if words else ""
    return None


def _grep_targets_non_code(tool_input: dict) -> bool:
    kind = str(tool_input.get("type") or "").lower()
    if kind in _NON_CODE_TYPES:
        return True
    target = f"{tool_input.get('glob') or ''} {tool_input.get('path') or ''}"
    return bool(_NON_CODE.search(target))


def _reason(pattern: str) -> str:
    term = re.sub(r"[\\^$()\[\]{}|*+?]", " ", pattern).strip() or "<what you are looking for>"
    term = " ".join(term.split())[:80]
    return (
        "codebase-index: this repository is indexed, and the index answers code "
        "searches with ranked, numbered lines in fewer tokens than grep. Run it first:\n"
        f'  codebase-index search "{term}" --compact     # where / how\n'
        '  codebase-index refs "Owner.member" --compact  # every call site, with callers\n'
        '  codebase-index symbol "Name"                 # a definition\n'
        "If the index does not answer, repeat this exact call and it will run. Once any "
        "codebase-index command has run in this session, searches are not intercepted."
    )


class _State:
    """Per-session guard state: whether the index was used, which calls were nudged."""

    def __init__(self, root: Path, session: str) -> None:
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session)[:80] or "default"
        self.dir = root / INDEX_REL.parent / _STATE_DIR
        self.path = self.dir / f"{safe}.json"
        self.data: dict[str, Any] = {"used": False, "denied": []}
        try:
            self.data.update(json.loads(self.path.read_text(encoding="utf-8")))
        except (OSError, ValueError):
            pass

    @property
    def used(self) -> bool:
        return bool(self.data.get("used"))

    def was_denied(self, fingerprint: str) -> bool:
        return fingerprint in self.data.get("denied", [])

    def mark_used(self) -> None:
        if not self.used:
            self.data["used"] = True
            self._save()

    def deny(self, fingerprint: str) -> None:
        self.data.setdefault("denied", []).append(fingerprint)
        self._save()

    def _save(self) -> None:
        try:
            self.dir.mkdir(parents=True, exist_ok=True)
            self.path.write_text(json.dumps(self.data), encoding="utf-8")
            _prune(self.dir)
        except OSError:
            pass


def _prune(directory: Path) -> None:
    cutoff = time.time() - _STATE_TTL_S
    for item in directory.glob("*.json"):
        try:
            if item.stat().st_mtime < cutoff:
                item.unlink()
        except OSError:
            pass


if __name__ == "__main__":
    raise SystemExit(main())
