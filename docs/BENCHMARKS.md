# Benchmarks

`codebase-index` has three benchmark surfaces.

## Public benchmark suite

Run:

```bash
python tests/benchmark_public.py --workdir .tmp-public-benchmark
```

The public suite builds a deterministic multi-language fixture repository and
reports JSON metrics:

- Retrieval quality: `recall_at_1`, `recall_at_3`, `recall_at_5`, `mrr`, `ndcg_at_5`
- Agent usefulness: `answer_correctness_at_3`
- Token economy: index context tokens versus a grep-window baseline
- Language breakdown: per-language recall and answer-correctness proxy
- Freshness: stale detection after an edit and incremental update latency
- Graph tasks: callers/dependencies/impact checks
- Scale counters: indexed files, symbols, edges, and bytes

Example output shape:

```json
{
  "retrieval_quality": {
    "recall_at_1": 0.75,
    "recall_at_3": 1.0,
    "recall_at_5": 1.0,
    "mrr": 0.875,
    "ndcg_at_5": 0.9077
  },
  "answer_correctness": {
    "answer_correctness_at_3": 1.0
  },
  "token_economy": {
    "index_tokens_avg": 25.0,
    "grep_window_tokens_avg": 72.375,
    "compression_vs_grep": 2.895
  }
}
```

The CI gate is `tests/test_public_benchmark.py`. It verifies the suite reports
all required metric families and catches obvious quality, freshness, graph, and
token-accounting regressions.

## Honest real-repo benchmark

Run:

```bash
python tests/benchmark_honest.py --repo /path/to/real/repo --rebuild
```

The current documented run is against a 55k LOC Java repository:
[tests/benchmark_honest_RESULTS.md](../tests/benchmark_honest_RESULTS.md).

That benchmark compares the index against a disciplined grep-window agent with
objective recall@3 ground truth.

## Smoke/perf benchmark

`tests/test_benchmark_comparison.py` and `tests/test_perf_smoke.py` guard basic
latency and output-size behavior. They are useful regression checks, not product
quality evidence.

## Remaining benchmark work

The public suite now has the metric framework, but the next step is adding
larger public or documented external repositories:

- 10k, 100k, and 1M LOC scale targets
- More real-world Python, TypeScript, Java, Go, Rust, C#, PHP repos
- Agent answer grading with human-reviewed expected answers
- Comparisons against repo-map style context and vanilla agent exploration
- Framework graph tasks: route -> handler -> service -> DB, migrations, config consumers, CI/infra
