"""Evidence-keyed memory: sound reuse of agent work, and the granularity law.

Hypotheses H3/H4. Unlike the retrieval plane, the claim here is about a *correctness*
property, so the experiment is not "does quality go up" but "how often does the
incumbent design return an answer that is silently wrong, and what does soundness
cost".

The three cache designs compared:

  query-keyed    the semantic cache. Key = the question. Reuse when the question
                 repeats (or is similar). Carries no information about whether the
                 code the answer was derived from still exists in that form.

  file-keyed     evidence-keyed at file granularity. Key = content hashes of every
                 file the conclusion read. Sound: any edit to any of those files
                 invalidates. This is what a straightforward implementation does.

  span-keyed     evidence-keyed at the granularity actually read -- the retrieved
                 line spans. Equally sound, but invalidated only by edits that
                 overlap the specific regions the conclusion depended on.

Survival is measured retrospectively against real history: for a conclusion whose
evidence is a set of spans at HEAD, was that evidence disturbed over the last `h`
commits? Because `git diff HEAD~h HEAD` reports hunks on the new side in HEAD's
coordinates, the overlap test is exact -- no re-indexing of historical trees and no
line-number mapping heuristics.

The semantic cache's unsound-hit rate is then exactly `1 - survival`: it would have
served every one of those conclusions, and each one whose evidence moved was stale.
"""

from __future__ import annotations

import hashlib
import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

_HUNK = re.compile(r"^@@ -\d+(?:,\d+)? \+(\d+)(?:,(\d+))? @@")


@dataclass(frozen=True)
class Span:
    path: str
    start: int
    end: int
    tokens: int = 0


@dataclass
class Conclusion:
    """One unit of agent work, with the evidence it consumed recorded at write time."""

    task: str
    spans: tuple[Span, ...]
    tokens: int = 0

    @property
    def files(self) -> frozenset[str]:
        return frozenset(s.path for s in self.spans)

    def key(self, content_hash: dict[str, str], *, granularity: str) -> str:
        """Content-addressed key. This is the whole mechanism.

        A conclusion is identified by what it *depended on*, not by what it was
        asked. Two agents that read the same evidence share a key and therefore
        share the work; an edit to that evidence changes the key, so the stale entry
        is not evicted by a heuristic -- it is simply never looked up again.
        """
        if granularity == "file":
            parts = sorted(f"{p}:{content_hash.get(p, '')}" for p in self.files)
        else:
            parts = sorted(
                f"{s.path}:{s.start}-{s.end}:{content_hash.get(s.path, '')}"
                for s in self.spans
            )
        return hashlib.sha256("\x00".join(parts).encode()).hexdigest()[:16]


def _git(repo: Path, *args: str) -> str:
    p = subprocess.run(["git", "-C", str(repo), *args], capture_output=True,
                       text=True, encoding="utf-8", errors="replace")
    if p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {p.stderr.strip()}")
    return p.stdout


def changed_regions(repo: Path, horizon: int) -> tuple[set[str], dict[str, list[tuple[int, int]]]]:
    """Files and new-side line ranges touched by the last `horizon` commits.

    Returns (changed_files, {path: [(start, end), ...]}) with ranges in HEAD
    coordinates, which is what makes the overlap test against HEAD spans exact.
    """
    try:
        diff = _git(repo, "diff", "--unified=0", f"HEAD~{horizon}", "HEAD")
    except RuntimeError:
        return set(), {}
    files: set[str] = set()
    hunks: dict[str, list[tuple[int, int]]] = {}
    current: str | None = None
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            current = line[6:].strip()
            if current == "/dev/null":
                current = None
            else:
                files.add(current)
                hunks.setdefault(current, [])
        elif line.startswith("@@") and current:
            m = _HUNK.match(line)
            if m:
                start = int(m.group(1))
                length = int(m.group(2) or 1)
                if length == 0:      # pure deletion: mark the seam
                    hunks[current].append((start, start + 1))
                else:
                    hunks[current].append((start, start + length - 1))
    return files, hunks


def survives(
    c: Conclusion, changed_files: set[str], hunks: dict[str, list[tuple[int, int]]],
    *, granularity: str,
) -> bool:
    if granularity == "file":
        return not (c.files & changed_files)
    for s in c.spans:
        if s.path not in changed_files:
            continue
        for lo, hi in hunks.get(s.path, ()):
            if s.start <= hi and lo <= s.end:
                return False
        # A file listed as changed with no parsable hunks (rename, mode change,
        # binary) is treated as disturbing every span in it. Conservative in the
        # direction that costs the mechanism hit-rate rather than soundness.
        if not hunks.get(s.path):
            return False
    return True


@dataclass
class MemoStore:
    """Content-addressed store of completed work, with exact invalidation."""

    granularity: str = "span"
    entries: dict[str, Conclusion] = field(default_factory=dict)
    hits: int = 0
    misses: int = 0
    tokens_saved: int = 0

    def get_or_compute(self, c: Conclusion, content_hash: dict[str, str]) -> bool:
        """True on reuse. The caller does the work only on False."""
        k = c.key(content_hash, granularity=self.granularity)
        if k in self.entries:
            self.hits += 1
            self.tokens_saved += c.tokens
            return True
        self.entries[k] = c
        self.misses += 1
        return False
