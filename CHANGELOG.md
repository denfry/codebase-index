# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [2.0.0] - 2026-09-14

Evidence release. Everything an agent reads through `codebase-index` is now identified
by the exact bytes of the span it came from, can be re-checked against the working tree
at any later moment, is not resent to a session that already holds it, and is reported
when it changes. 2.0.0 also carries the unreleased 1.10.0 ranking work below and the
community-readiness work merged from #26.

Measured by replaying this repository's own history in sessions of 5 to 87 tasks
(`tests/eval/results/2026-09-14-evidence-memory.md`): memory withheld **zero stale
snippets** at every session length while the locator-based alternative withheld
15–54, change notices had precision 1.000 and recall 0.87–0.97, restoring withheld
snippets reproduced the 1.10.0 packet on every task, and snippet tokens fell by
4–11%. The savings are modest on this corpus; correctness is the deliverable. Summary in
[docs/BENCHMARKS.md](docs/BENCHMARKS.md#evidence-memory), design in
[docs/MEMORY.md](docs/MEMORY.md).

### Added

- **Evidence identity and verification.** Every delivered snippet carries a
  `path:start-end@hash` reference whose hash covers the span's exact bytes under the
  indexer's line model. `codebase-index verify [REF ...] [--session TAG] [--strict]`
  and MCP `verify_evidence` re-check references against the working tree, read-only
  and without an index, returning `valid`, `relocated`, `changed`, `ambiguous`,
  `deleted`, `excluded` or `unreadable` per reference and `all_valid` overall.
  References are untrusted input: absolute paths, drive letters, `..` and NUL are
  rejected before any filesystem access.
- **Session-scoped evidence reuse.** `search`/`explain --session TAG` (MCP `session`)
  name one agent context. A snippet the session already received from byte-identical
  source comes back as `snippet: null, reused: true`; evidence the session received
  that has since changed is listed once under `memory.invalidated`. The evidence hook
  runs after ranking, budgeting and pagination are final, so memory can never change
  which results are returned. Sessions are only ever named explicitly.
- **Stale marking without a session.** A result whose index text no longer matches the
  working tree carries `stale: true`. Derived index text (config-key chunks, Markdown
  section summaries) is never flagged: a mismatch counts only when the file's current
  hash differs from the one the index was built from.
- **`memory.sqlite`**, a content-free ledger next to the index: hashes, paths, line
  numbers, token counts and timestamps; session tags stored hashed. Separate from
  `index.sqlite` so rebuilds and `clean` leave it alone and ledger writes never queue
  behind an update. A newer schema is refused, a corrupt file is moved aside, lock
  contention degrades to no-memory output. `memory gc` and `memory clear` are CLI-only
  maintenance, deliberately absent from the skill wrappers and MCP, like `clean`.
  `stats`, `doctor`, `index_stats` and `healthcheck` gain an additive `memory` block.
  Config: `memory.enabled` (true), `memory.retention_days` (14),
  `memory.max_deliveries` (50 000); `CBX_MEMORY=0` restores 1.10.0 output byte for byte.
- **Sequential real-history benchmark** (`tests/eval/memory_eval.py`) with an oracle
  independent of memory's hashing, plus repository-lifecycle, security and
  stale-context test suites driven by real git: branch switches, detached HEAD,
  worktrees, dirty trees, renames, rebases, CRLF checkouts, and excluded content that
  must never reach the ledger.
- **Upgrade test from a real 1.10.0 index.** The index schema stays at version 3; an
  upgraded project keeps its index, a 1.x config loads with memory defaults, and
  `memory.sqlite` attaches on the first `--session` call.
- **Skill: Find → Trace → Verify → Predict.** The agent wrappers pass one session tag
  per conversation, run `verify` before relying on evidence gathered earlier, and
  document `reused`, `stale` and `memory.invalidated` in `references/memory.md`.
  `verify` joins the wrapper whitelists; `memory` does not.

- **Public baseline benchmark.** `tests/eval/run_baselines.py` compares the index with
  a disciplined `rg` + 80-line-window agent and with repo-map-style context on
  Flask, Gson and Fastify at pinned commits, using git-derived ground truth, one
  tokenizer on every side, and paired bootstrap / permutation significance. The
  logged run is committed under `tests/eval/results/`: pooled over 450 queries,
  hit@3 0.547 vs 0.304 and MRR 0.456 vs 0.263 (p < 0.001) at 3.8k vs 3.5k context
  tokens per query. `scripts/gen_benchmark_chart.py` renders the chart from the log.
- **Reproducible demo.** `examples/demo/run_demo.sh|.ps1` run Find / Trace / Predict
  on `pallets/flask` at a pinned commit; `EXPECTED_OUTPUT.md` is the captured run and
  `assets/demo-terminal.svg` is rendered from it (`scripts/gen_terminal_svg.py`).
  `docs/DEMO.md` documents GIF/video recording.
- **Release and CI gates.** `scripts/check_versions.py` (package, plugin manifest,
  lock tag, skill stamps and changelog must agree), `scripts/check_links.py`
  (relative Markdown links must resolve), `scripts/release_notes.py` (GitHub release
  body comes from the changelog section and an empty section fails the release), and
  a `package` CI job that builds, `twine check`s and runs the clean-venv install smoke
  on every pull request.
- **Contributor onboarding.** `docs/DEVELOPMENT.md`, rewritten `CONTRIBUTING.md`,
  benchmark-report and language-support issue templates, `SUPPORT.md`, a labels
  manifest, and `docs/COMMUNITY_AUDIT.md` / `docs/COMMUNITY_LAUNCH.md`.

### Changed

- **Indexing gates are shared with later working-tree reads.** Evidence validation
  reads files long after they were indexed, so the walker and the validator now go
  through one `PathGate`; a parity test asserts the gate admits exactly the files a
  walk indexes. The resolved on-disk path is gated again, so a symlink or a
  differently-cased path on a case-insensitive filesystem cannot reach a file the
  walker would never have indexed.
- MCP `schema_version` stays **1**: every payload change is an added field. No CLI
  command, flag or JSON field is removed or retyped.

- **Read plan is bounded.** `recommended_reads` entries are capped at
  `retrieval.max_read_lines` (default 120) and carry `truncated: true` plus
  `line_end_full` when capped. A symbol-aligned chunk can be a whole class; on the
  public baseline benchmark the uncapped read plan cost 6.8k tokens per query against
  3.5k for grep, the capped one 3.8k, with identical ranking quality. Set the option to
  0 for the previous behaviour.
- **README, docs and examples show real output only.** Fabricated tables (an
  `AuthService.ts` example with a `Score` column, an invented `doctor` transcript,
  the mock-up `assets/demo.png`) are replaced by output captured on Flask.
  Duplicate pages (`DATABASE_SCHEMA`, `RETRIEVAL_PIPELINE`, `docs/SECURITY`) are
  redirect stubs; `SCHEMA.md` now matches `storage/schema.sql`.
- **Benchmark headline.** The "13× fewer tokens on a 55k LOC Java repo" figure is
  withdrawn: the repository is private and the accounting was asymmetric. The
  defensible claim is the public baseline run above.
- `SECURITY.md` points to GitHub private vulnerability reporting and states the
  supported line as 1.9.x.

### Fixed

- `codebase-index index` no longer crashes with `ValueError: ... is not in the subpath of ...`
  when the repository contains a symlink that points outside the tree (for example Bazel's
  `bazel-out` / `bazel-bin` convenience symlinks). Such entries are now skipped by the walker,
  matching the gate's existing "resolves outside the repository" exclusion (#27).
- **MCP server did not start on mcp 2.x.** The SDK renamed `FastMCP` to
  `MCPServer` and removed the old import path, so `codebase-index mcp` reported
  "needs the optional extra" even with the extra installed, and the MCP tests
  skipped silently in CI because the skip guard wrapped our own module's import.
  The server now imports `MCPServer` first and falls back to `FastMCP` on 1.x
  (verified against mcp 1.29 and 2.1); the tests skip only when the SDK itself is
  missing.
- **`codebase-index mcp --root <repo>` was rejected.** Every client template
  used that form, but `--root` was only a global option (`codebase-index --root
  <repo> mcp`). The subcommand now accepts it as well.
- **Plugin wrappers refused four documented commands.** `bin/cbx` and `bin/cbx.ps1`
  whitelisted ten subcommands while the skill allowed fourteen; `architecture`,
  `diff-impact`, `path` and `describe` now work from the plugin. A parity test pins
  the two lists together.
- **Benchmark leakage.** `gen_queries` documented that changelog-style files were
  excluded from the evaluation corpus, but the harness never applied the list, and
  Flask-style `CHANGES.rst` was not covered. Both are fixed; `CHANGES*`, `HISTORY*`,
  `NEWS*` and `RELEASE_NOTES*` are refused as answers and excluded from the corpus.

## [1.10.0] - 2026-09-02

Ranking release. 1.9.0's own diagnostics showed that a perfect reranker over the
candidate pool it already generated would score MRR 0.902 against the 0.577 actually
delivered — a ranking gap roughly three times larger than the remaining recall gap.
1.10.0 spends its entire budget on closing part of that gap, and adds the metrics
that make the gap visible.

Measured over **420 queries across eight repositories** (Python ×2, Java ×3,
TypeScript/TSX ×2, PowerShell ×1) against a pinned 1.9.0: MRR +0.0188 (p=0.004),
nDCG@10 +0.0304 (p<0.001), MAP +0.0213 (p=0.001), recall@10 +0.0627 (p<0.001, 37
wins / 0 losses), useful@budget +0.0292 (p=0.020), −19 tokens per query. The
candidate pool is unchanged, so every gain is reranking. No corpus regressed. Under
leave-one-repository-out the pooled gain is +0.0219 MRR with 7/8 folds improving and
0 regressing. Full tables in [docs/BENCHMARKS.md](docs/BENCHMARKS.md).

### Added

- **Query↔candidate name co-occurrence** (`retrieval/features.py`), the one new
  ranking signal. Every retriever scores each query term independently and RRF sums
  those independent verdicts, so nothing in the pipeline could distinguish a
  candidate that matched *one* query term well from one that matched *three* terms in
  a single name. On "graph resolution + traversal accessors" 1.9.0 ranked
  `graph/retrieval.py` (one term) above `test_graph_accessors_resolve_and_walk`
  (three); on "greedy token budgeting with redaction" it ranked `output/redact.py`
  above `retrieval/budget.py`. The signal credits query terms for occurring
  *together* in one name — file basename plus symbol, camel/snake split, directories
  excluded — and only for terms beyond the first, since the first match is already
  paid for by the retriever that surfaced the candidate. Cost is
  `O(len(path) + len(symbol) + len(terms))` per candidate: no corpus statistics, no
  posting-list scan, no model, no network. Ablatable via
  `RetrievalTuning(name_cooccurrence=False)`.
- **Oracle / headroom metrics** in the eval harness (`oracle`, `cand_recall`, `eff`).
  MRR alone cannot separate "retrieval never found it" from "the ranker buried it",
  and those two failures share no fix. `oracle` is the MRR a perfect reranker would
  achieve over the pool actually generated, `eff = MRR / oracle` is the fraction of
  achievable quality delivered (0.639 → 0.660 in this release). These also make
  ranking changes falsifiable in a new way: `-name_cooccurrence` moves eight quality
  metrics while leaving `oracle` at ±0.0000, proving the gain is not disguised recall.
- **`search(..., explain=True)`** returns a `diagnostics` block with the pre-rerank
  candidate pool and the final order, each candidate carrying source, symbol, score
  and retriever agreement. This is what the oracle metrics are computed from, and
  what turns "the ranking is wrong" into a decomposable failure. Measured at −0.8ms
  p50 (inside noise); nothing is allocated when the flag is off.
- **`RetrievalTuning.v190()`** pins the previous release as the comparison column, so
  "better than what we shipped last" cannot drift as the default changes.
  `run_eval.py` now reports 1.7.0, 1.9.0 and the current default side by side.

### Changed

- **Pages are packed with distinct files** (`max_per_file` 3 → 1). The agent's unit
  of decision is "which file do I open", so a 10-result page spending three slots on
  three regions of one file offers seven choices, not ten. 1.9.0's page held 7.1
  distinct files on average, and of the queries whose answer was in the pool but
  missing from the page, 45 of 57 had it past rank 10 — crowded out by repeat hits
  rather than better candidates. Monotone over 1–5, so this is a plateau boundary,
  not a fitted peak. Nothing is dropped: overflow hits keep their relative order at
  the tail. recall@10 +0.045, nDCG@10 +0.015, unchanged token cost.
- **Name co-occurrence is discounted for test and generated sources**
  (`name_cooccurrence_demoted_scale`, 0.5). Test function names are descriptive
  sentences (`test_compactor_output_is_redacted`), so they harvest query-term
  co-occurrences real identifiers never do. The value was chosen by splitting the
  benchmark on whether its own ground truth is a test: across the 261 queries whose
  answer is *not* a test the gain is flat at +0.020 MRR for every scale, so the whole
  aggregate difference between 0.5 and 1.0 comes from the 159 test-answer queries —
  an artifact of mining ground truth from commits, which touch tests. 0.5 is the only
  setting that improves both partitions.
- **Benchmark corpora no longer index changelog files.** `gen_queries` documented
  `CHANGELOG_EXCLUDES` as applied to the corpus but the harness never wired it in. A
  git-derived query *is* a commit subject and a changelog entry paraphrases it
  verbatim while never being an accepted answer, so every affected query carried an
  unbeatable distractor that compressed all variants toward the same floor.

### Performance

- **Duplicate detection roughly halved.** It was 42% of the query path on the Java
  corpus. Two independent fixes: the operator scan in `normalize_code_tokens` no
  longer runs up to 24 `str.startswith` calls per punctuation character (1.71×
  faster on 1600 real chunks, bit-identical token stream), and only the leading 2000
  characters of a body now decide duplication — two chunks agreeing for 2000
  characters are the same snippet. Recall, duplicate rate and useful-context are
  identical; MRR within −0.0003 (p=0.51).

### Fixed

- **Non-ASCII identifiers can now earn name-level ranking credit.** The query side
  parses Unicode correctly, so `расчёт_налога.py` produced matching query terms but
  its own name components were silently dropped, making the file unrankable by name.
- **`.skill_version` is pinned to LF in `.gitattributes`.** `sync_skill_copies.py`
  writes and byte-compares `"<version>\n"`, but the file carried no EOL attribute,
  so with `core.autocrlf=true` git materialised CRLF and `test_real_repo_is_in_sync`
  failed on any fresh Windows clone — and again after any `git checkout` of that file.
- **Lint is clean repository-wide.** `skill/scripts/` was outside the CI lint scope
  (`ruff check src tests`) and had accumulated three violations.

### Verdicts on existing signals

Every pre-existing signal was re-examined rather than inherited. `soft_lexical`
(−0.161 MRR when off) and `source_priors` (−0.029) remain load-bearing;
`file_agreement` (−0.010, p=0.048) and `dedup` (−0.0016, p=0.006) keep their places.

- **`query_expansion` survives a deletion attempt, and the reason is a lesson.** On
  the 420 git-derived queries the synonym vocabulary is worth nothing measurable
  (MRR −0.0022, p=0.40 when removed), and the flag's apparent benefit turned out to
  come from it also swapping the symbol retriever's tokenizer. It was removed — and
  then restored, because a commit subject is written by someone looking at the
  identifiers they just changed and so reuses the codebase's spelling, while a user
  asking a question does not. On the 36 hand-written natural-language queries removal
  cost −0.060 MRR. The git benchmark is structurally blind to morphology; both query
  families are needed to make this call.
- **The intent classifier is inert on commit-style queries but kept.** It returns
  `keyword` for 419 of 420 git-derived queries, and removing the layer entirely is
  bit-identical on that benchmark. It fires on 30.6% of hand-written questions, where
  removing it costs MRR, and the retriever *weights* it selects are worth +0.058 MRR
  against uniform weights. Deleting it would optimise for the benchmark's phrasing.
- **`fuzzy_symbols` and `graph_source` remain measurably inert** on all eight corpora
  (0/1 and 0/0 query changes respectively); both stay as-is rather than accumulating
  new tuning.

### Rejected

Recorded so they are not re-attempted without a new hypothesis. A pairwise logistic
ranker fitted over 19 deterministic query↔candidate features selected exactly one
feature, and forward selection found no second feature clearing the noise floor, so
one explainable term ships instead of a model. Individually measured and rejected:
idf weighting of matched terms (pool-local and corpus-wide), substring matching,
prefix/stem-tolerant matching, ordered-subsequence matching, term proximity in the
chunk body, body-text coverage, zone-size normalisation, restricting the name zone to
the filename or symbol alone, and including the parent directory. `exact_symbol` was
found to have no discriminative power at all (AUC 0.500) but is left untouched, since
changing it is a separate experiment from adding a signal.

## [1.9.0] - 2026-09-02

### Added

- **Objective ground truth from git history.** `tests/eval/gen_queries.py` mints a
  retrieval benchmark from any git repository by pairing a human-written commit
  subject with the files that commit actually changed. Unlike docstring-derived
  benchmarks the query text is not copied into the document being retrieved, so the
  set is leak-free by construction; merges, reverts, releases, version bumps,
  sweeping refactors, changelog-style answers and benchmark scaffolding are all
  filtered out.
- **Multi-corpus, multi-language evaluation.** `run_eval.py --corpus REPO:QUERIES`
  pools several repositories into one benchmark so ranking changes are validated
  outside this repository and outside Python. The 1.9.0 defaults were measured on
  305 queries across Python, Java and TypeScript corpora.
- **Significance testing.** Every non-baseline row now reports a paired bootstrap
  95% confidence interval and a paired permutation p-value (both seeded, therefore
  reproducible). Query sets of this size have a noise floor of several MRR points;
  signals now ship on the strength of that test rather than the sign of a delta.
- **Context-noise metrics.** The report adds mean emitted snippet tokens, duplicate
  rate of returned results, and p99 latency alongside the existing IR metrics.

### Changed

- **Fusion now scores cross-retriever agreement.** RRF fuses on
  `(path, line-bucket)`, so a symbol definition at line 40 and a lexical hit at line
  120 in the same file fused as two unrelated candidates — two retrievers agreeing
  on a file produced two weak results instead of one strong one, and cross-source
  agreement never reached the score. Each candidate now also receives, at
  `file_agreement_weight` (0.4), the RRF mass of every retriever that found its file
  at another locator, excluding retrievers already counted at that locator.
  Ablatable via `RetrievalTuning(file_agreement=False)`.
- **Documentation demotion deepened** from -0.05 to -0.20. Prose describing a
  feature matches a natural-language question more literally than the code
  implementing it, so design notes and plans were displacing the modules they
  describe. Because this only reorders prose relative to code, documentation-seeking
  queries improved as well (category MRR 0.579 → 0.612). Generated/vendor paths move
  to -0.25 so they remain the least-preferred role, and `MAX_ABS_PRIOR` now pins the
  invariant that priors stay tiebreakers.
- **Fuzzy identifier matching is now a recall fallback.** It runs only when the
  precise symbol lookup named no symbol and returned fewer than
  `fuzzy_fallback_min` (3) rows. It moved no ranking metric across 305 queries while
  accounting for ~20% of query latency; typo and acronym recall is unchanged because
  those are exactly the queries where the precise lookup comes up empty.
- **Candidate over-fetch is explicit.** `candidate_pool_multiplier` (default 2)
  replaces the implicit widening that happened whenever dedup or MMR was enabled.
  Making it explicit revealed that the quality previously credited to SimHash dedup
  was really the wider pool; dedup is retained for what it does measurably do, which
  is cutting the duplicate rate of returned snippets from ~1.6% to ~0%.

### Fixed

- **Synonym matches were reported as exact symbol matches.** `is_exact` came from
  SQL and was relative to whichever needle retrieved the row, so a synonym
  expansion ("config" for "configuration") marked an unrelated symbol as an exact
  match — worth a +0.20 rerank bonus and an unconditional `high` confidence.
  Exactness is now judged against the terms the user actually typed.
- **Duplicate suppression was order-dependent on ties.** Equal-scoring duplicates
  handed the slot to whichever copy arrived last, contradicting the documented
  "ties favor input order" and making the retained snippet depend on retriever
  emission order.

### Performance

- Query latency roughly halves: p50 78.6 ms → 51.2 ms, p95 193.2 ms → 94.9 ms,
  p99 277.1 ms → 152.2 ms on the pooled three-repository benchmark, from the fuzzy
  fallback plus a SimHash fingerprint that folds repeated tokens by multiplicity and
  caches token digests. Fingerprint output is bit-for-bit unchanged.
- Mean emitted snippet tokens fall 1183 → 1091 per query.

### Retrieval quality

Pooled over 305 queries (Python, Java, TypeScript), v1.8.0 → 1.9.0:

| Metric | v1.8.0 | 1.9.0 | Δ | p |
|---|---|---|---|---|
| MRR | 0.564 | 0.591 | +0.027 | <0.001 |
| MAP | 0.433 | 0.461 | +0.028 | <0.001 |
| nDCG@10 | 0.503 | 0.527 | +0.024 | <0.001 |
| recall@5 | 0.529 | 0.560 | +0.031 | <0.001 |
| P@5 | 0.182 | 0.192 | +0.009 | 0.001 |
| hit@3 | 0.649 | 0.666 | +0.016 | 0.124 |

## [1.8.0] - 2026-09-02

### Added

- **Reproducible retrieval evaluation.** Added a self-repository ground-truth
  query suite with Recall@K, MRR, nDCG, hit rate, precision, MAP, useful-context,
  latency percentiles, and one-signal ablations.

### Changed

- **Hybrid retrieval quality.** Natural-language lexical queries now use safe,
  down-weighted identifier/synonym expansion and soft term coverage; exact symbol
  lookup preserves framing-word tolerance and bounded fuzzy matching.
- **Packaging compatibility.** Cap the build backend below the Metadata 2.5
  default until the release validation toolchain supports that metadata version.
- **Ranking defaults are evidence-driven.** Implementation/test/documentation
  source priors are calibrated from the benchmark. Graph propagation is bounded
  and intent-directed; graph and MMR signals remain opt-in because ablations
  reduced direct retrieval quality on the reproducible corpus.

## [1.7.0] - 2026-07-29

### Added

- **Diff-aware blast-radius analysis.** `codebase-index diff-impact` and the MCP
  `impact_of_diff` tool aggregate graph impact for tracked working-tree changes
  relative to a verified Git commit, with a changed-file safety cap, unresolved
  file reporting, freshness, graph coverage, edge confidence, and exclusion of
  the tool's own derived cache.
- **Progressive skill references.** The installed agent skill now keeps its
  always-loaded evidence protocol compact and moves detailed commands and
  response handling into on-demand reference files.
- **Reproducible product identity.** Added a graph-route mark and redesigned
  README/social assets around Find / Trace / Predict.

### Changed

- Reworked the README, roadmap, product brief, package metadata, and plugin copy
  around the evidence-first product promise.
- Expanded the safe `cbx` wrappers to allow the shipped read-only
  `architecture`, `path`, `describe`, and `diff-impact` commands.
- Replaced broad skill shell permissions with an explicit command allowlist so
  `clean`, `init`, and `watch` cannot bypass the safe wrapper.
- Hardened the release workflow with least-privilege defaults and immutable
  commit pins for every GitHub Action that receives release or PyPI credentials.

## [1.6.0] - 2026-06-24

### Added
- **Snippet skeletonization & content-aware rendering.** `search`/`explain` snippets are now
  focus skeletons — import/signature/class lines and the query-matching line are kept while
  function bodies collapse to a `... N lines elided (read A-B)` marker — so more ranked results
  fit the same token budget. Content-aware (code via tree-sitter, markdown headings,
  structured-config keys), reversible via `recommended_reads`, and safe (raw fallback on any
  parse miss or non-win). New `skeletonized` / `elided_lines` result fields; new
  `retrieval.compact_snippets` / `retrieval.compact_min_reduction` config knobs (no reindex);
  disable per-call with `--raw` (CLI) or `raw: true` (MCP `search_code` / `explain_code`).

## [1.5.0] - 2026-06-24

### Added — graph visualization upgrade + interop exports
- **HTML graph is now legible at a glance**: nodes are coloured by module
  (community), sized by connectivity (god nodes are biggest), and edges are styled
  by confidence — solid `extracted`, dashed `inferred`, red-dotted `ambiguous` —
  with a legend. Community/degree are computed on the displayed subgraph.
- **`codebase-index graph --format graphml|dot|neo4j`** exports the same enriched
  graph for external tools: **GraphML** (Gephi / yEd / NetworkX), **DOT**
  (Graphviz, edge style = confidence), and **Cypher** (Neo4j / FalkorDB). All
  pure-stdlib, zero new dependencies. `--format html` (default) is unchanged.

### Added — graph navigation: `path` and `describe`
- **`codebase-index path <A> <B>`** — shortest undirected dependency/call path
  between two symbols or files ("how is X connected to Y"). Renders the node chain
  annotated with each link's edge type and confidence; `inferred`/`ambiguous` hops
  are marked, so a path is only as trustworthy as its weakest edge.
- **`codebase-index describe <symbol>`** — a node card: definition(s), direct
  callers and callees (with confidence), in/out degree, the symbol's module, and
  its god-node rank if it has one. The graphify `explain Symbol` idea, named
  `describe` so it doesn't collide with the existing how-it-works `explain`.
- **`path_between` and `describe_symbol` MCP tools** expose both to agents.

### Added — `architecture` command + `architecture_overview` MCP tool
- **`codebase-index architecture`** prints a high-level map of the codebase from
  the analytics cached at index time: detected modules (with auto-derived labels),
  god nodes (most-connected symbols/files), surprising cross-module connections,
  and suggested starting questions. `--json` for the structured payload.
- **`architecture_overview` MCP tool** exposes the same map to MCP clients, so an
  agent can orient itself before diving into specifics. Reports
  `available: false` (rather than crashing) on an index built before the analytics
  existed; a reindex fixes it.

### Added — graph foundation: edge confidence + architecture analytics (requires a one-time reindex)
- **Edge confidence audit trail.** Every graph edge now carries a `confidence`:
  `extracted` (exact — a same-file symbol or repo-unique name), `inferred` (a
  heuristic resolved it, e.g. an import path-suffix match), or `ambiguous` (a named
  target we could not pin to a unique node). `refs` and `impact` surface it so an
  empty or short answer over `ambiguous`/`inferred` edges reads as inconclusive,
  not as proof. Confidence is derived from *how* an edge resolved — never guessed by
  an LLM; the index stays fully local. **Bumps `SCHEMA_VERSION` 2 → 3.** Older
  indexes stay readable; `index`/`update` detect the mismatch and rebuild.
- **Architecture analytics (`graph/analysis.py`), zero new dependencies.** A pure,
  deterministic pass over the resolved edge graph computes communities (greedy
  modularity / Louvain local-move — does not collapse cliques joined by one bridge),
  god nodes (most-connected symbols/files), surprising connections (edges bridging
  weakly-linked communities), auto-labelled modules, and suggested questions. The
  summary is cached in `meta['graph_analysis']` at build time for instant reads.
  (Surfaced via the `architecture` command and HTML export in following changes.)

### Changed — retrieval ranking & fusion (requires a one-time reindex)
- **RRF fusion rescaled and re-keyed.** Fused scores were ~`w/k` (≈0.017), an order
  of magnitude below the reranker's bounded bonuses, so rerank silently became the
  primary ranker. RRF is now scaled by `k` (a pure monotonic rescale — order is
  unchanged) so fused scores and rerank bonuses share an O(1) scale. Fusion also
  merges on a coarse `(path, line-bucket)` key instead of an exact `(path, start,
  end)` one: different retrievers report different ranges for the same place, so the
  exact key almost never coincided and cross-source agreement never fired.
  `agreeing_sources` is now counted at file granularity.
- **Confidence uses a scale-invariant relative gap** instead of absolute thresholds.
- **Per-file diversification**: at most 3 hits per file stay on the page; the rest
  are pushed to the tail (nothing is dropped). Combined with bucketing this removes
  the "same small file returned six times at different line slivers" noise.
- **FTS recall on natural-language queries**: stopwords (`how`, `does`, `the`, …)
  are dropped before building the FTS `MATCH`, so a query like "how does auth work"
  no longer AND-s in filler that code chunks never contain.
- **Symbol names are FTS-indexed.** `chunks` gained a denormalized `symbol_names`
  column (mirrored verbatim by the FTS sync triggers, so external-content delete/
  update stays consistent) — a query matching a symbol's name now hits even when the
  body text doesn't repeat it. **Bumps `SCHEMA_VERSION` 1 → 2.** Older indexes are
  still readable; `index`/`update` detect the mismatch and rebuild from scratch.
- **Centrality fallback for ambiguous names**: symbols whose name isn't globally
  unique never get a resolved `in_degree`; they now receive a damped, half-capped
  bonus from a name-reference count so common names (`run`, `handle`, …) aren't
  flatly zeroed. Precise `in_degree`, where present, still takes precedence.
- **Test-file demotion is word-boundary aware**: `contest/`, `latest.py`,
  `testimonials.tsx` are no longer mistaken for test files.
- **Language-aware import resolution**: `import './base'` from a `.ts` file resolves
  to `base.ts` rather than a same-named `base.py` earlier in the fallback order.
- **Freshness is content-aware**: a bare `touch` (mtime change, identical bytes) is
  a no-op for `update`, so it no longer reports the index as stale — freshness now
  mirrors the sha-based incremental decision.

### Removed
- Dead legacy lexical-search path in `retrieval/searchers.py` (`fts_response`,
  `fts_search`, the second `Candidate` dataclass and `_confidence`/`_fallbacks`/
  `_trim`) — the live path goes through `pipeline.search` → `fts_candidates`.

## [1.4.0] - 2026-06-14

### Added
- **`clean` is now implemented** (it was a documented-but-stubbed `_todo` since M0).
  `codebase-index clean` resets the index database (`index.sqlite` + WAL/SHM
  sidecars); `codebase-index clean --all` wipes the whole per-project cache
  directory. It prompts before deleting (skip with `--yes`), supports `--json`,
  and never touches the installed skill. Locked in by `tests/test_clean_cli.py`.
- **`docs/PRODUCT_UPGRADE_PLAN.md`**: positioning, target users, competitor matrix,
  differentiators, current weaknesses, a ranked roadmap, and documentation /
  benchmark / distribution / technical task lists.
- **`docs/RELEASE_CHECKLIST.md`**: a repeatable release checklist (version sync,
  tests, benchmarks, doctor, install/plugin/MCP smoke, changelog) with signed
  checksums + SBOM tracked as future hardening.
- **MCP contract hardening (M11.5)**: every MCP tool payload — success *and* the
  no-index/error path — is now wrapped in a stable envelope (`schema_version`: 1,
  `tool`: <name>). Golden snapshots lock every tool's output
  (`tests/golden/mcp_*.json` via `tests/test_mcp_golden.py`), and the contract
  values are asserted explicitly so a golden can't freeze a wrong version. Closes
  the long-standing `docs/MCP.md` follow-ups and makes the `schema_version` claim
  in `docs/ARCHITECTURE.md` §8 true.
- **Config / IaC language labeling**: Dockerfile, Containerfile, `*.tf`/`*.tfvars`
  (terraform), `*.hcl`, `*.ini`/`*.cfg`/`*.conf`/`*.properties` (ini), and
  Makefiles now get a real language label. These files were already FTS-indexed as
  unknown text; labeling surfaces infra files in `stats` and lets agents scope
  searches to config. They stay on the line/FTS floor (no tree-sitter spec).
- **Typed framework edges — design doc**
  (`docs/superpowers/specs/2026-06-14-typed-framework-edges-design.md`): the
  documented-first deliverable for the M13 code-intelligence graph
  (route→handler→service→model, test→impl, config→consumer, …) with a schema,
  confidence/provenance model, resolver architecture, and a benchmark gate.
- **"Trust model in 60 seconds"** callout, identical in `README.md` and
  `docs/SECURITY.md`.
- **`tests/benchmark_public_RESULTS.md`**: a logged run of the public benchmark
  suite (Recall@k / MRR / nDCG / token economy / freshness / graph tasks) with the
  raw JSON and honest scope notes, per the `docs/BENCHMARKS.md` no-overclaim rule.

### Changed
- **Reranker: dampened the god-class `in_degree` tiebreak** (`retrieval/rerank.py`).
  The graph-centrality bonus is now logarithmic with a lower cap instead of linear
  (which saturated by in_degree 10, giving 100-caller "god classes" the full bonus
  and floating them above genuinely relevant low-degree matches on stray-term ties).
  Validated as no-regression on the public benchmark (Recall@k / MRR / nDCG
  unchanged) with a targeted regression test; the real-repo gain on the honest Java
  misses is tracked under M12.5. CLI/MCP `search` goldens regenerated accordingly.
- **`docs/ROADMAP.md`**: M10 MCP bridge marked shipped (was "planned"); reconciled
  the technical-vs-product milestone numbering instead of claiming one is canonical.

- **README**: added "Who Is It For?" and a "How Is This Different?" section that
  answers why-not-grep / Cursor / Aider repo-map / Sourcegraph / Codebase-Memory
  MCP on the first screen, plus a proven-today-vs-roadmap table.
- **`docs/COMPARISON.md`**: explicit rows and "choose them when / choose us when"
  guidance for Continue, Sourcegraph/Cody/Amp, and Codebase-Memory MCP.
- **`docs/BENCHMARKS.md`**: a status table separating proven / toy / honest
  surfaces, an explicit "claims that should NOT be made yet" list, and a
  TODO-friendly benchmark task checklist with a no-overclaim procedure.

### Fixed
- **MCP server failed to import on `mcp>=1.27` + `pydantic>=2.10`**: newer FastMCP
  auto-built a structured-output schema from each tool's `-> str` return annotation
  and raised `PydanticUserError` at import time, breaking the server and its test
  suite. Tools now register as unstructured (`structured_output=False` where the
  kwarg exists; older `mcp` is detected and unaffected), preserving the existing
  text-content wire contract.
- `docs/FAQ.md`: removed a dangling/duplicated sentence in "Is it
  production-ready?" and documented the real `clean` / `clean --all` behavior.

## [1.3.0] - 2026-06-09

### Added
- **Content-addressed embedding cache**: a new `vec_cache` table (keyed by `(model, content_sha)`)
  persists chunk embeddings across rebuilds. Because chunk ids churn on every full rebuild, the
  embedding pass now hashes chunk content and only calls the (potentially slow or paid) backend for
  text never embedded under the active model — unchanged content reuses its cached vector for free.
- **Shared CLI/MCP service layer** (`codebase_index/service.py`): both surfaces now resolve the
  index path, run search sessions, and build stats payloads through the same code, so they cannot
  drift. Two real drifts were closed: MCP `search_code`/`explain_code` now blend in vector results
  when embeddings are enabled (previously the vector channel was CLI-only), and MCP `index_stats`
  now reports the per-language `graph: full|partial` tier the skill keys on.
- **Repo-wide graph tier in diagnostics**: `stats` now tags each tree-sitter language with
  `graph: full|partial`, and `doctor` adds a `graph_coverage` finding listing Tier-B languages
  present in the index. Surfaces upfront which languages have partial `refs`/`impact` (symbols but
  no import/inheritance edges) instead of only signaling per-query.
- **Graph coverage signal**: `refs` and `impact` now report a `coverage` block
  (`partial`, `languages`, `reason`). Import/inheritance edges are only extracted
  for the hand-tuned (Tier-A) languages, so a symbol or file in a Tier-B language
  (generic tree-sitter walk, e.g. Lua) can produce an empty/short result that is
  inconclusive rather than authoritative. `coverage.partial` flags this so agents
  fall back to Grep instead of reading "no references" as proof. Markdown output
  prints a matching warning; the skill documents the field.
- **Skill-copy sync tooling**: `scripts/sync_skill_copies.py` regenerates every committed copy of
  the skill (`.claude/`, `.codex/`, `.opencode/`, `skills/`, shared `skill/` files) plus all
  version stamps from the canonical `src/codebase_index/skill_template/`; CI fails when copies
  drift (`--check`). The package version now lives in one place
  (`src/codebase_index/__init__.py`) via hatch dynamic versioning.
- `CBX_NO_SKILL_AUTO_UPDATE=1` disables the silent skill auto-update — used by the test suite,
  useful for CI and scripted environments.

### Changed
- **Graph build is batched**: edge resolution now runs one query for globally-unique symbol names
  and one pass over file paths (in-memory suffix map) instead of per-edge lookups and up to ~20
  full-table `LIKE` scans per import edge — 7–28× faster on a small repo with identical results,
  and the gap grows with repository size. Vector blobs are written with a single batched
  `executemany`; a new `edges(file_id)` index removes full-table scans from incremental updates
  and file-deletion cascades.
- Silent failure paths now report to stderr: the ProcessPool→sequential parsing fallback and skill
  auto-update failures were previously invisible; vector helpers only swallow
  `sqlite3.OperationalError` (missing vec tables) instead of every exception.
- The embedding pass reports cache **misses** (vectors actually computed) as its "embedded" count.
- `prune_orphan_vectors` now deletes stale `vec_chunks` rows in a single batched `executemany`.
- **Skill**: documented the `--mode vector` semantic-search path, the `intent`/`mode`/`pagination`
  response fields, and clarified that `graph --open` renders an HTML view for a human (use
  `impact`/`refs` for agent-readable dependency answers).
- **Skill**: narrowed the skill's `allowed-tools` from `Bash(python *)`/`Bash(python3 *)` to
  `Bash(python -m codebase_index *)`/`Bash(python3 -m codebase_index *)`, so the skill can no longer
  run arbitrary Python.

### Fixed
- `search` now exposes `--offset`, so the pagination contract is reachable from the CLI/skill.
  The retrieval pipeline and MCP already supported paging, but the CLI command never surfaced the
  flag — every call silently returned page one and the advertised `pagination.next_offset` was a
  dead end. Markdown output now also notes when more results are available. `--offset` rejects
  negative values.
- `explain` now honors the index freshness contract: it passes `root`/`config` into the retrieval
  pipeline, so `index.stale` / `files_changed_since_build` reflect reality instead of a hardcoded
  "fresh" block. Previously the skill's freshness check silently never triggered for
  "how does X work" questions. `explain` also blends in vector results when embeddings are enabled,
  matching `search --mode hybrid`.
- The `cbx` wrapper whitelist (skill + plugin `bin/`) now includes `doctor`, which the skill's
  fallback diagnostics already invoke; previously `cbx doctor` was refused.
- The test suite is green on Windows again (`bootstrap` path comparison) and no longer rewrites
  the committed `.skill_version` stamps as a side effect of running the CLI inside the checkout.
- `docs/ARCHITECTURE.md` no longer shows two contradictory repository layouts or claims `graph/`
  is a stub.

## [1.2.2] - 2026-06-05

### Changed
- Synced the version to `1.2.2` across the package, plugin manifest, and lockfile.
- Documentation cleanup: removed stale prompt files and screenshots, refreshed the README.

## [1.2.1] - 2026-06-05

### Added
- **Skill auto-update**: skills installed via `init` now silently self-update whenever the package
  version changes. On every CLI invocation the main callback compares the installed `.skill_version`
  stamp against the running package and re-materializes the template, saving a backup first.
- **`skill-update` command**: `codebase-index skill-update [--target] [--force] [--no-backup] [--json]`
  for manual skill updates with optional dry-run and JSON output.
- **`skill-rollback` command**: `codebase-index skill-rollback [--target] [--json]` restores the
  last backed-up version of installed skill(s).
- `scaffold.materialize_skill()` now writes a `.skill_version` stamp alongside copied template files
  so freshness is detectable without an extra network call.

## [1.2.0] - 2026-06-05

### Added
- **Interactive graph export** via `codebase-index graph [target]`, producing a local HTML graph of
  indexed files, symbols, and resolved edges, with optional `--open` browser launch.
- Project skill installers now advertise and whitelist the `graph` command for Claude, Codex, and
  OpenCode skill resources.

### Changed
- `search`, `symbol`, `refs`, `impact`, and `explain` now auto-build the local index when it is
  missing instead of failing with a manual "run index first" step.
- Natural-language kind words such as `method`, `function`, `class`, `interface`, `enum`, and
  `type` now constrain the symbol retriever inside `search`.
- Skill wrappers prefer the importable local `python -m codebase_index` module before falling back
  to a potentially stale `codebase-index` executable on `PATH`.

### Fixed
- `stats --json` and `doctor --json` now work as subcommand flags, matching the documented skill
  examples and the existing global `--json` behavior.
- `init --no-hooks` is accepted as the explicit counterpart to `--with-hooks`, preserving the
  default no-hook install while keeping the CLI option pair discoverable.

## [1.1.0] - 2026-06-02

### Added
- **MCP server** (`codebase-index mcp`): exposes the retrieval layer as MCP tools —
  `search_code`, `find_symbol`, `find_refs`, `impact_of`, `explain_code`, and `index_stats` —
  so MCP-capable editors (Cursor, Claude Desktop, VS Code, Zed, Windsurf) can query the index
  directly.
- **`codebase-index-mcp`** standalone entry point for use as a bare MCP server binary.
- **Multi-client `init`**: `--target` now accepts five MCP clients in addition to the three
  skill targets. Each writes the correct JSON config format and merges without overwriting
  other servers already present:
  - `cursor` -> `.cursor/mcp.json`
  - `windsurf` -> `.windsurf/mcp.json`
  - `vscode` -> `.vscode/mcp.json` (with `type: stdio`)
  - `zed` -> `.zed/settings.json` (with `context_servers`)
  - `claude-desktop` -> platform-specific `claude_desktop_config.json`
- `detect_mcp_targets()` auto-detects installed MCP clients during `--target auto`.
- New optional dependency group `mcp` (`pip install codebase-index[mcp]`).
- `tests/benchmark_public.py`, a reproducible multi-language public benchmark suite with
  Recall@1/3/5, MRR, nDCG, answer-correctness proxy, token economy, language breakdown,
  freshness latency, graph tasks, and scale counters.
- `docs/MCP.md` and `docs/BENCHMARKS.md` for first-class MCP setup and benchmark usage.

### Fixed
- `recommended_reads` was empty for queries where all results had short symbol-signature
  snippets (`token_est < 40`). Added a minimum useful-token threshold so snippets below it
  are still shown as previews and the result is also added to `recommended_reads`.

### Changed
- Aligned README, FAQ, architecture, language support, comparison, installation, and roadmap docs
  with the current `1.1.0` implementation.
- Replaced toy benchmark positioning with the honest benchmark summary and public benchmark suite.
- Corrected Aider repo-map comparison language to acknowledge graph-ranked, token-budgeted maps.
- Distribution is GitHub-only for now: docs and `requirements.lock` install from the GitHub
  release tarball pinned to `v1.1.0`; PyPI/uvx/Homebrew remain distribution-hardening roadmap
  items.

## [1.0.2] - 2026-05-29

### Added
- Added `codebase-index init --target claude|codex|opencode|auto|all`, with an
  interactive Rich target picker for terminal use.
- Added project scaffolding for Codex CLI (`AGENTS.md` + resources) and OpenCode
  (command, agent, and resources), while preserving the Claude Code skill path.

### Changed
- Refreshed README positioning and SEO structure around local codebase indexing for
  AI coding agents, including Claude Code, Codex CLI, and OpenCode.
- Updated quickstart and installation docs for multi-CLI initialization.

## [1.0.1] - 2026-05-29

### Fixed
- Pinned `tree-sitter` and `tree-sitter-language-pack` in package metadata and the plugin
  bootstrap lock so CI and local installs use the same grammars.
- Regenerated CLI golden snapshots against the pinned grammar set.

## [1.0.0] - 2026-05-29

### Fixed
- Multi-language tree-sitter symbol extraction. Previously a repo of 303 Java files produced
  **0 symbols**, silently disabling `symbol`/`refs`/`impact`. Java now yields 3,543 symbols;
  Go/Rust/C/C++/C#/Ruby/PHP/Kotlin plus a Tier-B generic path are covered.

### Added
- Symbol-aware retrieval ranking: candidates are scored by how many query terms their
  camelCase/underscore-split name covers, so multi-word concepts land on multi-word symbols.
  recall@3 against objective ground truth improved 20% → 70% (vs 40% for a disciplined grep agent)
  while using ~13× fewer tokens to answer.
- Parse guardrails with `parse_failed` / `treesitter_zero_symbols` counters and `doctor` reporting
  to lock symbol extraction against silent regression.
- Multi-CLI installer for Claude Code / Codex / OpenCode.
- Honest benchmark harness (`tests/benchmark_honest.py`) comparing the index against a no-skill
  grep agent on a real repository.

## [0.1.0] - 2026-05-29

### Added
- Local-first codebase index exposed as a Claude Code Skill + `codebase-index` CLI.
- `index` / `update`: discovery with layered ignore rules, secret/binary/size gates, and
  incremental re-index (M1, M8).
- `search`: FTS5 lexical + hybrid retrieval with RRF fusion, intent detection, token budgeting,
  confidence scoring, and fallback suggestions (M2, M4).
- `symbol` / `refs`: tree-sitter symbol extraction and reference lookup across supported languages
  with line-based fallback (M3).
- `impact`: dependency/call-graph blast-radius analysis (M5).
- Optional, opt-in local embeddings / `sqlite-vec` vector backend, gated behind `embeddings.enabled`
  and SECURITY.md rules (M6).
- `init`: materializes the bundled skill template, resolved `config.json`, and `.gitignore` rules;
  end-to-end freshness contract so the skill triggers `update`/`index` (M7).
- Hooks example + `watch` mode for keeping the index fresh without blocking the edit loop (M8).
- `doctor`, `stats`, `clean` diagnostics/maintenance commands.

[Unreleased]: https://github.com/denfry/codebase-index/compare/v1.10.0...HEAD
[2.0.0]: https://github.com/denfry/codebase-index/compare/v1.9.0...v2.0.0
[1.10.0]: https://github.com/denfry/codebase-index/compare/v1.9.0...v1.10.0
[1.9.0]: https://github.com/denfry/codebase-index/compare/v1.8.0...v1.9.0
[1.8.0]: https://github.com/denfry/codebase-index/compare/v1.7.0...v1.8.0
[1.7.0]: https://github.com/denfry/codebase-index/compare/v1.6.0...v1.7.0
[1.6.0]: https://github.com/denfry/codebase-index/compare/v1.5.0...v1.6.0
[1.5.0]: https://github.com/denfry/codebase-index/compare/v1.4.0...v1.5.0
[1.4.0]: https://github.com/denfry/codebase-index/compare/v1.3.0...v1.4.0
[1.3.0]: https://github.com/denfry/codebase-index/compare/v1.2.1...v1.3.0
[1.2.1]: https://github.com/denfry/codebase-index/compare/v1.2.0...v1.2.1
[1.2.0]: https://github.com/denfry/codebase-index/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/denfry/codebase-index/compare/v1.0.2...v1.1.0
[1.0.2]: https://github.com/denfry/codebase-index/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/denfry/codebase-index/compare/1.0.0...v1.0.1
[1.0.0]: https://github.com/denfry/codebase-index/releases/tag/1.0.0
[0.1.0]: https://github.com/denfry/codebase-index/releases/tag/v0.1.0
