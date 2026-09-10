# Retrieval evaluation

Measures whether a ranking change actually helps, on more than one repository, with
enough statistical care to tell an improvement from a reshuffle.

```bash
# shipped default vs the 1.7.0 baseline, on this repository
python tests/eval/run_eval.py

# + one-signal-off ablation, with significance for every row
python tests/eval/run_eval.py --ablate

# pool several repositories into one benchmark
python tests/eval/run_eval.py --queries self_repo_git \
    --corpus ../some-java-service:/tmp/svc.yml \
    --corpus ../some-ts-app:/tmp/app.yml --ablate
```

## Why the results are trustworthy

**The index cannot grade its own homework.** Two independent ground-truth sources,
neither produced by the retriever:

| Query set | Source | Size | Leakage |
|---|---|---|---|
| `self_repo` | Hand-written from the source tree | 36 | Query wording is human; answers verified against the tree |
| `self_repo_git` | Commit subject → files that commit changed | 87 | None: subjects live in git metadata, not in the corpus |

`harness.validate_queries()` fails the run if any expected file no longer exists,
so a stale expectation is a loud error rather than a silently deflated score.

**Benchmark scaffolding is excluded from the corpus it grades** (`CORPUS_EXCLUDES`).
The ground-truth YAML quotes every query verbatim; leaving it indexed would make it
the top lexical hit for almost every query.

**One index per corpus, shared by every variant.** Ablation deltas measure ranking,
never indexing variance.

**Every non-baseline row gets a significance test.** Query sets of this size have a
noise floor of several MRR points, so each metric is reported with a paired
bootstrap 95% CI and a paired permutation p-value (`metrics.paired_bootstrap_ci`,
`metrics.paired_permutation_p`, both seeded and therefore reproducible). Signals
ship on the strength of that test, not the sign of a delta. A one-query move on a
three-query category is noise, and the table is designed to make that visible.

## Adding a corpus

Tuning a ranker against one repository in one language produces numbers that only
move on that repository. `gen_queries.py` mints an objective query set from any git
repository, so a new corpus costs two commands:

```bash
python tests/eval/gen_queries.py --repo ../some-java-service --out /tmp/svc.yml
python tests/eval/run_eval.py --corpus ../some-java-service:/tmp/svc.yml
```

The generator pairs a human-written commit subject with the files that commit
actually changed. It keeps only localised, described changes: no merges, reverts,
releases, version bumps or formatting commits; at most `--max-files` files, all of
which must still exist at HEAD; at least `--min-words` content words after the
Conventional Commits prefix is stripped; duplicate subjects collapse. Changelog-like
files are never accepted as answers because they paraphrase commit subjects, and any
commit touching `tests/eval/` is dropped so the benchmark cannot grade itself.

Corpora used to validate the 1.10.0 ranking changes, beyond this repository:

| Corpus | Language | Files | Queries |
|---|---|---|---|
| Civitas | Java | 944 | 64 |
| PoliternalSite | TypeScript / TSX | 450 | 120 |
| PoliternalParkour | Java | 96 | 64 |
| TerraForge | Java | 325 | 17 |
| denfry.github.io | TypeScript / TSX | 48 | 39 |
| DevGraph | Python | 59 | 12 |
| Windows-Cleaner-and-Optimizer | PowerShell | 39 | 17 |

Those repositories are not vendored here — shipping someone else's source to run a
benchmark is not reproducible either. The generator is the reproducible part: point
it at any git repository and the protocol is identical.

## Two query families, and why both are load-bearing

The git-derived sets are large and objective, but they are not a substitute for
human phrasing, and 1.10.0 turned up a case where the difference decided a release.

A commit subject is written by someone looking at the identifiers they just
changed, so it reuses the codebase's own spelling. A user asking a question does
not: they type "where are secrets redacted", not "redact". So the git sets are
structurally blind to morphology. Removing the synonym vocabulary looked free on 420
git-derived queries (MRR −0.0022, p=0.40) and cost −0.060 MRR on the 36 hand-written
ones. The vocabulary stayed.

The reverse also holds. Ground truth mined from commits counts a *test* file as the
answer whenever the commit touched tests (159 of 420 queries here), which the
hand-written set never does. Any signal that rewards test files therefore looks
better than it is. `run_eval.py` reports both families; a change needs to survive
the large set and not visibly break the small one.

## Held-out validation

Hand-tuned coefficients are fitted parameters, so tuning them on the same corpora
that report the result is how a benchmark gets gamed by accident. Ranking parameters
are selected under **leave-one-repository-out**: choose on seven corpora, score on
the eighth, pool the eight held-out scores. A parameter is only shipped from a
*plateau* — a region where neighbouring values are statistically indistinguishable —
never from a single peak, and per-corpus scores are inspected so that no fold is
allowed to regress in exchange for a better aggregate.

## What is measured

Ranking quality is scored at **file** granularity, because the agent's unit of
decision is "which file do I open"; several hits inside one file collapse to its
best rank.

- `recall@5`, `recall@10`, `precision@5`, `hit@3`
- `MRR`, `MAP`, `nDCG@10`
- `useful@budget` — the fraction of the answer that fits in the token budget, i.e.
  what the agent can actually afford to read, not what is merely ranked somewhere
- `tokens` — mean snippet tokens actually emitted per query (results past the
  budget carry no snippet and are not billed)
- `dup%` — fraction of returned results that near-duplicate an earlier result
- `p50/p95/p99` latency, in-process, excluding interpreter start-up

### Oracle metrics: is this a recall problem or a ranking problem?

MRR alone cannot separate "the retrievers never found it" from "the ranker had it
and buried it", yet those two failures share no fix. Each variant therefore also
reports, against the *pre-rerank candidate pool* it actually generated:

- `oracle` — the MRR a perfect reranker would score over that pool. `1 - oracle` is
  the share of the query set that only better recall can ever fix.
- `cand_recall` — mean fraction of expected files present anywhere in the pool.
- `eff` = `MRR / oracle` — the share of achievable ranking quality delivered.

At 1.9.0 this read `oracle = 0.902`, `MRR = 0.577`, `eff = 0.639`: a third of the
answers already in the pool were ranked below something else, an error mode about
three times larger than the 0.098 of remaining recall headroom. That is why 1.10.0
worked on the reranker rather than adding retrievers, and it is also the cheapest
available check that a "ranking" change did not quietly change recall instead —
`-name_cooccurrence` moves eight quality metrics and leaves `oracle` at ±0.0000.

## Files

| File | Role |
|---|---|
| `run_eval.py` | CLI: corpora, variants, ablation, significance |
| `harness.py` | Index build, query execution, aggregation, pooling, tables |
| `metrics.py` | IR metrics + paired bootstrap / permutation tests |
| `gen_queries.py` | Ground-truth generator from git history |
| `queries/` | Checked-in query sets |
