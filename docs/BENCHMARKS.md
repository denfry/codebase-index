# Benchmarks

`codebase-index` has three benchmark surfaces. Read them with their status in
mind — the whole point of this page is to keep evidence and aspiration separate.

| Surface | What it is | Status | Use it as |
|---|---|---|---|
| Public suite (`tests/benchmark_public.py`) | Deterministic synthetic multi-language fixture with the full metric framework | **Toy/synthetic** | CI regression gate + metric shape, **not** product-quality evidence |
| Smoke/perf (`test_perf_smoke.py`, `test_benchmark_comparison.py`) | Latency + output-size guards on a tiny fixture | **Toy/smoke** | Regression checks only |
| Honest real-repo (`tests/benchmark_honest.py`) | 55k LOC Java repo, recall@3 vs disciplined `rg` baseline, symmetric token accounting | **Proven (one repo)** | The only headline product-quality number we stand behind today |

### Claims that should NOT be made yet

Do not write, imply, or ship any of these until a run with published logs exists:

- Any 10k / 100k / 1M LOC scale or speed claim (no real run at that size).
- "Beats Cursor / Sourcegraph / Codebase-Memory MCP" — no head-to-head exists.
- Per-language quality claims beyond Java (the honest run is Java-only).
- Generic "Nx faster" / "Nx fewer tokens" without naming the baseline and repo.
- Latency claims — the honest run explicitly does not headline latency
  (Python process start dominates; real `rg` is tens of ms).

The defensible headline today is exactly: **on one 55k LOC Java repo, recall@3 was
70% (index) vs 40% (`rg`+window), using ~13× fewer answer tokens.** Everything
else is roadmap.

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

## Remaining benchmark work (TODO checklist)

The public suite has the metric framework; the next step is real, larger,
documented repositories. Each task must publish raw logs alongside any headline
number (the pattern set by `tests/benchmark_honest_RESULTS.md`).

- [ ] **10k LOC public repo** — Recall@1/3/5, MRR, nDCG, token economy; named repo + commit SHA.
- [ ] **100k LOC public repo** — same metrics, plus full index build time and incremental update latency.
- [ ] **1M LOC target** — feasibility + scale counters (files/symbols/edges/bytes); may be partial.
- [ ] **Multi-language repo** (≥3 Tier-A languages) — per-language recall and answer-correctness breakdown.
- [ ] **vs vanilla agent grep/read** — tokens and recall against an undisciplined agent exploring the same questions.
- [ ] **vs repo-map-style context** — tokens and recall against an Aider-repo-map-style context blob.
- [ ] **Graph task benchmark** — `refs`, `impact`, and route→handler→service paths against hand-labeled ground truth.
- [ ] **Answer grading** — human-reviewed expected answers, not just file-level recall proxies.
- [ ] **Framework graph tasks** — migrations, config consumers, CI/infra wiring once typed edges land.

How to add one without overclaiming:

1. Pick a public repo; record its URL and commit SHA.
2. Derive ground truth independently of the index (e.g. naming convention), so the
   index cannot grade its own homework.
3. Use a symmetric token estimator and read window on both sides.
4. Commit the raw run output next to a short `*_RESULTS.md` summary.
5. Only then update README/COMPARISON headline numbers.
