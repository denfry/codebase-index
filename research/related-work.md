# Stage 1 — The existing frontier and where each approach structurally stops

This is not a literature survey for its own sake. For each family the question is
narrow: **what does this method make impossible?** A limitation that a bigger model
or a better index would fix is an engineering gap, not a fundamental one. Only the
latter justifies a new architecture.

Throughout, `q` is a query, `d` a document/chunk, `S` a retrieved set, `t` a task.

---

## 1. Sparse lexical retrieval (BM25, FTS5, tf-idf)

**What it computes.** `score(q,d) = Σ_{w∈q} IDF(w)·tf-saturation(w,d)`. A bag-of-words
independence assumption per term, summed.

**Fundamental limitation — the vocabulary/necessity confusion.** BM25 can only rank a
document that *contains the query's words*. For code retrieval this is not a synonym
problem (fixable with expansion) but a **causality problem**: the file you must edit
alongside `auth/token.py` is `api/service.py`, which contains none of the query's
terms and never will. No re-weighting of a term-overlap function can produce a
document with zero term overlap. The ceiling is structural, not parametric.

Measured in this repository (`docs/BENCHMARKS.md`): the shipped hybrid ranker reaches
`recall@10 = 0.693` while `oracle = 0.90`. The residual is dominated by gold files
that share no vocabulary with the query.

## 2. Dense retrieval / embeddings (DPR, sentence encoders, code encoders)

**What it computes.** `score(q,d) = ⟨E(q), E(d)⟩` — a single vector per document,
compared by inner product.

**Fundamental limitation — the single-vector bottleneck and pointwise independence.**
Two distinct failures:

1. *Capacity.* One vector must encode everything a document could ever be relevant
   for. A file participating in 30 unrelated concerns gets one point in space. This
   is a known information-theoretic bound: a `k`-dimensional vector cannot preserve
   all pairwise relevance orderings of a corpus beyond a critical size (the
   "embedding dimension vs. retrievable set" limit).
2. *Independence.* `score` factorises over documents. The model can express
   "d is similar to q" but **cannot express "d is needed only if d' is also
   retrieved"**. Every retrieval-as-ranking system inherits this: the top-k of a
   pointwise scorer is not a set-optimal answer, it is `k` independently good answers.

This second point is the one that matters here, and no amount of encoder quality
removes it. It is an artifact of the *objective*, not the representation.

## 3. Hybrid + fusion (RRF, convex combination)

**What it computes.** `RRF(d) = Σ_r w_r / (k + rank_r(d))`.

**Fundamental limitation.** Fusion is still pointwise: it aggregates independent
opinions about the *same* document. It adds robustness, never set-awareness. This
repository's own data shows the ceiling precisely: 1.10.0 improved reranking
efficiency 0.639 → 0.660 while `oracle` and `cand_recall` moved by less than 1e-4.
Fusion redistributes the pool; it cannot create a candidate no retriever proposed.

## 4. ColBERT / late interaction

**What it computes.** `score(q,d) = Σ_i max_j ⟨E_i(q), E_j(d)⟩` — token-level
MaxSim, avoiding the single-vector bottleneck.

**Fundamental limitation.** Fixes capacity, keeps independence, and multiplies index
size by ~`|d|`. Still `argmax` over documents scored in isolation, so it inherits §2.2
in full. Late interaction makes similarity finer, not necessity computable.

## 5. ANN indexes: HNSW, IVF, PQ, LSH

**What they compute.** Approximate `argmax_d ⟨q,d⟩` in sublinear time.

**Fundamental limitation — they optimise the wrong operation faster.** These are
accelerators for a metric-space nearest-neighbour query. They presuppose that
"relevant" = "near in a fixed metric". If the target relation is *asymmetric*,
*conditional* (`d` needed given `d'`), or *non-metric* (violates triangle
inequality — necessity plainly does: A needs B, B needs C, A may not need C), the
data structure has no way to represent it. PQ additionally trades recall for memory
in a way that is invisible to the caller — a silent quality knob.

## 6. Graph retrieval / GraphRAG / knowledge graphs / PPR

**What it computes.** Entry by similarity, then diffusion (personalised PageRank,
community summarisation, multi-hop traversal).

**Fundamental limitation — undirected diffusion is not necessity, and it competes for
the same slots.** Two concrete failures, both visible in this repository:

1. *Isotropy.* PPR spreads probability along every edge type at once. "Related to"
   is not "required for". A hub file is reached from everywhere and therefore ranks
   highly for everything — the god-node problem, documented in
   `tests/benchmark_honest_RESULTS.md`.
2. *Slot competition.* When graph neighbours are injected as another retriever into
   the fusion, they displace direct lexical hits. This repo measured exactly that and
   **shipped `graph_source = False`** (`retrieval/tuning.py`): "the self-repository
   ablation showed lower MRR when architectural neighbors displaced direct lexical
   hits."

This is the single most informative prior result available to me. The failure was not
"structure is useless" — my Stage-2 diagnostic shows resolved edges connect 30.7% of
anchor→target gold pairs. The failure was **architectural**: structural evidence was
forced to compete pointwise with lexical evidence in one ranked list, at one weight,
for one budget. That diagnosis is what the proposed architecture is built around.

## 7. GraphRAG specifically

Community detection + LLM-generated community summaries, queried by similarity.
**Limitation:** the summarisation is lossy and *query-independent* — it must guess in
advance which facts matter. It also costs an LLM pass over the whole corpus, which
makes incremental update expensive: one edited file can change community membership.
Good for global sensemaking questions, structurally poor at "which four files must I
edit".

## 8. AST / symbol / code-structure indexing (LSP, tree-sitter, ctags, Aider repo-map)

**What it computes.** Exact symbol definitions/references; repo-map ranks files by
PageRank over the symbol graph.

**Fundamental limitation — static structure is *incomplete*, not merely noisy.** It
sees only relations the language makes explicit. It cannot see: a schema and the
migration that must accompany it; a config key and its consumer; a feature flag and
its test; a protocol and its two independent implementations. My diagnostic quantifies
this: static edges cover 30.7% of the pairs, while 9.8% are reachable *only* by
history. Structural indexing is a high-precision, low-recall relation.

## 9. Evolutionary coupling / MSR (Zimmermann's ROSE, Ying et al.)

**What it computes.** Association rules over co-changed files mined from VCS history.

**Fundamental limitation.** Cold start (new files have no history), drift (couplings
decay as the design changes), and — decisively for benchmark honesty — **it is
trivially leaky if evaluated without a temporal split**. It is also a *recommender*
for an already-known seed file, not a retriever from a natural-language question. It
answers "what else changes with X", never "what is X".

That is precisely why it composes with §1: lexical retrieval is good at finding X from
a question, and bad at finding what accompanies X.

## 10. Semantic caching of LLM calls

**What it computes.** Reuse a cached answer when `sim(q, q_cached) > τ`.

**Fundamental limitation — it is unsound by construction.** Validity of a cached
answer depends on whether the *world it was computed from* has changed, and query
similarity carries no information about that. Two identical questions asked before and
after an edit must get different answers; a semantic cache returns the stale one with
high confidence. There is no threshold that fixes this, because the failure is not in
the similarity estimate — it is that the cache key omits the dependency.

This is the gap the memory plane of the proposed architecture targets.

## 11. Context compression (LLMLingua, RECOMP, selective context)

**What it computes.** Drop low-information tokens from an already-retrieved context.

**Fundamental limitation — it operates strictly downstream of a bad selection.**
Compression can shrink what you retrieved; it cannot retrieve what you missed. If the
required file was never in `S`, no compressor recovers it. Compression improves the
constant factor on `tokens`, and does nothing for `recall`.

## 12. KV-cache reuse / prefix caching

**Limitation.** Reuse is keyed on *literal token-prefix identity*. Any reordering or
one-token edit invalidates everything downstream. It is a systems optimisation with
zero semantic model of what the cached computation depended on — the same blind spot
as §10, at a different layer.

## 13. Memory-augmented agents (episodic / semantic / procedural stores)

**Limitation — write-time amnesia about provenance.** Nearly all implementations store
*what was concluded* and not *what it was concluded from*. Consequently they cannot
invalidate: a memory is retired by recency heuristics or LLM-judged staleness, never
by the fact that its evidence changed. They also store natural-language conclusions,
which cannot be checked for consistency automatically.

## 14. Multi-agent routing / mixture-of-agents / task graphs

**Limitation.** Routing is normally learned over *task descriptions*, so two agents
working on overlapping code are not detected as overlapping. Coordination cost grows
with agent count because there is no shared, addressable substrate — agents exchange
prose, so identical intermediate work is redone with no way to notice.

## 15. Learned / neural indexes (DSI, generative retrieval)

**Limitation.** The corpus is baked into model weights, so incremental update means
retraining or a fragile patching scheme. For a codebase changing hourly this is
disqualifying. Also inherits pointwise independence.

---

## The common root

Reading down the list, four distinct families collapse into **one** structural
assumption:

> **Retrieval = rank documents independently by similarity to the query, then take the
> top k.**

Everything above is an optimisation of some part of that sentence: better `sim`
(§2,§4), faster `argmax` (§5), more robust aggregation (§3), a wider candidate net
(§6,§8,§9), or post-hoc cleanup (§11).

Three consequences follow, and none of them are fixable inside the assumption:

1. **Sets are never optimised.** The objective factorises over documents, so
   "necessary together" is inexpressible. The top-k of a pointwise scorer is `k`
   individually-plausible documents, which is not the same object as a sufficient set.
2. **Necessity is conflated with similarity.** The system answers "what looks like the
   question", where the agent needs "what must be true for the task to be completed".
   These coincide only for lookup questions.
3. **Reuse is unsound.** Nothing records what a conclusion depended on, so nothing can
   be safely reused after the corpus changes.

Stage 2 attacks these three directly.

---

## Prior art most adjacent to the proposal (stated up front, not buried)

Honesty requires naming these before claiming anything. The proposed architecture is
**not** the first system to use co-change or structure for code retrieval:

- **Zimmermann et al., "Mining Version Histories to Guide Software Changes" (ROSE,
  ICSE'04 / TSE'05)** — association-rule co-change recommendation. Directly prior art
  for the evolutionary relation. Differences: ROSE is seeded by a file the developer
  already opened, not by a natural-language query; it recommends *changes*, not
  retrieval context; and it optimises confidence/support, not a token budget.
- **Ying et al., "Predicting Source Code Changes by Mining Change History" (TSE'04)** —
  frequent-pattern mining, same family, same seeding assumption.
- **Aider's repo-map / PageRank over the symbol graph** — structural ranking of files
  for LLM context. Query-independent global ranking; no conditional completion, no
  history, no budgeted coverage objective.
- **CoCoMIC, RepoHyper, RepoFusion, GraphCodeBERT** — cross-file code completion using
  dependency context. Closest in spirit on the structural side; targeted at *code
  completion at a cursor*, where the seed is given by construction, rather than at
  retrieval from a task description.
- **Build systems (Bazel, Nix, `ccache`) and incremental computation (Adapton,
  self-adjusting computation)** — content-addressed action caches with dependency-keyed
  invalidation. This is the direct ancestor of the memory plane; the transplant to
  *agent reasoning* is the part I claim as new, and §8 of `novelty.md` scopes that
  claim carefully.
- **Submodular / facility-location summarisation (Lin & Bilmes 2011), MMR** — budgeted
  set selection in IR. Prior art for the selection stage's mathematics. MMR maximises
  *dissimilarity*; the objective proposed here maximises *coverage of implicated
  obligations*, which is a different function with a different optimum.

The claim under test is therefore not "co-change is new" or "greedy coverage is new".
It is that **conditional set-completion, budget-separated from anchor ranking, is the
composition that makes structural and historical evidence pay off where injecting it
into fusion measurably does not** — a claim this repository's own shipped
`graph_source = False` makes falsifiable rather than rhetorical.
