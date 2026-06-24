"""Retrieval-time snippet skeletonization (line-granularity StructureMask).

Turns a raw code/text snippet into a compact skeleton: signature/structural
lines are kept, function bodies (and other compressible runs) collapse into a
marker that points at the absolute line range to read for the full body. A
line-granularity port of headroom's StructureMask, adapted for a retrieval
system: the query-matching line is always preserved, routing is by file
extension, and the transform never makes output worse than the raw snippet.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from ..parsers.line_chunker import estimate_tokens


def render_skeleton(
    content: str, keep: list[bool], *, line_start: int
) -> tuple[str, int]:
    """Collapse consecutive ``keep=False`` lines into one elision marker.

    ``line_start`` is the absolute file line number of ``content``'s first line,
    so markers cite the real range to ``Read``. Returns (text, elided_count).
    """
    lines = content.split("\n")
    if len(keep) != len(lines):
        # Defensive: mask/line mismatch must never corrupt output.
        return content, 0

    out: list[str] = []
    elided_total = 0
    i = 0
    n = len(lines)
    while i < n:
        if keep[i]:
            out.append(lines[i])
            i += 1
            continue
        run_start = i
        while i < n and not keep[i]:
            i += 1
        run_len = i - run_start
        elided_total += run_len
        a = line_start + run_start
        b = line_start + i - 1
        out.append(f"... {run_len} lines elided (read {a}-{b})")
    return "\n".join(out), elided_total


# Languages we skeletonize via tree-sitter signatures. Mirrors
# discovery.classify._TREE_SITTER_LANGS (kept local to avoid a private import).
_CODE_LANGS = frozenset({
    "python", "typescript", "javascript", "go", "java", "rust",
    "c", "cpp", "csharp", "ruby", "php", "kotlin", "lua",
})
# Languages whose body opens at a line containing '{' vs. one ending in ':'.
_BRACE_LANGS = frozenset({
    "typescript", "javascript", "go", "java", "rust",
    "c", "cpp", "csharp", "php", "kotlin",
})
_MAX_SIG_SCAN = 5  # bound the multi-line-signature lookahead


@dataclass
class Compacted:
    text: str
    token_est: int
    elided_lines: int
    skeletonized: bool


def _raw(content: str) -> Compacted:
    return Compacted(text=content, token_est=estimate_tokens(content),
                     elided_lines=0, skeletonized=False)


def _signature_end(lines: list[str], start: int, lang: str | None, end: int) -> int:
    """0-based index of the last signature line for a def starting at ``start``.

    Scans forward (bounded) for the line that opens the body so multi-line
    signatures stay visible; defaults to ``start`` when nothing matches.
    """
    limit = min(end, start + _MAX_SIG_SCAN)
    for i in range(start, limit + 1):
        s = lines[i].strip()
        if lang in _BRACE_LANGS and "{" in s:
            return i
        if lang not in _BRACE_LANGS and s.endswith(":"):
            return i
    return start


def _classify_code(content: str, lines: list[str], lang: str) -> list[bool] | None:
    """Keep imports/signatures/headers; elide function & method bodies.

    Returns None when parsing yields no usable symbols (caller falls back).
    """
    from ..parsers.treesitter import parse_file

    try:
        result = parse_file(lang, content)
    except Exception:
        return None
    symbols = result.symbols
    if not symbols:
        return None

    n = len(lines)
    keep = [True] * n
    # Pass 1: elide the interior of every callable body.
    for sym in symbols:
        if sym.kind not in ("function", "method"):
            continue
        start0 = sym.line_start - 1
        if not (0 <= start0 < n):
            continue
        end0 = min(sym.line_end - 1, n - 1)
        sig_end = _signature_end(lines, start0, lang, end0)
        for i in range(sig_end + 1, end0 + 1):
            keep[i] = False
    # Pass 2: re-keep every symbol's signature line(s) (restores nested defs).
    for sym in symbols:
        start0 = sym.line_start - 1
        if not (0 <= start0 < n):
            continue
        end0 = min(sym.line_end - 1, n - 1)
        sig_end = _signature_end(lines, start0, lang, end0)
        for i in range(start0, sig_end + 1):
            keep[i] = True
    return keep


def _apply_focus(lines: list[str], keep: list[bool],
                 query_terms: list[str], ctx_lines: int) -> None:
    """Force-keep any line containing a query term, plus +/- ctx_lines."""
    if not query_terms:
        return
    n = len(lines)
    for i, line in enumerate(lines):
        low = line.lower()
        if any(t in low for t in query_terms):
            for j in range(max(0, i - ctx_lines), min(n, i + ctx_lines + 1)):
                keep[j] = True


_STRUCT_LANGS = frozenset({"json", "yaml", "toml", "ini"})
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s")
_SECTION_RE = re.compile(r"^\s*\[.*\]\s*$")        # toml/ini section header
_KEY_RE = re.compile(r"[:=]")                       # key/value introducer
_BRACKET = {"{", "}", "[", "]", "{}", "[]", "},", "],"}


def _classify_markdown(lines: list[str]) -> list[bool]:
    keep = [False] * len(lines)
    for i, line in enumerate(lines):
        if _HEADING_RE.match(line):
            keep[i] = True
            # keep the first non-blank line of the section
            for j in range(i + 1, len(lines)):
                if lines[j].strip():
                    keep[j] = True
                    break
    return keep


def _classify_structured(lines: list[str]) -> list[bool]:
    keep = [False] * len(lines)
    for i, line in enumerate(lines):
        s = line.strip()
        if not s or s in _BRACKET or _SECTION_RE.match(s) or _KEY_RE.search(s):
            keep[i] = True
    return keep


def classify_lines(content: str, *, lang: str | None,
                   query_terms: list[str], ctx_lines: int) -> list[bool]:
    lines = content.split("\n")
    keep: list[bool] | None = None
    if lang in _CODE_LANGS:
        keep = _classify_code(content, lines, lang)
    elif lang == "markdown":
        keep = _classify_markdown(lines)
    elif lang in _STRUCT_LANGS:
        keep = _classify_structured(lines)
    if keep is None:
        keep = [True] * len(lines)        # unknown / parse miss -> keep all (raw)
    _apply_focus(lines, keep, query_terms, ctx_lines)
    return keep


def compact(content: str, *, path: str, line_start: int, ctx_lines: int,
            query_terms: list[str], min_reduction: float) -> Compacted:
    """Route -> classify -> render -> guard. Never raises; raw fallback on any miss."""
    if not content.strip():
        return _raw(content)
    try:
        from ..discovery.classify import detect_language
        lang = detect_language(path)
        keep = classify_lines(content, lang=lang,
                              query_terms=[t.lower() for t in query_terms],
                              ctx_lines=ctx_lines)
        if all(keep):
            return _raw(content)
        text, elided = render_skeleton(content, keep, line_start=line_start)
        if elided == 0:
            return _raw(content)
        new_tok = estimate_tokens(text)
        raw_tok = estimate_tokens(content)
        if new_tok > raw_tok * (1.0 - min_reduction):
            return _raw(content)          # not a meaningful win
        return Compacted(text=text, token_est=new_tok,
                         elided_lines=elided, skeletonized=True)
    except Exception:
        return _raw(content)
