#!/usr/bin/env python3
"""Extract one version's section from CHANGELOG.md as GitHub release notes.

    python scripts/release_notes.py                 # current __version__, to stdout
    python scripts/release_notes.py 1.9.0           # explicit version
    python scripts/release_notes.py --out notes.md  # write instead of print

Exits non-zero when the section is missing or empty, so a tag with an unwritten
changelog fails the release job instead of shipping an empty release page.
Stdlib only; used by .github/workflows/release.yml.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
REPO_URL = "https://github.com/denfry/codebase-index"

VERSION_RE = re.compile(r'^__version__ = "([^"]+)"$', re.M)
HEADING_RE = re.compile(r"^## \[(?P<version>[^\]]+)\](?:\s*-\s*(?P<date>\S+))?\s*$", re.M)
LINK_DEF_RE = re.compile(r"^\[(?P<version>[^\]]+)\]:\s*(?P<url>\S+)\s*$", re.M)


def package_version(repo: Path = REPO) -> str:
    text = (repo / "src/codebase_index/__init__.py").read_text(encoding="utf-8")
    match = VERSION_RE.search(text)
    if not match:
        raise SystemExit("could not find __version__ in src/codebase_index/__init__.py")
    return match.group(1)


def extract_section(changelog: str, version: str) -> tuple[str, str | None, str | None]:
    """Return (body, date, previous_version) for `version`.

    `body` is the text between this version's heading and the next `## ` heading,
    with trailing link definitions removed. Raises KeyError when the heading is
    absent.
    """
    headings = list(HEADING_RE.finditer(changelog))
    for idx, match in enumerate(headings):
        if match.group("version") != version:
            continue
        end = headings[idx + 1].start() if idx + 1 < len(headings) else len(changelog)
        body = changelog[match.end():end]
        # Link definitions live at the bottom of the file; they are not notes.
        body = LINK_DEF_RE.sub("", body).strip()
        previous = headings[idx + 1].group("version") if idx + 1 < len(headings) else None
        return body, match.group("date"), previous
    raise KeyError(version)


def compare_url(changelog: str, version: str, previous: str | None) -> str | None:
    for match in LINK_DEF_RE.finditer(changelog):
        if match.group("version") == version:
            return match.group("url")
    if previous and previous.lower() != "unreleased":
        return f"{REPO_URL}/compare/v{previous}...v{version}"
    return None


def render(changelog: str, version: str) -> str:
    body, _date, previous = extract_section(changelog, version)
    if not body:
        raise SystemExit(f"CHANGELOG.md section for {version} is empty")
    footer = [
        "",
        "---",
        "",
        "**Install**",
        "",
        "```bash",
        f"pip install codebase-index=={version}",
        f"pipx install codebase-index=={version}",
        "```",
    ]
    url = compare_url(changelog, version, previous)
    if url:
        footer += ["", f"Full diff: {url}"]
    return body + "\n" + "\n".join(footer) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("version", nargs="?", help="default: package __version__")
    ap.add_argument("--changelog", default=str(REPO / "CHANGELOG.md"))
    ap.add_argument("--out", help="write notes here instead of stdout")
    args = ap.parse_args(argv)

    version = args.version or package_version()
    changelog = Path(args.changelog).read_text(encoding="utf-8")
    try:
        notes = render(changelog, version)
    except KeyError:
        print(f"CHANGELOG.md has no '## [{version}]' section", file=sys.stderr)
        return 1

    if args.out:
        Path(args.out).write_text(notes, encoding="utf-8")
        print(f"wrote release notes for {version} to {args.out}")
    else:
        # The changelog uses arrows and dashes; a cp1251 console must not crash.
        sys.stdout.buffer.write(notes.encode("utf-8"))
        sys.stdout.flush()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
