# Benchmarks

`codebase-index` has four benchmark surfaces. Read them with their status in
mind — the whole point of this page is to keep evidence and aspiration separate.

| Surface | What it is | Status | Use it as |
|---|---|---|---|
| Retrieval eval (`tests/eval/`) | Ranking quality vs a fixed baseline across multiple real repositories, with significance tests | **Proven (relative)** | The gate for ranking changes; measures *deltas*, not absolute superiority |
| Public suite (`tests/benchmark_public.py`) | Deterministic synthetic multi-language fixture with the full metric framework | **Toy/synthetic** | CI regression gate + metric shape, **not** product-quality evidence |
| Smoke/perf (`test_perf_smoke.py`, `test_benchmark_comparison.py`) | Latency + output-size guards on a tiny fixture | **Toy/smoke** | Regression checks only |
| Honest real-repo (`tests/benchmark_honest.py`) | 55k LOC Java repo, recall@3 vs disciplined `rg` baseline, symmetric token accounting | **Proven (one repo)** | The only headline product-quality number we stand behind today |

### Claims that should NOT be made yet

Do not write, imply, or ship any of these until a run with published logs exists:

- Any 10k / 100k / 1M LOC scale or speed claim (no real run at that size).
- "Beats Cursor / Sourcegraph / Codebase-Memory MCP" — no head-to-head exists.
- Per-language *absolute* quality claims beyond Java. The retrieval eval covers
  Python, Java and TypeScript, but it measures this system against its own earlier
  versions — it says a change helped, not that the product beats an alternative.
- Generic "Nx faster" / "Nx fewer tokens" without naming the baseline and repo.
- Latency claims against external tools — the honest run explicitly does not
  headline latency (Python process start dominates; real `rg` is tens of ms).
  Version-over-version latency from the retrieval eval is in-process and is only
  comparable to other runs of that harness.

The defensible headline today is exactly: **on one 55k LOC Java repo, recall@3 was
70% (index) vs 40% (`rg`+window), using ~13× fewer answer tokens.** Everything
else is roadmap.

## Retrieval evaluation (ranking gate)

See [tests/eval/README.md](../tests/eval/README.md) for the full protocol. In short:
ground truth comes from hand-written queries verified against the source tree and
from commit-subject → changed-files pairs mined from git history (leak-free: the
query text is not in the indexed corpus). Corpora are pooled across languages, one
index per corpus is shared by every variant, and every non-baseline row carries a
paired bootstrap CI and permutation p-value.

`1.10.0` was measured over **420 queries across eight repositories** (Python ×2,
Java ×3, TypeScript/TSX ×2, PowerShell ×1) against a pinned `1.9.0`
(`RetrievalTuning.v190()`, so the comparison point cannot drift with the default):

| Metric | 1.9.0 | 1.10.0 | Δ | 95% CI | p | W/L/T |
|---|---|---|---|---|---|---|
| MRR | 0.5767 | 0.5955 | +0.0188 | [+0.0061, +0.0321] | 0.004 | 44/14/362 |
| nDCG@10 | 0.5352 | 0.5656 | +0.0304 | [+0.0197, +0.0416] | <0.001 | 64/19/337 |
| MAP | 0.4654 | 0.4867 | +0.0213 | [+0.0104, +0.0331] | 0.001 | 64/19/337 |
| recall@5 | 0.6026 | 0.6212 | +0.0187 | [+0.0089, +0.0306] | <0.001 | 14/0/406 |
| recall@10 | 0.6306 | 0.6933 | +0.0627 | [+0.0421, +0.0847] | <0.001 | 37/0/383 |
| P@5 | 0.1971 | 0.2033 | +0.0062 | [+0.0030, +0.0099] | <0.001 | 14/2/404 |
| useful@budget | 0.5919 | 0.6210 | +0.0292 | [+0.0048, +0.0550] | 0.020 | 36/17/367 |
| hit@3 | 0.6690 | 0.6833 | +0.0143 | [+0.0000, +0.0286] | 0.107 | 8/2/410 |
| tokens/query | 1080 | 1061 | −19 | — | — | — |

Two properties of that table matter more than the deltas:

- **`oracle` and `cand_recall` are unchanged to four decimals.** The candidate pool
  is identical, so every gain is reranking, not new recall. Reranking efficiency
  (MRR / oracle) went 0.639 → 0.660, closing ~6% of the ranking headroom 1.9.0 left
  on the table.
- **No corpus regressed.** An aggregate improvement is worthless if one large corpus
  masks a regression elsewhere, so per-corpus MRR is checked on every run.

Held-out validation, because hand-picked coefficients are still fitted parameters:
under leave-one-repository-out — both tuned numbers selected on seven corpora and
scored on the eighth — the pooled gain is **+0.0219 MRR, with 7/8 folds improving
and 0 regressing**. The shipped configuration is deliberately *more conservative*
than that selection would pick (see the `name_cooccurrence_demoted_scale` rationale
in `retrieval/tuning.py`), so these numbers under-claim what the benchmark alone
would support.

Known cost, stated because the benchmark family that reveals it is the small one: on
the 36 hand-written natural-language queries MRR moved −0.028 (p=0.63; 1 win, 3
losses, 32 ties). Three questions fell from rank 1 to rank 2–3 where a test file's
descriptive function name matches more query terms than the implementation's name.

Per-corpus `oracle` ranges 0.795–1.000 and reranking efficiency 0.557–0.753, so the
largest remaining headroom is still ranking, not recall — see §10 of
[RETRIEVAL.md](RETRIEVAL.md).

`1.9.0` was measured over 305 queries across Python, Java and TypeScript corpora
against `1.8.0`: MRR +0.027, MAP +0.028, nDCG@10 +0.024, recall@5 +0.031 (all
p < 0.001), with p50 latency 78.6 ms → 51.2 ms. These are version-over-version
ranking deltas on those corpora, not a universal quality claim.

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
