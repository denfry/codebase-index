# Index vs grep-style and repo-map-style baselines on public repositories

- **Date:** 2026-09-04
- **codebase-index:** 1.9.0
- **Tokenizer (both sides):** tiktoken/cl100k_base
- **ripgrep:** ripgrep 14.1.1 (rev 4649aa9700)
- **Platform:** Windows 11 / Python 3.12.12
- **Read model:** top-3 follow-through reads, 80-line grep windows, `rg` listing capped at 50 lines; repo maps packed under 2000 / 8000 tokens
- **Ground truth:** commit subject → files that commit changed (`tests/eval/gen_queries.py`), newest N localised commits per repository; changelog-style files excluded from both answers and corpus

## Corpora

| corpus | commit | files indexed | symbols | edges | queries | index build |
|---|---|---:|---:|---:|---:|---:|
| flask | `d318b6834711` | 229 | 1622 | 4425 | 150 | 3.2 s |
| gson | `b3f4ca20087f` | 311 | 4193 | 22407 | 150 | 5.3 s |
| fastify | `15ebc8e2fe69` | 389 | 1185 | 34297 | 150 | 2.0 s |

### Pooled — ranked retrieval (n=450)

| method | hit@3 | recall@5 | MRR | packet / listing tokens | + top-3 reads (mean) | + top-3 reads (median) |
|---|---:|---:|---:|---:|---:|---:|
| index | 0.547 | 0.525 | 0.456 | 2,402 | 3,835 | 3,860 |
| index (uncapped reads) | 0.547 | 0.525 | 0.456 | 2,385 | 6,803 | 4,207 |
| rg+window | 0.304 | 0.293 | 0.263 | 1,351 | 3,495 | 3,442 |

### Pooled — repo-map-style context (n=450)

| method | answer present in map | tokens/query |
|---|---:|---:|
| repo-map 2k | 0.384 | 1,999 |
| repo-map 2k query-aware | 0.418 | 2,000 |
| repo-map 8k | 0.991 | 7,495 |
| repo-map 8k query-aware | 0.964 | 7,495 |

### Index vs rg+window, paired significance (pooled)

| metric | delta (index − rg) | 95% CI | p | significant |
|---|---:|---:|---:|---|
| hit@3 | +0.242 | [+0.187, +0.298] | 0.000 | yes |
| recall@5 | +0.231 | [+0.183, +0.278] | 0.000 | yes |
| MRR | +0.194 | [+0.151, +0.235] | 0.000 | yes |
| tokens | 340 | [238, 440] | 0.000 | yes |

### flask — ranked retrieval (n=150)

| method | hit@3 | recall@5 | MRR | packet / listing tokens | + top-3 reads (mean) | + top-3 reads (median) |
|---|---:|---:|---:|---:|---:|---:|
| index | 0.487 | 0.503 | 0.383 | 2,359 | 3,591 | 3,576 |
| index (uncapped reads) | 0.487 | 0.503 | 0.383 | 2,350 | 5,724 | 3,776 |
| rg+window | 0.233 | 0.245 | 0.229 | 1,009 | 3,079 | 3,187 |

### flask — repo-map-style context (n=150)

| method | answer present in map | tokens/query |
|---|---:|---:|
| repo-map 2k | 0.313 | 1,998 |
| repo-map 2k query-aware | 0.273 | 1,999 |
| repo-map 8k | 1.000 | 7,728 |
| repo-map 8k query-aware | 1.000 | 7,728 |

### gson — ranked retrieval (n=150)

| method | hit@3 | recall@5 | MRR | packet / listing tokens | + top-3 reads (mean) | + top-3 reads (median) |
|---|---:|---:|---:|---:|---:|---:|
| index | 0.573 | 0.523 | 0.503 | 2,418 | 4,375 | 4,376 |
| index (uncapped reads) | 0.573 | 0.523 | 0.503 | 2,382 | 10,659 | 8,680 |
| rg+window | 0.347 | 0.337 | 0.290 | 1,865 | 4,117 | 4,092 |

### gson — repo-map-style context (n=150)

| method | answer present in map | tokens/query |
|---|---:|---:|
| repo-map 2k | 0.480 | 2,000 |
| repo-map 2k query-aware | 0.613 | 2,000 |
| repo-map 8k | 1.000 | 6,757 |
| repo-map 8k query-aware | 1.000 | 6,757 |

### fastify — ranked retrieval (n=150)

| method | hit@3 | recall@5 | MRR | packet / listing tokens | + top-3 reads (mean) | + top-3 reads (median) |
|---|---:|---:|---:|---:|---:|---:|
| index | 0.580 | 0.547 | 0.482 | 2,428 | 3,539 | 3,562 |
| index (uncapped reads) | 0.580 | 0.547 | 0.482 | 2,423 | 4,027 | 3,611 |
| rg+window | 0.333 | 0.297 | 0.269 | 1,178 | 3,290 | 3,312 |

### fastify — repo-map-style context (n=150)

| method | answer present in map | tokens/query |
|---|---:|---:|
| repo-map 2k | 0.360 | 2,000 |
| repo-map 2k query-aware | 0.367 | 2,000 |
| repo-map 8k | 0.973 | 8,000 |
| repo-map 8k query-aware | 0.893 | 7,999 |

## How to read this

- `hit@3` is the metric that matters for an agent that opens the top three files. `recall@5` credits multi-file answers. `MRR` rewards putting the answer first.
- `packet / listing tokens` is what the agent sees before opening anything: the full JSON search payload for the index (snippets included), the first 50 `rg` lines for grep. `+ top-3 reads` adds the follow-through: the index's top-3 `recommended_reads` ranges in full, or three 80-line grep windows. Same tokenizer on every side.
- The index packet already carries budgeted snippets, so an agent that answers from the packet pays the first column only; an agent that re-reads every recommended range pays the second. Grep has no first-column equivalent — the listing alone rarely answers anything.
- A repo map is not a ranking, so it is scored on whether the answer file is *present* at all — an upper bound on what an agent could do with it.
- Ground truth is one commit's files; a query can have a correct answer the commit did not touch. Absolute numbers understate every method equally; read the *deltas*, and read the CI before the delta.
- Latency is deliberately not tabulated: the index runs in-process, ripgrep is a separate binary; neither number is a fair claim against the other.
- Not measured here: an LLM-driven agent exploring the repository. That needs model calls and is tracked as future work in `docs/BENCHMARKS.md`.
