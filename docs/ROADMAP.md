# Roadmap & First Implementation Tasks

Milestones are vertical-ish slices: each ends with something runnable and testable.

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

## M4 — Hybrid search + ranking
- `retrieval/intent.py`, path + symbol searchers, `fusion.py` (RRF), `rerank.py`, `budget.py`.
- `confidence` + `fallback_suggestions`; `search --mode hybrid` (default); `explain`.
- **Exit:** hybrid results outrank single-retriever on the fixture queries; token budget enforced.

## M5 — Graph edges + impact
- `graph/builder.py`: import/call/reference/inheritance edges; target resolution; degree denorm.
- `graph/expand.py` + `impact` command (up/down/both, depth).
- **Exit:** `codebase-index impact "<file/symbol>"` returns a sensible blast radius on fixtures.

## M6 — Optional embeddings / vector backend
- `embeddings/backend.py` protocol, `local.py`, `noop.py`; `sqlite-vec` `vec_chunks`.
- Vector searcher wired into fusion; all behind `embeddings.enabled`. External backend gated by
  SECURITY.md rules.
- **Exit:** with extras installed + enabled, semantic queries improve recall; disabled path unchanged.

## M7 — Claude Code Skill packaging
- Finalize `skill/SKILL.md` + `scripts/cbx`(.ps1); `skill_template/` shipped in wheel; `init` writes it.
- Freshness contract honored end-to-end (skill triggers `update`/`index`).
- **Exit:** fresh `init` → ask a question in Claude Code → skill returns compact reads; manual QA.

## M8 — Hooks + watch mode
- `examples/hooks/settings.json`; `--with-hooks`; `watch/watcher.py` (debounced, async).
- `doctor` reports enabled hooks.
- **Exit:** editing files keeps the index fresh via hook or watch; no blocking of the edit loop.

## M9 — Tests, docs, examples, release
- Coverage across modules; CLI golden-output tests; perf check on a medium repo.
- `examples/queries.md`, finalized docs, CHANGELOG, PyPI release, tagged GitHub release.
- **Exit:** `pipx install codebase-index` + `init` + ask a question works on a clean machine.

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
