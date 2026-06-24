# Multi-language Scale Benchmark Campaign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a generic, index-independent multi-language benchmark harness and run it across a public-repo matrix (10k/100k/1M LOC) to produce publishable, roadmap-grade evidence.

**Architecture:** Extract the trusted token/recall accounting from `benchmark_honest.py` into a shared `tests/bench_common.py`. Add a `tests/benchmark_scale.py` that derives ground truth via a zero-dependency regex def-extractor (structurally independent of the index), synthesizes natural-language queries, and measures `recall@3` + symmetric token economy. A `tests/run_scale_campaign.py` orchestrates shallow clone -> index -> run -> cleanup sequentially under a disk guard.

**Tech Stack:** Python 3.11+, `tiktoken` (cl100k_base), `git --depth 1`, the `codebase-index` CLI, `pytest`.

## Global Constraints

- Python 3.11+ (matches `pyproject.toml`).
- Zero new third-party dependencies (regex extractor instead of ctags; `tiktoken` already installed).
- Token accounting MUST be symmetric: identical estimator and read window on index and baseline sides.
- Ground truth MUST be derived independently of the index (regex line-scan), and queries MUST be humanized identifiers, never the raw identifier.
- Disk: ~8.8 GB free on `C:`. Process one repo at a time; delete clone+index before the next. Disk guard: require >= 3 GB free (10k/100k tiers) / >= 5 GB (1M tier) before cloning.
- Every committed headline number cites repo + commit SHA + log file.
- Run all `git`/`pytest`/CLI commands from the project root `C:\Projects\codebase-index`.
- Work happens on branch `bench/multilang-scale-campaign`.

---

### Task 1: Extract shared accounting into `tests/bench_common.py`

Move the trusted, repo-agnostic helpers out of `benchmark_honest.py` so both benchmarks share one estimator. This is a pure move — no behavior change.

**Files:**
- Create: `tests/bench_common.py`
- Modify: `tests/benchmark_honest.py` (delete moved symbols, add import)
- Test: `tests/test_bench_common.py`

**Interfaces:**
- Produces (the public surface other tasks consume):
  - Constants: `WINDOW: int = 80`, `TOP_K: int = 3`, `TOKENIZER: str`, `STOPWORDS: set[str]`, `TEXT_EXTS: set[str]`, `IGNORE_PARTS: set[str]`
  - `count_tokens(text: str) -> int`
  - `salient_terms(query: str) -> list[str]`
  - `class RepoFiles` with `root: Path`, `files: list[Path]`, `load() -> None`, `lines(p: Path) -> list[str]`
  - `merge_ranges(ranges: list[tuple[int,int]]) -> list[tuple[int,int]]` (renamed from `_merge_ranges`)
  - `tokens_for_reads(repo: RepoFiles, reads: dict[str, list[tuple[int,int]]]) -> tuple[int,int,int]` (renamed from `_tokens_for_reads`)
  - `run_index(repo: RepoFiles, query: str) -> dict` (returns keys: `elapsed_ms, tokens, files_read, lines_read, full_tokens, full_files, recommended_reads, confidence, n_results, top_files`)
  - `run_baseline(repo: RepoFiles, query: str) -> dict` (returns keys: `terms, elapsed_ms, matched_files, total_match_lines, window_tokens, window_lines, wholefile_tokens, wholefile_lines, top_files`)
  - `overlap(a: list[str], b: list[str]) -> int`
  - `hits_truth(top_files: list[str], truth_suffix: str) -> bool` (renamed from `_hits_truth`)
  - `ratio(a: float, b: float) -> str`, `pct(a: float, b: float) -> str`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bench_common.py
from pathlib import Path

import tests.bench_common as bc


def test_public_surface_exists():
    for name in [
        "WINDOW", "TOP_K", "TOKENIZER", "STOPWORDS", "TEXT_EXTS", "IGNORE_PARTS",
        "count_tokens", "salient_terms", "RepoFiles", "merge_ranges",
        "tokens_for_reads", "run_index", "run_baseline", "overlap",
        "hits_truth", "ratio", "pct",
    ]:
        assert hasattr(bc, name), f"missing {name}"


def test_merge_ranges_merges_adjacent():
    assert bc.merge_ranges([(1, 5), (6, 9), (20, 25)]) == [(1, 9), (20, 25)]


def test_salient_terms_drops_stopwords():
    terms = bc.salient_terms("how does the war system capture work")
    assert "war" in terms and "system" in terms and "capture" in terms
    assert "how" not in terms and "the" not in terms


def test_count_tokens_positive():
    assert bc.count_tokens("hello world") > 0


def test_hits_truth_suffix_match():
    assert bc.hits_truth(["a/b/WarManager.java"], "war/WarManager.java") is False
    assert bc.hits_truth(["x/war/WarManager.java"], "war/WarManager.java") is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_bench_common.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'tests.bench_common'` (or import error).

- [ ] **Step 3: Create `tests/bench_common.py`**

Move these symbols verbatim from `tests/benchmark_honest.py` into the new module, renaming the underscore-prefixed shared helpers to public names: `_merge_ranges` -> `merge_ranges`, `_tokens_for_reads` -> `tokens_for_reads`, `_hits_truth` -> `hits_truth`. Keep their bodies identical (update internal call sites to the new names). Symbols to move: the tiktoken `count_tokens`/`TOKENIZER` block, `WINDOW`, `TOP_K`, `STOPWORDS`, `TEXT_EXTS`, `IGNORE_PARTS`, `salient_terms`, `RepoFiles`, `merge_ranges`, `tokens_for_reads`, `run_index`, `run_baseline`, `overlap`, `hits_truth`, `ratio`, `pct`.

Add a module docstring:

```python
"""Shared, trusted accounting for codebase-index benchmarks.

Extracted from benchmark_honest.py so the honest (NewTowny) benchmark and the
multi-language scale benchmark use ONE token estimator and ONE baseline, keeping
all numbers symmetric and comparable. No repo-specific queries or ground truth
live here.
"""
```

Ensure `tests/__init__.py` exists (create empty file if absent) so `tests.bench_common` imports.

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_bench_common.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add tests/bench_common.py tests/test_bench_common.py tests/__init__.py
git commit -m "test: extract shared benchmark accounting into bench_common"
```

---

### Task 2: Refactor `benchmark_honest.py` to import from `bench_common` (equivalence-locked)

**Files:**
- Modify: `tests/benchmark_honest.py`
- Test: manual equivalence run against NewTowny

**Interfaces:**
- Consumes: everything from `tests.bench_common` (Task 1).
- Produces: `benchmark_honest.py` keeps `QUERIES`, `GROUND_TRUTH`, `recall_at_3`, `main` only.

- [ ] **Step 1: Capture the baseline output BEFORE refactor**

Run: `python tests/benchmark_honest.py --repo "C:/Users/denfry/IdeaProjects/NewTowny" > C:/Users/denfry/AppData/Local/Temp/claude/C--Projects-codebase-index/dae97416-3101-48f2-90b2-27a61a0ae770/scratchpad/honest_before.txt 2>&1`
Expected: completes; file contains the recall@3 + aggregate tables.

- [ ] **Step 2: Edit `benchmark_honest.py` to delete moved symbols and import them**

Replace the moved definitions with a single import near the top (after `from __future__`):

```python
from tests.bench_common import (
    TOP_K, WINDOW, TOKENIZER,
    RepoFiles, count_tokens, salient_terms,
    run_index, run_baseline, overlap, hits_truth, ratio, pct,
)
```

Update `recall_at_3` to call `hits_truth(...)` instead of `_hits_truth(...)`. Keep `QUERIES`, `GROUND_TRUTH`, and `main()` bodies otherwise unchanged. If `benchmark_honest.py` is run as a script (`python tests/benchmark_honest.py`), ensure the import works by adding at the very top, before other imports:

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
```

- [ ] **Step 3: Capture the output AFTER refactor**

Run: `python tests/benchmark_honest.py --repo "C:/Users/denfry/IdeaProjects/NewTowny" > C:/Users/denfry/AppData/Local/Temp/claude/C--Projects-codebase-index/dae97416-3101-48f2-90b2-27a61a0ae770/scratchpad/honest_after.txt 2>&1`
Expected: completes.

- [ ] **Step 4: Diff to prove equivalence**

Run: `diff C:/Users/denfry/AppData/Local/Temp/claude/C--Projects-codebase-index/dae97416-3101-48f2-90b2-27a61a0ae770/scratchpad/honest_before.txt C:/Users/denfry/AppData/Local/Temp/claude/C--Projects-codebase-index/dae97416-3101-48f2-90b2-27a61a0ae770/scratchpad/honest_after.txt`
Expected: empty diff except possibly per-query `elapsed_ms` lines (latency varies run-to-run). The recall@3 percentages, token aggregates, and VERDICT MUST be identical. If anything else differs, the extraction changed behavior — fix before continuing.

- [ ] **Step 5: Commit**

```bash
git add tests/benchmark_honest.py
git commit -m "refactor: benchmark_honest imports shared bench_common (equivalence-locked)"
```

---

### Task 3: Regex def-extractor + ground-truth builder

**Files:**
- Create: `tests/bench_groundtruth.py`
- Test: `tests/test_bench_groundtruth.py`

**Interfaces:**
- Produces:
  - `LANG_EXTS: dict[str, set[str]]`
  - `split_words(ident: str) -> list[str]`
  - `@dataclass SymbolDef(name: str, file: str, line: int)`
  - `extract_defs(repo_root: Path, language: str, files: list[Path]) -> list[SymbolDef]`
  - `build_ground_truth(repo_root: Path, language: str, files: list[Path], *, target: int = 25, min_lines: int = 30) -> list[tuple[str, str]]` returning `(query_text, truth_file)` pairs.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bench_groundtruth.py
from pathlib import Path

import tests.bench_groundtruth as gt


def test_split_words_camel_and_snake():
    assert gt.split_words("UserAuthService") == ["user", "auth", "service"]
    assert gt.split_words("refresh_access_token") == ["refresh", "access", "token"]
    assert gt.split_words("HTTPServer") == ["http", "server"]


def test_extract_defs_python(tmp_path: Path):
    f = tmp_path / "pkg" / "user_service.py"
    f.parent.mkdir(parents=True)
    f.write_text("class UserService:\n    def do(self):\n        pass\n", encoding="utf-8")
    defs = gt.extract_defs(tmp_path, "python", [f])
    names = {d.name for d in defs}
    assert "UserService" in names


def test_extract_defs_go(tmp_path: Path):
    f = tmp_path / "server.go"
    f.write_text(
        "package main\n"
        "type AuthHandler struct {}\n"
        "func (h *AuthHandler) ServeAuth() {}\n"
        "func StartServer() {}\n",
        encoding="utf-8",
    )
    names = {d.name for d in gt.extract_defs(tmp_path, "go", [f])}
    assert {"AuthHandler", "ServeAuth", "StartServer"} <= names


def test_build_ground_truth_humanizes_and_is_unique(tmp_path: Path):
    a = tmp_path / "UserAuthService.java"
    a.write_text("public class UserAuthService {\n" + "    // body\n" * 40 + "}\n", encoding="utf-8")
    b = tmp_path / "PaymentGateway.java"
    b.write_text("public class PaymentGateway {\n" + "    // body\n" * 40 + "}\n", encoding="utf-8")
    pairs = gt.build_ground_truth(tmp_path, "java", [a, b], target=25, min_lines=10)
    qmap = dict(pairs)
    assert "user auth service" in qmap
    assert qmap["user auth service"].endswith("UserAuthService.java")
    # queries are humanized, never the raw identifier
    assert "UserAuthService" not in qmap
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_bench_groundtruth.py -v`
Expected: FAIL with import error.

- [ ] **Step 3: Implement `tests/bench_groundtruth.py`**

```python
"""Index-independent ground truth for the scale benchmark.

A regex line-scanner finds definition sites (class/type/func) per language. This
is structurally different from the index's Tree-sitter + hybrid pipeline, so the
index cannot grade its own homework. Queries are humanized identifiers
(UserAuthService -> "user auth service"), never the raw identifier.
"""
from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

LANG_EXTS: dict[str, set[str]] = {
    "java": {".java"},
    "kotlin": {".kt"},
    "python": {".py"},
    "typescript": {".ts", ".tsx"},
    "javascript": {".js", ".jsx", ".mjs"},
    "go": {".go"},
}

_DEF_PATTERNS: dict[str, list[re.Pattern[str]]] = {
    "java": [re.compile(r"\b(?:class|interface|enum|record)\s+([A-Z][A-Za-z0-9_]+)")],
    "kotlin": [re.compile(r"\b(?:class|interface|object)\s+([A-Z][A-Za-z0-9_]+)")],
    "python": [
        re.compile(r"^\s*class\s+([A-Za-z_][A-Za-z0-9_]+)"),
        re.compile(r"^def\s+([A-Za-z_][A-Za-z0-9_]+)"),
    ],
    "typescript": [
        re.compile(
            r"^\s*export\s+(?:default\s+)?(?:abstract\s+)?"
            r"(?:class|interface|function|const|type|enum)\s+([A-Za-z_][A-Za-z0-9_]+)"
        ),
        re.compile(r"^\s*(?:abstract\s+)?(?:class|interface)\s+([A-Za-z_][A-Za-z0-9_]+)"),
    ],
    "javascript": [
        re.compile(r"^\s*export\s+(?:default\s+)?(?:class|function|const)\s+([A-Za-z_][A-Za-z0-9_]+)"),
        re.compile(r"^\s*(?:class|function)\s+([A-Za-z_][A-Za-z0-9_]+)"),
    ],
    "go": [
        re.compile(r"^func\s+(?:\([^)]*\)\s+)?([A-Za-z_][A-Za-z0-9_]+)"),
        re.compile(r"^type\s+([A-Za-z_][A-Za-z0-9_]+)\s+(?:struct|interface)\b"),
    ],
}

_WORD = re.compile(r"[A-Z]+(?=[A-Z][a-z])|[A-Z]?[a-z0-9]+|[A-Z]+")


def split_words(ident: str) -> list[str]:
    words: list[str] = []
    for part in re.split(r"_+", ident):
        words.extend(_WORD.findall(part))
    return [w.lower() for w in words if w]


@dataclass(frozen=True)
class SymbolDef:
    name: str
    file: str
    line: int


def extract_defs(repo_root: Path, language: str, files: list[Path]) -> list[SymbolDef]:
    patterns = _DEF_PATTERNS[language]
    out: list[SymbolDef] = []
    for p in files:
        try:
            text = p.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        rel = str(p.relative_to(repo_root)).replace("\\", "/")
        for i, line in enumerate(text.splitlines(), 1):
            for pat in patterns:
                m = pat.search(line)
                if m:
                    out.append(SymbolDef(m.group(1), rel, i))
                    break
    return out


def build_ground_truth(
    repo_root: Path,
    language: str,
    files: list[Path],
    *,
    target: int = 25,
    min_lines: int = 30,
) -> list[tuple[str, str]]:
    defs = extract_defs(repo_root, language, files)

    name_files: dict[str, set[str]] = defaultdict(set)
    for d in defs:
        name_files[d.name].add(d.file)

    line_counts: dict[str, int] = {}

    def file_lines(rel: str) -> int:
        if rel not in line_counts:
            p = repo_root / rel
            try:
                line_counts[rel] = sum(1 for ln in p.read_text(encoding="utf-8", errors="ignore").splitlines() if ln.strip())
            except OSError:
                line_counts[rel] = 0
        return line_counts[rel]

    candidates: list[SymbolDef] = []
    seen: set[str] = set()
    for d in sorted(defs, key=lambda x: (x.name, x.file)):
        if d.name in seen:
            continue
        if len(name_files[d.name]) != 1:
            continue
        if len(split_words(d.name)) < 2:
            continue
        if file_lines(d.file) < min_lines:
            continue
        seen.add(d.name)
        candidates.append(d)

    if len(candidates) > target:
        step = len(candidates) / target
        sampled = [candidates[int(i * step)] for i in range(target)]
    else:
        sampled = candidates

    return [(" ".join(split_words(d.name)), d.file) for d in sampled]
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `python -m pytest tests/test_bench_groundtruth.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add tests/bench_groundtruth.py tests/test_bench_groundtruth.py
git commit -m "feat: index-independent regex ground-truth extractor for scale benchmark"
```

---

### Task 4: Single-repo scale harness `tests/benchmark_scale.py`

**Files:**
- Create: `tests/benchmark_scale.py`
- Test: `tests/test_benchmark_scale.py`

**Interfaces:**
- Consumes: `tests.bench_common` (run_index, run_baseline, RepoFiles, overlap, hits_truth, TOP_K), `tests.bench_groundtruth` (build_ground_truth, LANG_EXTS).
- Produces:
  - `count_code_loc(repo: RepoFiles, language: str) -> int`
  - `tier_for(code_loc: int) -> str` (returns `"10k" | "100k" | "1M" | "other"`)
  - `run_repo(repo_root: Path, language: str, *, label: str, sha: str | None = None, build_ms: float | None = None, target: int = 25) -> dict`
  - `format_report(result: dict) -> str` (human-readable log text)
  - CLI `main()` so `python tests/benchmark_scale.py --repo <path> --language python` works standalone.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_benchmark_scale.py
from pathlib import Path

import tests.benchmark_scale as bs


def test_tier_for_bands():
    assert bs.tier_for(12_000) == "10k"
    assert bs.tier_for(120_000) == "100k"
    assert bs.tier_for(800_000) == "1M"
    assert bs.tier_for(100) == "other"


def test_run_repo_on_tiny_python_fixture(tmp_path: Path):
    (tmp_path / ".gitignore").write_text(".claude/cache/codebase-index/\n", encoding="utf-8")
    svc = tmp_path / "user_service.py"
    svc.write_text("class UserService:\n" + "    x = 1\n" * 40, encoding="utf-8")
    pay = tmp_path / "payment_gateway.py"
    pay.write_text("class PaymentGateway:\n" + "    y = 2\n" * 40, encoding="utf-8")

    # build the index via the CLI first
    import subprocess, sys
    subprocess.run([sys.executable, "-m", "codebase_index", "--root", str(tmp_path), "index"],
                   capture_output=True, text=True)

    result = bs.run_repo(tmp_path, "python", label="fixture", target=5)
    assert result["n_queries"] >= 1
    assert "index_recall_at_3" in result
    assert "baseline_recall_at_3" in result
    assert result["code_loc"] > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_benchmark_scale.py -v`
Expected: FAIL with import error.

- [ ] **Step 3: Implement `tests/benchmark_scale.py`**

```python
#!/usr/bin/env python3
"""Generic multi-language scale benchmark for codebase-index.

For a single repo: derive index-independent ground truth (regex extractor),
synthesize natural-language queries, then measure recall@3 + symmetric token
economy for the index vs an rg+window baseline. Shares ALL accounting with
benchmark_honest.py via bench_common, so numbers are comparable.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.bench_common import (  # noqa: E402
    TOKENIZER, TOP_K, RepoFiles, hits_truth, overlap, run_baseline, run_index,
)
from tests.bench_groundtruth import LANG_EXTS, build_ground_truth  # noqa: E402


def count_code_loc(repo: RepoFiles, language: str) -> int:
    exts = LANG_EXTS[language]
    total = 0
    for p in repo.files:
        if p.suffix.lower() in exts:
            total += sum(1 for ln in repo.lines(p) if ln.strip())
    return total


def tier_for(code_loc: int) -> str:
    if 5_000 <= code_loc < 30_000:
        return "10k"
    if 60_000 <= code_loc < 300_000:
        return "100k"
    if code_loc >= 600_000:
        return "1M"
    return "other"


def run_repo(
    repo_root: Path,
    language: str,
    *,
    label: str,
    sha: str | None = None,
    build_ms: float | None = None,
    target: int = 25,
) -> dict:
    repo = RepoFiles(repo_root)
    repo.load()

    lang_files = [p for p in repo.files if p.suffix.lower() in LANG_EXTS[language]]
    pairs = build_ground_truth(repo_root, language, lang_files, target=target)

    rows = []
    idx_hits = base_hits = 0
    idx_tok_sum = base_tok_sum = ov_sum = 0
    for query, truth in pairs:
        idx = run_index(repo, query)
        base = run_baseline(repo, query)
        i_ok = hits_truth(idx["top_files"], truth)
        b_ok = hits_truth(base["top_files"], truth)
        idx_hits += int(i_ok)
        base_hits += int(b_ok)
        idx_tok_sum += idx["tokens"]
        base_tok_sum += base["window_tokens"]
        ov_sum += overlap(idx["top_files"], base["top_files"])
        rows.append({
            "query": query, "truth": truth,
            "index_ok": i_ok, "baseline_ok": b_ok,
            "index_top": idx["top_files"], "baseline_top": base["top_files"],
            "index_tokens": idx["tokens"], "baseline_window_tokens": base["window_tokens"],
        })

    n = len(pairs) or 1
    return {
        "label": label,
        "language": language,
        "sha": sha,
        "code_loc": count_code_loc(repo, language),
        "files_indexed_text": len(repo.files),
        "lang_files": len(lang_files),
        "tier": tier_for(count_code_loc(repo, language)),
        "tokenizer": TOKENIZER,
        "build_ms": build_ms,
        "n_queries": len(pairs),
        "index_recall_at_3": idx_hits / n,
        "baseline_recall_at_3": base_hits / n,
        "index_tokens_avg": idx_tok_sum / n,
        "baseline_window_tokens_avg": base_tok_sum / n,
        "avg_overlap_at_3": ov_sum / n,
        "rows": rows,
    }


def format_report(r: dict) -> str:
    out = []
    out.append("=" * 100)
    out.append(f"  SCALE BENCHMARK  -  {r['label']}  ({r['language']})")
    out.append("=" * 100)
    out.append(f"  SHA            : {r['sha']}")
    out.append(f"  code_loc       : {r['code_loc']:,}  ({r['lang_files']} {r['language']} files; tier={r['tier']})")
    out.append(f"  text files     : {r['files_indexed_text']}")
    out.append(f"  tokenizer      : {r['tokenizer']}")
    if r["build_ms"] is not None:
        out.append(f"  index build    : {r['build_ms']:.0f} ms")
    out.append(f"  queries        : {r['n_queries']} (humanized identifiers, index-independent ground truth)")
    out.append("-" * 100)
    for row in r["rows"]:
        flag = f"[{'I' if row['index_ok'] else ' '}index {'B' if row['baseline_ok'] else ' '}grep]"
        out.append(f"  {flag}  {row['truth']:<55} q: {row['query']}")
    out.append("-" * 100)
    out.append(f"  Index    recall@3 : {r['index_recall_at_3']*100:5.0f}%")
    out.append(f"  rg+window recall@3: {r['baseline_recall_at_3']*100:5.0f}%")
    out.append(f"  Index    tok/query: {r['index_tokens_avg']:8.0f}")
    out.append(f"  rg+window tok/query: {r['baseline_window_tokens_avg']:8.0f}")
    out.append(f"  avg top-{TOP_K} overlap : {r['avg_overlap_at_3']:.2f}/{TOP_K}")
    tokens_win = r["index_tokens_avg"] <= r["baseline_window_tokens_avg"]
    recall_win = r["index_recall_at_3"] >= r["baseline_recall_at_3"]
    verdict = "WIN" if (tokens_win and recall_win) else "NOT A WIN"
    out.append(f"  VERDICT: {verdict}")
    out.append("=" * 100)
    return "\n".join(out)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--language", required=True, choices=sorted(LANG_EXTS))
    ap.add_argument("--label", default=None)
    ap.add_argument("--target", type=int, default=25)
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args()

    root = Path(args.repo).resolve()
    if not root.is_dir():
        print(f"repo not found: {root}", file=sys.stderr)
        return 2
    result = run_repo(root, args.language, label=args.label or root.name, target=args.target)
    print(format_report(result))
    if args.json_out:
        Path(args.json_out).write_text(json.dumps(result, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `python -m pytest tests/test_benchmark_scale.py -v`
Expected: PASS (2 tests). (The second test shells out to the CLI to build a tiny index — allow it a few seconds.)

- [ ] **Step 5: Commit**

```bash
git add tests/benchmark_scale.py tests/test_benchmark_scale.py
git commit -m "feat: single-repo multi-language scale benchmark harness"
```

---

### Task 5: Repo manifest `tests/bench_repos.json`

**Files:**
- Create: `tests/bench_repos.json`

**Interfaces:**
- Produces: a JSON array of `{name, url, language, expected_tier}` consumed by the campaign runner (Task 6). No SHA here — the runner records the resolved SHA at clone time.

- [ ] **Step 1: Create the manifest**

```json
[
  {"name": "flask",                "url": "https://github.com/pallets/flask.git",                "language": "python",     "expected_tier": "10k"},
  {"name": "gin",                  "url": "https://github.com/gin-gonic/gin.git",                "language": "go",         "expected_tier": "10k"},
  {"name": "nest",                 "url": "https://github.com/nestjs/nest.git",                  "language": "typescript", "expected_tier": "100k"},
  {"name": "guava",                "url": "https://github.com/google/guava.git",                 "language": "java",       "expected_tier": "100k"},
  {"name": "spring-framework",     "url": "https://github.com/spring-projects/spring-framework.git", "language": "java",   "expected_tier": "1M"},
  {"name": "kubernetes",           "url": "https://github.com/kubernetes/kubernetes.git",        "language": "go",         "expected_tier": "1M"}
]
```

- [ ] **Step 2: Validate it parses**

Run: `python -c "import json; d=json.load(open('tests/bench_repos.json')); print(len(d), 'repos:', [r['name'] for r in d])"`
Expected: `6 repos: ['flask', 'gin', 'nest', 'guava', 'spring-framework', 'kubernetes']`

- [ ] **Step 3: Commit**

```bash
git add tests/bench_repos.json
git commit -m "feat: scale-benchmark public-repo manifest"
```

---

### Task 6: Sequential campaign runner `tests/run_scale_campaign.py`

**Files:**
- Create: `tests/run_scale_campaign.py`
- Create: `docs/benchmarks/.gitkeep`

**Interfaces:**
- Consumes: `tests.benchmark_scale` (run_repo, format_report), the manifest from Task 5.
- Produces: per-repo `docs/benchmarks/<name>_<sha7>.txt` and `.json`; orchestration only.

- [ ] **Step 1: Implement the runner**

```python
#!/usr/bin/env python3
"""Sequential, disk-safe scale-benchmark campaign runner.

For each repo in the manifest: disk-guard -> shallow clone -> record SHA ->
index (timed) -> run_repo -> write log+json into docs/benchmarks/ -> delete the
clone. Peak disk = one repo at a time. Designed for the ~8.8 GB-free C: drive.
"""
from __future__ import annotations

import argparse
import json
import shutil
import stat
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from tests.benchmark_scale import format_report, run_repo  # noqa: E402

DISK_MIN = {"10k": 3 * 2**30, "100k": 3 * 2**30, "1M": 5 * 2**30, "other": 3 * 2**30}


def _on_rm_error(func, path, exc_info):
    # Windows: clear read-only bit on .git objects, then retry.
    try:
        Path(path).chmod(stat.S_IWRITE)
        func(path)
    except OSError:
        pass


def free_bytes(path: Path) -> int:
    return shutil.disk_usage(path).free


def clone(url: str, dest: Path) -> str | None:
    if dest.exists():
        shutil.rmtree(dest, onerror=_on_rm_error)
    proc = subprocess.run(
        ["git", "clone", "--depth", "1", url, str(dest)],
        capture_output=True, text=True,
    )
    if proc.returncode != 0:
        print(f"  clone FAILED: {proc.stderr.strip()[:300]}", file=sys.stderr)
        return None
    sha = subprocess.run(
        ["git", "-C", str(dest), "rev-parse", "HEAD"],
        capture_output=True, text=True,
    ).stdout.strip()
    return sha


def index_repo(dest: Path) -> float:
    start = time.perf_counter()
    subprocess.run(
        [sys.executable, "-m", "codebase_index", "--root", str(dest), "index"],
        capture_output=True, text=True,
    )
    return (time.perf_counter() - start) * 1000


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="tests/bench_repos.json")
    ap.add_argument("--workdir", default="C:/bench-tmp")
    ap.add_argument("--outdir", default="docs/benchmarks")
    ap.add_argument("--only", default=None, help="comma-separated repo names to run")
    ap.add_argument("--target", type=int, default=25)
    ap.add_argument("--keep", action="store_true", help="do not delete clones")
    args = ap.parse_args()

    manifest = json.loads(Path(args.manifest).read_text(encoding="utf-8"))
    if args.only:
        wanted = {x.strip() for x in args.only.split(",")}
        manifest = [m for m in manifest if m["name"] in wanted]

    workdir = Path(args.workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    summary = []
    for m in manifest:
        name, url, lang, tier = m["name"], m["url"], m["language"], m["expected_tier"]
        print(f"\n>>> {name} ({lang}, expected {tier})")
        need = DISK_MIN.get(tier, 3 * 2**30)
        if free_bytes(workdir) < need:
            print(f"  SKIP: insufficient disk ({free_bytes(workdir)//2**30} GB < {need//2**30} GB)")
            summary.append({"name": name, "status": "skipped_disk"})
            continue

        dest = workdir / name
        sha = clone(url, dest)
        if not sha:
            summary.append({"name": name, "status": "clone_failed"})
            continue
        print(f"  SHA {sha[:7]}  free {free_bytes(workdir)//2**30} GB")

        build_ms = index_repo(dest)
        print(f"  indexed in {build_ms:.0f} ms")

        try:
            result = run_repo(dest, lang, label=name, sha=sha, build_ms=build_ms, target=args.target)
        except Exception as exc:  # noqa: BLE001
            print(f"  run FAILED: {exc}", file=sys.stderr)
            summary.append({"name": name, "status": f"run_failed:{exc}"})
            if not args.keep:
                shutil.rmtree(dest, onerror=_on_rm_error)
            continue

        sha7 = sha[:7]
        (outdir / f"{name}_{sha7}.txt").write_text(format_report(result), encoding="utf-8")
        (outdir / f"{name}_{sha7}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
        print(format_report(result))

        summary.append({
            "name": name, "status": "ok", "sha": sha, "tier": result["tier"],
            "code_loc": result["code_loc"],
            "index_recall_at_3": result["index_recall_at_3"],
            "baseline_recall_at_3": result["baseline_recall_at_3"],
            "index_tokens_avg": result["index_tokens_avg"],
            "baseline_window_tokens_avg": result["baseline_window_tokens_avg"],
            "build_ms": result["build_ms"],
        })

        if not args.keep:
            shutil.rmtree(dest, onerror=_on_rm_error)
            cache = dest  # index lives under dest/.claude; removed with the clone
            print(f"  cleaned up; free {free_bytes(workdir)//2**30} GB")

    (outdir / "campaign_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print("\n=== CAMPAIGN SUMMARY ===")
    for s in summary:
        print(s)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
```

- [ ] **Step 2: Create the output dir placeholder**

Run: create empty file `docs/benchmarks/.gitkeep`.

- [ ] **Step 3: Sanity-check the runner parses and shows help**

Run: `python tests/run_scale_campaign.py --help`
Expected: argparse help text with `--only`, `--workdir`, `--outdir`.

- [ ] **Step 4: Commit**

```bash
git add tests/run_scale_campaign.py docs/benchmarks/.gitkeep
git commit -m "feat: sequential disk-safe scale-benchmark campaign runner"
```

---

### Task 7: Smoke-run the two smallest repos

**Files:**
- Produces: `docs/benchmarks/flask_*.txt|json`, `docs/benchmarks/gin_*.txt|json`

- [ ] **Step 1: Run the 10k tier only**

Run: `python tests/run_scale_campaign.py --only flask,gin`
Expected: each repo clones, indexes, prints a report with non-empty `n_queries`, a recall@3 for both sides, and a VERDICT; clones are cleaned up; `campaign_summary.json` written.

- [ ] **Step 2: Sanity-check the outputs**

Run: `python -c "import json,glob; [print(f, json.load(open(f))['n_queries'], json.load(open(f))['index_recall_at_3']) for f in glob.glob('docs/benchmarks/flask_*.json')+glob.glob('docs/benchmarks/gin_*.json')]"`
Expected: prints each file with `n_queries >= 5` and a recall fraction in `[0,1]`. If `n_queries` is 0, the language detection or extractor patterns need fixing before scaling up.

- [ ] **Step 3: Commit the 10k-tier evidence**

```bash
git add docs/benchmarks/flask_*.txt docs/benchmarks/flask_*.json docs/benchmarks/gin_*.txt docs/benchmarks/gin_*.json docs/benchmarks/campaign_summary.json
git commit -m "bench: 10k-tier scale results (flask, gin)"
```

---

### Task 8: Run the 100k and 1M tiers

**Files:**
- Produces: `docs/benchmarks/{nest,guava,spring-framework,kubernetes}_*.txt|json`

- [ ] **Step 1: Run the 100k tier**

Run: `python tests/run_scale_campaign.py --only nest,guava`
Expected: both clone/index/run; reports written. Watch the printed free-GB after each cleanup.

- [ ] **Step 2: Run the 1M tier (heaviest; may take many minutes)**

Run: `python tests/run_scale_campaign.py --only spring-framework,kubernetes`
Expected: each large repo clones shallow, indexes (build_ms will be large), runs, and is cleaned up. If a repo is skipped for disk or the clone fails, that is recorded in `campaign_summary.json` as `skipped_disk`/`clone_failed` — note it and, if `kubernetes` fails on disk, either free space or substitute a lighter ~1M Go repo and rerun just that cell.

- [ ] **Step 3: Sanity-check all six results exist or are accounted for**

Run: `python -c "import json; s=json.load(open('docs/benchmarks/campaign_summary.json')); [print(r['name'], r['status'], r.get('tier'), r.get('code_loc')) for r in s]"`
Expected: a line per repo; each either `ok` with a tier+LOC or an explicit skip/fail reason.

- [ ] **Step 4: Commit the remaining evidence**

```bash
git add docs/benchmarks/
git commit -m "bench: 100k and 1M-tier scale results"
```

---

### Task 9: Aggregate results doc + roadmap update

**Files:**
- Create: `docs/SCALE_BENCHMARK_RESULTS.md`
- Modify: `docs/BENCHMARKS.md` (tick achieved TODO items)
- Test: link/consistency self-check

**Interfaces:**
- Consumes: `docs/benchmarks/campaign_summary.json` + per-repo logs.

- [ ] **Step 1: Generate the aggregate table**

Run: `python -c "import json; s=json.load(open('docs/benchmarks/campaign_summary.json')); ok=[r for r in s if r['status']=='ok']; [print(f\"| {r['name']} | {r.get('tier')} | {r['code_loc']:,} | {r['sha'][:7]} | {r['index_recall_at_3']*100:.0f}% | {r['baseline_recall_at_3']*100:.0f}% | {r['index_tokens_avg']:.0f} | {r['baseline_window_tokens_avg']:.0f} | {r['build_ms']:.0f} |\") for r in ok]"`
Expected: one Markdown table row per successful repo. Copy these rows into the doc.

- [ ] **Step 2: Write `docs/SCALE_BENCHMARK_RESULTS.md`**

Use this skeleton, pasting the generated rows and reading the per-repo logs for the per-tier narrative:

```markdown
# Scale benchmark — codebase-index across a multi-language public-repo matrix

Harness: `tests/benchmark_scale.py` + `tests/run_scale_campaign.py`
Ground truth: index-independent regex def-extractor (`tests/bench_groundtruth.py`)
Token counter: tiktoken cl100k_base — identical estimator both sides.
Read model: top-3 hits, 80-line window — symmetric on both sides.
Raw logs: `docs/benchmarks/<repo>_<sha7>.txt`. Run date: 2026-06-24.

## Method (why these numbers are honest)

- Ground truth derived by regex line-scan (class/type/func -> defining file),
  structurally different from the index's Tree-sitter+hybrid pipeline.
- Queries are humanized identifiers ("user auth service"), never the raw
  identifier, so the index must retrieve, not echo.
- Symmetric per-file deduped line-range token accounting on both sides.
- Latency is NOT headlined (index = real CLI incl. process start; baseline =
  pure-Python scan).

## Results

| Repo | Tier | code_loc | SHA | Index recall@3 | rg recall@3 | Index tok/q | rg tok/q | Build ms |
|---|---|---|---|---|---|---|---|---|
<!-- generated rows here -->

## Per-tier reading

- 10k: ...
- 100k: ...
- 1M: ... (note any partial/skipped cell and why)

## What we still cannot claim

- Anything about a skipped/failed cell.
- Latency / wall-clock superiority.
- Per-language quality beyond the languages actually run.
```

- [ ] **Step 3: Tick achieved items in `docs/BENCHMARKS.md`**

Edit the "Remaining benchmark work (TODO checklist)" section: change `[ ]` to `[x]` ONLY for tiers that produced an `ok` result with committed logs (10k LOC, 100k LOC, multi-language; 1M LOC only if it actually completed). Add a one-line pointer to `docs/SCALE_BENCHMARK_RESULTS.md` next to each ticked item. Leave any skipped/failed tier unticked with a note.

- [ ] **Step 4: Consistency self-check**

Run: `python -c "import re,glob,json; s=json.load(open('docs/benchmarks/campaign_summary.json')); doc=open('docs/SCALE_BENCHMARK_RESULTS.md',encoding='utf-8').read(); [print('MISSING in doc:', r['name']) for r in s if r['status']=='ok' and r['sha'][:7] not in doc]"`
Expected: no `MISSING in doc:` lines — every successful repo's SHA appears in the results doc.

- [ ] **Step 5: Commit**

```bash
git add docs/SCALE_BENCHMARK_RESULTS.md docs/BENCHMARKS.md
git commit -m "docs: aggregate scale-benchmark results + roadmap tick"
```

---

### Task 10: Full regression + branch wrap-up

- [ ] **Step 1: Run the whole test suite**

Run: `python -m pytest -q`
Expected: all pass (including the new `test_bench_common.py`, `test_bench_groundtruth.py`, `test_benchmark_scale.py`).

- [ ] **Step 2: Lint the new files**

Run: `ruff check tests/bench_common.py tests/bench_groundtruth.py tests/benchmark_scale.py tests/run_scale_campaign.py`
Expected: no errors (fix any reported).

- [ ] **Step 3: Confirm `C:/bench-tmp` is empty (no leftover clones)**

Run: `python -c "import os; p='C:/bench-tmp'; print(os.listdir(p) if os.path.isdir(p) else 'gone')"`
Expected: `[]` or `gone`. If clones remain, remove them.

- [ ] **Step 4: Final status + offer PR**

Run: `git log --oneline main..HEAD`
Expected: the chain of commits from this plan. Then offer to open a PR to `main`.

---

## Self-Review

**Spec coverage:**
- §1 architecture -> Tasks 1,3,4,5,6 (every module created).
- §2 ground-truth method -> Task 3 (extractor) + Task 4 (recall wiring); humanized-query honesty guard tested in Task 3 Step 1.
- §2 Constants (25 queries, 30 min lines, multi-word, LOC bands) -> Task 3 `build_ground_truth` defaults + Task 4 `tier_for`.
- §3 repo matrix -> Task 5 manifest; substitution path -> Task 8 Step 2.
- §4 deliverables -> Tasks 7,8 (logs+json), Task 9 (aggregate + roadmap).
- §5 disk-safe procedure -> Task 6 (`DISK_MIN`, sequential cleanup, `_on_rm_error`).
- §6 testing -> equivalence (Task 2), extractor units (Task 3), runner smoke (Task 7), full suite (Task 10).

**Placeholder scan:** No "TBD"/"handle edge cases" — the results-doc narrative ("...") in Task 9 is intentional prose to fill from real logs, gated by the consistency check in Step 4.

**Type consistency:** `run_index`/`run_baseline` return-dict keys used in Task 4 (`top_files`, `tokens`, `window_tokens`) match the keys produced in Task 1's moved functions. `build_ground_truth` returns `list[tuple[str,str]]` and Task 4 unpacks `(query, truth)`. `hits_truth` name consistent across Tasks 1, 2, 4.
