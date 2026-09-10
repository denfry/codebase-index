# Stage 6–7 — Experiments, ablations, and the refutation

## Protocol

**Corpora.** Eight real repositories, four languages (Python ×2, Java ×3,
TypeScript/TSX ×2, PowerShell ×1), 2 264 indexed files, 420 queries. Identical to the
set `docs/BENCHMARKS.md` reports 1.10.0 against, so the numbers here sit next to the
product's own published numbers.

**Ground truth.** Commit subject → files that commit changed, mined by the shipped
`tests/eval/gen_queries.py`. Leak-free: the query text lives in git metadata, not in
the indexed corpus. Changelog-like files are excluded as both documents and answers.

**Metrics.** `tests/eval/metrics.py` verbatim — never reimplemented. Every non-baseline
row carries a paired bootstrap 95% CI and a paired permutation p-value, both seeded.

**Indexing.** One index per corpus, built once, shared by every system, so deltas
measure retrieval and never indexing variance.

**Temporal discipline.** The co-change relation could trivially leak, since ground
truth is mined from commits. `CoChangeModel` is append-only and queries are swept
oldest-first, so a query's own commit and every later commit are structurally
unreachable — `test_cochange_model_refuses_lookahead` asserts that rewinding raises.

**Attribution.** `NucleusParams(accrete=False)` reproduces
`codebase_index.retrieval.pipeline.search` result-for-result
(`test_accretion_off_reproduces_shipped_pipeline`, 5 queries × exact snippet match).
Without that equivalence every "NUCLEUS vs incumbent" delta would be confounded with
an incidental reimplementation.

---

## Experiment 0 — Is the premise even true?

Before building anything: are the members of a required set related to each other by
anything computable? Over 900 anchor→target gold pairs, no lookahead:

| relation | covers | uniquely |
|---|---|---|
| stem (shared name tokens) | 35.8% | — |
| static edge (import/call/ref) | 30.7% | 5.3% |
| co-change (strictly prior history) | 30.4% | 9.8% |
| same directory | 23.8% | — |
| test ↔ impl | 14.4% | — |
| **union** | **71.8%** | |

The premise holds, and structure and history are **not** redundant. This is what
justified proceeding, and it is also what makes the eventual negative result
interesting rather than trivial: the signal is genuinely there.

Gold-set sizes: 53.1% single-file, 46.9% multi-file (2–4). Completion can only ever
help the 46.9%.

---

## Experiment 1 — First implementation: a significant loss

Default configuration (3 completions inserted after a 3-result anchor head):

| vs `hybrid` | Δ | 95% CI | p |
|---|---|---|---|
| MRR | **−0.0073** | [−0.0108, −0.0038] | **<0.001** |
| P@5 | **−0.0102** | [−0.0176, −0.0029] | **0.009** |
| recall@10 | −0.0105 | [−0.0312, +0.0103] | 0.330 |
| tokens | **+108** | — | — |

A clear loss. The interesting part is *why*, and three very different causes produce
the same number.

## Experiment 2 — Decomposing the failure

`diagnose_accretion.py`, 420 queries:

```
gold missed by baseline top-10   266  (36.6% of all gold)
  ... proposed by accretion      142  (53.4%)   <- generation works
  ... never proposed             124  (46.6%)
rank of proposed gold within the accretion list: median 17, p25 5, p75 41
  within top-1  9.2%   top-3 16.2%   top-5 23.9%   top-10 36.6%
```

So generation is not the bottleneck — **ranking inside the accretion list is**. Then
the economics, from `diagnose_slots.py`:

```
baseline gold density by rank:  r1 0.467  r2 0.233  r3 0.122  r4 0.096
                                r5 0.066  r6 0.021  r7 0.027  r8 0.025
                                r9 0.034  r10 0.035

accretion recovers (gold the baseline missed): @1 0.0310  @2 0.0476  @3 0.0548
cost of evicting the cheapest slot (rank 10):         0.0347
```

**Every completion slot is net-negative**: 0.0310 gained < 0.0347 lost, and the second
and third slots are worse (+0.0166 and +0.0072 against 0.0339 and 0.0247). Inserting at
rank 4 was worse still — it displaced a slot holding gold at 0.096, which is why MRR
and P@5 fell while recall barely moved.

The "free slot" escape is empty: only 17.6% of queries return fewer than 10 files, and
accretion placed exactly **1** gold file into all of them combined.

## Experiment 3 — Fitting the weights: overfits, reported as such

The weights had never been fitted (all 1.0). Leave-one-repository-out,
objective `recovery@1`:

| | uniform | fitted | Δ |
|---|---|---|---|
| in-sample | 0.0310 | 0.0452 | +46% |
| **held-out (pooled)** | **0.0310** | **0.0286** | **−0.0024** |

1 of 8 folds improved, 2 regressed, and the coefficients swing wildly across folds
(`cochange` 0.91–4.21, `edge` 0.00–0.28). **The fit does not generalise**, so uniform
weights are used everywhere below. A 46% in-sample gain that reverses out of sample is
exactly the artifact leave-one-out exists to catch.

## Experiment 4 — Calibration: the signal is real and selective

Accretion proposes nothing on 58% of queries. Conditioned on firing (n=177):

| fire on top | threshold | precision | vs slot cost 0.035 |
|---|---|---|---|
| 2% | 2.095 | 0.667 | **19×** |
| 10% | 1.547 | 0.353 | **10×** |
| 20% | 1.321 | 0.200 | 5.8× |
| 50% | 0.826 | 0.125 | 3.6× |
| 100% | 0.124 | 0.073 | 2.1× |

The score is **well calibrated** — precision rises monotonically and steeply. Gate
selected under LORO: τ = 0.600 in 7 of 8 folds, on a plateau (net gold/query flat at
0.021–0.024 for τ ∈ [0, 1.1]). This is a plateau interior, not a peak.

## Experiment 5 — Fixing the slot policy: a null result

Tail placement, one gated completion:

| vs `hybrid` | Δ | 95% CI | p |
|---|---|---|---|
| recall@10 | +0.0062 | [−0.0085, +0.0212] | 0.431 |
| MRR | −0.0005 | [−0.0019, +0.0007] | 0.732 |
| useful@budget | +0.0038 | [−0.0062, +0.0145] | 0.501 |

Nothing significant either way. The regression is repaired; no gain replaces it.

## Experiment 5b — Comparison against the required baseline families

All seven systems, same 420 queries, same indexes, same 1500-token budget, same
`apply_budget` and compactor, so token accounting is symmetric:

| system | recall@5 | recall@10 | MRR | nDCG@10 | useful@budget | tokens | useful/token | p50 ms |
|---|---|---|---|---|---|---|---|---|
| `bm25` (FTS5 Okapi) | 0.452 | 0.497 | 0.368 | 0.370 | 0.423 | 1184.6 | 3.57e-4 | 13.5 |
| `dense` (LSA-160) | 0.351 | 0.386 | 0.243 | 0.262 | 0.333 | 741.3 | 4.49e-4 | 6.3 |
| `rag` (BM25 ⊕ dense, RRF) | 0.448 | 0.512 | 0.324 | 0.351 | 0.426 | 1131.7 | 3.76e-4 | 15.1 |
| `graph` (PPR, forced on) | 0.616 | 0.698 | 0.587 | 0.563 | 0.617 | 1083.2 | **5.70e-4** | 63.5 |
| `hybrid` (shipped 1.10.0) | 0.618 | 0.693 | 0.583 | 0.559 | 0.617 | 1093.0 | 5.64e-4 | 45.9 |
| `hybrid13` | 0.629 | 0.695 | 0.589 | 0.564 | 0.644 | 1168.4 | 5.51e-4 | 55.9 |
| `nucleus13` | 0.629 | **0.696** | **0.590** | **0.565** | **0.649** | 1243.0 | 5.22e-4 | 61.4 |

Three things worth naming:

- **The dense baseline is LSA, not a neural encoder** (no `sentence-transformers`, GPU
  or network here). It is weak — MRR 0.243 — and I therefore make **no claim of
  beating "embeddings"**. Its role is to keep the hybrid-RAG row honest, not to stand
  in for a modern code encoder.
- **`graph` with PPR forced on is essentially tied with `hybrid`** (MRR +0.004, ns) but
  raises `cand_recall` +0.049 (p<0.001). Structural expansion genuinely widens the
  pool and genuinely fails to convert that into ranking gains — independent
  corroboration of this repository's decision to ship `graph_source=False`, and the
  first sign that Experiment 6 was going to come out the way it did.
- **Token efficiency falls monotonically with page size** (5.70 → 5.64 → 5.51 → 5.22
  e-4). "Useful per token" alone always favours returning less, so it cannot be used
  as a lone objective; the honest object is the recall-versus-tokens curve, on which
  NUCLEUS sits *below* the baseline.

## Experiment 6 — The decisive comparison

If the constraint is tokens rather than rank slots, completions can be *appended* as
contract slices (signatures, not bodies) instead of evicting. But then the baseline
must be allowed the same page growth, or "bigger page wins" is indistinguishable from
"better page wins". Hence `hybrid13`.

| system | recall@10 | recall@15 | MRR | useful@budget | tokens | useful/token |
|---|---|---|---|---|---|---|
| `hybrid` (limit 10) | 0.693 | — | 0.583 | 0.617 | 1093 | 5.65e-4 |
| `hybrid13` (limit 13) | 0.695 | 0.723 | 0.589 | **0.644** | 1168 | **5.51e-4** |
| `nucleus` (10 + 3) | 0.694 | 0.717 | 0.584 | 0.629 | 1189 | 5.29e-4 |
| `nucleus13` (13 + 3) | 0.696 | **0.741** | 0.590 | **0.649** | 1243 | 5.22e-4 |

Paired, against the page-matched baseline:

| `nucleus` vs `hybrid13` | Δ | p | | `nucleus13` vs `hybrid13` | Δ | p |
|---|---|---|---|---|---|---|
| useful@1000 | **−0.0171** | **0.038** | | useful@budget | +0.0056 | **0.030** |
| cand_recall | **−0.0190** | **<0.001** | | useful@500 | +0.0062 | **0.029** |
| useful@budget | −0.0149 | 0.075 | | recall@15 | +0.0181 | **<0.001** |
| MRR | −0.0051 | 0.343 | | MAP | +0.0025 | **<0.001** |

**This is the refutation.**

1. `nucleus` (spending slots) is **worse** than simply returning three more results.
2. `nucleus13` (spending tokens) does beat the page-matched baseline significantly —
   but by +0.0056 useful@budget for **+75 tokens (+6.4%)**. Its token efficiency is
   **5.22e-4 vs 5.51e-4 useful-per-token: NUCLEUS is 5% *less* efficient than the
   baseline it beats.**

On the axis the whole research programme was aimed at — more answer per token — the
mechanism is negative. A +0.9% relative gain bought with +6.4% more tokens is not
minimal sufficient context; it is a slightly bigger context.

## Experiment 7 — Ablations

Every component ablated independently against `nucleus13` (420 queries):

| variant | useful@budget Δ | tokens Δ |
|---|---|---|
| `-accretion` (= `hybrid13`) | −0.006 | −74.7 |
| `-cochange` | 0.000 | −0.5 |
| `-edges` | +0.001 | −16.7 |
| `-testlink` | −0.001 | −2.6 |
| `-stem` | −0.002 | −65.9 |
| `-dir` | 0.000 | −4.4 |
| `-coverage_select` (H2 off) | −0.001 | −4.0 |
| `-hub_penalty` | +0.009 | +67.6 |
| `-compact_completions` (H8 off) | −0.003 | +14.7 |
| `combine=max` | +0.003 | −17.6 |
| `gate=0.0` | +0.001 | +77.1 |
| `slots=1` | −0.001 | −36.5 |

**No single relation carries the effect.** Every individual ablation moves
useful@budget by ≤0.003 — within noise on this query set. The only ablation that moves
anything is removing accretion wholesale. H2's coverage selection contributes −0.001,
i.e. nothing measurable: the elegant submodular objective is doing no work here,
because with `max_completions = 3` from a gated pool there is rarely a redundancy to
resolve.

`-compact_completions` costs −0.003 useful@budget while *adding* 15 tokens, which is
the one place H8 (contracts instead of bodies) shows its expected sign.

## Experiment 8 — Memory plane (H3/H4): validated

Evidence = the spans the shipped retriever actually returns for each of the 420
queries. Survival measured retrospectively against real history via
`git diff --unified=0 HEAD~h HEAD` new-side hunks, which are already in HEAD
coordinates — exact overlap, no line mapping, no re-indexing.

| horizon (commits) | file-keyed survival | span-keyed survival | span/file | **semantic-cache unsound rate** |
|---|---|---|---|---|
| 1 | 0.729 | 0.795 | 1.09 | **20.5%** |
| 2 | 0.624 | 0.740 | 1.19 | 26.0% |
| 5 | 0.474 | 0.629 | 1.33 | 37.1% |
| 10 | 0.383 | 0.521 | 1.36 | **47.9%** |
| 20 | 0.213 | 0.309 | 1.45 | 69.1% |
| 50 | 0.099 | 0.130 | 1.32 | 87.0% |

Two results:

**Query-keyed caches are unsound at a rate that makes them unusable for code.** A
semantic cache reuses on question identity, so it would serve every one of these
entries; after 10 commits **47.9% of them are stale**, and after a *single* commit,
20.5%. There is no similarity threshold that fixes this, because the failure is not in
the similarity estimate — the cache key omits the dependency entirely. Evidence keying
drives this to zero by construction, not by tuning.

**H4 holds, but weaker than predicted.** I predicted a large multiplicative retention
gain from finer granularity. Measured: **1.36× at h=10**, rising to 1.45× at h=20 —
real, and growing with horizon as predicted, but not the 2–3× I claimed. Per-repo
variance is large (1.00 for `denfry.github.io` and `DevGraph`, 2.75 for
`codebase-index` at h=10) and tracks whether commits touch files at a granularity
finer than the whole file. The mean evidence footprint is 4.1 spans across 4.1 files —
one span per file — which caps how much span-keying can possibly recover.

**Cross-agent sharing.** Over the 420-task workload, 1738 atom reads collapse to 1098
distinct atoms: **42.0% of tokens are never re-sent** by a content-addressed shared
memory (range 13.1% `TerraForge` – 65.4% `denfry.github.io`). This is deduplication,
not compression, and it is exact.

---

## Stage 7 — Trying to destroy the surviving result

**Adversarial corpora.** `denfry.github.io` (a website: 48 files, 30 symbols) and
`WinCleaner` (PowerShell: 39 files, **0** symbols, **0** edges) were kept in
deliberately. They break the retrieval plane (reachability 0.333 and structure-free)
and they do *not* break the memory plane, whose mechanism needs no symbols at all.
`PoliternalParkour` is the pathological case for memory: survival 0.203 at h=1,
because its commits are enormous — exactly the "highly dynamic codebase" failure mode.
Reported, not hidden.

**Is the survival result just "code changes"?** Partly, and that is the point: the
contribution is the *magnitude* on real repositories and the demonstration that
granularity is a lever. But it means the numbers are corpus-specific and would differ
on a slow-moving repository. They are not a universal constant.

**Does the memo help if evidence sets never repeat exactly?** This is the strongest
objection. Exact-set keying is brittle: two agents must read *identically* to share an
entry. The 42% dedup figure is measured at *atom* granularity (sub-conclusion sharing),
which is the level where reuse actually occurs; whole-conclusion reuse will be far
rarer. **I did not measure whole-conclusion hit rate under a realistic multi-agent
workload, and the architecture's `MemoStore.get_or_compute` is therefore untested at
the level that matters most for the "don't redo work" claim.** That is the largest
remaining hole in this work.

**Is the retrieval refutation an artifact of file-level ground truth?** Plausibly, and
this is the fairest defence of H1. The benchmark scores at file granularity, so a
completion that supplies exactly the right *function* in a file the baseline already
returned earns nothing. Symbol-level ground truth might change the verdict. It would
not change the token-efficiency arithmetic, which is granularity-independent.

**Threat I cannot close.** Ground truth is "files the commit touched", a proxy for
"files the agent needed". H6 (a `ddmin` oracle over an executable verifier) is the
right instrument and needs an LLM agent loop I do not have here. Every number above
inherits that proxy, on both sides of every comparison.
