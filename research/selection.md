# Stage 4 — Scoring, TOP-3, and composition

Scores are 1–5. `Feasible` means *testable with evidence available in this
environment* (eight real repositories, git history, no LLM API, no GPU) — a
hypothesis that can only be validated by machinery I do not have scores low no matter
how good it is, and is recorded as follow-up rather than silently dropped.

| # | Hypothesis | Novelty | Theory | Feasible | Scale | Δtokens | Δlatency | Quality | Multi-agent | Risk |
|---|---|---|---|---|---|---|---|---|---|---|
| H1 | Conditional set completion | 4 | 5 | **5** | 5 | 3 | 4 | **5** | 3 | 2 |
| H2 | Budgeted coverage selection | 3 | 5 | **5** | 5 | **5** | 4 | 4 | 3 | 2 |
| H3 | Evidence-keyed memoisation | 4 | 4 | **5** | 5 | **5** | **5** | 3 | **5** | 2 |
| H4 | Granularity law of survival | 4 | 4 | **5** | 4 | 4 | 4 | 2 | 4 | 1 |
| H5 | Entropy-minimising retrieval | 4 | **5** | 1 | 2 | 4 | 1 | 4 | 2 | 4 |
| H6 | ddmin oracle for minimal context | **5** | **5** | 1 | 1 | 5 | 1 | 5 | 2 | 3 |
| H7 | Trace prefetching | 4 | 4 | 1 | 4 | 2 | 5 | 3 | 3 | 3 |
| H8 | Obligation-level slices | 2 | 3 | 4 | 5 | **5** | 4 | 2 | 2 | 1 |
| H9 | Index the derivative | 4 | 3 | 2 | 3 | 2 | 3 | 3 | 2 | **5** |
| H10 | Self-organising index | 3 | 4 | 1 | 4 | 2 | 2 | 4 | 4 | 4 |
| H11 | Obligation routing | 4 | 4 | 2 | 4 | 3 | 3 | 2 | **5** | 3 |
| H12 | Negative-result atoms | 4 | 2 | 3 | 4 | 4 | 4 | 2 | **5** | 2 |
| H13 | Speculative closure | 2 | 2 | 3 | 3 | 1 | 2 | 1 | 2 | 3 |

## TOP-3

**H1 — conditional set completion.** Highest expected quality gain, premise already
measured at 71.8% reachability, and it has a *falsifiable prior*: this repository
shipped `graph_source = False` after structural evidence failed inside fusion. If H1's
composition claim is wrong, the experiment will reproduce that failure and say so.

**H2 — budgeted coverage selection.** The only candidate that attacks token cost at the
objective level rather than by post-hoc compression, and it is the natural consumer of
H1's output: once completion produces a *set* of candidates with overlapping coverage,
top-k is provably the wrong selector.

**H3 — evidence-keyed memoisation** (with **H4** as its measurement). Orthogonal to
H1/H2 — it addresses reuse, not retrieval — and it is the only one of the thirteen
that changes a *correctness* property rather than a quality metric: unsound reuse goes
to zero by construction. H4 makes it quantitative and is nearly free to measure once
H3 exists.

## Rejected, with reasons

- **H6** (ddmin oracle) is the single most valuable idea in the list and I cannot run
  it: it needs `O(|S| log|S|)` LLM-agent executions per query plus a per-repo test
  harness. Recorded as the top follow-up. Its absence is also the main threat to
  validity of everything below, because it means I inherit the proxy label "files the
  commit touched" rather than true minimal sufficiency — stated again in `experiments.md`.
- **H5, H7, H10** need a live agent workload or LLM scorer. Deferred, not disproven.
- **H13** rejected on measurement: closure latency turns out to be ~1 ms (§ results),
  so there is nothing to amortise.
- **H9** carries an unacceptable circularity risk against a commit-derived benchmark;
  its safe fragment (co-change under strict temporal split) is absorbed into H1.
- **H8** is largely already implemented here (`retrieval/skeleton.py`); it enters as a
  cost model, not a claim.

## Composition

H1, H2, H3 compose without conflict because they act on different objects:

```
        query
          │
          ▼
   ┌─────────────┐   H1: anchors are found by the existing high-precision
   │  NUCLEATE   │       lexical/symbol retriever — unchanged, and deliberately so
   └─────────────┘
          │  A₀
          ▼
   ┌─────────────┐   H1: completion conditioned on A₀, NOT on the query;
   │   ACCRETE   │       typed relation union {edge, cochange, testlink, stem, dir}
   └─────────────┘
          │  candidates with coverage sets
          ▼
   ┌─────────────┐   H2: greedy coverage-per-token under budget B,
   │   SELECT    │       replacing top-k + MMR
   └─────────────┘
          │  S
          ▼
   ┌─────────────┐   H3/H4: conclusions computed over S are stored keyed by
   │  MEMOISE    │       H(content hashes of S); invalidation is exact
   └─────────────┘
```

The composed system is specified in `architecture.md` under the working name
**NUCLEUS** (*Necessity-driven Unified Closure over Lexical, Evolutionary and
Structural relations*).

One property of this composition is worth stating before any measurement, because it
is what makes the design defensible against the prior negative result: **accretion
never displaces an anchor.** Completions are allocated their own budget and appended
behind the anchor head, so a completion can only take a slot that a *lower-ranked
baseline result* would have taken. The 2015-vintage failure mode of graph retrieval —
architectural neighbours evicting direct hits — is excluded by construction rather
than by tuning. Whether that is enough is Stage 6's problem.
