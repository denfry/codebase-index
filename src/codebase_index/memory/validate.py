"""Validate evidence references against the current working tree.

Validity is byte identity with the working tree — never a commit, a timestamp, or a
similarity score. Every uncertain outcome is reported as invalid: a false invalidation
costs the agent one re-read, a false validation costs it a wrong answer.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..discovery.gates import PathGate
from . import identity as ident

VALID_STATES = frozenset({"valid", "relocated"})

MAX_SCAN_STEPS = 200_000
"""Upper bound on line-slices hashed while searching a file for moved content."""


@dataclass(frozen=True)
class Verdict:
    ref: ident.EvidenceRef
    state: str
    line_start: Optional[int] = None
    line_end: Optional[int] = None
    reason: str = ""

    @property
    def valid(self) -> bool:
        return self.state in VALID_STATES

    def as_dict(self) -> dict:
        return {
            "ref": str(self.ref),
            "state": self.state,
            "valid": self.valid,
            "line_start": self.line_start,
            "line_end": self.line_end,
            "reason": self.reason,
        }


class FileView:
    """Lines of one working-tree file; per-line hashes are computed only if needed."""

    def __init__(self, lines: list[str]) -> None:
        self.lines = lines
        self._line_shas: Optional[list[str]] = None

    def line_shas(self) -> list[str]:
        if self._line_shas is None:
            self._line_shas = [ident.line_sha(line) for line in self.lines]
        return self._line_shas

    def sha(self, line_start: int, line_end: int) -> Optional[str]:
        return ident.span_sha(self.lines, line_start, line_end)


def locate(
    view: FileView,
    sha: str,
    line_count: int,
    *,
    first_line_sha: Optional[str] = None,
    limit: int = 2,
    max_steps: Optional[int] = None,
) -> Optional[list[int]]:
    """1-based start lines where a span with this hash occurs (at most ``limit``).

    Returns ``None`` when the bounded search gave up, which callers must treat as "not
    found". With ``first_line_sha`` only lines that hash like the span's first line are
    tried, which makes relocation cheap for stored evidence.
    """
    if max_steps is None:
        max_steps = MAX_SCAN_STEPS
    total = len(view.lines)
    if line_count < 1 or line_count > total:
        return []
    starts: list[int] | range = range(total - line_count + 1)
    if first_line_sha is not None:
        shas = view.line_shas()
        starts = [i for i in starts if shas[i] == first_line_sha]
    if len(starts) * line_count > max_steps:
        return None
    found: list[int] = []
    for i in starts:
        if ident.sha_hex("\n".join(view.lines[i : i + line_count])).startswith(sha):
            found.append(i + 1)
            if len(found) >= limit:
                break
    return found


class WorkingTree:
    """Gated, cached file access for one validation batch (one CLI/MCP call)."""

    def __init__(self, gate: PathGate) -> None:
        self.gate = gate
        self._views: dict[str, tuple[Optional[FileView], str, str]] = {}

    def view(self, rel: str) -> tuple[Optional[FileView], str, str]:
        cached = self._views.get(rel)
        if cached is None:
            result = self.gate.read(rel)
            if result.state == "ok":
                cached = (FileView(ident.split_lines(result.data)), "ok", "")
            else:
                cached = (None, result.state, result.reason)
            self._views[rel] = cached
        return cached


def validate(
    ref: ident.EvidenceRef,
    tree: WorkingTree,
    *,
    first_line_sha: Optional[str] = None,
) -> Verdict:
    view, state, reason = tree.view(ref.path)
    if view is None:
        return Verdict(ref, state, reason=reason)
    if ref.matches(view.sha(ref.line_start, ref.line_end)):
        return Verdict(ref, "valid", ref.line_start, ref.line_end, "unchanged")
    starts = locate(view, ref.sha, ref.line_count, first_line_sha=first_line_sha)
    if starts is None:
        return Verdict(
            ref, "changed",
            reason="differs at the recorded lines; file too large to search for moved content",
        )
    if len(starts) == 1:
        start = starts[0]
        end = start + ref.line_count - 1
        return Verdict(ref, "relocated", start, end, f"identical content now at lines {start}-{end}")
    if len(starts) > 1:
        return Verdict(
            ref, "ambiguous",
            reason="identical content occurs more than once in the file; cannot identify it",
        )
    return Verdict(ref, "changed", reason="content no longer occurs in the file")
