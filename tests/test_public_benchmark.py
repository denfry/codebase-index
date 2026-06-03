from __future__ import annotations

from tests.benchmark_public import build_public_fixture, run_public_benchmark


def test_public_benchmark_reports_required_metrics(tmp_path):
    root = build_public_fixture(tmp_path / "repo", filler_files=12)
    report = run_public_benchmark(root)

    quality = report.retrieval_quality
    assert set(quality) == {"recall_at_1", "recall_at_3", "recall_at_5", "mrr", "ndcg_at_5"}
    assert quality["recall_at_3"] >= 0.50
    assert quality["mrr"] > 0.0
    assert quality["ndcg_at_5"] > 0.0

    answer = report.answer_correctness
    assert answer["answer_correctness_at_3"] >= 0.50

    tokens = report.token_economy
    assert tokens["index_tokens_avg"] > 0
    assert tokens["grep_window_tokens_avg"] > 0
    assert tokens["compression_vs_grep"] > 0

    assert {"python", "typescript", "java", "go", "rust", "csharp", "php", "sql"} <= set(
        report.language_breakdown
    )
    assert report.freshness["stale_after_edit"] is True
    assert report.freshness["fresh_after_update"] is True
    assert report.freshness["update_latency_ms"] >= 0
    assert report.graph_tasks["pass_rate"] >= 1 / 3
    assert report.scale["files_indexed"] >= 10
    assert report.cases
