#!/usr/bin/env python3
"""Fail when the version is not the same everywhere it is recorded.

    python scripts/check_versions.py

Canonical: src/codebase_index/__init__.py::__version__ (hatch dynamic version).
Mirrors that must agree:
  .claude-plugin/plugin.json               "version"
  requirements.lock                        refs/tags/v<version>.tar.gz
  .claude|.codex|.opencode/skills/codebase-index/.skill_version
  CHANGELOG.md                             a `## [<version>]` heading, OR the
                                           version is newer than every released
                                           heading and `## [Unreleased]` exists
                                           (main between releases).
Stdlib only; runs in CI lint and before the release build.
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

VERSION_RE = re.compile(r'^__version__ = "([^"]+)"$', re.M)
LOCK_TAG_RE = re.compile(r"refs/tags/v([0-9][^/]*?)\.tar\.gz")
HEADING_RE = re.compile(r"^## \[([^\]]+)\]", re.M)
STAMPS = (
    Path(".claude/skills/codebase-index/.skill_version"),
    Path(".codex/skills/codebase-index/.skill_version"),
    Path(".opencode/skills/codebase-index/.skill_version"),
)


def _vtuple(version: str) -> tuple[int, ...]:
    return tuple(int(p) for p in re.findall(r"\d+", version))


def check(repo: Path = REPO) -> list[str]:
    """Return a list of mismatch descriptions; empty means consistent."""
    problems: list[str] = []
    init = (repo / "src/codebase_index/__init__.py").read_text(encoding="utf-8")
    match = VERSION_RE.search(init)
    if not match:
        return ["src/codebase_index/__init__.py: no __version__"]
    version = match.group(1)

    plugin = json.loads((repo / ".claude-plugin/plugin.json").read_text(encoding="utf-8"))
    if plugin.get("version") != version:
        problems.append(f".claude-plugin/plugin.json: {plugin.get('version')!r} != {version!r}")

    lock = (repo / "requirements.lock").read_text(encoding="utf-8")
    tag = LOCK_TAG_RE.search(lock)
    if not tag:
        problems.append("requirements.lock: no refs/tags/vX.Y.Z.tar.gz pin found")
    elif tag.group(1) != version:
        problems.append(f"requirements.lock: tag v{tag.group(1)} != v{version}")

    for rel in STAMPS:
        path = repo / rel
        if not path.is_file():
            problems.append(f"{rel.as_posix()}: missing")
            continue
        stamp = path.read_text(encoding="utf-8").strip()
        if stamp != version:
            problems.append(f"{rel.as_posix()}: {stamp!r} != {version!r}")

    changelog = (repo / "CHANGELOG.md").read_text(encoding="utf-8")
    headings = HEADING_RE.findall(changelog)
    released = [h for h in headings if h.lower() != "unreleased"]
    if version in released:
        pass
    elif "Unreleased" in headings and all(_vtuple(version) > _vtuple(h) for h in released):
        pass  # main between releases: version bumped ahead, notes still under Unreleased
    else:
        problems.append(
            f"CHANGELOG.md: no '## [{version}]' heading and version is not newer than "
            f"the latest released heading ({released[0] if released else 'none'})"
        )
    return problems


def main() -> int:
    problems = check()
    if problems:
        print("version mismatch:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 1
    version = VERSION_RE.search(
        (REPO / "src/codebase_index/__init__.py").read_text(encoding="utf-8")
    ).group(1)  # type: ignore[union-attr]
    print(f"versions consistent: {version} (package, plugin.json, requirements.lock, "
          f"{len(STAMPS)} skill stamps, CHANGELOG)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
