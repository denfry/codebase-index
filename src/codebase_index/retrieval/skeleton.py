"""Retrieval-time snippet skeletonization (line-granularity StructureMask).

Turns a raw code/text snippet into a compact skeleton: signature/structural
lines are kept, function bodies (and other compressible runs) collapse into a
marker that points at the absolute line range to read for the full body. A
line-granularity port of headroom's StructureMask, adapted for a retrieval
system: the query-matching line is always preserved, routing is by file
extension, and the transform never makes output worse than the raw snippet.
"""

from __future__ import annotations

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
