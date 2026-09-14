"""Baselines the index is compared against, with symmetric token accounting.

Two baselines model what an agent does *without* an index:

* ``rg_window`` — a disciplined grep agent. Drop stop-words from the question,
  search the salient terms with ripgrep, rank files by match density, then read
  an 80-line window around the densest hit of each of the top-K files.
* ``repo_map`` — a repo-map-style context blob in the spirit of Aider's map:
  file paths plus definition signatures, ranked by graph degree (and, in the
  query-aware variant, by identifier overlap with the question), packed under a
  fixed token budget and handed to the agent up front.

Both are approximations of a *style* of context construction, not a
re-implementation of any specific product. Neither uses the ranking pipeline;
``repo_map`` reads the symbol table from the index database only because
Tree-sitter signatures are what a repo map is built from.

Symmetry rules
--------------
Every side is charged with the same tokenizer for the text that actually enters
the agent's context:

* index: the JSON payload the agent receives, plus the top-K
  ``recommended_reads`` line ranges (a "follow-through read");
* rg_window: the ripgrep listing (capped at ``LISTING_CAP`` lines — agents
  truncate long tool output) plus the top-K windows it reads;
* repo_map: the map itself (the budget it was packed under).

Latency is reported for context only. The index runs in-process, ripgrep is a
separate binary; neither is a fair wall-clock claim against the other.
"""

from __future__ import annotations

import json
import os
import re
import shutil
import sqlite3
import subprocess
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

from codebase_index.retrieval.pipeline import search
from codebase_index.retrieval.tuning import RetrievalTuning

from . import metrics
from .harness import EvalQuery

# --- shared configuration ---------------------------------------------------
WINDOW = 80
"""Lines read around a grep hit; matches the index's code window."""
TOP_K = 3
"""Files an agent opens after a search: it 'starts with ranks 1-3'."""
LISTING_CAP = 50
"""Lines of `rg` output an agent actually looks at before deciding what to open."""
REPO_MAP_BUDGETS = (2000, 8000)
"""Token budgets for the repo-map baseline: a small chat-context map and a large one."""

# --- token counting (identical on every side) --------------------------------
try:  # pragma: no cover - exercised only when tiktoken is installed
    import tiktoken

    _ENC = tiktoken.get_encoding("cl100k_base")

    def count_tokens(text: str) -> int:
        return len(_ENC.encode(text, disallowed_special=()))

    TOKENIZER = "tiktoken/cl100k_base"
except Exception:  # pragma: no cover
    def count_tokens(text: str) -> int:
        return max(0, len(text) // 4)

    TOKENIZER = "chars//4 (tiktoken not installed)"


# --- salient-term extraction (what an agent greps for) ------------------------
STOPWORDS = frozenset(
    """
    the a an is are was were be been being how does do did what where which who whom
    when why to of in on for and or with from down up it this that these those i would
    should could can will show me all work works happen happens other into during if
    rename use used uses get got set via across between add adds added fix fixes fixed
    remove removes removed update updates updated make makes made support supports
    allow allows allowed change changes changed improve improves improved when not
    """.split()
)
_TERM_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]+")


def salient_terms(query: str, *, max_terms: int = 6) -> list[str]:
    """Terms an agent would grep for: identifiers kept whole, stop-words dropped."""
    out: list[str] = []
    seen: set[str] = set()
    for term in _TERM_RE.findall(query):
        key = term.lower()
        if key in STOPWORDS or len(term) < 3 or key in seen:
            continue
        seen.add(key)
        out.append(term)
    # Longest terms first: an agent greps the most specific identifier before
    # generic words, and ripgrep's OR of all of them is order-independent anyway.
    out.sort(key=len, reverse=True)
    return out[:max_terms]


# --- repository file access ----------------------------------------------------
TEXT_EXTS = frozenset(
    """
    .py .pyi .js .mjs .cjs .jsx .ts .tsx .java .kt .kts .go .rs .rb .php .cs .c .h .cc
    .cpp .hpp .swift .scala .lua .sql .sh .ps1 .md .rst .txt .yml .yaml .toml .json
    .xml .gradle .cfg .ini
    """.split()
)
IGNORE_PARTS = frozenset(
    """
    .git node_modules __pycache__ .venv venv dist build target .idea .gradle out
    .claude .codex .opencode .tox .mypy_cache .pytest_cache .ruff_cache
    """.split()
)


def _norm(path: str) -> str:
    return path.replace("\\", "/")


@dataclass
class Corpus:
    root: Path
    _lines: dict[str, list[str]] = field(default_factory=dict)

    def lines(self, rel: str) -> list[str]:
        rel = _norm(rel)
        cached = self._lines.get(rel)
        if cached is None:
            try:
                cached = (self.root / rel).read_text(
                    encoding="utf-8", errors="ignore"
                ).splitlines()
            except OSError:
                cached = []
            self._lines[rel] = cached
        return cached

    def read_range(self, rel: str, start: int, end: int) -> str:
        lines = self.lines(rel)
        if not lines:
            return ""
        start = max(1, start)
        end = min(len(lines), end)
        if end < start:
            return ""
        return "\n".join(lines[start - 1 : end])

    def is_text(self, rel: str) -> bool:
        parts = _norm(rel).split("/")
        if any(p in IGNORE_PARTS for p in parts):
            return False
        return Path(rel).suffix.lower() in TEXT_EXTS


def _merge(ranges: Iterable[tuple[int, int]]) -> list[tuple[int, int]]:
    merged: list[list[int]] = []
    for s, e in sorted(ranges):
        if merged and s <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return [(s, e) for s, e in merged]


def tokens_for_reads(corpus: Corpus, reads: dict[str, list[tuple[int, int]]]) -> int:
    """Charge every (file, line range) once, ranges merged per file."""
    total = 0
    for rel, ranges in reads.items():
        for s, e in _merge(ranges):
            total += count_tokens(corpus.read_range(rel, s, e))
    return total


# --- outcome -------------------------------------------------------------------
@dataclass
class BaselineOutcome:
    ranked_files: list[str]
    tokens: int
    """Everything that entered context: listing/packet + top-K reads."""
    packet_tokens: int
    """The listing / packet / map alone, before any follow-through read."""
    latency_ms: float
    extra: dict = field(default_factory=dict)


# --- index side ----------------------------------------------------------------
def run_index(
    conn: sqlite3.Connection,
    corpus: Corpus,
    q: EvalQuery,
    *,
    tuning: RetrievalTuning | None = None,
    limit: int = 10,
    token_budget: int = 1500,
    max_read_lines: int = 120,
) -> BaselineOutcome:
    start = time.perf_counter()
    payload = search(
        conn,
        q.query,
        mode="hybrid",
        limit=limit,
        token_budget=token_budget,
        no_fallback=True,
        tuning=tuning or RetrievalTuning(),
        max_read_lines=max_read_lines,
    )
    latency_ms = (time.perf_counter() - start) * 1000.0

    ranked: list[str] = []
    for r in payload.get("results", []):
        p = _norm(r["path"])
        if p not in ranked:
            ranked.append(p)

    # The packet is what an MCP / --json agent literally receives.
    packet_tokens = count_tokens(json.dumps(payload, ensure_ascii=False))

    # Follow-through: the agent opens the top-K recommended ranges.
    reads: dict[str, list[tuple[int, int]]] = {}
    for rr in payload.get("recommended_reads", [])[:TOP_K]:
        s = int(rr.get("line_start") or 1)
        e = int(rr.get("line_end") or s)
        if e <= s:
            e = s + WINDOW - 1
        reads.setdefault(_norm(rr["path"]), []).append((s, e))
    read_tokens = tokens_for_reads(corpus, reads)

    return BaselineOutcome(
        ranked_files=ranked,
        tokens=packet_tokens + read_tokens,
        packet_tokens=packet_tokens,
        latency_ms=latency_ms,
        extra={"confidence": payload.get("confidence"), "read_tokens": read_tokens},
    )


# --- rg + window ---------------------------------------------------------------
RG = os.environ.get("CBX_RG") or shutil.which("rg")
"""Path to ripgrep; set CBX_RG when `rg` is a shell alias rather than a binary on PATH."""


def rg_version() -> str | None:
    """`ripgrep X.Y.Z` for the report, or None when the Python fallback is in use."""
    if not RG:
        return None
    try:
        out = subprocess.run([RG, "--version"], capture_output=True, text=True, timeout=10).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    return out.splitlines()[0].strip() if out else None


def _rg_hits(corpus: Corpus, terms: Sequence[str]) -> tuple[dict[str, list[int]], list[str], float]:
    """Return ({file: [line numbers]}, listing lines, elapsed ms) using ripgrep.

    Falls back to a pure-Python scan when ripgrep is not installed; the fallback
    is labelled in the report because its latency is not comparable.
    """
    if not terms:
        return {}, [], 0.0
    start = time.perf_counter()
    hits: dict[str, list[int]] = {}
    listing: list[str] = []
    if RG:
        cmd = [RG, "-n", "-i", "--no-heading", "--no-messages", "--color", "never"]
        for t in terms:
            cmd += ["-e", re.escape(t)]
        for part in sorted(IGNORE_PARTS):
            cmd += ["--glob", f"!{part}"]
        proc = subprocess.run(
            cmd, cwd=corpus.root, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
        for line in proc.stdout.splitlines():
            path, _, rest = line.partition(":")
            lineno, _, _text = rest.partition(":")
            rel = _norm(path)
            if not corpus.is_text(rel) or not lineno.isdigit():
                continue
            hits.setdefault(rel, []).append(int(lineno))
            listing.append(line)
    else:  # pragma: no cover - only without ripgrep
        pats = [re.compile(re.escape(t), re.I) for t in terms]
        for p in corpus.root.rglob("*"):
            if not p.is_file():
                continue
            rel = _norm(str(p.relative_to(corpus.root)))
            if not corpus.is_text(rel):
                continue
            for i, text in enumerate(corpus.lines(rel), 1):
                if any(pat.search(text) for pat in pats):
                    hits.setdefault(rel, []).append(i)
                    listing.append(f"{rel}:{i}:{text}")
    return hits, listing, (time.perf_counter() - start) * 1000.0


def run_rg_window(corpus: Corpus, q: EvalQuery) -> BaselineOutcome:
    terms = salient_terms(q.query)
    hits, listing, elapsed = _rg_hits(corpus, terms)

    # Rank by match density: the heuristic a grep agent applies when scanning
    # `rg` output ("this file lights up the most").
    ranked = [rel for rel, _ in sorted(hits.items(), key=lambda kv: (-len(kv[1]), kv[0]))]

    reads: dict[str, list[tuple[int, int]]] = {}
    for rel in ranked[:TOP_K]:
        lines = hits[rel]
        center = lines[len(lines) // 2]
        reads.setdefault(rel, []).append((center - WINDOW // 2, center + WINDOW // 2))

    listing_text = "\n".join(listing[:LISTING_CAP])
    packet_tokens = count_tokens(listing_text)
    read_tokens = tokens_for_reads(corpus, reads)
    return BaselineOutcome(
        ranked_files=ranked,
        tokens=packet_tokens + read_tokens,
        packet_tokens=packet_tokens,
        latency_ms=elapsed,
        extra={
            "terms": terms,
            "matched_files": len(hits),
            "match_lines": sum(len(v) for v in hits.values()),
            "read_tokens": read_tokens,
        },
    )


# --- repo-map style ------------------------------------------------------------
@dataclass(frozen=True)
class MapEntry:
    path: str
    text: str
    """Rendered map block: the path plus its definition signatures."""
    tokens: int
    degree: int
    names: frozenset[str]


def build_repo_map_entries(conn: sqlite3.Connection) -> list[MapEntry]:
    """One block per file: path + top-level definition signatures, from the symbol table."""
    rows = conn.execute(
        """
        SELECT f.path, s.name, s.kind, s.signature, s.in_degree, s.parent_id
        FROM files f LEFT JOIN symbols s ON s.file_id = f.id
        ORDER BY f.path, s.line_start
        """
    ).fetchall()
    by_file: dict[str, list[tuple]] = {}
    for row in rows:
        by_file.setdefault(_norm(row[0]), []).append(row)

    entries: list[MapEntry] = []
    for path, syms in by_file.items():
        lines = [f"{path}:"]
        degree = 0
        names: set[str] = set()
        for _p, name, kind, signature, in_degree, parent_id in syms:
            if name is None:
                continue
            degree += int(in_degree or 0)
            names.add(str(name).lower())
            if parent_id is None:  # top-level definitions only, like a repo map
                sig = (signature or f"{kind} {name}").strip().splitlines()[0]
                lines.append(f"  {sig}")
        text = "\n".join(lines)
        entries.append(MapEntry(path, text, count_tokens(text), degree, frozenset(names)))
    return entries


def pack_repo_map(
    entries: Sequence[MapEntry],
    *,
    budget: int,
    query_terms: Sequence[str] = (),
) -> tuple[list[str], int]:
    """Greedy pack of map blocks under `budget` tokens.

    Ordering: query-aware variant first ranks files whose definition names overlap
    the question's identifiers, then by graph degree (a stand-in for the PageRank
    a real repo map uses); the query-agnostic variant uses degree alone.
    """
    terms = {t.lower() for t in query_terms}

    def overlap(e: MapEntry) -> int:
        if not terms:
            return 0
        return sum(1 for n in e.names if any(t in n or n in t for t in terms))

    ordered = sorted(entries, key=lambda e: (-overlap(e), -e.degree, e.path))
    chosen: list[str] = []
    used = 0
    for e in ordered:
        if used + e.tokens > budget:
            continue
        chosen.append(e.path)
        used += e.tokens
    return chosen, used


def run_repo_map(
    entries: Sequence[MapEntry], q: EvalQuery, *, budget: int, query_aware: bool
) -> BaselineOutcome:
    start = time.perf_counter()
    terms = salient_terms(q.query) if query_aware else ()
    chosen, used = pack_repo_map(entries, budget=budget, query_terms=terms)
    latency = (time.perf_counter() - start) * 1000.0
    # A repo map is a blob, not a ranking: `ranked_files` is the pack order, so
    # hit@K on it says "is the answer even present in what the agent was handed".
    return BaselineOutcome(
        ranked_files=chosen,
        tokens=used,
        packet_tokens=used,
        latency_ms=latency,
        extra={"files_in_map": len(chosen), "budget": budget},
    )


# --- scoring -------------------------------------------------------------------
METRICS = ("hit@3", "recall@5", "MRR")


def score(outcome: BaselineOutcome, q: EvalQuery, *, present_only: bool = False) -> dict[str, float]:
    rel = q.expected_files
    ranked = outcome.ranked_files
    if present_only:
        # For a context blob, "present in the map" is the only meaningful hit.
        present = 1.0 if any(p in set(ranked) for p in rel) else 0.0
        return {"present": present, "recall": metrics.recall_at_k(ranked, rel, len(ranked) or 1)}
    return {
        "hit@3": metrics.hit_rate_at_k(ranked, rel, 3),
        "recall@5": metrics.recall_at_k(ranked, rel, 5),
        "MRR": metrics.reciprocal_rank(ranked, rel),
    }
