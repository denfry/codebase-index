# Public benchmark — results

Logged run of the reproducible public suite (`tests/benchmark_public.py`). Per
`docs/BENCHMARKS.md`, no headline number is published without a logged run; this
file is that log.

- **Date:** 2026-06-14
- **Version:** 1.4.0 line (branch `chore/benchmarks-and-release`)
- **Fixture:** synthetic multi-language repo built by `build_public_fixture`
  (8 ground-truth cases across python/typescript/java/go/rust/csharp/php/sql,
  plus 24 filler docs). This is a *toy* fixture — it proves the pipeline and
  guards regressions; it is **not** evidence of real-repo quality.
- **Embeddings:** disabled (lexical + symbol + graph only).

Reproduce:

```bash
python tests/benchmark_public.py --workdir .tmp-public-benchmark
```

## Headline metrics

| Family | Metric | Value |
|---|---|---|
| Retrieval quality | Recall@1 / @3 / @5 | 0.75 / 1.00 / 1.00 |
| | MRR | 0.875 |
| | nDCG@5 | 0.908 |
| Answer correctness | answer_correctness@3 | 1.00 |
| Token economy | index tokens (avg, top-3) | 21.1 |
| | grep-window tokens (avg, top-3) | 72.4 |
| | compression vs grep | 3.43× |
| Freshness | stale detected after edit → fresh after update | yes / yes |
| | incremental update latency | ~48 ms (1 file) |
| Graph tasks | pass rate | 1 / 3 (0.33) |
| Scale | files / symbols / edges indexed | 35 / 18 / 7 |

## Reading the numbers honestly

- Retrieval is at ceiling on this fixture (Recall@3 = 1.0), so it confirms
  *no regression*, not headroom. The rerank `in_degree` dampening shipped in this
  line is flat here by design — the fixture has no "god classes". Its real-repo
  effect is tracked under **M12.5** (needs a maintainer-labeled real repo).
- `graph_tasks` pass rate (0.33) reflects the import/call/ref/inheritance graph
  only; the framework-aware edges that would lift it are designed in
  `docs/superpowers/specs/2026-06-14-typed-framework-edges-design.md` (M13) and
  not yet implemented.
- Token economy (~3.4× vs an rg+window baseline) is a synthetic-fixture figure;
  the real-repo figure (~13× on a 55k LOC Java repo) lives in
  `tests/benchmark_honest_RESULTS.md`.

## Raw output

```json
{
  "retrieval_quality": {
    "recall_at_1": 0.75,
    "recall_at_3": 1.0,
    "recall_at_5": 1.0,
    "mrr": 0.875,
    "ndcg_at_5": 0.9077324383928644
  },
  "answer_correctness": {
    "answer_correctness_at_3": 1.0
  },
  "token_economy": {
    "index_tokens_avg": 21.125,
    "grep_window_tokens_avg": 72.375,
    "tokens_saved_avg": 51.25,
    "compression_vs_grep": 3.42603550295858
  },
  "language_breakdown": {
    "csharp": { "cases": 1.0, "recall_at_3": 1.0, "answer_correctness_at_3": 1.0 },
    "go": { "cases": 1.0, "recall_at_3": 1.0, "answer_correctness_at_3": 1.0 },
    "java": { "cases": 1.0, "recall_at_3": 1.0, "answer_correctness_at_3": 1.0 },
    "php": { "cases": 1.0, "recall_at_3": 1.0, "answer_correctness_at_3": 1.0 },
    "python": { "cases": 1.0, "recall_at_3": 1.0, "answer_correctness_at_3": 1.0 },
    "rust": { "cases": 1.0, "recall_at_3": 1.0, "answer_correctness_at_3": 1.0 },
    "sql": { "cases": 1.0, "recall_at_3": 1.0, "answer_correctness_at_3": 1.0 },
    "typescript": { "cases": 1.0, "recall_at_3": 1.0, "answer_correctness_at_3": 1.0 }
  },
  "freshness": {
    "was_fresh_before_edit": true,
    "stale_after_edit": true,
    "files_changed_after_edit": 1.0,
    "update_latency_ms": 47.64110000178334,
    "files_reindexed": 1.0,
    "fresh_after_update": true
  },
  "graph_tasks": { "tasks": 3, "passed": 1, "pass_rate": 0.3333333333333333 },
  "scale": { "files_indexed": 35, "symbols_indexed": 18, "edges_indexed": 7, "bytes_indexed": 3632 }
}
```
