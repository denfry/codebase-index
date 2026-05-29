"""Quality-first benchmark: does search return the right files/symbols?

Measures recall against ground-truth expected_answers.yml.
Run: pytest tests/test_quality_benchmark.py -v --tb=short -s
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from codebase_index.config import Config
from codebase_index.indexer.pipeline import build_index
from codebase_index.retrieval.pipeline import search
from codebase_index.storage.db import Database

FIXTURE_ROOT = Path(__file__).parent / "fixtures"
EXPECTED_ANSWERS = FIXTURE_ROOT / "expected_answers.yml"


def _load_expected() -> list[dict]:
    with open(EXPECTED_ANSWERS) as f:
        return yaml.safe_load(f)


def _build_fresh_index(sample_repo: Path, tmp_path: Path) -> Database:
    cfg = Config()
    cfg.root = str(sample_repo)
    cfg.embeddings.enabled = False
    db = Database(tmp_path / "quality_index.sqlite").open()
    build_index(cfg, db, root=sample_repo)
    return db


class TestQualityBenchmark:
    @pytest.fixture(autouse=True)
    def _setup_index(self, sample_repo: Path, tmp_path: Path):
        self.db = _build_fresh_index(sample_repo, tmp_path)
        self.cwd = sample_repo
        yield
        self.db.close()

    def test_quality_report(self):
        expected = _load_expected()
        results = []

        for entry in expected:
            query = entry["query"]
            expected_files = set(entry.get("expected_files", []))
            expected_symbols = set(entry.get("expected_symbols", []))

            result = search(
                self.db.conn, query,
                mode="hybrid", limit=10, token_budget=5000, no_fallback=False,
            )

            result_paths = {r["path"] for r in result.get("results", [])}
            result_symbols = set()
            for r in result.get("results", []):
                result_symbols.update(r.get("symbols", []))

            top3_paths = {r["path"] for r in result.get("results", [])[:3]}
            top5_symbols = set()
            for r in result.get("results", [])[:5]:
                top5_symbols.update(r.get("symbols", []))

            top3_recall = bool(expected_files & top3_paths) if expected_files else None
            top5_symbol_recall = bool(expected_symbols & top5_symbols) if expected_symbols else None
            usefulness = bool(expected_files & {result["results"][0]["path"]}) if (expected_files and result.get("results")) else None
            zero_results = len(result.get("results", [])) == 0

            results.append({
                "query": query,
                "expected_files": expected_files,
                "expected_symbols": expected_symbols,
                "top3_recall": top3_recall,
                "top5_symbol_recall": top5_symbol_recall,
                "usefulness": usefulness,
                "zero_results": zero_results,
                "result_count": len(result.get("results", [])),
            })

        _print_quality_table(results)
        _assert_quality_thresholds(results)


def _print_quality_table(results: list[dict]) -> None:
    print(f"\n{'=' * 80}")
    print("  Quality Benchmark Report")
    print(f"{'=' * 80}")

    for r in results:
        status = []
        if r["top3_recall"] is not None:
            status.append(f"top3={'PASS' if r['top3_recall'] else 'FAIL'}")
        if r["top5_symbol_recall"] is not None:
            status.append(f"top5_sym={'PASS' if r['top5_symbol_recall'] else 'FAIL'}")
        if r["usefulness"] is not None:
            status.append(f"useful={'PASS' if r['usefulness'] else 'FAIL'}")
        zero = "ZERO_RESULT" if r["zero_results"] else f"{r['result_count']} results"

        print(f"\n  Query: '{r['query']}'")
        print(f"    Expected files: {r['expected_files']}")
        print(f"    Expected symbols: {r['expected_symbols']}")
        print(f"    {' | '.join(status)} | {zero}")

    with_expectations = [r for r in results if r["top3_recall"] is not None]
    if with_expectations:
        pass_rate = sum(1 for r in with_expectations if r["top3_recall"]) / len(with_expectations)
        print(f"\n  Top-3 recall pass rate: {pass_rate:.0%} ({sum(1 for r in with_expectations if r['top3_recall'])}/{len(with_expectations)})")

    zero_count = sum(1 for r in results if r["zero_results"])
    print(f"  Zero-result queries: {zero_count}/{len(results)}")
    print(f"{'=' * 80}")


def _assert_quality_thresholds(results: list[dict]) -> None:
    with_expectations = [r for r in results if r["top3_recall"] is not None]
    if with_expectations:
        pass_rate = sum(1 for r in with_expectations if r["top3_recall"]) / len(with_expectations)
        assert pass_rate >= 0.5, f"Top-3 recall pass rate {pass_rate:.0%} below threshold 50%"
