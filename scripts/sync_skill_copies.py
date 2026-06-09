# scripts/sync_skill_copies.py
"""Keep every committed copy of the skill package in sync with the canonical
source: src/codebase_index/skill_template/ (the copy shipped in the wheel) and
the package version in src/codebase_index/__init__.py.

Derived copies maintained:
  .claude/skills/codebase-index/    installed copy, committed for this repo
  .codex/skills/codebase-index/     installed copy, committed for this repo
  .opencode/skills/codebase-index/  installed copy, committed for this repo
  skills/codebase-index/SKILL.md    plugin skill (Claude Code picks up skills/)
  skill/SKILL.md, skill/scripts/cbx, skill/scripts/cbx.ps1
                                    installer source package (shared files only;
                                    the rest of skill/ is owned by install.sh)

Version stamps maintained:
  <installed copy>/.skill_version   == __version__
  .claude-plugin/plugin.json        "version" field == __version__
  requirements.lock                 release tag v<__version__>

Usage:
  python scripts/sync_skill_copies.py          # rewrite derived copies
  python scripts/sync_skill_copies.py --check  # list drift, exit 1 (for CI)
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]

TEMPLATE_REL = Path("src/codebase_index/skill_template")
INSTALLED_COPIES = (
    Path(".claude/skills/codebase-index"),
    Path(".codex/skills/codebase-index"),
    Path(".opencode/skills/codebase-index"),
)
PLUGIN_SKILL_REL = Path("skills/codebase-index")
INSTALLER_SHARED = ("SKILL.md", "scripts/cbx", "scripts/cbx.ps1")

VERSION_RE = re.compile(r'^__version__ = "([^"]+)"$', re.M)
PLUGIN_VERSION_RE = re.compile(r'("version"\s*:\s*)"[^"]+"')
LOCK_TAG_RE = re.compile(r"(refs/tags/v)[0-9][^/]*?(\.tar\.gz)")


def package_version(repo: Path) -> str:
    text = (repo / "src/codebase_index/__init__.py").read_text(encoding="utf-8")
    match = VERSION_RE.search(text)
    if not match:
        raise SystemExit("could not find __version__ in src/codebase_index/__init__.py")
    return match.group(1)


def template_files(repo: Path) -> list[Path]:
    root = repo / TEMPLATE_REL
    return sorted(p.relative_to(root) for p in root.rglob("*") if p.is_file())


def expected_files(repo: Path, version: str) -> dict[Path, bytes]:
    """Map every derived file (repo-relative) to the bytes it must contain."""
    template = repo / TEMPLATE_REL
    rels = template_files(repo)
    expected: dict[Path, bytes] = {}

    for copy in INSTALLED_COPIES:
        for rel in rels:
            expected[copy / rel] = (template / rel).read_bytes()
        expected[copy / ".skill_version"] = f"{version}\n".encode()

    expected[PLUGIN_SKILL_REL / "SKILL.md"] = (template / "SKILL.md").read_bytes()

    for rel in INSTALLER_SHARED:
        expected[Path("skill") / rel] = (template / rel).read_bytes()

    return expected


def version_stamp_problems(repo: Path, version: str) -> list[str]:
    problems: list[str] = []

    plugin_path = repo / ".claude-plugin/plugin.json"
    plugin_ver = json.loads(plugin_path.read_text(encoding="utf-8")).get("version")
    if plugin_ver != version:
        problems.append(f".claude-plugin/plugin.json: version {plugin_ver!r} != {version!r}")

    lock_path = repo / "requirements.lock"
    match = LOCK_TAG_RE.search(lock_path.read_text(encoding="utf-8"))
    lock_ver = match.group(0).removeprefix("refs/tags/v").removesuffix(".tar.gz") if match else None
    if lock_ver != version:
        problems.append(f"requirements.lock: release tag {lock_ver!r} != {version!r}")

    return problems


def _norm(data: bytes) -> bytes:
    """Normalize line endings before comparing: with core.autocrlf the worktree
    may hold CRLF for files that the index stores with LF, and that must not
    count as drift."""
    return data.replace(b"\r\n", b"\n")


def check(repo: Path, version: str) -> list[str]:
    problems: list[str] = []
    for rel, want in expected_files(repo, version).items():
        path = repo / rel
        if not path.exists():
            problems.append(f"{rel.as_posix()}: missing")
        elif _norm(path.read_bytes()) != _norm(want):
            problems.append(f"{rel.as_posix()}: differs from skill_template")
    problems.extend(version_stamp_problems(repo, version))
    return problems


def sync(repo: Path, version: str) -> list[str]:
    written: list[str] = []
    for rel, want in expected_files(repo, version).items():
        path = repo / rel
        if path.exists() and _norm(path.read_bytes()) == _norm(want):
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(want)
        written.append(rel.as_posix())

    plugin_path = repo / ".claude-plugin/plugin.json"
    plugin_text = plugin_path.read_text(encoding="utf-8")
    new_text = PLUGIN_VERSION_RE.sub(rf'\g<1>"{version}"', plugin_text, count=1)
    if new_text != plugin_text:
        plugin_path.write_text(new_text, encoding="utf-8")
        written.append(".claude-plugin/plugin.json")

    lock_path = repo / "requirements.lock"
    lock_text = lock_path.read_text(encoding="utf-8")
    new_lock = LOCK_TAG_RE.sub(rf"\g<1>{version}\g<2>", lock_text)
    if new_lock != lock_text:
        lock_path.write_text(new_lock, encoding="utf-8")
        written.append("requirements.lock")

    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="report drift without writing")
    parser.add_argument("--repo", type=Path, default=REPO, help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    repo = args.repo.resolve()
    version = package_version(repo)

    if args.check:
        problems = check(repo, version)
        if problems:
            print(f"skill copies out of sync with skill_template / version {version}:")
            for p in problems:
                print(f"  - {p}")
            print("run: python scripts/sync_skill_copies.py")
            return 1
        print(f"all skill copies in sync (version {version})")
        return 0

    written = sync(repo, version)
    if written:
        print(f"updated {len(written)} file(s) to match skill_template / version {version}:")
        for w in written:
            print(f"  - {w}")
    else:
        print(f"all skill copies already in sync (version {version})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
