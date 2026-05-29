"""Layer built-in deny rules with root-level ignore files."""

from __future__ import annotations

from pathlib import Path

import pathspec

DEFAULT_IGNORE_FILES = [".gitignore", ".cursorignore", ".claudeignore", ".codeindexignore"]

BUILTIN_DENYLIST = [
    ".git/",
    ".hg/",
    ".svn/",
    ".claude/cache/codebase-index/",
    "node_modules/",
    "__pycache__/",
    ".pytest_cache/",
    ".mypy_cache/",
    ".ruff_cache/",
    ".venv/",
    "venv/",
    "build/",
    "dist/",
    "target/",
    ".next/",
]

BUILTIN_DENY_DIRS = {p.rstrip("/") for p in BUILTIN_DENYLIST if p.endswith("/")}


class IgnoreMatcher:
    """Gitignore-style matcher for root-level ignore files and built-in denylist."""

    def __init__(self, patterns: list[str]) -> None:
        self._spec = pathspec.PathSpec.from_lines("gitignore", patterns)

    @classmethod
    def from_root(
        cls,
        root: Path,
        *,
        ignore_files: list[str] | None = None,
        extra_ignore: list[str] | None = None,
    ) -> "IgnoreMatcher":
        patterns = list(BUILTIN_DENYLIST)
        for ignore_file in ignore_files or DEFAULT_IGNORE_FILES:
            path = root / ignore_file
            if path.is_file():
                patterns.extend(path.read_text(encoding="utf-8").splitlines())
        patterns.extend(extra_ignore or [])
        return cls(patterns)

    def is_ignored(self, rel_path: str) -> bool:
        return self._spec.match_file(rel_path.replace("\\", "/"))

    def is_ignored_dir(self, dirname: str) -> bool:
        return dirname in BUILTIN_DENY_DIRS
