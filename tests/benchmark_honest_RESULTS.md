# Honest benchmark — codebase-index vs no-skill agent (NewTowny)

Script: `tests/benchmark_honest.py` · Raw run: `tests/benchmark_honest_newtowny.txt`
Repo under test: `C:/Users/denfry/IdeaProjects/NewTowny` (303 Java files, ~55k LOC; 574 text files indexed)
Token counter: `tiktoken/cl100k_base` (real tokens, identical estimator both sides)
Read model: top-3 hits, 80-line window — **symmetric on both sides**.
Last run: 2026-05-29, after the multi-language symbol-extraction fix (branch `m3-treesitter-symbols`).

## Why this replaces `test_benchmark_comparison.py`

The existing test is not trustworthy:
1. Runs on a 29-line toy fixture (`tests/fixtures/sample_repo`) — absolute numbers are noise.
2. Baseline splits the whole question into keywords **including stopwords** (`the`, `is`, `how`)
   and matches any of them — noise no real agent generates.
3. Counts only the index's curated `recommended_reads`, but **every** grep match line for the
   baseline → asymmetric accounting that structurally favors the index.

This benchmark: real repo, stopword-stripped salient-term baseline, symmetric per-file
deduped line-range token accounting, two baseline variants to bracket real agent behavior, plus
a **recall@3 answer-quality gate** against objective ground truth.

## Answer quality: recall@3 vs objective ground truth (the headline)

Ground truth is derived independently of the index — by Java naming convention, `class Foo`
lives in `Foo.java` — so the index cannot grade its own homework. recall@3 = did the top-3
files surfaced contain the file that actually defines the answer?

| Method | recall@3 |
|---|---|
| **INDEX** | **70 % (7/10)** |
| rg + window | 40 % (4/10) |

**Verdict: WIN — recall@3 ≥ baseline AND fewer tokens.** After fixing symbol extraction *and*
making retrieval symbol-aware (camelCase/underscore coverage scoring), the index now points at
the right defining file nearly twice as often as a disciplined grep agent.

## Token results (avg over 10 realistic developer queries)

| Method | Tokens/query | vs index |
|---|---|---|
| **INDEX top-3 (signature snippets the index returns)** | **~27** | — |
| INDEX full returned plan (all 10 results, follow-through reads) | ~422 | — |
| no-skill: rg + 80-line window (disciplined) | 5,604 | **~13× more** than index full plan |
| no-skill: rg + read whole matched files | 172,931 | ~410× more than index full plan |

The honest token comparison is **full-plan ~422 vs rg+window 5,604 ≈ 13×**, not the
signatures-vs-code-windows 200× the raw top-3 line implies. The index returns precise symbol
*signatures* (~27 tok) plus exact line ranges; a real agent then reads the pointed code, so the
~422 tok full-plan figure is the fair "tokens to actually answer." Either way the index is far
leaner *and* now more accurate.

Top-3 file overlap between index and baseline: **0.40 / 3** — they read mostly *different* files,
and (per recall@3) the index's are more often the right ones.

## Honest interpretation

- **The dead-symbols bug is fixed and verified.** Before: 303 Java files → **0 Java symbols**
  (symbol/refs/impact silently off). After: `codebase-index stats` reports **3,543 Java symbols**
  across 303 files (plus 103 JS). `symbol "BattlePassCatalog"`, `refs "build"`, and `impact` all
  return real Java results. The registry-consistency test and Guardrail-2 counters
  (`parse_failed`, `treesitter_zero_symbols`) lock it against silent regression.

- **Symbol-aware ranking is what turned the recall corner.** The old symbol retriever searched
  only the single longest query term, so "religion manager" exact-matched the bare `Religion`
  class and never reached `ReligionManager`. It now scores every candidate by how many query
  terms its camelCase/underscore-split name covers, so multi-word concepts land on multi-word
  symbols. recall@3 went **20 % → 70 %**.

- **The 3 remaining misses are honest** (religion, quest, skill). Two causes: (1) very high
  `in_degree` "god classes" (`NewTowny.java`, `BattlePassCatalog`, `AdminGuiSessionManager`)
  over-rank when they match a stray term, because in_degree is a strong tiebreak; (2) strict
  ground truth — e.g. the quest query surfaces `QuestManager` but we credit only `QuestListener`.
  Dampening the god-class tiebreak is a follow-up tuning task, not a correctness bug.

- **Latency is not a fair claim and is not headlined.** Index ≈ 1.3 s/query (real CLI, incl.
  Python process start each call); Python baseline ≈ 0.3 s. Real ripgrep would be tens of ms.

## Bottom line

The "symbols are dead" caveat is gone. Java (and Go/Rust/C/C++/C#/Ruby/PHP/Kotlin, plus a Tier-B
generic path) now produce symbols; `symbol`/`refs`/`impact` work. With symbol-aware ranking the
index finds the right defining file **70 % vs grep's 40 %** while using **~13× fewer tokens** to
answer — a genuine win on both axes. Remaining headroom is god-class tiebreak tuning, tracked as a
follow-up.
