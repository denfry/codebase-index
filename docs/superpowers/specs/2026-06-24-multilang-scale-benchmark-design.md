# Design: Multi-language scale benchmark campaign

**Date:** 2026-06-24
**Status:** Approved (brainstorming complete; awaiting implementation plan)
**Author:** denfry (with Claude)

## Goal

Close the open roadmap items in `docs/BENCHMARKS.md`:

- [ ] 10k LOC public repo
- [ ] 100k LOC public repo
- [ ] 1M LOC target (feasibility / may be partial)
- [ ] Multi-language repo (>=3 Tier-A languages)

Produce **publishable, roadmap-grade evidence**: named public repos with pinned
commit SHAs, symmetric token accounting, `recall@3` vs an `rg` baseline, and raw
logs + a `*_RESULTS.md` summary committed to the repository. Every headline
number must cite repo + SHA + log file. No overclaiming.

## Non-goals

- Latency/wall-clock "skill vs no-skill" claims (Python process start dominates
  the index side; real `rg` is far faster than the pure-Python baseline scan).
  Latency is shown for context only and labelled as such, same as the honest
  benchmark.
- Beating Cursor / Sourcegraph / Codebase-Memory MCP (no head-to-head exists).
- Replacing the existing honest NewTowny benchmark — it stays as the Java anchor.

## Decisions captured during brainstorming

1. **Purpose:** publishable evidence to close the roadmap gap (not just internal
   validation).
2. **Language composition:** multi-language set (Python, Go, TypeScript, Java),
   which also closes the "multi-language repo" roadmap item.
3. **Scope:** full matrix — 2 languages x 3 size tiers (10k / 100k / 1M LOC),
   plus the existing NewTowny anchor (~55k LOC Java).
4. **Build approach (A):** extract the shared, trusted accounting from
   `benchmark_honest.py` into `tests/bench_common.py`; both the honest benchmark
   and the new scale harness import it. De-risk the refactor with a before/after
   equivalence run on NewTowny.

## Environment facts (verified 2026-06-24)

- CLI runs: `python -m codebase_index ...`.
- Network/cloning works (`git ls-remote` returns HEAD SHA); first failure was a
  transient SSL flake.
- `tiktoken` installed -> real symmetric `cl100k_base` token counting available.
- `universal-ctags` NOT installed -> use the zero-dependency regex def-extractor.
- git 2.51 -> `--depth 1` shallow clone supported.
- **Disk: only ~8.8 GB free on `C:` (97% used)** -> process repos sequentially
  with cleanup; peak disk = one repo at a time.

## §1 Architecture & components

```
tests/
  bench_common.py        # NEW: shared, trusted core extracted from benchmark_honest.py
                         #   count_tokens (tiktoken cl100k_base, fallback chars/4)
                         #   _merge_ranges, _tokens_for_reads (symmetric accounting)
                         #   rg+window / rg+wholefile baseline
                         #   recall@k helpers, RepoFiles cache, salient_terms
  benchmark_honest.py    # REFACTORED: imports bench_common; NewTowny anchor unchanged
  benchmark_scale.py     # NEW: generic harness
                         #   regex def-extractor per language
                         #   deterministic query sampler
                         #   run one repo: index vs rg baseline, recall@3, tokens
  bench_repos.json       # NEW: manifest (repo url, pinned SHA, language, expected tier)
  run_scale_campaign.py  # NEW: sequential runner clone->index->run->write->cleanup
docs/
  benchmarks/                    # NEW: per-repo raw logs + json (committed evidence)
  SCALE_BENCHMARK_RESULTS.md     # NEW: aggregate table + honesty notes
```

Each unit has one job: `bench_common` = accounting (no repo knowledge),
`benchmark_scale` = one-repo measurement (no clone/disk knowledge),
`run_scale_campaign` = orchestration + disk safety.

## §2 Ground-truth method (rigor crux)

Ground truth is derived by a method structurally different from the index's
Tree-sitter + hybrid pipeline, so the index cannot grade its own homework.

1. **Independent regex def-extractor** over raw file text per language:
   - Java/Kotlin: `(class|interface|enum|record)\s+(\w+)`
   - Python: `^\s*class\s+(\w+)` and top-level `^def\s+(\w+)`
   - TS/JS: `export\s+(class|function|const|interface|type)\s+(\w+)` (+ non-export)
   - Go: `^func\s+(\w+)`, `^type\s+(\w+)\s+(struct|interface)`
2. **Deterministic candidate filter:** keep symbols that are (a) multi-word when
   split on camelCase/underscore, (b) defined in exactly one file across the
   repo, (c) in a non-trivial file (>= min lines).
3. **Deterministic sample:** sort candidates by name, take a fixed stride to get
   ~25 queries/repo. No randomness, no index involvement.
4. **Query synthesis:** humanize the identifier (`UserAuthService` ->
   "user auth service"). Never the exact identifier, so the index must retrieve,
   not echo.
5. **Metric:** `recall@3` (index and `rg` baseline) against the extractor's
   defining file, plus symmetric token economy (index top-3 vs `rg`+window /
   wholefile), same tiktoken estimator both sides.

Honesty caveats printed and documented: latency not headlined; index build cost
reported separately; regex extractor limits disclosed.

### Constants & measurement (explicit, to remove ambiguity)

- **Queries per repo:** target 25; if fewer than 25 candidates survive the
  filter, use all and record the actual count.
- **Min file size for a candidate:** 30 non-blank lines.
- **Multi-word:** identifier splits into >= 2 tokens on camelCase / underscore.
- **LOC measurement (tier classification):** non-blank lines in code files of the
  repo's primary language(s), excluding the harness IGNORE_PARTS dirs (`.git`,
  `node_modules`, `build`, `target`, `dist`, `vendor`, etc.). Tests included.
  Recorded as `code_loc` alongside file count in each run's JSON.
- **Tier label** is assigned from measured `code_loc` (10k = 5k-30k,
  100k = 60k-300k, 1M = >= 600k), not from the candidate name. A repo that misses
  its expected band is relabelled to its actual band and noted.

## §3 Repo matrix

Full matrix = 2 languages x 3 tiers + NewTowny anchor. Candidates below; the
runner shallow-clones, measures actual code-LOC, records the exact SHA, and may
substitute a repo if it misses its tier. The 1M tier is explicitly
feasibility / "may be partial."

| Tier | Lang A (candidate) | Lang B (candidate) |
|---|---|---|
| ~10k LOC | Python — `pallets/flask` | Go — `gin-gonic/gin` |
| ~100k LOC | TypeScript — `nestjs/nest` | Java — `google/guava` |
| ~1M LOC | Java — `spring-projects/spring-framework` | Go — `kubernetes/kubernetes` |
| anchor (~55k) | Java — local `NewTowny` (already done) | — |

Notes:
- `kubernetes` is the heaviest clone; if disk is tight at run time, swap the
  1M-Go cell for a lighter ~1M repo or downgrade to "partial/feasibility only"
  and say so explicitly.
- All clones are `--depth 1` at the pinned default-branch HEAD SHA (recorded),
  processed one at a time with cleanup.

## §4 Output & deliverables

- `docs/benchmarks/<repo>_<sha7>.txt` — raw per-repo run log (committed evidence).
- `docs/benchmarks/<repo>_<sha7>.json` — machine-readable metrics.
- `docs/SCALE_BENCHMARK_RESULTS.md` — aggregate table: repo · lang · LOC · files ·
  SHA · index recall@3 · rg recall@3 · index tok/query · rg tok/query · index
  build time; per-tier reading; explicit "what we still cannot claim."
- Update `docs/BENCHMARKS.md` TODO checklist (tick only tiers actually achieved).
- Update README/COMPARISON headline **only if** numbers support it, always citing
  repo + SHA + log file.

## §5 Disk-safe run procedure (8.8 GB cap)

Per repo, sequentially:
1. Check free space; require >= 3 GB free for 10k/100k tiers and >= 5 GB free for
   the 1M tier before cloning. If below threshold, skip the cell (logged as
   "skipped: insufficient disk").
2. Shallow-clone into a temp dir outside the project (`C:\bench-tmp\<repo>`).
3. Record resolved SHA.
4. `codebase-index index` (timed).
5. Run the harness; write log + json into `docs/benchmarks/`.
6. Delete the clone and its index.
7. Next repo.

Peak disk ~= one repo + its index at a time.

## §6 Testing

- Equivalence test: honest benchmark output identical before/after the
  `bench_common` extraction.
- Unit test for the def-extractor on a tiny fixture per language (known defs ->
  known files).
- Campaign runner smoke-tested on the smallest repo first.

## Open risks

- 1M-tier clone/index may exceed disk or take very long -> sequential cleanup +
  disk guard + "partial/feasibility" downgrade path.
- Regex extractor mislabels some symbols -> mitigated by the "exactly one
  defining file" filter and disclosed as a known limit.
- Index build time on 1M LOC unknown -> measured and reported, not predicted.
