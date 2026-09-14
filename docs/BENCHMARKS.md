# Benchmarks

The rule of this project is *measure improvements, don't assert them*. This page
lists every benchmark surface, what it can and cannot prove, and the exact
numbers we are willing to put in a README. Anything not on this page is not a
claim.

## The one-paragraph version

On three public repositories at pinned commits (Flask, Gson, Fastify: Python,
Java, JavaScript), across 450 questions mined from git history, `codebase-index`
put the right file in its top three **55% of the time versus 30% for a
disciplined ripgrep agent**, at roughly the same context cost (3.8k vs 3.5k
tokens per question, same tokenizer on both sides). Every metric delta is
significant at p < 0.001 with paired bootstrap confidence intervals. Raw run:
[tests/eval/results/2026-09-04-public-baselines.md](../tests/eval/results/2026-09-04-public-baselines.md).
Reproduce it with one command (below). That is the headline; the rest of this
page is the fine print.

## Surfaces

| Surface | What it measures | Status | Use it as |
|---|---|---|---|
| **Public baselines** (`tests/eval/run_baselines.py`) | Index vs `rg`+window and vs repo-map-style context on public repos, symmetric tokens, significance | **Proven, reproducible** | The headline comparison against *not having an index* |
| **Retrieval eval** (`tests/eval/run_eval.py`) | Ranking quality of the shipped default vs the 1.7.0 baseline and one-signal ablations, pooled across corpora, with significance | **Proven (relative)** | The gate every ranking change must pass; measures deltas between versions, not superiority over other tools |
| Public synthetic suite (`tests/benchmark_public.py`) | Full metric framework on a deterministic toy fixture | Toy | CI regression gate for metric *shape*; not product evidence |
| Smoke/perf (`test_perf_smoke.py`, `test_benchmark_comparison.py`) | Latency and output-size guards on a tiny fixture | Toy | Regression checks only |
| Single-repo honest run (`tests/benchmark_honest.py`) | recall@3 and tokens vs `rg` on one 55k LOC Java repository | **Historical, not reproducible by others** | The repository is private; the script is kept because its read model informed the public baselines. Do not quote its numbers |

## Public baselines (the headline)

```bash
pip install -e ".[dev]" tiktoken
python tests/eval/run_baselines.py --clone --workdir .tmp-baselines \
    --out tests/eval/results/$(date +%F)-public-baselines
```

`--clone` fetches the three corpora at the commits pinned in the script. Pass
`--repo /path/to/any/git/repo` to benchmark your own repository the same way;
please post the result with the *benchmark report* issue template, especially
when it is unflattering.

### Protocol

- **Ground truth** is mined from git history by `tests/eval/gen_queries.py`: the
  query is a human-written commit subject, the answer is the set of files that
  commit changed. Neither is produced by the retriever, and the subject text is
  not in the indexed corpus, so the set is leak-free by construction. The newest
  150 localised commits per repository are used (no merges, reverts, releases,
  formatting commits, or sweeping changes over more than four files).
- **Changelog-style files** (`CHANGELOG*`, `CHANGES*`, `HISTORY*`, `NEWS*`) are
  excluded both as answers and from the indexed corpus, because they paraphrase
  commit subjects.
- **Index side**: `search()` with the shipped defaults (`limit 10`,
  `token_budget 1500`, hybrid mode). Context = the full JSON payload the agent
  receives, plus the top-3 `recommended_reads` ranges read in full.
- **rg + window**: stop-words dropped from the question, up to six salient terms
  searched with real ripgrep, files ranked by match density, an 80-line window
  read around the densest hit in each of the top-3 files. Context = the first
  50 lines of `rg` output plus the three windows.
- **repo-map-style**: file paths plus top-level definition signatures packed
  under a 2k or 8k token budget, ordered by graph degree (or by identifier
  overlap with the question in the *query-aware* variant). This is an
  approximation of the *style* of context Aider builds, not Aider itself. A map
  is not a ranking, so it is scored on whether the answer file is present at
  all, an upper bound on what an agent could do with it.
- **Tokens** are counted with `tiktoken/cl100k_base` on every side.
- **Significance**: paired bootstrap 95% CI and paired permutation p-value,
  seeded, index vs rg.

### Logged run (2026-09-04, codebase-index 1.9.0)

| corpus | commit | language | files | queries |
|---|---|---|---:|---:|
| pallets/flask | `d318b683` | Python | 229 | 150 |
| google/gson | `b3f4ca20` | Java | 311 | 150 |
| fastify/fastify | `15ebc8e2` | JavaScript | 389 | 150 |

Pooled, n = 450:

| method | hit@3 | recall@5 | MRR | packet / listing tokens | + top-3 reads |
|---|---:|---:|---:|---:|---:|
| codebase-index | **0.547** | **0.525** | **0.456** | 2,402 | 3,835 |
| rg + 80-line windows | 0.304 | 0.293 | 0.263 | 1,351 | 3,495 |

| index − rg | delta | 95% CI | p |
|---|---:|---:|---:|
| hit@3 | +0.242 | [+0.187, +0.298] | < 0.001 |
| recall@5 | +0.231 | [+0.183, +0.278] | < 0.001 |
| MRR | +0.194 | [+0.151, +0.235] | < 0.001 |
| tokens | +340 | [+238, +440] | < 0.001 |

Repo-map-style context, pooled: the answer file is present in a 2k-token map
38% of the time (42% query-aware) and in an 8k-token map 99% of the time. Those
repositories are small enough that 8k tokens covers nearly every file, so the
8k row says little; on a large monorepo it would not.

![chart](../assets/benchmark.svg)

### How to read it honestly

- The index is **1.8× more likely** to put the answer in the top three than a
  disciplined grep agent, at **about 10% more context tokens**. It is not
  "13× fewer tokens"; that earlier number came from charging the index for
  signature snippets and grep for code windows, which is not symmetric. The
  public run charges both sides for what actually enters context.
- The token parity is *new in this line*. Before the `max_read_lines` cap
  (1.9.1), the index's follow-through reads averaged 6.8k tokens because a
  symbol-aligned chunk can be a whole 1,500-line class; the benchmark found
  that, and the cap fixed it without touching ranking (the "uncapped" row in the
  raw log has identical quality).
- Ground truth is one commit's files. A question can have a correct answer the
  commit did not touch, so absolute numbers understate every method equally.
  Read the deltas, and read the confidence interval before the delta.
- Per-corpus results move together (hit@3 index/rg: 0.49/0.23 Flask,
  0.57/0.35 Gson, 0.58/0.33 Fastify), which is the point of pooling three
  languages: the effect is not a Python artefact.
- Latency is deliberately not tabulated. The index runs in-process, ripgrep is
  a separate binary; neither number is a fair claim against the other.

## Retrieval evaluation (the ranking gate)

See [tests/eval/README.md](../tests/eval/README.md) for the full protocol. This
harness compares the shipped ranker with its own earlier version and with
one-signal-off ablations, pooled across corpora, with the same significance
machinery. It cannot say the index beats an alternative; it says whether a
change to the ranker helped.

`1.9.0` was measured over 305 queries across Python, Java and TypeScript corpora
against `1.8.0`: MRR +0.027, MAP +0.028, nDCG@10 +0.024, recall@5 +0.031 (all
p < 0.001), with p50 latency 78.6 ms → 51.2 ms. Two of the three corpora used
for that run are private; the generator is the reproducible part, and the public
baselines above use the same generator on public repositories.

Every ranking signal that ships has an ablation row. 1.9.0 removed two signals
that could not demonstrate a benefit and rejected several plausible ones
(IDF-weighted coverage, stemming, graph propagation, MMR, a file-length prior).

## Claims that must NOT be made

Do not write, imply, or ship any of these until a run with published logs exists:

- Any 1M-LOC or monorepo scale or speed claim (no real run at that size).
- "Beats Cursor / Sourcegraph / Aider / Codebase-Memory MCP": no head-to-head
  exists. The repo-map baseline here is a style approximation, not Aider.
- Any *token savings* multiplier without naming the read model. Under
  symmetric accounting the index costs about the same as disciplined grep.
- Latency comparisons against external tools.
- Any statement about *LLM agent task success*. The baselines here are
  retrieval metrics; nobody has measured whether an agent with the index
  finishes tasks faster or better. That is the most important open item.

## Future work, in priority order

1. **Agent task-level evaluation**: the same questions, an actual coding agent
   (Claude Code or Codex CLI) with and without the skill, measuring answer
   correctness, files read, tokens, and wall time. Needs model calls and a
   grading rubric; not started.
2. **Large repository run**: a 500k–1M LOC monorepo, reporting index build
   time, incremental update latency, memory, and the same retrieval metrics.
3. **Graph task benchmark**: hand-labelled `refs`, `impact`, and
   route → handler → service paths.
4. **Framework-aware edges** benchmark once typed edges land (roadmap).

How to add a benchmark without overclaiming: pick a public repository and pin
the commit; derive ground truth independently of the index; use one token
estimator and one read model on both sides; commit the raw run next to a short
summary; only then touch README numbers.
