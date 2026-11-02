"""Claude Code hooks that make the index the default way to search code.

Two events, both no-ops outside a repository that has an index:

- ``session-start`` adds one short note to the session context: this repository
  is indexed, and which commands answer code questions.
- ``guard`` (PreToolUse on Grep, Bash and PowerShell) intercepts a code search the first time
  in a session, before any ``codebase-index`` command has run, and names the
  index command to use instead. It is a nudge, not a wall: searching for the
  same term again lets it through, the first ``codebase-index`` command in the
  session turns the guard off (even one that has yet to build the index), and
  searches over docs, logs or config, or inside heredoc and here-string bodies,
  are never intercepted.

Measured on a 5.9k-file monorepo, an agent spent 19% fewer tokens with the index
than with grep (tests/eval/results/2026-09-24-agent-pilot.md), but agents reach
for Grep out of habit. The guard runs on every shell call, so this module imports
only the standard library and does no index work beyond one small SQLite read.

Entry point: ``codebase-index-hook <event>`` reads the hook JSON on stdin and
prints the hook JSON reply (or nothing). ``CBX_GUARD=0`` disables the guard.
Per-session state lives in the system temp directory (``CBX_HOOK_STATE``
overrides it), so it exists before the repository has an index.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Optional

INDEX_REL = Path(".claude") / "cache" / "codebase-index" / "index.sqlite"
_STATE_DIR = "codebase-index-hooks"
_STATE_TTL_S = 2 * 24 * 3600
SHELL_TOOLS = ("Bash", "PowerShell")

# A shell segment that searches file contents: the first command of the segment
# (after `&&`, `||`, `;`, a newline or the start), so `ps aux | grep x` is not a
# repo search. Quoted arguments may hold `|`, as in grep "a\|b".
_SEARCH_CMD = re.compile(
    r"(?:^|&&|\|\||;|\n)[ \t]*(?:cd\s+\S+\s*&&\s*)?"
    r"(?P<cmd>git\s+grep|grep|egrep|fgrep|rg|ag|ack|findstr|Select-String)\b"
    r"""(?P<args>(?:"[^"\n]*"|'[^'\n]*'|[^|;&\n"'])*)""",
    re.IGNORECASE,
)
# A heredoc body is file content (a script being written, stdin for python), not
# commands; an unterminated one runs to the end of the command.
_HEREDOC = re.compile(
    r"""(?<!<)<<-?(?!<)[ \t]*(['"]?)([A-Za-z_][\w-]*)\1(?P<rest>[^\n]*)\n"""
    r".*?(?:^[ \t]*\2[ \t]*$|\Z)",
    re.DOTALL | re.MULTILINE,
)
# PowerShell's heredoc: the closing `'@` or `"@` starts its own line.
_HERE_STRING = re.compile(r"""@(['"])[ \t]*\r?\n.*?^\1@""", re.DOTALL | re.MULTILINE)
_INDEX_CMD = re.compile(r"(?:^|[\s;&|/\\\"'])(?:codebase-index|cbx)(?:\.exe|\.ps1)?\s+\w")
# Searches over prose, logs, config, binaries and git internals are what grep is for;
# leave them alone.
_NON_CODE = re.compile(
    r"\.(?:md|mdx|rst|txt|log|ya?ml|json|toml|ini|cfg|conf|csv|xml|properties|lock|env|html?"
    r"|exe|dll|so|jar|class|bin|sqlite|db)\b"
    r"|--include=\*?\.(?:md|txt|log|ya?ml|json|toml)"
    r"|(?:^|[\s'\"/\\])\.git[\\/]",
    re.IGNORECASE,
)
# Shell words of a search's arguments: a quoted string or a bare word.
_WORD = re.compile(r""""([^"]*)"|'([^']*)'|(\S+)""")
# An absolute path: a drive (C:\, C:/), an MSYS drive or POSIX root (/c/, /), or home.
_ABS_PATH = re.compile(r"^(?:[A-Za-z]:[\\/]|/|~(?:[\\/]|$)|\$HOME\b|\$\{HOME\})")
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
    if tool != "Grep" and tool not in SHELL_TOOLS:
        return None
    state = _State(str(payload.get("session_id") or "default"))

    if tool in SHELL_TOOLS:
        command = _HEREDOC.sub(lambda m: "<<" + m.group("rest"), str(tool_input.get("command") or ""))
        if tool == "PowerShell":
            command = _HERE_STRING.sub("''", command)
        if _INDEX_CMD.search(command):
            # Checked before the index exists: the first search is what builds it.
            state.mark_used()
            return None
        root = find_index_root(_cwd(payload))
        if root is None:
            return None
        pattern = _shell_search_pattern(command, root)
        if pattern is None:
            return None
    else:
        root = find_index_root(_cwd(payload))
        if root is None or _grep_targets_non_code(tool_input):
            return None
        target = str(tool_input.get("path") or "")
        if target and _outside_repo([target], root):
            return None
        pattern = str(tool_input.get("pattern") or "")

    if state.used:
        return None
    # Keyed by the search term, not the whole call: a retry rarely repeats the
    # command byte for byte (a new description, another pipe, a regenerated script).
    fingerprint = hashlib.sha1(_term(pattern).lower().encode("utf-8")).hexdigest()
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


def _shell_search_pattern(command: str, root: Path) -> Optional[str]:
    """The search term of a content search in `command`, or None if there is none."""
    for match in _SEARCH_CMD.finditer(command):
        args = match.group("args")
        if _NON_CODE.search(args):
            continue
        words = [next(g for g in m.groups() if g is not None) for m in _WORD.finditer(args)]
        if match.group("cmd").lower() == "select-string":
            pattern, paths = _select_string_terms(words)
        else:
            positional = [w for w in words if not w.startswith("-") and not w.isdigit()]
            # The first positional word is the pattern, the rest are the paths searched.
            paths = positional[1:]
            quoted = re.search(r"""(['"])(.+?)\1""", args)
            pattern = quoted.group(2) if quoted else (positional[0] if positional else "")
        if not _outside_repo(paths, root):
            return pattern
    return None


def _select_string_terms(words: list[str]) -> tuple[str, list[str]]:
    """The pattern and paths of a Select-String call, named or positional."""
    pattern: list[str] = []
    paths: list[str] = []
    positional: list[str] = []
    target = None
    for word in words:
        if target is not None:
            target.extend(word.split(",") if target is paths else [word])
            target = None
        elif word.lower() in ("-path", "-literalpath", "-lp"):
            target = paths
        elif word.lower() == "-pattern":
            target = pattern
        elif not word.startswith("-") and not word.isdigit():
            positional.append(word)
    if not pattern and positional:
        pattern.append(positional.pop(0))
    return (pattern[0] if pattern else ""), paths or positional


def _outside_repo(paths: list[str], root: Path) -> bool:
    """True when every path is absolute and none lies inside the indexed repository."""
    if not paths or not all(_ABS_PATH.match(p) for p in paths):
        return False
    base = os.path.normcase(os.path.abspath(root))
    for raw in paths:
        path = re.sub(r"^(?:~|\$HOME\b|\$\{HOME\})", lambda _m: str(Path.home()), raw)
        msys = re.match(r"^/([a-zA-Z])(/.*)?$", path)
        if os.name == "nt" and msys:
            path = f"{msys.group(1)}:{msys.group(2) or '/'}"
        full = os.path.normcase(os.path.abspath(path))
        if full == base or full.startswith(base.rstrip(os.sep) + os.sep):
            return False
    return True


def _grep_targets_non_code(tool_input: dict) -> bool:
    kind = str(tool_input.get("type") or "").lower()
    if kind in _NON_CODE_TYPES:
        return True
    target = f"{tool_input.get('glob') or ''} {tool_input.get('path') or ''}"
    return bool(_NON_CODE.search(target))


def _term(pattern: str) -> str:
    """A regex search pattern as plain query words."""
    return " ".join(re.sub(r"""[\\^$()\[\]{}|*+?"']""", " ", pattern).split())[:80]


def _reason(pattern: str) -> str:
    term = _term(pattern) or "<what you are looking for>"
    return (
        "codebase-index: this repository is indexed, and the index answers code "
        "searches with ranked, numbered lines in fewer tokens than grep. Run it first:\n"
        f'  codebase-index search "{term}" --compact     # where / how\n'
        '  codebase-index refs "Owner.member" --compact  # every call site, with callers\n'
        '  codebase-index symbol "Name"                 # a definition\n'
        "If the index does not answer, search for the same term again and it will run. "
        "Once any codebase-index command has run in this session, searches are not "
        "intercepted."
    )


class _State:
    """Per-session guard state: whether the index was used, which calls were nudged."""

    def __init__(self, session: str) -> None:
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", session)[:80] or "default"
        self.dir = Path(os.environ.get("CBX_HOOK_STATE") or Path(tempfile.gettempdir()) / _STATE_DIR)
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
