# Roadmap & First Implementation Tasks

Milestones are vertical-ish slices: each ends with something runnable and testable.
This numbering is canonical — the product-level [ROADMAP.md](../ROADMAP.md) and the
`(Mx)` tags in [CHANGELOG.md](../CHANGELOG.md) follow it.

## M0 — Architecture & scaffold ✅ (this repo)
- Repo tree, docs (ARCHITECTURE/RETRIEVAL/SCHEMA/SECURITY/INSTALLATION), SKILL.md draft.
- `pyproject.toml`, module skeletons with responsibilities, CLI command stubs.
- **Exit:** `pip install -e .` works; `codebase-index --help` lists all commands (stubs ok).

## M1 — Storage + discovery + ignore rules ✅
- `storage/db.py`: connection, pragmas, apply `schema.sql`, `meta.schema_version`.
- `discovery/`: walker, layered ignore (`pathspec`), `classify.py` (lang/binary/size/secret gates).
- **Exit:** `codebase-index index` populates `files` correctly; secrets/binaries/build dirs excluded.
- Tests: `test_ignore.py`, `test_discovery.py`, `test_storage.py`.

## M2 — FTS5 lexical indexing ✅
- `parsers/line_chunker.py`: window chunks with overlap + token estimate.
- `fts_chunks` virtual table + sync triggers + code-aware tokenizer.
- `retrieval/searchers.py` (FTS only) + `output/` renderers + `search --mode fts`.
- **Exit:** `codebase-index search "<q>"` returns ranked lexical results with line ranges/snippets.
- `snake_case` is split at index time (plain unicode61 tokenizer); camelCase is expanded at query
  time. A true custom FTS5 tokenizer via APSW is deferred.

## M3 — Tree-sitter symbol extraction ✅
- `parsers/treesitter.py` + `languages.py` (grammar registry, node→symbol maps for Python,
  JavaScript, and TypeScript).
- Populate `symbols`; symbol-aligned chunks; `symbol` + `refs` (intra-file first).
- **Exit:** `codebase-index symbol "<name>"` and `refs` work for supported languages; line fallback
  for the rest.
- Shipped languages: Python, JavaScript, TypeScript. Go/Java/Rust/C/C++/Ruby/PHP follow the recipe
  in `docs/LANGUAGES.md`. `refs` is intra-file (call sites + defs); cross-file resolution is M5.

## M4 — Hybrid search + ranking ✅
- `retrieval/intent.py`, path + symbol searchers, `fusion.py` (RRF), `rerank.py`, `budget.py`.
- `confidence` + `fallback_suggestions`; `search --mode hybrid` (default); `explain`.
- **Exit:** hybrid results outrank single-retriever on the fixture queries; token budget enforced.

## M5 — Graph edges + impact ✅
- `parsers/languages.py`: `imports_query` slot with import/extends/implements patterns (Python end-to-end; JS/TS query slots wired).
- `parsers/treesitter.py`: extract import + inheritance edges via capture-prefixed queries.
- `graph/builder.py`: cross-file edge resolution by unambiguous symbol name / module→file suffix; degree denormalization.
- `graph/expand.py`: bounded BFS impact walk (up/down/both, depth).
- **Exit:** `codebase-index impact "<file/symbol>" --direction up|down|both --depth N` returns a sensible blast radius on fixtures. Ambiguous symbol names are left unresolved by design.

## M6 — Optional embeddings / vector backend ✅
- `embeddings/` package (protocol + noop default + lazy local + gated external), `sqlite-vec` `vec_chunks` store loaded on demand, indexer embedding pass behind `embeddings.enabled`, and a vector retriever fused into hybrid with per-intent weights. External backend refused unless `allow_external` + `$CBX_EMBEDDINGS_API_KEY` + an endpoint warning (SECURITY.md §4). Disabled path imports no optional dep and is byte-for-byte unchanged.
- **Exit:** with extras installed + enabled, semantic queries improve recall; disabled path unchanged.

## M7 — Claude Code Skill packaging ✅
- Shipped: `init` materializes the wheel-bundled skill template (SKILL.md + cbx/cbx.ps1) to `.claude/skills/codebase-index/`, writes resolved `config.json`, and idempotently gitignores the cache (`--force` to overwrite). The freshness contract is honored end-to-end — `search` returns real `stale`/`files_changed_since_build` (git clean-tree fast-path + mtime diff), so the skill triggers `update`/`index` per SKILL.md. `--with-hooks` writes a reviewable hooks example; auto-merging hooks + `watch` are M8.

## M7.5 — One-command plugin install ✅
- Repo doubles as a Claude Code plugin (`.claude-plugin/plugin.json` + `marketplace.json`).
- `SessionStart` hook (`scripts/bootstrap.sh`/`.ps1`) provisions a venv in `${CLAUDE_PLUGIN_DATA}`
  with the pinned CLI (uv-preferred, pip fallback), reinstalling only when `requirements.lock` changes.
- `bin/cbx` + `bin/codebase-index` wrappers resolve the venv via a `.venv-path` pointer and keep the
  subcommand whitelist.
- **Exit:** `/plugin install codebase-index@<marketplace>` → ask a codebase question → compact reads,
  no manual `pip`/`init`/`index`. The bootstrap installs the package from the GitHub release tarball
  pinned in `requirements.lock` (not PyPI); `CBX_INSTALL_SPEC` overrides the source for local/dev installs.

## M8 — Hooks + watch mode ✅
- Shipped: incremental `update` (mtime fast-path + sha verify + prune; `--since <ref>`, `--all`) is the engine the freshness contract calls; `init --with-hooks` auto-merges the `PostToolUse` update hook into `.claude/settings.json` idempotently; `watch` mode (optional `[watch]` extra) coalesces edit bursts into one debounced `update` and degrades to a clear error when watchdog is absent; `doctor` reports enabled hooks, cache-gitignore coverage, and freshness, exiting non-zero under `--strict` on high-severity findings. The full SECURITY.md §6 doctor checklist (secret-leak scan, perms, allowed-tools diff) is M9.

## M9 — Tests, docs, examples, release ✅
- Coverage across modules; CLI golden-output tests; perf check on a medium repo.
- `examples/queries.md`, finalized docs, CHANGELOG, tagged GitHub release (GitHub-only distribution — no PyPI).
- **Exit:** `pipx install "git+https://github.com/denfry/codebase-index.git@v1.0.2"` + `init` + ask a question works on a clean machine.

*Shipped: golden-file tests lock CLI `--json` output; a `--runslow` perf smoke test guards
index/search latency on a synthetic medium repo; coverage is gated (`--cov-fail-under`) in a
CI matrix (Ubuntu/macOS/Windows × py3.10–3.13). `CHANGELOG.md` tracks releases; a tag-triggered
release pipeline builds, runs `twine check` + a clean-venv install smoke, and publishes a GitHub
release with the built artifacts (GitHub-only distribution — no PyPI publish). `pipx install
"git+https://github.com/denfry/codebase-index.git@v1.0.2"` → `init` → `index` → ask a question is
verified end-to-end by `scripts/release_smoke.py`.*

## M10 — Optional MCP bridge (planned)
- Model Context Protocol server exposing `search`, `symbol`, `refs`, `impact` as tools for
  MCP-compatible clients (Claude Desktop, Cursor, etc.). An optional addition, not a replacement
  for the Skill/CLI interface.
- **Exit:** `codebase-index` can be used as an MCP tool by any MCP-compatible client.

---

## First concrete tasks (start here)

1. **Scaffold the package** so `codebase-index --help` runs: flesh out `cli.py` Typer app with all
   commands as stubs that print "not implemented" and parse the documented flags.
2. **Implement `storage/db.py` + `schema.sql`** exactly per SCHEMA.md; add a migration guard on
   `meta.schema_version`. Test: open/close/recreate, pragma assertions.
3. **Implement `discovery/ignore.py`** with `pathspec`, merging the four ignore files + built-in
   denylist + secret-filename + size + binary gates. Test against `tests/fixtures/` with planted
   secrets and a `node_modules` dir — assert they're excluded.
4. **Implement `discovery/walker.py` + minimal `index`** to populate `files` (no chunks yet), so
   `stats` shows real coverage. This gives the first end-to-end runnable slice.
5. **Build a fixture repo** under `tests/fixtures/sample_repo/` (a few py/ts files, an `.env`, a
   `node_modules`, a binary, a generated file) used across all later milestone tests.

Each task should land behind tests (TDD) and keep the base install network-free.
