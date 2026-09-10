# Stage 2–3 — Thirteen hypotheses

Each entry states what is proposed, why the field has not already done it, and a
formal model. They are deliberately drawn from different parent disciplines; the
selection matrix in `selection.md` then cuts them down by feasibility *on evidence
available here*, not by appeal.

Notation: corpus of atoms `A`; task `t`; retrieved set `S ⊆ A`; token cost
`c: A → ℕ`; budget `B`; gold/necessary set `N(t) ⊆ A`.

---

## H1 — Retrieval as conditional set completion ("nucleate and accrete")

**Hypothesis.** Replace `top-k argmax_d P(d|q)` with a two-stage set construction:
find a small high-precision *anchor* set `A₀` from the query, then **complete** it
using relations conditioned on the anchor rather than on the query:

```
A₀ = argtop_a  P(a | q)                     (lexical/symbol; high precision, low recall)
S  = A₀ ∪ argtop_c  P(c ∈ N(t) | A₀, c ∉ A₀)   (completion; query-independent)
```

**Why it may work / why it is not already done.** Every mainstream system scores
documents *independently given the query*, so the factor `P(c | A₀)` — by far the
strongest available signal for "needed together" — is structurally inexpressible.
Where systems do inject structure (PPR, graph retrievers) they inject it as *another
pointwise opinion into the same fusion*, which forces architectural neighbours to
compete with direct hits for the same ranked slots. This repository ran that
experiment and shipped `graph_source = False` because it lost MRR. The hypothesis is
that the signal was fine and the **composition** was wrong.

**Mathematical intuition.** The true objective is a set posterior which does not
factorise:

```
P(N(t) = S | q) ≠ Π_{d∈S} P(d ∈ N(t) | q)
```

Model the dependence with a first-order chain (Chow–Liu style tree over the
change-set): each non-anchor member attaches to some already-selected member,

```
P(S | q) ≈ max_{a∈A₀} P(a | q) · Π_{c ∈ S\A₀} max_{s ∈ S, s≺c} P(c | s)
```

so `log P(S|q)` decomposes into an anchor term plus **pairwise completion terms**
`log P(c|s)` estimated over a typed relation union. Empirically (see
`diagnose_structure.py`) `P(∃ relation | c,s both gold) = 0.718` pooled across eight
repositories, with no temporal lookahead, versus a base rate of `O(1/|A|)` for a
random pair — a likelihood ratio of roughly `10²–10³`.

---

## H2 — Selection as budgeted maximum coverage over latent obligations

**Hypothesis.** Replace "take top-k, then MMR for diversity" with an explicit
**budgeted maximum coverage** program. Posit latent *obligations* `O` (things the task
must account for: a symbol, a contract, a config key). Each atom `a` covers
`cov(a) ⊆ O`; the task implicates `O(t) ⊆ O`. Then

```
maximise   f(S) = | O(t) ∩ ⋃_{a∈S} cov(a) |     subject to   Σ_{a∈S} c(a) ≤ B
```

**Why it may work.** `f` is monotone submodular, so greedy by *coverage gain per
token* is a `(1 − 1/e)`-approximation (Nemhauser; Khuller–Moss–Naor for the budgeted
variant). More importantly it is the *correct* objective: MMR maximises pairwise
dissimilarity, which is a proxy that actively misfires here — two files implementing
the same contract are highly similar and both necessary, exactly the pair MMR
suppresses. No mainstream retriever optimises coverage of task obligations because
obligations are never materialised.

**Mathematical intuition.** Diminishing returns: `f(S∪{a}) − f(S)` is non-increasing
in `S`. Greedy picks `argmax_a (f(S∪{a}) − f(S)) / c(a)`. Contrast with top-k, which
picks `argmax_a score(a)` — identical only when `cov` are disjoint and equal-cost,
i.e. never.

---

## H3 — Evidence-keyed memoisation: agent reasoning as a content-addressed build

**Hypothesis.** Store every agent conclusion keyed not by its *question* but by a hash
of the **evidence it consumed**:

```
key(r) = H( sort{ (atom_id, content_hash(atom)) : atom ∈ evidence(r) } ‖ H(prompt_class) )
```

A cached conclusion is reusable **iff every atom in its key still hashes to the same
value**. Otherwise it is not "probably stale" — it is *definitely* invalid, and is
evicted deterministically.

**Why it may work / why it is not already done.** Semantic caches key on query
similarity, which carries zero information about whether the world changed. Build
systems (Bazel, Nix, `ccache`) solved exactly this problem for compilation two decades
ago with content-addressed action caches, and self-adjusting computation (Acar et al.)
solved it for general programs. Agent memory has not adopted it because agent
conclusions are usually stored as prose with no recorded provenance — the dependency
set is thrown away at write time. It is an *engineering omission that has a
correctness consequence*, which is the most promising kind.

**Mathematical intuition.** Let `V(r,τ)` be the event "r is still valid at time τ".
Under evidence keying, `P(unsound reuse) = 0` exactly (a hash collision aside), while a
similarity cache has `P(unsound reuse) = P(evidence changed | q ≈ q_cached) > 0` and
*uncorrelated with the threshold*. The interesting quantity is therefore not
soundness — which is free — but **survival**: `P(V(r,τ))` as a function of evidence
granularity. That is H4.

---

## H4 — The granularity law of memory survival

**Hypothesis.** Reuse survival is governed by the *measure* of the evidence footprint,
not its semantic breadth. If a conclusion depends on `m` atoms each independently
invalidated at per-commit rate `λ`, survival after `n` commits is

```
P(valid after n commits) ≈ (1 − λ)^{m·n}
```

so shrinking atom granularity (file → symbol) shrinks `λ` roughly in proportion to the
fraction of the file a typical commit touches. **Prediction: symbol-level evidence keys
retain multiplicatively more valid reuse than file-level keys**, and the multiplier is
measurable directly from git history with no model in the loop.

**Why it matters.** It converts "choose your memory granularity" from taste into an
estimable quantity, and it predicts that the naive choice (file-level provenance,
which is what any straightforward implementation would do) is the expensive one.

---

## H5 — Retrieval as entropy minimisation over the answer set

**Hypothesis.** Choose the next atom that maximally reduces uncertainty about the
answer: `a* = argmax_a I(Y ; a | S)` where `Y` is the answer random variable.

**Mathematical intuition.** `H(Y|S)` decreasing is the ideal stopping criterion:
retrieve until `H(Y|S) < ε`, which yields *adaptive* `k` — few atoms for a sharp
question, many for a diffuse one. Beautiful, and it subsumes H2 (coverage is a
tractable surrogate for mutual information under a set-cover likelihood).

**Why it is hard here.** Estimating `I(Y;a|S)` needs either a scoring LLM in the loop
(cost, non-determinism, no API in this environment) or a strong proxy. Kept as theory:
it is the *justification* for H2's objective rather than an independently testable
mechanism.

---

## H6 — A delta-debugging oracle for minimal sufficient context

**Hypothesis.** Ground truth for "minimal necessary context" can be *computed*, not
guessed: given a task with an executable verifier (test suite), run `ddmin` over
candidate context sets to find a 1-minimal `S` such that the agent still succeeds.
Then distil a cheap predictor from those labels.

**Why it may work.** Every code-retrieval benchmark today uses a weak proxy label
("the files the commit touched"). ddmin would produce true minimal sufficient sets and
expose how wrong the proxy is.

**Why it is not selected.** Requires `O(|S| log |S|)` *agent executions per query* with
a working LLM and per-repo test harness. Out of reach in this environment; recorded as
the highest-value follow-up in `further-work`.

---

## H7 — Context prefetching from agent access traces

**Hypothesis.** An agent's file-access sequence is a memory reference stream. Apply
correlation/Markov prefetching: `P(next atom | last k atoms)`, prefetch on anchor
resolution, and bound the achievable gain with a Belady-style offline optimum.

**Why it may work.** Hardware prefetching theory is mature and directly transferable;
"working set" and reuse-distance (Mattson stack distance) give principled context-window
sizing. **Why it is not selected now:** it needs a corpus of real agent traces, which I
do not have. Note the co-change relation in H1 is a *degenerate offline form* of this
(commits as access traces), which is the part that is testable today.

---

## H8 — Obligation-level granularity: index contracts, return slices

**Hypothesis.** The retrievable unit should be an *obligation* (signature +
pre/post-conditions + error modes), with full bodies returned only for atoms the task
must modify. Expected 3–10× token reduction on "how do I call X" tasks.

**Mathematical intuition.** `tokens(signature) / tokens(body) ≈ 0.05–0.2`. If a
fraction `ρ` of retrieved atoms are needed only as *callees* (understand the contract)
rather than *editees*, the bill falls to `ρ·0.1 + (1−ρ)` of baseline.

**Status.** Compatible with, and partially already implemented by, this repository's
`retrieval/skeleton.py` compactor. Folded into the architecture as a cost model rather
than claimed as novel.

---

## H9 — Index the derivative, not the state

**Hypothesis.** Make the indexed document a *change* (commit: subject + diff +
co-changed set), not a file. Retrieval then answers "what changed like this before",
returning both the precedent and the files it touched.

**Why it may work.** Causal/intentional information ("why") lives in change records
and is absent from the tree. **Risk:** benchmark circularity — the ground truth here is
itself derived from commits, so indexing commits would let the system read the answer.
Only admissible under a strict temporal split; that discipline is adopted for the
co-change relation and this hypothesis is otherwise deferred.

---

## H10 — Self-organising index (Hebbian re-weighting)

**Hypothesis.** Relation weights adapt online: atoms co-retrieved in successful tasks
strengthen their link, `w ← w + η(1−w)`; unsuccessful, decay. The index reorganises
toward the workload.

**Mathematical intuition.** Stochastic approximation on the completion model of H1 —
`P(c|s)` becomes an online-estimated parameter. Convergence under Robbins–Monro
conditions; the risk is a rich-get-richer collapse without exploration.

**Status.** A natural extension of H1 once feedback exists. Not testable without a
live agent workload; the architecture leaves the parameter slot open for it.

---

## H11 — Routing by obligation ownership

**Hypothesis.** Route multi-agent work by *which obligations a task implicates*, not by
task-description similarity. Two agents whose implicated obligation sets intersect are
on a collision course and must share memory or serialise.

**Mathematical intuition.** Predicted conflict = `|O(t₁) ∩ O(t₂)| > 0`. Assignment
becomes graph partitioning of the obligation hypergraph minimising cut (shared
obligations) — the classic distributed-systems objective, with obligations as the
shared state.

**Status.** Designed into the architecture; measurable only in simulation here.

---

## H12 — Negative results as first-class atoms

**Hypothesis.** Store *refuted* hypotheses and failed attempts with their evidence
keys. A second agent asking a question whose evidence key matches a recorded failure
gets the refutation instead of repeating the search.

**Why it may work.** Failed work is the largest silent cost in multi-agent systems and
is never recorded because it produces no artifact. Under H3's keying it is free: a
failure is just a conclusion with a negative polarity.

---

## H13 — Speculative closure precomputation

**Hypothesis.** Precompute and cache completion closures for the `O(k)` most likely
near-future tasks (derived from open diffs, recent commits, TODOs), so the closure is
warm when the task arrives.

**Mathematical intuition.** Amortises closure cost; value = `hit_rate ×
closure_latency`. Only worthwhile if closure latency is a bottleneck — measured below,
it is ~1 ms, so this is premature. **Rejected on measurement**, which is the correct
reason to reject something.

---

## What the diagnostic already tells us

Before any selection, `diagnose_structure.py` (run on 900 anchor→target gold pairs,
eight repositories, strict temporal split) reports:

| relation | covers | uniquely |
|---|---|---|
| stem (shared name tokens) | 35.8% | — |
| static edge (import/call/ref) | 30.7% | 5.3% |
| co-change (history before the query commit) | 30.4% | 9.8% |
| same directory | 23.8% | — |
| test↔impl link | 14.4% | — |
| **union** | **71.8%** | |

Two facts decide Stage 4. First, the union is far above any single relation, so the
completer must be **multi-relation**. Second, structure and history each contribute
*uniquely* (5.3% and 9.8%), so neither subsumes the other and a system with only one of
them leaves measurable recall on the table. H1 is therefore not merely plausible — its
central premise is already measured, on the same corpora the final benchmark uses.
