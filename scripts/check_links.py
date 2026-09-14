#!/usr/bin/env python3
"""Fail on broken relative links in Markdown files.

    python scripts/check_links.py            # whole repository
    python scripts/check_links.py docs README.md

Checks `[text](target)` and `<img src="target">` / `<a href="target">` where the
target is a relative path. `#fragment` suffixes are stripped; http(s):, mailto:,
and fragment-only links are ignored. Prints `path:line: target` for each broken
link and exits 1 when any is found. Stdlib only; runs in CI lint.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "dist", "build", ".tmp-public-benchmark"}

MD_LINK_RE = re.compile(r"(?<!\!)\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
MD_IMAGE_RE = re.compile(r"!\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
HTML_SRC_RE = re.compile(r"<(?:img|a)\b[^>]*?\b(?:src|href)=\"([^\"]+)\"", re.I)
FENCE_RE = re.compile(r"^\s*(```|~~~)")
INLINE_CODE_RE = re.compile(r"`[^`]*`")
SCHEME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9+.-]*:")


def _is_external(target: str) -> bool:
    return bool(SCHEME_RE.match(target)) or target.startswith(("#", "//", "${", "<"))


def find_broken(md_file: Path, repo: Path = REPO) -> list[tuple[int, str]]:
    broken: list[tuple[int, str]] = []
    in_fence = False
    for lineno, line in enumerate(md_file.read_text(encoding="utf-8", errors="replace").splitlines(), 1):
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        line = INLINE_CODE_RE.sub("", line)  # `[x](y)` inside code spans is prose, not a link
        targets = MD_LINK_RE.findall(line) + MD_IMAGE_RE.findall(line) + HTML_SRC_RE.findall(line)
        for raw in targets:
            target = raw.strip("<>")
            if _is_external(target):
                continue
            target = target.split("#", 1)[0].split("?", 1)[0]
            if not target:
                continue
            base = repo if target.startswith("/") else md_file.parent
            resolved = (base / target.lstrip("/")).resolve()
            if not resolved.exists():
                broken.append((lineno, raw))
    return broken


def iter_markdown(paths: list[Path], repo: Path = REPO):
    for root in paths:
        if root.is_file():
            yield root
            continue
        for p in sorted(root.rglob("*.md")):
            if any(part in SKIP_DIRS for part in p.relative_to(root).parts):
                continue
            yield p


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    roots = [Path(a).resolve() for a in args] or [REPO]
    total_files = 0
    total_broken = 0
    for md in iter_markdown(roots, REPO):
        total_files += 1
        for lineno, target in find_broken(md, REPO):
            total_broken += 1
            try:
                shown = md.relative_to(REPO).as_posix()
            except ValueError:
                shown = md.as_posix()
            print(f"{shown}:{lineno}: {target}")
    if total_broken:
        print(f"\n{total_broken} broken link(s) in {total_files} markdown file(s)", file=sys.stderr)
        return 1
    print(f"links OK: {total_files} markdown file(s), no broken relative links")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
