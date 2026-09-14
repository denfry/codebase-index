#!/usr/bin/env python3
"""Render a captured terminal transcript as a static SVG "terminal card".

    bash examples/demo/run_demo.sh .tmp-demo/flask > demo.txt 2>&1
    python scripts/gen_terminal_svg.py demo.txt --out assets/demo-terminal.svg

Why an SVG and not a screenshot: the card is regenerated from a real transcript
(see docs/DEMO.md), diffable in git, crisp at any width, and never shows text the
tool did not actually print. Stdlib only.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from xml.sax.saxutils import escape

ANSI_RE = re.compile(r"\x1b\[[0-9;]*m")

# GitHub-dark inspired palette; the card carries its own background so it reads
# identically on light and dark README themes.
BG = "#0d1117"
BAR = "#161b22"
BORDER = "#30363d"
FG = "#e6edf3"
MUTED = "#8b949e"
BLUE = "#58a6ff"
GREEN = "#3fb950"
PURPLE = "#bc8cff"
AMBER = "#d29922"

CHAR_W = 8.4   # px per monospace character at 14px
LINE_H = 20
PAD = 18
FONT = "ui-monospace, SFMono-Regular, Menlo, Consolas, 'Liberation Mono', monospace"


def load_transcript(path: Path, *, stop_at: str | None, max_lines: int) -> list[str]:
    lines = []
    for raw in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = ANSI_RE.sub("", raw).rstrip()
        if stop_at and line.startswith("$ ") and stop_at in line:
            break
        if line.startswith("```"):
            continue  # fence markers carry no information in a terminal card
        lines.append(line)
    # Trim leading/trailing blank lines and collapse runs of blanks.
    out: list[str] = []
    for line in lines:
        if line == "" and (not out or out[-1] == ""):
            continue
        out.append(line)
    while out and out[-1] == "":
        out.pop()
    return out[:max_lines]


def _tspan(text: str, fill: str, *, weight: str | None = None) -> str:
    attrs = f' fill="{fill}"'
    if weight:
        attrs += f' font-weight="{weight}"'
    return f"<tspan{attrs}>{escape(text)}</tspan>"


def render_line(line: str) -> str:
    """Colour a line the way a reader would scan it: commands, headers, tables, confidence."""
    if line.startswith("$ "):
        return _tspan("$ ", GREEN) + _tspan(line[2:], BLUE, weight="600")
    if line.startswith("|"):
        cells = line.split("|")
        parts = []
        for i, cell in enumerate(cells):
            if i:
                parts.append(_tspan("|", BORDER))
            stripped = cell.strip()
            if re.fullmatch(r"-+:?|:?-+", stripped):
                parts.append(_tspan(cell, BORDER))
            elif stripped in ("extracted", "exact"):
                parts.append(_tspan(cell, GREEN))
            elif "ambiguous" in stripped or stripped == "inferred":
                parts.append(_tspan(cell, AMBER))
            elif stripped.startswith("`") and stripped.endswith("`"):
                parts.append(_tspan(cell.replace("`", ""), FG))
            else:
                parts.append(_tspan(cell, FG if i in (0, 1, 2, 3) else MUTED))
        return "".join(parts)
    if line.startswith("**"):
        # "**Query:** text · **Confidence:** medium"
        out = []
        for chunk in re.split(r"(\*\*[^*]+\*\*)", line):
            if chunk.startswith("**"):
                out.append(_tspan(chunk.strip("*"), PURPLE, weight="600"))
            else:
                out.append(_tspan(chunk, FG))
        return "".join(out)
    if line.startswith("- `") or line.startswith("  →") or line.startswith("`"):
        return _tspan(line.replace("`", ""), FG)
    if line.startswith("```"):
        return _tspan("", MUTED)
    if line.startswith("Indexed") or line.startswith("  parse"):
        return _tspan(line, MUTED)
    return _tspan(line, FG)


def render_svg(lines: list[str], *, title: str, cols: int) -> str:
    width = int(PAD * 2 + cols * CHAR_W)
    height = int(PAD * 2 + 36 + len(lines) * LINE_H)
    body = []
    y = PAD + 36 + LINE_H - 6
    for line in lines:
        body.append(
            f'<text x="{PAD}" y="{y}" xml:space="preserve">{render_line(line[:cols])}</text>'
        )
        y += LINE_H
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" font-family="{FONT}" font-size="14">
  <title>{escape(title)}</title>
  <rect width="{width}" height="{height}" rx="10" fill="{BG}" stroke="{BORDER}"/>
  <rect x="1" y="1" width="{width - 2}" height="34" rx="9" fill="{BAR}"/>
  <circle cx="20" cy="18" r="6" fill="#ff5f57"/><circle cx="40" cy="18" r="6" fill="#febc2e"/><circle cx="60" cy="18" r="6" fill="#28c840"/>
  <text x="{width / 2}" y="23" text-anchor="middle" fill="{MUTED}" font-size="12">{escape(title)}</text>
  {chr(10).join(body)}
</svg>
"""


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("transcript", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    ap.add_argument("--title", default="codebase-index · Flask @ d318b683 · examples/demo/run_demo.sh")
    ap.add_argument("--cols", type=int, default=100)
    ap.add_argument("--max-lines", type=int, default=60)
    ap.add_argument("--stop-at", default="--json", help="drop everything from the first command containing this")
    args = ap.parse_args(argv)

    lines = load_transcript(args.transcript, stop_at=args.stop_at, max_lines=args.max_lines)
    if not lines:
        print("empty transcript", file=sys.stderr)
        return 1
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render_svg(lines, title=args.title, cols=args.cols), encoding="utf-8")
    print(f"wrote {args.out} ({len(lines)} lines)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
