# Stage 8 — Novelty assessment

The brief forbids claiming "nobody has done this" without a real check. I ran one, and
the honest answer is uncomfortable: **neither of the two mechanisms I designed is
novel.** Both have close, recent prior art that I was unaware of when designing them.
What survives as a contribution is narrower and mostly empirical.

Searches run 2026-09-09 across arXiv/Scholar-indexed literature and the code-retrieval
ecosystem. Phrasing throughout is "novel relative to the reviewed literature" or, where
prior art was found, no novelty claim at all.

---

## The retrieval plane (H1 + H2) — **not novel**

| Prior work | Overlap |
|---|---|
| **RepoHyper** (Search-Expand-Refine on a Repo-level Semantic Graph, arXiv 2403.06095) | This is essentially my architecture. "Search-then-Expand" = nucleate-then-accrete; a link predictor refines the expanded set = my scored relation union. Published 2024. |
| **CoCoMIC** | Method-level dependency graph for cross-file completion; the anchor-plus-dependency-context pattern. |
| **GRACE** (2509.05980), **RANGER** (2509.25257) | Graph-guided / graph-enhanced repository-level retrieval, same family. |
| **PACMS** (2606.20047) | "Recasts agent context assembly as budget-constrained submodular selection", facility-location coverage, and reports it beats both MMR-style diversification and pure relevance. This is H2, done first and done better. |
| **Context-Picker** (2512.14465) | "Shifts the paradigm from similarity-based ranking to minimal sufficient subset selection", mining minimal sufficient sets via leave-one-out. This is both my framing *and* my rejected H6 oracle. |
| **Zimmermann et al. ROSE** (ICSE'04), **Ying et al.** (TSE'04) | Co-change association-rule mining — the evolutionary relation, twenty years prior. |
| **Aider repo-map** | PageRank over the symbol graph for LLM context. |

I independently rederived a design that the field converged on, and the literature is
ahead of it on the selection objective in particular. That is worth stating plainly
rather than hedging.

## The memory plane (H3 + H4) — **not novel as a mechanism**

| Prior work | Overlap |
|---|---|
| **Invalidation Contracts for Cross-Episode Agent Memory** (2609.00243) | Version stamps + cacheability hints attached to cached agent conclusions so stale entries can be evicted without trial and error. Same problem, same diagnosis. |
| **Fresh Memory, Stale Plans: Dependency-Scoped Validation for Distributed LLM-Agent Memory** (2609.03340) | PlanFence: plans cite the exact records they used; the executor validates only records that can affect the pending action. This is dependency-keyed validity for agent memory. |
| **From Agent Traces to Trust: Evidence Tracing and Execution Provenance** (2606.04990) | Provenance over retrieved passages, tool outputs, memory items. |
| **Bazel / Nix / ccache; Adapton, self-adjusting computation** | Content-addressed action caches with dependency-keyed invalidation — the actual ancestor, decades old. |

The transplant of build-system content addressing to agent memory, which I framed as
the novel step, was published at least twice in 2026 before this work.

---

## What is left, stated conservatively

Novel relative to the reviewed literature, and all of it **empirical rather than
mechanistic**:

1. **A quantified refutation of anchor-and-expand retrieval under a page-matched
   baseline.** The graph-expansion literature (RepoHyper, GRACE, RANGER) reports gains
   against a fixed-size retrieval baseline. I find that on commit-derived ground truth
   across eight repositories, the gain is dominated by the trivial control of
   *returning more results*, and that the mechanism is 5% **less** token-efficient than
   the baseline it beats. I did not find this control reported in the reviewed papers.
   It is cheap, and it should be standard.

2. **Slot economics as a decision procedure.** Expressing an expansion mechanism's
   value as `gain(slot) vs P(gold at the displaced rank)` — measured here as 0.031
   vs 0.035 — turns "should we add graph expansion" into arithmetic. This framing, and
   the per-rank gold-density table it needs, I did not find in the reviewed literature.

3. **Magnitude of query-keyed cache unsoundness on real code history**: 20.5% stale
   after 1 commit, 47.9% after 10, 69.1% after 20. The invalidation-contract papers
   argue the problem exists; I have not seen it *measured* against version history on
   real repositories.

4. **The granularity/retention measurement**: span-keyed evidence retains 1.36× more
   valid reuse than file-keyed at a 10-commit horizon, growing to 1.45× at 20, with
   the multiplier tracking file size versus commit size. Apparently novel as a
   measurement; the underlying idea (finer dependencies invalidate less) is folklore.

5. **42.0% cross-task evidence deduplication** on a 420-task workload over eight
   repositories — a concrete ceiling for shared agent memory.

6. **A reproducible negative-result protocol**: no-lookahead history enforced by the
   data structure rather than by discipline, equivalence-to-incumbent asserted by test,
   and leave-one-repository-out applied to a fit that then *failed* to generalise and
   was reported anyway.

## What I would have done differently knowing the prior art

Read PACMS and Context-Picker before Stage 5. PACMS in particular reports the
submodular selection result I set out to obtain, which would have redirected the
effort toward the memory plane — where the measurements turned out to be worth having —
several hours earlier.

## Sources

- [RepoHyper: Search-Expand-Refine on Semantic Graphs](https://arxiv.org/abs/2403.06095)
- [PACMS: Submodular Context Selection as a Pluggable Engine for LLM Agents](https://arxiv.org/html/2606.20047)
- [Context-Picker: Dynamic Context Selection Using Multi-stage RL](https://arxiv.org/html/2512.14465)
- [GRACE: Graph-Guided Repository-Aware Code Completion](https://arxiv.org/pdf/2509.05980)
- [RANGER: Repository-level Agent for Graph-Enhanced Retrieval](https://arxiv.org/html/2509.25257)
- [Invalidation Contracts for Cross-Episode Agent Memory](https://arxiv.org/html/2609.00243)
- [Fresh Memory, Stale Plans: Dependency-Scoped Validation](https://arxiv.org/html/2609.03340)
- [From Agent Traces to Trust: Evidence Tracing and Execution Provenance](https://arxiv.org/html/2606.04990v1)
- [Enhancing Software Maintenance: Learning to Rank for Co-changed Method Identification](https://arxiv.org/pdf/2411.19099)
- [Retrieval-Augmented Code Generation: A Survey with Focus on Repository-Level Approaches](https://arxiv.org/html/2510.04905v1)
