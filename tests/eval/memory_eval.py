#!/usr/bin/env python3
"""Sequential real-history benchmark for evidence memory.

Replays a repository's own history. For every git-derived query (a commit subject whose
answer is the files that commit changed) the working tree is checked out at the commit's
*parent* — what an agent sees before making the change — the index is updated
incrementally, and one retrieval call is made. Consecutive tasks form agent sessions of K
tasks, so the repository genuinely evolves between the calls of one session: unrelated
commits, edits to evidence already delivered, moves, deletions and refactors.

Each task produces one retrieval packet. Every arm is computed from that same packet and
the same candidates, so arms differ only in what they do with evidence:

  A      read the full file behind every delivered result ("just reread the file")
  A-mem  A, skipping a file this session already read whose bytes are unchanged
  B      the 1.10.0 packet: every snippet, every time
  S      unsafe dedup: withhold any result whose (path, lines) the session saw before,
         without looking at the source ("trust what you already read")
  C      2.0 evidence memory: withhold only byte-identical evidence; report changes

The oracle is independent of memory's hashing and relocation code. It keeps the text each
session was actually handed; a withheld snippet is **stale** unless the text B would
deliver now is text that session already holds. Invalidation notices are scored against a
list-comparison re-implementation of span presence.

Sources are never modified: each corpus is replayed in a `git clone --shared` inside a
temporary directory.

    python tests/eval/memory_eval.py
    python tests/eval/memory_eval.py --corpus ../svc:/tmp/svc.yml --sessions 1,5,10,all
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
import statistics
import subprocess
import sys
import tempfile
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Optional

REPO_ROOT = Path(__file__).resolve().parents[2]
if __package__ in (None, ""):
    sys.path.insert(0, str(REPO_ROOT / "tests"))
    sys.path.insert(0, str(REPO_ROOT / "src"))
    from eval import harness, metrics  # type: ignore[no-redef]
else:
    from . import harness, metrics

import yaml  # noqa: E402

from codebase_index.config import Config  # noqa: E402
from codebase_index.indexer.pipeline import build_index, update_index  # noqa: E402
from codebase_index.memory import identity as ident  # noqa: E402
from codebase_index.memory.session import (  # noqa: E402
    EvidenceProcessor,
    Session,
    index_sha_lookup,
)
from codebase_index.memory.store import MemoryStore  # noqa: E402
from codebase_index.output.redact import redact_snippet  # noqa: E402
from codebase_index.parsers.line_chunker import estimate_tokens  # noqa: E402
from codebase_index.retrieval.pipeline import search  # noqa: E402
from codebase_index.storage.db import Database  # noqa: E402

LIMIT = 10
BUDGET = 1500
SURVIVAL_HORIZONS = (1, 5, 10, 20)
_EPOCH = datetime(2026, 1, 1, tzinfo=timezone.utc)


# --- replay setup ------------------------------------------------------------------


@dataclass(frozen=True)
class Task:
    query: str
    expected_files: tuple[str, ...]
    commit: str
    parent: str


def git(repo: Path, *args: str) -> str:
    proc = subprocess.run(["git", "-C", str(repo), *args], capture_output=True, text=True,
                          encoding="utf-8", errors="replace")
    if proc.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {proc.stderr.strip()}")
    return proc.stdout


def load_tasks(queries_path: Path, work: Path) -> tuple[list[Task], dict[str, int]]:
    """Tasks oldest-first, plus each commit's `git log` position (0 = newest)."""
    order: dict[str, int] = {}
    parents: dict[str, Optional[str]] = {}
    for i, line in enumerate(git(work, "log", "--format=%H %P", "HEAD").splitlines()):
        parts = line.split()
        order[parts[0]] = i
        parents[parts[0]] = parts[1] if len(parts) > 1 else None
    by_prefix = {sha[:12]: sha for sha in order}
    tasks: list[Task] = []
    for entry in yaml.safe_load(queries_path.read_text(encoding="utf-8")) or []:
        full = by_prefix.get(str(entry.get("commit", ""))[:12])
        if not full or not parents.get(full):
            continue  # unknown commit or a root commit: no "before" state to replay
        tasks.append(Task(
            query=entry["query"],
            expected_files=tuple(f.replace("\\", "/") for f in entry.get("expected_files", ())),
            commit=full,
            parent=str(parents[full]),
        ))
    tasks.sort(key=lambda t: -order[t.commit])
    return tasks, order


def corpus_config(work: Path) -> Config:
    cfg = Config()
    cfg.root = str(work)
    cfg.embeddings.enabled = False
    cfg.extra_ignore = [*cfg.extra_ignore, *harness.CORPUS_EXCLUDES]
    cfg.memory.retention_days = 36500  # the replay's synthetic clock must never expire a session
    return cfg


# --- oracle ------------------------------------------------------------------------


class FileCache:
    """Working-tree reads for one task, shared by every arm's oracle."""

    def __init__(self, work: Path) -> None:
        self.work = work
        self._bytes: dict[str, Optional[bytes]] = {}

    def raw(self, rel: str) -> Optional[bytes]:
        if rel not in self._bytes:
            path = self.work / rel
            self._bytes[rel] = path.read_bytes() if path.is_file() else None
        return self._bytes[rel]

    def lines(self, rel: str) -> Optional[list[str]]:
        raw = self.raw(rel)
        if raw is None:
            return None
        text = raw.decode("utf-8", "surrogateescape")
        return text.replace("\r\n", "\n").replace("\r", "\n").splitlines()


def _sha16(lines: list[str]) -> str:
    return hashlib.sha256("\n".join(lines).encode("utf-8", "surrogateescape")).hexdigest()[:16]


def span_present(lines: Optional[list[str]], span: list[str], line_start: int) -> bool:
    """List comparison: the span sits at its recorded lines, or occurs exactly once."""
    if lines is None or not span:
        return False
    n = len(span)
    if lines[line_start - 1:line_start - 1 + n] == span:
        return True
    return sum(1 for i in range(len(lines) - n + 1) if lines[i:i + n] == span) == 1


def _occurrences(lines: Optional[list[str]], span: list[str]) -> Optional[int]:
    if lines is None or not span:
        return None
    n = len(span)
    return sum(1 for i in range(len(lines) - n + 1) if lines[i:i + n] == span)


def session_holds(truth: "SessionTruth", path: str, snippet: str, span_text: str) -> bool:
    """Does the session hold what it would be sent now?

    Yes if it was handed this exact snippet before, or the whole current span (the
    snippet — skeleton, signature or full text — is derived from those very bytes).
    Both sides are plain strings read from packets and files, never memory's hashes.
    """
    return (snippet in truth.held.get(path, set())
            or span_text in truth.full_spans.get(path, set()))


@dataclass
class Atom:
    path: str
    line_start: int
    span: list[str]
    delivered_position: int
    last_valid: int = 0
    invalid_at: Optional[int] = None


@dataclass
class SessionTruth:
    held: dict[str, set[str]] = field(default_factory=dict)
    full_spans: dict[str, set[str]] = field(default_factory=dict)
    seen_at: dict[tuple[str, int, int], str] = field(default_factory=dict)
    files_read: dict[str, str] = field(default_factory=dict)
    atoms: dict[tuple[str, str], Atom] = field(default_factory=dict)


@dataclass
class Totals:
    tasks: int = 0
    sessions: int = 0
    deliveries: int = 0
    b_tokens: int = 0
    c_tokens: int = 0
    s_tokens: int = 0
    a_tokens: int = 0
    amem_tokens: int = 0
    b_packet_tokens: int = 0
    c_packet_tokens: int = 0
    c_reused: int = 0
    s_reused: int = 0
    c_stale_withheld: int = 0
    s_stale_withheld: int = 0
    s_stale_gold: int = 0
    c_stale_flags: int = 0
    notices: int = 0
    notice_tp: int = 0
    notice_fp: int = 0
    notice_fn: int = 0
    page_mismatches: int = 0
    distinct_atoms: int = 0
    store_bytes: int = 0
    survival: dict[int, list[int]] = field(
        default_factory=lambda: {h: [0, 0] for h in SURVIVAL_HORIZONS})
    useful_b: list[float] = field(default_factory=list)
    useful_s: list[float] = field(default_factory=list)
    saved_per_task: list[float] = field(default_factory=list)
    memory_ms: list[float] = field(default_factory=list)
    examples: list[dict] = field(default_factory=list)
    """Bounded diagnostics for any event that should not happen (never committed: they
    can quote private source)."""

    def example(self, kind: str, **info: Any) -> None:
        if sum(1 for e in self.examples if e["kind"] == kind) < 10:
            self.examples.append({"kind": kind, **info})

    def merge(self, other: "Totals") -> None:
        for name, value in vars(other).items():
            mine = getattr(self, name)
            if isinstance(value, int):
                setattr(self, name, mine + value)
            elif isinstance(value, list):
                mine.extend(value)
            elif isinstance(value, dict):
                for h, (survived, observed) in value.items():
                    mine[h][0] += survived
                    mine[h][1] += observed


def close_session(truth: SessionTruth, stat: Totals) -> None:
    """Fold one session's evidence into survival counts (interval-censored)."""
    stat.distinct_atoms += len(truth.atoms)
    for atom in truth.atoms.values():
        for h in SURVIVAL_HORIZONS:
            if atom.last_valid >= h:
                stat.survival[h][0] += 1
                stat.survival[h][1] += 1
            elif atom.invalid_at is not None and atom.invalid_at <= h:
                stat.survival[h][1] += 1


# --- scoring one task --------------------------------------------------------------


def score_task(*, files: FileCache, processor: EvidenceProcessor, task: Task, packet: dict,
               candidates: list, truth: SessionTruth, stat: Totals, position: int,
               token_budget: int) -> None:
    stat.tasks += 1

    # Ground truth for evidence this session holds, established before memory runs.
    truth_invalid: set[tuple[str, str]] = set()
    for key, atom in truth.atoms.items():
        if atom.invalid_at is not None:
            continue
        distance = atom.delivered_position - position
        if span_present(files.lines(atom.path), atom.span, atom.line_start):
            atom.last_valid = max(atom.last_valid, distance)
        else:
            atom.invalid_at = distance
            truth_invalid.add(key)

    memory_packet = copy.deepcopy(packet)
    started = time.perf_counter()
    processor(memory_packet, candidates)
    stat.memory_ms.append((time.perf_counter() - started) * 1000)

    notices = {(r.path, r.sha[:16]) for r in
               (ident.parse_ref(n["ref"]) for n in memory_packet["memory"]["invalidated"])}
    stat.notices += len(notices)
    stat.notice_tp += len(notices & truth_invalid)
    stat.notice_fp += len(notices - truth_invalid)
    stat.notice_fn += len(truth_invalid - notices)
    states = {(r.path, r.sha[:16]): n["state"] for n in memory_packet["memory"]["invalidated"]
              for r in [ident.parse_ref(n["ref"])]}
    for key in sorted(notices ^ truth_invalid):
        atom = truth.atoms.get(key)
        stat.example("notice_fp" if key in notices else "notice_fn", path=key[0], sha=key[1],
                      memory_state=states.get(key), oracle_known=atom is not None,
                      oracle_line_start=atom.line_start if atom else None,
                      oracle_occurrences=_occurrences(files.lines(key[0]), atom.span)
                      if atom else None)

    # Filling withheld snippets back in must reproduce the no-memory packet exactly.
    restored = copy.deepcopy(memory_packet)
    restored.pop("memory")
    for mine, base in zip(restored["results"], packet["results"]):
        if mine.pop("reused", False):
            mine["snippet"] = base["snippet"]
        mine.pop("stale", None)
    if restored != packet:
        stat.page_mismatches += 1

    returned_s: list[tuple[str, int]] = []
    saved = 0
    delivered_files: set[str] = set()
    padded = list(candidates) + [None] * max(0, len(packet["results"]) - len(candidates))
    for base, mine, candidate in zip(packet["results"], memory_packet["results"], padded):
        path = base["path"].replace("\\", "/")
        tokens = int(base.get("token_est") or 0)
        snippet = base.get("snippet")
        if not snippet:
            returned_s.append((path, tokens))
            continue
        stat.deliveries += 1
        stat.b_tokens += tokens
        delivered_files.add(path)
        span_now = (files.lines(path) or [])[base["line_start"] - 1:base["line_end"]]

        # C: evidence memory
        if mine.get("stale"):
            stat.c_stale_flags += 1
            stat.example("stale_flag", path=path, lines=[base["line_start"], base["line_end"]],
                         chunk_kind=getattr(candidate, "kind", None),
                         source=getattr(candidate, "source", None),
                         content=(getattr(candidate, "content", None) or "")[:240],
                         span="\n".join(span_now)[:240])
        span_text = "\n".join(span_now)
        if mine.get("reused"):
            stat.c_reused += 1
            saved += tokens
            if not session_holds(truth, path, snippet, span_text):
                stat.c_stale_withheld += 1
                stat.example("c_stale_withheld", path=path,
                             lines=[base["line_start"], base["line_end"]],
                             source=getattr(candidate, "source", None),
                             skeletonized=base.get("skeletonized"), snippet=snippet[:400],
                             held=[h[:400] for h in sorted(truth.held.get(path, set()))[:3]])
        else:
            stat.c_tokens += tokens
            truth.held.setdefault(path, set()).add(snippet)
            if snippet == redact_snippet(span_text):
                truth.full_spans.setdefault(path, set()).add(span_text)
            if not mine.get("stale"):
                span = (files.lines(path) or [])[base["line_start"] - 1:base["line_end"]]
                key = (path, _sha16(span))
                known = truth.atoms.get(key)
                if known is None or known.invalid_at is not None:
                    truth.atoms[key] = Atom(path, int(base["line_start"]), span, position)

        # S: unsafe dedup by locator
        locator = (path, int(base["line_start"]), int(base["line_end"]))
        if locator in truth.seen_at:
            stat.s_reused += 1
            if truth.seen_at[locator] != snippet:
                stat.s_stale_withheld += 1
                if path in task.expected_files:
                    stat.s_stale_gold += 1
                continue  # the session holds a stale version: not useful evidence
        else:
            truth.seen_at[locator] = snippet
            stat.s_tokens += tokens
        returned_s.append((path, tokens))

    # A / A-mem: whole-file reads of every delivered result's file
    for path in sorted(delivered_files):
        raw = files.raw(path) or b""
        cost = estimate_tokens(raw.decode("utf-8", "ignore")) if raw else 0
        stat.a_tokens += cost
        digest = hashlib.sha256(raw).hexdigest()
        if truth.files_read.get(path) != digest:
            stat.amem_tokens += cost
            truth.files_read[path] = digest

    stat.b_packet_tokens += estimate_tokens(json.dumps(packet, separators=(",", ":")))
    stat.c_packet_tokens += estimate_tokens(json.dumps(memory_packet, separators=(",", ":")))
    stat.saved_per_task.append(float(saved))
    returned_b = [(r["path"].replace("\\", "/"), int(r.get("token_est") or 0))
                  for r in packet["results"]]
    stat.useful_b.append(
        metrics.useful_context_at_budget(returned_b, task.expected_files, token_budget))
    stat.useful_s.append(
        metrics.useful_context_at_budget(returned_s, task.expected_files, token_budget))


# --- one corpus --------------------------------------------------------------------


@dataclass
class CorpusResult:
    name: str
    tasks: int
    totals: dict[Optional[int], Totals]
    search_ms: list[float]
    update_ms: list[float]


def replay_corpus(repo: Path, queries: Path, sessions: Sequence[Optional[int]], *,
                  limit: int = LIMIT, token_budget: int = BUDGET,
                  max_tasks: Optional[int] = None,
                  log: Callable[[str], None] = lambda _m: None) -> CorpusResult:
    with tempfile.TemporaryDirectory() as tmp_name:
        tmp = Path(tmp_name)
        work = tmp / "work"
        subprocess.run(["git", "clone", "-q", "--shared", "--no-checkout", str(repo), str(work)],
                       check=True, capture_output=True)
        tasks, order = load_tasks(queries, work)
        if max_tasks is not None:
            tasks = tasks[:max_tasks]
        cfg = corpus_config(work)
        repo_id = ident.repo_id_for(work)
        totals = {k: Totals() for k in sessions}
        truths: dict[Optional[int], SessionTruth] = {k: SessionTruth() for k in sessions}
        active: dict[Optional[int], int] = {}
        stores = {k: MemoryStore.open(tmp / f"memory-{k or 'all'}.sqlite") for k in sessions}
        search_ms: list[float] = []
        update_ms: list[float] = []
        db = Database(tmp / "index.sqlite").open()
        try:
            for index, task in enumerate(tasks):
                git(work, "checkout", "-q", "-f", "--detach", task.parent)
                started = time.perf_counter()
                if index == 0:
                    build_index(cfg, db, root=work)
                else:
                    update_index(cfg, db, root=work)
                update_ms.append((time.perf_counter() - started) * 1000)

                captured: dict[str, Any] = {}
                started = time.perf_counter()
                packet = search(db.conn, task.query, mode="hybrid", limit=limit,
                                token_budget=token_budget, no_fallback=True,
                                evidence=lambda _p, c: captured.update(candidates=list(c)))
                search_ms.append((time.perf_counter() - started) * 1000)

                files = FileCache(work)
                now = _EPOCH + timedelta(minutes=index)
                for k in sessions:
                    session_index = 0 if k is None else index // k
                    if active.get(k) != session_index:
                        if k in active:
                            close_session(truths[k], totals[k])
                        truths[k] = SessionTruth()
                        totals[k].sessions += 1
                        active[k] = session_index
                    tag = f"k{k or 'all'}-s{session_index}"
                    store = stores[k]
                    session_id = store.touch_session(
                        repo_id, ident.session_key(repo_id, tag), now=now)
                    processor = EvidenceProcessor(
                        root=work, config=cfg, now=now,
                        session=Session(tag=tag, repo_id=repo_id, store=store,
                                        session_id=session_id),
                        index_sha=index_sha_lookup(db.conn))
                    score_task(files=files, processor=processor, task=task, packet=packet,
                               candidates=captured.get("candidates", []), truth=truths[k],
                               stat=totals[k], position=order[task.parent],
                               token_budget=token_budget)
                if (index + 1) % 25 == 0:
                    log(f"    {index + 1}/{len(tasks)} tasks")
            for k in sessions:
                if k in active:
                    close_session(truths[k], totals[k])
        finally:
            db.close()
            for k, store in stores.items():
                store.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
                totals[k].store_bytes = store.stats(repo_id)["bytes"]
                store.close()
        return CorpusResult(Path(repo).resolve().name, len(tasks), totals, search_ms, update_ms)


# --- reporting ---------------------------------------------------------------------


def _pct(part: float, whole: float) -> str:
    return f"{100.0 * part / whole:.1f}%" if whole else "—"


def _ratio(num: int, den: int) -> str:
    return f"{num / den:.3f}" if den else "—"


def summarise(label: str, t: Totals) -> dict:
    mean_saved, lo, hi = metrics.paired_bootstrap_ci(t.saved_per_task, resamples=2000)
    return {
        "sessions_k": label,
        "tasks": t.tasks,
        "sessions": t.sessions,
        "deliveries": t.deliveries,
        "distinct_atoms": t.distinct_atoms,
        "B_tokens": t.b_tokens,
        "C_tokens": t.c_tokens,
        "S_tokens": t.s_tokens,
        "A_tokens": t.a_tokens,
        "A_mem_tokens": t.amem_tokens,
        "C_token_reuse_rate": (t.b_tokens - t.c_tokens) / t.b_tokens if t.b_tokens else 0.0,
        "C_evidence_reuse_rate": t.c_reused / t.deliveries if t.deliveries else 0.0,
        "C_saved_per_task": mean_saved,
        "C_saved_per_task_ci95": [lo, hi],
        "C_stale_withheld": t.c_stale_withheld,
        "C_validated_reuse_rate": (
            (t.c_reused - t.c_stale_withheld) / t.c_reused if t.c_reused else None),
        "S_token_reuse_rate": (t.b_tokens - t.s_tokens) / t.b_tokens if t.b_tokens else 0.0,
        "S_stale_withheld": t.s_stale_withheld,
        "S_stale_reuse_rate": t.s_stale_withheld / t.s_reused if t.s_reused else None,
        "S_stale_gold": t.s_stale_gold,
        "notices": t.notices,
        "invalidation_precision": t.notice_tp / (t.notice_tp + t.notice_fp)
        if (t.notice_tp + t.notice_fp) else None,
        "invalidation_recall": t.notice_tp / (t.notice_tp + t.notice_fn)
        if (t.notice_tp + t.notice_fn) else None,
        "page_mismatches": t.page_mismatches,
        "stale_flags": t.c_stale_flags,
        "B_packet_tokens": t.b_packet_tokens,
        "C_packet_tokens": t.c_packet_tokens,
        "useful_B_equals_C": statistics.fmean(t.useful_b) if t.useful_b else 0.0,
        "useful_S": statistics.fmean(t.useful_s) if t.useful_s else 0.0,
        "survival": {h: (s / o if o else None, o) for h, (s, o) in t.survival.items()},
        "memory_ms_p50": metrics.percentile(t.memory_ms, 50),
        "memory_ms_p95": metrics.percentile(t.memory_ms, 95),
        "store_bytes": t.store_bytes,
        "examples": t.examples,
    }


def format_report(rows: list[dict]) -> str:
    out = [
        "| K | tasks | sessions | B tokens | C tokens (reuse) | 95% CI saved/task | "
        "C stale withheld | S tokens (reuse) | S stale withheld | notices P/R | "
        "A tokens | A-mem tokens | packet tok B→C |",
        "|" + "---|" * 13,
    ]
    for r in rows:
        lo, hi = r["C_saved_per_task_ci95"]
        precision = r["invalidation_precision"]
        recall = r["invalidation_recall"]
        out.append(
            f"| {r['sessions_k']} | {r['tasks']} | {r['sessions']} | {r['B_tokens']} | "
            f"{r['C_tokens']} ({100 * r['C_token_reuse_rate']:.1f}%) | "
            f"{r['C_saved_per_task']:.1f} [{lo:.1f}, {hi:.1f}] | {r['C_stale_withheld']} | "
            f"{r['S_tokens']} ({100 * r['S_token_reuse_rate']:.1f}%) | "
            f"{r['S_stale_withheld']} | "
            f"{'—' if precision is None else f'{precision:.3f}'}/"
            f"{'—' if recall is None else f'{recall:.3f}'} | "
            f"{r['A_tokens']} | {r['A_mem_tokens']} | "
            f"{r['B_packet_tokens']}→{r['C_packet_tokens']} |"
        )
    out.append("")
    out.append("| K | useful@budget B=C | useful@budget S | S stale gold | page mismatches | "
               "stale flags | distinct atoms | survival h=1/5/10/20 | memory ms p50/p95 | "
               "store bytes |")
    out.append("|" + "---|" * 10)
    for r in rows:
        surv = "/".join("—" if v[0] is None else f"{v[0]:.2f}" for v in r["survival"].values())
        out.append(
            f"| {r['sessions_k']} | {r['useful_B_equals_C']:.3f} | {r['useful_S']:.3f} | "
            f"{r['S_stale_gold']} | {r['page_mismatches']} | {r['stale_flags']} | "
            f"{r['distinct_atoms']} | {surv} | {r['memory_ms_p50']:.2f}/{r['memory_ms_p95']:.2f} | "
            f"{r['store_bytes']} |"
        )
    return "\n".join(out)


def _parse_corpus(spec: str) -> tuple[Path, Path]:
    head, sep, tail = spec.rpartition(":")
    if not sep or (len(head) == 1 and head.isalpha()):
        raise argparse.ArgumentTypeError(f"--corpus expects '<repo>:<queries.yml>', got {spec!r}")
    return Path(head).resolve(), Path(tail)


def _parse_sessions(spec: str) -> list[Optional[int]]:
    out: list[Optional[int]] = []
    for part in spec.split(","):
        part = part.strip().lower()
        if part == "all":
            out.append(None)
        elif part:
            out.append(max(1, int(part)))
    return out


def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--corpus", action="append", default=[], metavar="REPO:QUERIES")
    ap.add_argument("--sessions", default="1,5,10,25,all",
                    help="session lengths in tasks; 'all' = one session per corpus")
    ap.add_argument("--limit", type=int, default=LIMIT)
    ap.add_argument("--token-budget", type=int, default=BUDGET)
    ap.add_argument("--max-tasks", type=int, default=None)
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args(argv)
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

    corpora = [_parse_corpus(s) for s in args.corpus] or [
        (REPO_ROOT, harness.QUERY_DIR / "self_repo_git.yml")]
    sessions = _parse_sessions(args.sessions)
    results: list[CorpusResult] = []
    for repo, queries in corpora:
        print(f"replaying {repo.name} ({queries})", file=sys.stderr, flush=True)
        results.append(replay_corpus(
            repo, queries, sessions, limit=args.limit, token_budget=args.token_budget,
            max_tasks=args.max_tasks, log=lambda m: print(m, file=sys.stderr, flush=True)))

    def label(k: Optional[int]) -> str:
        return "all" if k is None else str(k)

    report: dict[str, Any] = {"corpora": {}, "pooled": []}
    for res in results:
        rows = [summarise(label(k), res.totals[k]) for k in sessions]
        report["corpora"][res.name] = {
            "tasks": res.tasks,
            "rows": rows,
            "search_ms_p50": metrics.percentile(res.search_ms, 50),
            "search_ms_p95": metrics.percentile(res.search_ms, 95),
            "update_ms_p50": metrics.percentile(res.update_ms, 50),
        }
        print(f"\n## {res.name} ({res.tasks} tasks; search p50 "
              f"{report['corpora'][res.name]['search_ms_p50']:.1f} ms, update p50 "
              f"{report['corpora'][res.name]['update_ms_p50']:.1f} ms)\n")
        print(format_report(rows))

    pooled_rows = []
    for k in sessions:
        merged = Totals()
        for res in results:
            merged.merge(res.totals[k])
        pooled_rows.append(summarise(label(k), merged))
    report["pooled"] = pooled_rows
    if len(results) > 1:
        print(f"\n## POOLED ({sum(r.tasks for r in results)} tasks, {len(results)} corpora)\n")
        print(format_report(pooled_rows))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(report, indent=2, default=str),
                                       encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
