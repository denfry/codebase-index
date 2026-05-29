#!/usr/bin/env python3
"""Honest benchmark: codebase-index skill vs a realistic no-skill (ripgrep) agent.

Why this exists
---------------
`tests/test_benchmark_comparison.py` is misleading:
  1. It runs on a 29-line toy fixture (`tests/fixtures/sample_repo`).
  2. Its "grep" baseline splits the whole natural-language question into
     keywords *including stopwords* ("the", "is", "how") and matches any of
     them, so the baseline drowns in noise no real agent would generate.
  3. It counts only the index's curated `recommended_reads` line ranges but
     counts *every* grep match line for the baseline -> asymmetric accounting.

This benchmark fixes all three:
  * Runs against a real repository (default: the big NewTowny Java repo).
  * The baseline models what an agent without the skill actually does:
    drop stopwords, search for the *salient* terms, rank files by match
    density, then read a bounded window around the top hits.
  * Token accounting is SYMMETRIC: both sides are charged for the exact
    line ranges they pull into context, measured the same way, deduped
    per file. We report two baseline variants to bracket real behavior:
      - "rg+window":   disciplined agent, reads an N-line window per top hit
      - "rg+wholefile": agent reads each top matched file in full

Honesty notes that are PRINTED with the results:
  * Latency is NOT headlined. The index side shells out to the real CLI
    (process start + import cost included); the baseline is a pure-Python
    scan. Real ripgrep is far faster than this Python scan, so neither
    latency number is a fair "skill vs no-skill" wall-clock claim. We show
    them only for context and label them as such.
  * Index build cost is reported separately and amortized explicitly.

Usage:
    python tests/benchmark_honest.py --repo "C:/Users/denfry/IdeaProjects/NewTowny"
    python tests/benchmark_honest.py --repo <path> --rebuild   # rebuild index first
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path

# --- token estimation (symmetric: identical for both sides) -----------------
try:
    import tiktoken

    _ENC = tiktoken.get_encoding("cl100k_base")

    def count_tokens(text: str) -> int:
        return len(_ENC.encode(text))

    TOKENIZER = "tiktoken/cl100k_base"
except Exception:  # pragma: no cover - fallback when tiktoken missing
    def count_tokens(text: str) -> int:
        return max(0, len(text) // 4)

    TOKENIZER = "chars//4 (tiktoken not installed)"


# --- baseline (no-skill ripgrep agent) configuration ------------------------
WINDOW = 80  # lines read around a hit; matches the index's 80-line code windows
TOP_K = 3    # an agent "starts with rank 1-3" -> reads ~3 files/regions

STOPWORDS = {
    "the", "a", "an", "is", "are", "was", "were", "be", "been", "being",
    "how", "does", "do", "did", "what", "where", "which", "who", "whom",
    "when", "why", "to", "of", "in", "on", "for", "and", "or", "with",
    "from", "down", "up", "it", "this", "that", "these", "those", "i",
    "would", "should", "could", "can", "will", "show", "me", "all", "work",
    "works", "happen", "happens", "other", "into", "during", "if", "rename",
    "use", "used", "uses", "get", "got", "set", "via", "across", "between",
}

TEXT_EXTS = {
    ".java", ".kt", ".ts", ".tsx", ".js", ".jsx", ".mjs", ".py", ".go",
    ".rs", ".rb", ".c", ".h", ".cpp", ".cs", ".yml", ".yaml", ".json",
    ".xml", ".sql", ".md",
}
IGNORE_PARTS = {
    ".git", "node_modules", "__pycache__", ".venv", "venv", "dist",
    "build", "target", ".idea", ".gradle", "out",
}


def salient_terms(query: str) -> list[str]:
    """Extract the terms an agent would actually grep for.

    Keeps CamelCase / identifier-ish tokens whole; drops stopwords and very
    short tokens. This is the single biggest fix vs the old benchmark.
    """
    raw = re.findall(r"[A-Za-z_][A-Za-z0-9_]+", query)
    terms: list[str] = []
    for t in raw:
        if t.lower() in STOPWORDS:
            continue
        if len(t) < 3:
            continue
        terms.append(t)
    # dedup preserve order
    seen: set[str] = set()
    out = []
    for t in terms:
        k = t.lower()
        if k not in seen:
            seen.add(k)
            out.append(t)
    return out


# --- repo file cache --------------------------------------------------------
@dataclass
class RepoFiles:
    root: Path
    files: list[Path] = field(default_factory=list)
    _text_cache: dict[Path, list[str]] = field(default_factory=dict)

    def load(self) -> None:
        for p in self.root.rglob("*"):
            if not p.is_file():
                continue
            if p.suffix.lower() not in TEXT_EXTS:
                continue
            rel = p.relative_to(self.root)
            if any(part in IGNORE_PARTS for part in rel.parts):
                continue
            self.files.append(p)

    def lines(self, p: Path) -> list[str]:
        cached = self._text_cache.get(p)
        if cached is None:
            try:
                cached = p.read_text(encoding="utf-8", errors="ignore").splitlines()
            except OSError:
                cached = []
            self._text_cache[p] = cached
        return cached


def _merge_ranges(ranges: list[tuple[int, int]]) -> list[tuple[int, int]]:
    """Dedup/merge overlapping (start,end) 1-based inclusive line ranges."""
    if not ranges:
        return []
    ranges = sorted(ranges)
    merged = [list(ranges[0])]
    for s, e in ranges[1:]:
        if s <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], e)
        else:
            merged.append([s, e])
    return [(s, e) for s, e in merged]


def _tokens_for_reads(repo: RepoFiles, reads: dict[str, list[tuple[int, int]]]) -> tuple[int, int, int]:
    """Charge tokens for a set of per-file line ranges. Returns (tokens, files, lines)."""
    total_tokens = 0
    total_lines = 0
    nfiles = 0
    for rel, ranges in reads.items():
        p = repo.root / rel
        lines = repo.lines(p)
        if not lines:
            continue
        nfiles += 1
        for s, e in _merge_ranges(ranges):
            s = max(1, s)
            e = min(len(lines), e)
            if e < s:
                continue
            chunk = "\n".join(lines[s - 1 : e])
            total_tokens += count_tokens(chunk)
            total_lines += (e - s + 1)
    return total_tokens, nfiles, total_lines


# --- INDEX side (the skill) -------------------------------------------------
def run_index(repo: RepoFiles, query: str) -> dict:
    start = time.perf_counter()
    proc = subprocess.run(
        [sys.executable, "-m", "codebase_index", "--root", str(repo.root), "--json", "search", query],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    elapsed_ms = (time.perf_counter() - start) * 1000
    try:
        data = json.loads(proc.stdout)
    except json.JSONDecodeError:
        data = {"recommended_reads": [], "results": [], "confidence": "error"}

    results = data.get("results", [])
    rr = data.get("recommended_reads", [])

    def reads_from(entries: list[dict]) -> dict[str, list[tuple[int, int]]]:
        reads: dict[str, list[tuple[int, int]]] = {}
        for r in entries:
            path = r["path"]
            ls = int(r.get("line_start", 1) or 1)
            le = int(r.get("line_end", ls) or ls)
            # A 1..1 "whole-file pointer" means the agent opens the file; charge
            # it like a real read (cap so a giant file does not dominate unfairly).
            if le <= ls:
                le = ls + WINDOW - 1
            reads.setdefault(path, []).append((ls, le))
        return reads

    def context_tokens(entries: list[dict]) -> tuple[int, int, int]:
        """Charge for what ACTUALLY enters context per result: the inline snippet if the
        index returned one, otherwise the pointed-at line range (a real read). Counting only
        recommended_reads would undercount, since inline snippets are real context tokens too.
        """
        pointer_reads: dict[str, list[tuple[int, int]]] = {}
        snippet_tokens = 0
        files: set[str] = set()
        for r in entries:
            files.add(r["path"])
            snip = r.get("snippet")
            if snip:
                snippet_tokens += count_tokens(snip)
            else:
                ls = int(r.get("line_start", 1) or 1)
                le = int(r.get("line_end", ls) or ls)
                if le <= ls:
                    le = ls + WINDOW - 1
                pointer_reads.setdefault(r["path"], []).append((ls, le))
        read_tokens, _, read_lines = _tokens_for_reads(repo, pointer_reads)
        return snippet_tokens + read_tokens, len(files), read_lines

    # Symmetric with the baseline: an agent "starts with rank 1-3". Charge real context
    # (snippets + pointer reads), not just the (often-empty) recommended_reads list.
    topk_tokens, topk_files, topk_lines = context_tokens(results[:TOP_K])
    full_tokens, full_files, _ = context_tokens(results)
    top_files = [r["path"] for r in results][:TOP_K]
    return {
        "elapsed_ms": elapsed_ms,
        "tokens": topk_tokens,           # headline: top-K context, symmetric with baseline
        "files_read": topk_files,
        "lines_read": topk_lines,
        "full_tokens": full_tokens,      # if the agent consumes every returned result
        "full_files": full_files,
        "recommended_reads": len(rr),
        "confidence": data.get("confidence"),
        "n_results": len(results),
        "top_files": top_files,
    }


# --- BASELINE side (no-skill ripgrep agent) ---------------------------------
def run_baseline(repo: RepoFiles, query: str) -> dict:
    terms = salient_terms(query)
    patterns = [re.compile(re.escape(t), re.IGNORECASE) for t in terms]

    start = time.perf_counter()
    # file -> list of matching line numbers
    file_hits: dict[Path, list[int]] = {}
    for p in repo.files:
        lines = repo.lines(p)
        hits: list[int] = []
        for i, line in enumerate(lines, 1):
            if any(pat.search(line) for pat in patterns):
                hits.append(i)
        if hits:
            file_hits[p] = hits
    elapsed_ms = (time.perf_counter() - start) * 1000

    # rank files by number of matching lines (match density proxy)
    ranked = sorted(file_hits.items(), key=lambda kv: len(kv[1]), reverse=True)
    top = ranked[:TOP_K]

    # Variant A: disciplined agent reads an N-line window around densest hit
    window_reads: dict[str, list[tuple[int, int]]] = {}
    # Variant B: agent reads each top matched file in full
    whole_reads: dict[str, list[tuple[int, int]]] = {}
    for p, hits in top:
        rel = str(p.relative_to(repo.root)).replace("\\", "/")
        center = hits[len(hits) // 2]
        window_reads.setdefault(rel, []).append((center - WINDOW // 2, center + WINDOW // 2))
        whole_reads.setdefault(rel, []).append((1, len(repo.lines(p))))

    w_tokens, w_files, w_lines = _tokens_for_reads(repo, window_reads)
    f_tokens, f_files, f_lines = _tokens_for_reads(repo, whole_reads)

    top_files = [str(p.relative_to(repo.root)).replace("\\", "/") for p, _ in top]
    return {
        "terms": terms,
        "elapsed_ms": elapsed_ms,
        "matched_files": len(file_hits),
        "total_match_lines": sum(len(v) for v in file_hits.values()),
        "window_tokens": w_tokens,
        "window_lines": w_lines,
        "wholefile_tokens": f_tokens,
        "wholefile_lines": f_lines,
        "top_files": top_files,
    }


# --- queries: realistic developer questions about the Java codebase ---------
QUERIES = [
    "where is a new town created and persisted",
    "how does the war system damage and capture work",
    "player join event listener registration",
    "battle pass reward catalog and tiers",
    "economy balance deposit and withdraw",
    "where are religions and governments config loaded",
    "admin command handling and permissions",
    "how is player data saved to the database",
    "nether and end resource generation",
    "town experience and level bonus calculation",
]

# --- ground-truth recall@3 (answer-quality gate) ----------------------------
# Each query has an OBJECTIVE answer location: the file that defines the relevant class.
# Ground truth is derived from the Java naming convention (class Foo lives in Foo.java),
# independent of the index, so the index cannot grade its own homework. recall@3 = "did
# the top-3 files surfaced include the file that actually contains the answer?"
#
# Tokens-cheaper-but-wrong is not a win. The skill wins only when recall@3 >= the grep
# baseline AND tokens are lower (plan Task 7 acceptance).
GROUND_TRUTH = [
    ("how does the war system manage capture and sieges", "war/WarManager.java"),
    ("battle pass reward catalog tiers and rewards", "BattlePassCatalog.java"),
    ("religion manager belief and faith handling", "managers/ReligionManager.java"),
    ("new player join welcome listener", "listeners/NewPlayerListener.java"),
    ("admin command handling and dispatch", "commands/AdminCommand.java"),
    ("town banner rendering and management", "banner/TownBannerManager.java"),
    ("quest progress event listener", "quests/listeners/QuestListener.java"),
    ("building bonus calculation manager", "builds/building/BuildingBonusManager.java"),
    ("dynasty persistence repository", "repositories/DynastyRepository.java"),
    ("player skill event listener", "listeners/SkillListener.java"),
]


def _hits_truth(top_files: list[str], truth_suffix: str) -> bool:
    truth = truth_suffix.replace("\\", "/")
    return any(f.replace("\\", "/").endswith(truth) for f in top_files)


def recall_at_3(repo: RepoFiles) -> dict:
    """Run each ground-truth query through both sides; return per-side recall@3."""
    idx_hits = 0
    base_hits = 0
    detail = []
    for q, truth in GROUND_TRUTH:
        idx = run_index(repo, q)
        base = run_baseline(repo, q)
        i_ok = _hits_truth(idx["top_files"], truth)
        b_ok = _hits_truth(base["top_files"], truth)
        idx_hits += int(i_ok)
        base_hits += int(b_ok)
        detail.append((q, truth, i_ok, b_ok, idx["top_files"], base["top_files"]))
    n = len(GROUND_TRUTH)
    return {
        "n": n,
        "index_recall": idx_hits / n,
        "baseline_recall": base_hits / n,
        "detail": detail,
    }


def overlap(a: list[str], b: list[str]) -> int:
    sa = {x.replace("\\", "/") for x in a}
    sb = {x.replace("\\", "/") for x in b}
    return len(sa & sb)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--rebuild", action="store_true")
    args = ap.parse_args()

    root = Path(args.repo).resolve()
    if not root.is_dir():
        print(f"repo not found: {root}", file=sys.stderr)
        return 2

    build_ms = None
    if args.rebuild:
        bstart = time.perf_counter()
        subprocess.run(["codebase-index", "--root", str(root), "index"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace")
        build_ms = (time.perf_counter() - bstart) * 1000

    repo = RepoFiles(root)
    repo.load()

    print(f"\n{'=' * 100}")
    print("  HONEST BENCHMARK  -  codebase-index skill  vs  realistic no-skill (ripgrep) agent")
    print(f"{'=' * 100}")
    print(f"  Repo            : {root}")
    print(f"  Text files seen : {len(repo.files)}")
    print(f"  Token counter   : {TOKENIZER}")
    print(f"  Read model      : top-{TOP_K} hits, {WINDOW}-line window (both sides symmetric)")
    if build_ms is not None:
        print(f"  Index build     : {build_ms:.0f} ms (one-time, amortized over all queries in a session)")
    print("  NOTE: latency below is context-only. Index = real CLI (incl. process start);")
    print("        baseline = pure-Python scan. Real ripgrep is far faster than this scan,")
    print("        so do NOT read these as a skill-vs-no-skill wall-clock claim.")
    print(f"{'=' * 100}\n")

    rows = []
    for q in QUERIES:
        idx = run_index(repo, q)
        base = run_baseline(repo, q)
        rows.append((q, idx, base))

        print(f"Q: {q}")
        print(f"   salient terms     : {base['terms']}")
        print(f"   INDEX (top-{TOP_K})       : {idx['tokens']:>6} tok  | {idx['files_read']} files, {idx['lines_read']} lines"
              f"  | confidence={idx['confidence']}  | {idx['elapsed_ms']:.0f}ms")
        print(f"   INDEX (full plan) : {idx['full_tokens']:>6} tok  | {idx['full_files']} files")
        print(f"   rg + window       : {base['window_tokens']:>6} tok  | {base['window_lines']} lines"
              f"  | {base['matched_files']} files matched, {base['total_match_lines']} match-lines  | {base['elapsed_ms']:.0f}ms")
        print(f"   rg + wholefile    : {base['wholefile_tokens']:>6} tok  | {base['wholefile_lines']} lines")
        print(f"   top-{TOP_K} file overlap : {overlap(idx['top_files'], base['top_files'])}/{TOP_K}")
        print()

    # ---- aggregates ----
    n = len(rows)
    avg_idx = sum(r[1]["tokens"] for r in rows) / n
    avg_idx_full = sum(r[1]["full_tokens"] for r in rows) / n
    avg_win = sum(r[2]["window_tokens"] for r in rows) / n
    avg_whole = sum(r[2]["wholefile_tokens"] for r in rows) / n

    print(f"{'=' * 100}")
    print("  AGGREGATE (tokens that actually enter context to answer the question)")
    print(f"{'-' * 100}")
    print(f"  Avg INDEX (top-{TOP_K})      : {avg_idx:8.0f} tok/query   <- symmetric with baseline")
    print(f"  Avg INDEX (full plan) : {avg_idx_full:8.0f} tok/query   (if agent reads every recommended_read)")
    print(f"  Avg rg + window       : {avg_win:8.0f} tok/query   "
          f"(index top-{TOP_K} uses {pct(avg_idx, avg_win)} of baseline; {ratio(avg_win, avg_idx)} vs index)")
    print(f"  Avg rg + wholefile    : {avg_whole:8.0f} tok/query   "
          f"(index top-{TOP_K} uses {pct(avg_idx, avg_whole)} of baseline; {ratio(avg_whole, avg_idx)} vs index)")
    print(f"{'-' * 100}")
    avg_ov = sum(overlap(r[1]["top_files"], r[2]["top_files"]) for r in rows) / n
    print(f"  Avg top-{TOP_K} file overlap (index vs rg): {avg_ov:.2f}/{TOP_K}"
          "   <- how often both surface the same files")
    print(f"{'=' * 100}\n")

    # ---- answer-quality gate: recall@3 against objective ground truth ----
    rec = recall_at_3(repo)
    print(f"{'=' * 100}")
    print("  ANSWER QUALITY  -  recall@3 vs objective ground truth (file that defines the answer)")
    print(f"{'-' * 100}")
    for q, truth, i_ok, b_ok, _itop, _btop in rec["detail"]:
        print(f"  [{'I' if i_ok else ' '}index {'B' if b_ok else ' '}grep]  {truth:<46} {q}")
    print(f"{'-' * 100}")
    print(f"  Index    recall@3 : {rec['index_recall']*100:5.0f}%  ({int(rec['index_recall']*rec['n'])}/{rec['n']})")
    print(f"  rg+window recall@3: {rec['baseline_recall']*100:5.0f}%  ({int(rec['baseline_recall']*rec['n'])}/{rec['n']})")
    tokens_win = avg_idx <= avg_win
    recall_win = rec["index_recall"] >= rec["baseline_recall"]
    verdict = "WIN" if (tokens_win and recall_win) else "NOT A WIN"
    print(f"{'-' * 100}")
    print(f"  VERDICT: {verdict}  "
          f"(recall@3 {'>=' if recall_win else '<'} baseline AND tokens {'lower' if tokens_win else 'NOT lower'})")
    print(f"{'=' * 100}\n")

    return 0


def ratio(a: float, b: float) -> str:
    if b <= 0:
        return "n/a"
    return f"{a / b:.1f}x"


def pct(a: float, b: float) -> str:
    if b <= 0:
        return "n/a"
    return f"{100 * a / b:.0f}%"


if __name__ == "__main__":
    raise SystemExit(main())
