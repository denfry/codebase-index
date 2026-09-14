# Stage 5 — NUCLEUS: architecture, algorithms, complexity

> **Status after Stage 6–7. Read this first.**
> The **retrieval plane (H1/H2) is refuted** on this benchmark: it is dominated by the
> trivial baseline of returning more results, and is *less* token-efficient. The
> **memory plane (H3/H4) is validated** and is the part worth keeping. The
> architecture is documented in full anyway, because a design that was measured and
> rejected is a result, and because the refutation only makes sense against the
> design it refutes. Numbers: `experiments.md`.

**NUCLEUS** — *Necessity-driven Unified Closure over Lexical, Evolutionary and
Structural relations.*

---

## 1. Core abstraction: the evidence atom

Everything in the system is an operation on one object.

```
Atom = (id, kind, span, content_hash, obligations)
    id            stable identity: (path, line_start, line_end)
    kind          file | span | symbol | conclusion
    content_hash  hash of the bytes this atom currently holds
    obligations   set of identifiers the atom defines or references
```

Three properties fall out of this and are the whole reason for the choice:

- **Content addressing gives deduplication for free.** Two agents that read the same
  region name it identically, so a shared store holds it once. Measured: 1738 atom
  reads across a 420-task workload collapse to 1098 distinct atoms — **42% of tokens
  never re-sent**.
- **Content addressing gives *exact* invalidation.** A conclusion records the atoms it
  consumed; it is valid iff every one of those hashes is unchanged. Not "probably
  fresh", not "recent enough" — decidable.
- **Obligations give a coverage objective.** A set of atoms can be scored by what it
  covers rather than by how similar its members are to a query.

## 2. Data model

```
atoms(id, kind, path, line_start, line_end, content_hash, token_est)
obligations(atom_id, symbol)                   -- bipartite atom x obligation
relations(src, dst, type, weight)              -- typed, undirected at file level
                                               -- type in {edge, cochange, testlink,
                                               --           stem, dir}
memo(key, task_class, result, evidence[], created_at)
                                               -- key = H(sorted atom content hashes)
```

`relations` is the union of two very different sources, and the diagnostic in
`hypotheses.md` is what justifies carrying both: static edges connect 30.7% of gold
co-members, history connects 30.4%, and each contributes *uniquely* (5.3% / 9.8%).

## 3. Indexing algorithm

```
INDEX(repo):
  for each file f:                                    # O(N) files
      parse f -> symbols, spans                       # tree-sitter, O(|f|)
      atoms   += spans;  obligations += symbols
  resolve edges globally                              # O(E α(N)) with a suffix map
  fold git history into co-change counts              # O(C · k²), k = files/commit
  build name/dir/stem inverted maps                   # O(N · t), t = tokens per name
```

`k` is bounded by `MAX_COMMIT_FILES = 40`, so the history fold is linear in commits,
not quadratic in repository size. This matters: it is what makes the evolutionary
relation affordable on a repository with a long history.

## 4. Retrieval algorithm

```
NUCLEUS_SEARCH(q, B):                                 # B = token budget
  # -- NUCLEATE ------------------------------------------------------
  A  <- incumbent_hybrid(q)                           # unchanged, deliberately
  A0 <- distinct_paths(A[:anchor_head])               # anchors

  # -- ACCRETE -------------------------------------------------------
  contrib <- {}
  for i, a in enumerate(A0):
      alpha <- 1 / (1 + decay·i)
      for c in neighbours(a):                         # relation-local, not a scan
          for r in RELATIONS:
              contrib[c][r] += alpha · rel_r(a, c)
  for c in contrib:                                   # hub damping
      contrib[c] /= sqrt(1 + degree(c))
  score(c) <- Σ_r θ_r · contrib[c][r]                 # linear in θ by construction
  C <- { c : score(c) ≥ τ }

  # -- SELECT (budgeted greedy coverage) ------------------------------
  covered <- obligations(A0) ∪ terms(q)
  S <- {}
  while |S| < max_completions and C ≠ ∅:
      c* <- argmax_{c∈C}  score(c) · sqrt(1 + |obligations(c) \ covered|)
      S <- S ∪ {c*};  covered <- covered ∪ obligations(c*);  C <- C \ {c*}

  # -- EMIT -----------------------------------------------------------
  render each c ∈ S as a CONTRACT SLICE (signatures, not bodies)
  return A ++ S  under budget B
```

Two design decisions are load-bearing and both came from measurement, not taste:

**Score is linear in θ.** `contrib` is per-relation, so re-weighting never re-walks the
graph. That is what made leave-one-repository-out fitting affordable (`fit_weights.py`)
— and therefore what made it possible to *discover* that the fit does not generalise.

**Completions are appended, never inserted.** The first implementation inserted at
rank 4 and lost significantly (MRR −0.0073, p<0.001). `diagnose_slots.py` explains why:
a completion has precision 0.073, while the rank-4 slot it displaces holds gold with
probability 0.096. Appending removes the eviction entirely, so a completion must only
justify its own tokens.

## 5. Memory algorithm (the part that survived)

```
REMEMBER(task, evidence, result):
  key <- H( sort{ (atom.id, atom.content_hash) for atom in evidence } ‖ H(task_class) )
  memo[key] <- (result, evidence)

RECALL(task, evidence):
  key <- H( ... )                                     # same construction
  return memo.get(key)                                # a hit is sound by construction
```

There is no eviction policy, no TTL, no similarity threshold, and no staleness
heuristic. An entry whose evidence changed is not evicted — it simply becomes
unreachable, because the key that would address it can no longer be constructed. This
is the Bazel/Nix action-cache discipline applied to agent reasoning.

**Granularity is the only tuning knob, and it is the one that matters.** Keying on
whole files is the obvious implementation and costs 26% of the achievable reuse at a
10-commit horizon (survival 0.383 vs 0.521 span-keyed).

## 6. Complexity

| Operation | Cost | Notes |
|---|---|---|
| Index construction | `O(Σ|f| + E·α(N) + C·k²)` | parse + global edge resolve + history fold; `k ≤ 40` |
| Insert / update one file | `O(|f| + deg(f) + k²)` | re-parse, re-resolve its edges, re-fold its commits |
| Accretion (per query) | `O(|A₀| · d̄ · \|R\|)` | `d̄` = mean relation degree; **no corpus scan** |
| Coverage selection | `O(m · max_completions · \|O\|)` | `m` = gated candidates; greedy, `(1−1/e)` |
| Retrieval total | anchor stage + ~1 ms | measured: p50 41.3 ms → 56.2 ms |
| Memo lookup | `O(\|E\|)` hash + `O(1)` | `\|E\|` = evidence atoms, measured mean 4.1 |
| Memo invalidation | `O(1)` amortised | no scan: stale keys are simply never formed |
| Memory usage | `O(N + E + P)` | `P` = distinct co-change pairs, bounded by `C·k²` |
| Multi-agent sync | `O(1)` per atom | content-addressed ⇒ no coordination, no consensus |

The `O(1)` synchronisation is worth naming: because every atom and every memo entry is
named by a hash of its content, two agents never need to agree on anything. There is
no invalidation broadcast, no version vector, and no leader. It is the CRDT-like
property that content addressing buys.

## 7. Fault tolerance and incremental update

- **Partial index is safe.** Missing relations reduce accretion recall; they cannot
  produce a wrong answer, because relations only *propose* candidates.
- **Corrupt/absent history degrades to structure-only.** `CoChangeModel` with no
  commits yields zero co-change weight and the system still runs (asserted in
  `test_nucleus.py`).
- **The memo cannot serve a stale entry** even after a crash mid-write: a partially
  written entry has a key nothing will construct.
- **Incremental update** is per-file; the co-change fold is append-only, which is also
  what enforces the no-lookahead property in evaluation.

## 8. Agent communication and distributed operation (designed, not measured)

Routing by obligation ownership (H11): a task's implicated obligation set determines
which shard owns its atoms, so assignment is graph partitioning of the atom×obligation
bipartite graph minimising cut. Two agents whose obligation sets intersect are
predicted to conflict *before* either writes. This is specified but **not measured** —
it needs a live multi-agent workload, and no claim is made for it here.

## 9. What the architecture got right and wrong

Right: content addressing as the single abstraction; separating anchor budget from
completion budget; keeping the score linear so it could be fitted and falsified;
contract slices instead of bodies.

Wrong: the central bet. Conditional completion assumed the incumbent's tail slots were
weak. They are not — a tuned hybrid ranker's rank-6..10 results carry gold at
0.021–0.035, and the relation union's top candidate carries it at 0.073 only when it
fires at all, on 42% of queries. The margin is real but too thin to pay for its tokens.
