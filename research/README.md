# NUCLEUS — a research spike on necessity-driven context for coding agents

**The question.** Can an agent be given not "similar data" but a *computed minimal set
of knowledge necessary for the task at hand*?

**The answer this work supports.** Partly, and not the part I expected. Computing the
required *set* by relation-based completion is measurable, real, and **not worth its
tokens** — it is dominated by simply returning more results. Computing what a
conclusion *depended on*, so that work can be reused soundly, is worth a great deal.

Everything below is measured on 420 queries across eight real repositories in four
languages, with paired significance tests, leave-one-repository-out fitting, and a
no-lookahead guarantee enforced by the data structure rather than by discipline.

---

## Headline results

| Claim | Verdict | Evidence |
|---|---|---|
| Required-set members are related by computable relations | **True** | 71.8% of 900 anchor→target gold pairs, no lookahead |
| Structure and history are non-redundant | **True** | edges contribute 5.3% uniquely, co-change 9.8% |
| Anchor + completion beats a hybrid ranker | **False** | dominated by `hybrid13`; 5% *worse* useful-per-token |
| Relation weights can be fitted | **False** | LORO: in-sample +46%, held-out −0.0024, 1/8 folds improve |
| The completion score is calibrated | **True** | precision 0.073 → 0.353 from "always fire" to "top 10%" |
| Query-keyed ("semantic") caches are unsound for code | **True** | **47.9% stale after 10 commits**, 20.5% after one |
| Finer evidence granularity retains more valid reuse | **True, weaker than predicted** | 1.36× at h=10 (predicted 2–3×), rising to 1.45× at h=20 |
| Agent work is heavily shareable | **True** | **42.0%** of tokens never re-sent across a 420-task workload |

## The one number that killed the retrieval plane

```
accretion recovers gold the baseline missed :  0.0310 per query
cost of evicting even the cheapest rank slot:  0.0347 per query
```

Every completion slot is net-negative. Removing the eviction (appending contract
slices instead) makes it positive but not efficient: **+0.9% answer for +6.4% tokens**,
i.e. 5.22e-4 useful-per-token against the baseline's 5.51e-4.

## The one number that saved the memory plane

```
conclusions whose evidence had changed after 10 commits:  47.9%
what a query-keyed cache would do with them             :  serve all of them
what an evidence-keyed cache does with them             :  cannot address them at all
```

Soundness here is free — a property of the key construction, not a tuned threshold.

---

## Documents

| File | Stage | Contents |
|---|---|---|
| `related-work.md` | 1 | 15 approach families, the *fundamental* limit of each, and the single shared assumption underneath them |
| `hypotheses.md` | 2–3 | 13 hypotheses with formal models; the go/no-go diagnostic |
| `selection.md` | 4 | Scoring matrix, TOP-3, what was rejected and why |
| `architecture.md` | 5 | NUCLEUS: abstraction, data model, algorithms, pseudocode, Big-O |
| `experiments.md` | 6–7 | Full protocol, 8 experiments, ablations, and the attempt to destroy the result |
| `novelty.md` | 8 | Prior-art check. **Both mechanisms turned out to have close prior art**; what remains is empirical |

## Code

```
research/
  nucleus/
    relations.py    typed relation union; CoChangeModel with a structural no-lookahead guarantee
    search.py       nucleate -> accrete -> select; reproduces the shipped pipeline when accretion is off
    baselines.py    BM25, LSA dense (numpy-only randomized SVD), hybrid RAG, product hybrid, forced-PPR graph
    memory.py       evidence-keyed memo, span/file granularity, exact invalidation
    evalrun.py      benchmark runner; reuses tests/eval/metrics.py verbatim
  build_indexes.py        one persistent index per corpus
  diagnose_structure.py   Experiment 0: is the premise true at all
  diagnose_accretion.py   generation vs ranking vs displacement decomposition
  diagnose_slots.py       slot economics: gain vs eviction cost per rank
  diagnose_calibration.py precision as a function of score
  fit_weights.py          LORO weight fit (result: does not generalise)
  fit_gate.py             LORO gate selection (result: tau=0.6, 7/8 folds, on a plateau)
  experiment_memory.py    H3/H4: survival, unsoundness, cross-task sharing
  test_nucleus.py         correctness, incl. equivalence-to-incumbent and no-lookahead
```

## Reproducing

```bash
# 1. query sets from git history (leak-free: subjects live in metadata, not the corpus)
python tests/eval/gen_queries.py --repo <path> --out research/data/<name>.yml

# 2. one index per corpus, shared by every system
PYTHONPATH=. python research/build_indexes.py --corpus "<name>:<path>" ...

# 3. correctness first -- the equivalence test is what makes deltas attributable
PYTHONPATH=. python -m pytest research/test_nucleus.py --no-cov -q

# 4. the experiments
PYTHONPATH=. python research/diagnose_structure.py --corpus "<name>|<path>|<qs>|<idx>" ...
PYTHONPATH=. python -m research.nucleus.evalrun --systems bm25,dense,rag,graph,hybrid,hybrid13,nucleus13
PYTHONPATH=. python -m research.nucleus.evalrun --systems hybrid13,nucleus13 --ablate --baseline-label nucleus13
PYTHONPATH=. python research/diagnose_slots.py
PYTHONPATH=. python research/fit_weights.py --rebuild --c 1
PYTHONPATH=. python research/experiment_memory.py
```

External corpora are not vendored — shipping someone else's source to run a benchmark
is not reproducible either. The generator is the reproducible part: point it at any
git repository and the protocol is identical.

## Honest limits

- **Ground truth is a proxy.** "Files the commit touched" ≠ "files the agent needed".
  The right instrument is a `ddmin` oracle over an executable verifier (H6); it needs
  an LLM agent loop unavailable here. Every number inherits this proxy — on both sides
  of every comparison.
- **The dense baseline is LSA, not a neural code encoder.** No
  `sentence-transformers`, GPU, or network in this environment. **No claim of the form
  "beats embeddings" is made anywhere.** The load-bearing comparison is the paired one
  against NUCLEUS's own anchor stage.
- **Whole-conclusion memo hit rate is unmeasured.** The 42% figure is atom-level
  sharing. Exact-set keying is brittle and the "agents don't redo work" claim is not
  fully tested. This is the largest hole.
- **Neither mechanism is novel.** See `novelty.md`. The contribution is measurement
  and falsification, not invention.
- **Multi-agent routing (H11) is designed, not measured.** No claim is made for it.
