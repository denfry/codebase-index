"""Benchmark: index-based search vs grep-based search.

Measures wall-clock time and estimated token count for answering
"where is X implemented?" style questions using:
1. The codebase-index hybrid search (index-based, in-memory API)
2. Pure file scanning (grep-based)

Run: pytest tests/test_benchmark_comparison.py -v --tb=short -s
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path

import pytest

from codebase_index.config import Config
from codebase_index.indexer.pipeline import build_index
from codebase_index.retrieval.pipeline import search
from codebase_index.storage.db import Database

QUERIES = [
    "where is auth token refresh implemented",
    "how does the User model work",
    "who calls send_email",
    "find the database connection setup",
    "explain the retrieval pipeline architecture",
]

COMPLEX_QUERIES = [
    # Multi-hop: what files depend on User model and how
    "what files import or reference the User class and what do they do with it",
    # Cross-file dependency chain
    "trace how refresh_access_token is called from the API layer down to the database",
    # Architectural understanding
    "how does the indexing pipeline flow from file discovery to storing vectors in the database",
    # Refactoring impact
    "if I rename the build_index function what other files and symbols would break",
    # Symbol resolution across boundaries
    "show me all unresolved symbol references and which files they appear in",
    # Intent classification test
    "what is the difference between hybrid search and vector search modes",
    # Configuration + behavior
    "how does the config system work and what options control chunking behavior",
    # Graph / edge analysis
    "which symbols have the highest incoming degree and what calls them",
    # Performance-related
    "where are the token estimation calculations done and how is the budget applied during search",
    # Error handling
    "how does the system handle parse failures and missing tree-sitter grammars",
]


def _estimate_tokens_from_chars(char_count: int) -> int:
    """Rough token count: ~4 chars per token for English/code."""
    return max(1, char_count // 4)


def _run_index_search(db: Database, query: str, root: Path) -> tuple[float, int, int]:
    """Run codebase-index search via in-memory API."""
    start = time.perf_counter()
    result = search(
        db.conn, query,
        mode="hybrid", limit=10, token_budget=5000, no_fallback=False,
    )
    elapsed_ms = (time.perf_counter() - start) * 1000

    # Count tokens from recommended_reads only (what the LLM actually reads)
    total_chars = 0
    for rr in result.get("recommended_reads", [])[:5]:
        try:
            p = root / rr["path"]
            if p.exists():
                lines = p.read_text(encoding="utf-8", errors="ignore").splitlines()
                ls = rr.get("line_start", 1)
                le = rr.get("line_end", ls + 20)
                snippet = "\n".join(lines[ls - 1 : le])
                total_chars += len(snippet)
        except Exception:
            pass

    return elapsed_ms, _estimate_tokens_from_chars(total_chars), len(result.get("results", []))


def _run_grep_search(cwd: Path, query: str) -> tuple[float, int, int]:
    """Run Python-based file search mimicking ripgrep fallback."""
    keywords = [kw.lower() for kw in query.split()]
    start = time.perf_counter()

    all_matches: list[str] = []
    for ext in ("*.py", "*.md", "*.ts", "*.js", "*.json", "*.yaml", "*.yml", "*.toml", "*.cfg", "*.txt"):
        for f in cwd.rglob(ext):
            rel = f.relative_to(cwd)
            if any(part in (".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build") for part in rel.parts):
                continue
            try:
                text = f.read_text(encoding="utf-8", errors="ignore")
                lines = text.splitlines()
                for i, line in enumerate(lines, 1):
                    low = line.lower()
                    if any(kw in low for kw in keywords):
                        all_matches.append(f"{rel}:{i}:{line}")
            except (OSError, PermissionError):
                pass

    elapsed_ms = (time.perf_counter() - start) * 1000
    combined = "\n".join(all_matches)
    line_count = len(all_matches)

    return elapsed_ms, _estimate_tokens_from_chars(len(combined)), line_count


def _build_fresh_index(sample_repo: Path, tmp_path: Path) -> Database:
    cfg = Config()
    cfg.root = str(sample_repo)
    cfg.embeddings.enabled = False
    db = Database(tmp_path / "bench_index.sqlite").open()
    build_index(cfg, db, root=sample_repo)
    return db


@dataclass
class BenchmarkResult:
    query: str
    method: str
    elapsed_ms: float
    estimated_tokens: int
    result_count: int


class TestBenchmarkComparison:
    @pytest.fixture(autouse=True)
    def _setup_index(self, sample_repo: Path, tmp_path: Path):
        self.db = _build_fresh_index(sample_repo, tmp_path)
        self.cwd = sample_repo
        yield
        self.db.close()

    @pytest.mark.parametrize("query", QUERIES)
    def test_comparison(self, query: str):
        idx_time, idx_tokens, idx_count = _run_index_search(self.db, query, self.cwd)
        grep_time, grep_tokens, grep_count = _run_grep_search(self.cwd, query)

        print(f"\n--- Query: '{query}' ---")
        print(f"Index:  {idx_time:.0f}ms, ~{idx_tokens} tokens, {idx_count} results")
        print(f"Grep:   {grep_time:.0f}ms, ~{grep_tokens} tokens, {grep_count} results")
        if grep_time > 0:
            print(f"Speedup: {grep_time / max(idx_time, 0.01):.1f}x")
        print(f"Token delta: {grep_tokens - idx_tokens:+d}")

    def test_summary_report(self):
        results: list[BenchmarkResult] = []

        for query in QUERIES:
            idx_time, idx_tokens, idx_count = _run_index_search(self.db, query, self.cwd)
            grep_time, grep_tokens, grep_count = _run_grep_search(self.cwd, query)

            results.append(BenchmarkResult(query, "index", idx_time, idx_tokens, idx_count))
            results.append(BenchmarkResult(query, "grep", grep_time, grep_tokens, grep_count))

        _print_table(results, "Simple Queries Benchmark")

        avg_idx_time = sum(r.elapsed_ms for r in results if r.method == "index") / len(QUERIES)
        avg_grep_time = sum(r.elapsed_ms for r in results if r.method == "grep") / len(QUERIES)
        avg_idx_tokens = sum(r.estimated_tokens for r in results if r.method == "index") / len(QUERIES)
        avg_grep_tokens = sum(r.estimated_tokens for r in results if r.method == "grep") / len(QUERIES)

        _print_averages(avg_idx_time, avg_grep_time, avg_idx_tokens, avg_grep_tokens)

    def test_complex_summary_report(self):
        results: list[BenchmarkResult] = []

        for query in COMPLEX_QUERIES:
            idx_time, idx_tokens, idx_count = _run_index_search(self.db, query, self.cwd)
            grep_time, grep_tokens, grep_count = _run_grep_search(self.cwd, query)

            results.append(BenchmarkResult(query, "index", idx_time, idx_tokens, idx_count))
            results.append(BenchmarkResult(query, "grep", grep_time, grep_tokens, grep_count))

        _print_table(results, "Complex Queries Benchmark")

        avg_idx_time = sum(r.elapsed_ms for r in results if r.method == "index") / len(COMPLEX_QUERIES)
        avg_grep_time = sum(r.elapsed_ms for r in results if r.method == "grep") / len(COMPLEX_QUERIES)
        avg_idx_tokens = sum(r.estimated_tokens for r in results if r.method == "index") / len(COMPLEX_QUERIES)
        avg_grep_tokens = sum(r.estimated_tokens for r in results if r.method == "grep") / len(COMPLEX_QUERIES)

        _print_averages(avg_idx_time, avg_grep_time, avg_idx_tokens, avg_grep_tokens)


def _truncate(s: str, width: int) -> str:
    if len(s) <= width:
        return s
    return s[: width - 1] + "…"


def _print_table(results: list[BenchmarkResult], title: str) -> None:
    queries = [r.query for r in results if r.method == "index"]
    label_map: dict[str, str] = {}
    for i, q in enumerate(queries, 1):
        label_map[q] = f"Q{i}"

    W_LABEL = 5
    W_TIME = 10
    W_TOKENS = 8
    W_RESULTS = 8
    W_QUERY = 60
    sep = f"+-{'-' * W_LABEL}-+-{'-' * W_QUERY}-+-{'-' * W_TIME}-+-{'-' * W_TOKENS}-+-{'-' * W_RESULTS}-+"

    print(f"\n{'=' * 80}")
    print(f"  {title}")
    print(f"{'=' * 80}")

    # Print query legend
    for i, q in enumerate(queries, 1):
        print(f"  Q{i}: {q}")
    print()

    # Print compact table
    print(sep)
    print(f"| {'#':<{W_LABEL}} | {'Query':<{W_QUERY}} | {'Time':>{W_TIME}} | {'Tokens':>{W_TOKENS}} | {'Results':>{W_RESULTS}} |")
    print(sep)

    for q in queries:
        idx = next(r for r in results if r.query == q and r.method == "index")
        gr = next(r for r in results if r.query == q and r.method == "grep")
        label = label_map[q]
        q_short = _truncate(q, W_QUERY)

        print(f"| {label:<{W_LABEL}} | {q_short:<{W_QUERY}} | {idx.elapsed_ms:>4.0f}ms  | {idx.estimated_tokens:>6}   | {idx.result_count:>7} |")
        print(f"| {'':<{W_LABEL}} | {'  vs grep':<{W_QUERY}} | {gr.elapsed_ms:>4.0f}ms  | {gr.estimated_tokens:>6}   | {gr.result_count:>7} |")

        speedup = gr.elapsed_ms / max(idx.elapsed_ms, 0.01)
        token_save = gr.estimated_tokens - idx.estimated_tokens
        print(f"| {'':<{W_LABEL}} | {'':<{W_QUERY}} | {speedup:>3.0f}x{'':>{W_TIME - 5}} | {token_save:>+5}   | {'':>{W_RESULTS}} |")
        print(sep)


def _print_averages(avg_idx_time: float, avg_grep_time: float, avg_idx_tokens: float, avg_grep_tokens: float) -> None:
    print(f"\n  Avg time:  index {avg_idx_time:.0f}ms  |  grep {avg_grep_time:.0f}ms  |  speedup {avg_grep_time / max(avg_idx_time, 0.01):.1f}x")
    print(f"  Avg tokens: index {avg_idx_tokens:.0f}  |  grep {avg_grep_tokens:.0f}  |  savings {avg_grep_tokens - avg_idx_tokens:+.0f}")
    if avg_grep_tokens > 0:
        ratio = avg_grep_tokens / max(avg_idx_tokens, 1)
        print(f"  Output compression: {ratio:.1f}x smaller output vs grep")
    print(f"{'=' * 80}")


class TestComplexQueriesBenchmark:
    """Benchmark on harder, multi-hop, architectural, and impact-analysis queries."""

    @pytest.fixture(autouse=True)
    def _setup_index(self, sample_repo: Path, tmp_path: Path):
        self.db = _build_fresh_index(sample_repo, tmp_path)
        self.cwd = sample_repo
        yield
        self.db.close()

    @pytest.mark.parametrize("query", COMPLEX_QUERIES)
    def test_complex_comparison(self, query: str):
        idx_time, idx_tokens, idx_count = _run_index_search(self.db, query, self.cwd)
        grep_time, grep_tokens, grep_count = _run_grep_search(self.cwd, query)

        print(f"\n--- Complex Query: '{query}' ---")
        print(f"Index:  {idx_time:.0f}ms, ~{idx_tokens} tokens, {idx_count} results")
        print(f"Grep:   {grep_time:.0f}ms, ~{grep_tokens} tokens, {grep_count} results")
        if grep_time > 0:
            print(f"Speedup: {grep_time / max(idx_time, 0.01):.1f}x")
        print(f"Token delta: {grep_tokens - idx_tokens:+d}")

    def test_complex_summary_report(self):
        results: list[BenchmarkResult] = []

        for query in COMPLEX_QUERIES:
            idx_time, idx_tokens, idx_count = _run_index_search(self.db, query, self.cwd)
            grep_time, grep_tokens, grep_count = _run_grep_search(self.cwd, query)

            results.append(BenchmarkResult(query, "index", idx_time, idx_tokens, idx_count))
            results.append(BenchmarkResult(query, "grep", grep_time, grep_tokens, grep_count))

        _print_table(results, "Complex Queries Benchmark")

        avg_idx_time = sum(r.elapsed_ms for r in results if r.method == "index") / len(COMPLEX_QUERIES)
        avg_grep_time = sum(r.elapsed_ms for r in results if r.method == "grep") / len(COMPLEX_QUERIES)
        avg_idx_tokens = sum(r.estimated_tokens for r in results if r.method == "index") / len(COMPLEX_QUERIES)
        avg_grep_tokens = sum(r.estimated_tokens for r in results if r.method == "grep") / len(COMPLEX_QUERIES)

        _print_averages(avg_idx_time, avg_grep_time, avg_idx_tokens, avg_grep_tokens)
