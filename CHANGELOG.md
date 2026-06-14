# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

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

[Unreleased]: https://github.com/denfry/codebase-index/compare/v1.2.1...HEAD
[1.2.1]: https://github.com/denfry/codebase-index/compare/v1.2.0...v1.2.1
[1.2.0]: https://github.com/denfry/codebase-index/compare/v1.1.0...v1.2.0
[1.1.0]: https://github.com/denfry/codebase-index/compare/v1.0.2...v1.1.0
[1.0.2]: https://github.com/denfry/codebase-index/compare/v1.0.1...v1.0.2
[1.0.1]: https://github.com/denfry/codebase-index/compare/1.0.0...v1.0.1
[1.0.0]: https://github.com/denfry/codebase-index/releases/tag/1.0.0
[0.1.0]: https://github.com/denfry/codebase-index/releases/tag/v0.1.0
