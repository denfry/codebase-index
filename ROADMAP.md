# Roadmap

`codebase-index` is developed in milestone-driven slices. Each milestone delivers a runnable, testable feature.

## Milestones

Milestone numbering matches [docs/ROADMAP.md](docs/ROADMAP.md) (the detailed
implementation roadmap) and the `(Mx)` tags in [CHANGELOG.md](CHANGELOG.md).

### M0 — Architecture & scaffold ✅
- Repo tree, core docs (ARCHITECTURE, RETRIEVAL, SCHEMA, SECURITY, INSTALLATION), SKILL.md draft.
- `pyproject.toml`, module skeletons, CLI command stubs, MIT license, changelog, contributing guide.
- **Exit:** `codebase-index --help` lists all commands; repository is ready for public listing.

### M1 — Storage + discovery + ignore rules ✅
- SQLite storage with `meta.schema_version`; file discovery with layered ignore rules
  (`.gitignore`, `.codeindexignore`, built-in denylist) and secret/binary/size gates.
- Incremental indexing with file-hash tracking.
- **Exit:** `codebase-index index` populates the database; secrets and binaries are excluded.

### M2 — FTS5 lexical indexing ✅
- Line-window chunks + FTS5 virtual table with sync triggers and a code-aware tokenizer.
- **Exit:** `codebase-index search "<query>"` returns ranked lexical results with line ranges.

### M3 — Tree-sitter symbol extraction ✅
- AST symbol extraction for Python, JavaScript, TypeScript; symbol-aligned chunking.
- `symbol` and `refs` commands for symbol lookup, with a line-based fallback for other languages.
- **Exit:** `codebase-index symbol "AuthService"` returns definitions and references.

### M4 — Hybrid search + ranking ✅
- Path + symbol + FTS5 (+ optional vector) retrieval with Reciprocal Rank Fusion (RRF),
  confidence scoring, fallback suggestions, and token-budgeted retrieval packets.
- **Exit:** hybrid results outrank single-retriever search; output stays within the token budget.

### M5 — Graph edges + impact ✅
- Import, call, and inheritance edge extraction; bounded BFS impact walk (up/down/both, depth).
- **Exit:** `codebase-index impact "src/auth/AuthService.ts"` shows affected files and symbols.

### M6 — Optional local embeddings ✅
- `sqlite-vec` vector backend (opt-in), local sentence-transformers as default, external
  embedding APIs gated behind explicit opt-in with warnings.
- **Exit:** semantic queries improve recall when enabled; the disabled path imports no optional dep.

### M7 — Claude Code Skill packaging ✅
- `init` materializes the bundled skill template, resolved `config.json`, and `.gitignore` rules;
  end-to-end freshness contract so the skill triggers `update`/`index`.
- **Exit:** the skill returns real `stale`/`files_changed_since_build` signals for codebase questions.

### M7.5 — One-command plugin install ✅
- Repo doubles as a Claude Code plugin; a `SessionStart` bootstrap provisions an isolated venv
  from the GitHub-pinned `requirements.lock` (uv-preferred, pip fallback).
- **Exit:** `/plugin install codebase-index@codebase-index` → ask a question → compact reads,
  no manual `pip`/`init`/`index`.

### M8 — Hooks + watch mode ✅
- Incremental `update`; `init --with-hooks` auto-merges the PostToolUse hook idempotently;
  `watch` mode coalesces edit bursts into one debounced `update`; `doctor` reports freshness.
- **Exit:** the index stays fresh automatically after file edits.

### M9 — Tests, docs, examples, release ✅
- Coverage gates, CLI golden-output tests, perf smoke on a medium repo.
- Finalized docs, CHANGELOG, tagged GitHub release (distribution is GitHub-only — not on PyPI).
- **Exit:** `pipx install "git+https://github.com/denfry/codebase-index.git@v1.0.2"` works on a clean machine.

### M10 — Optional MCP bridge (planned)
- Model Context Protocol server exposing `search`, `symbol`, `refs`, `impact` as tools.
- Compatible with Claude Desktop, Cursor, and other MCP clients.
- **Exit:** `codebase-index` can be used as an MCP tool by any MCP-compatible client.

---

See [CHANGELOG.md](CHANGELOG.md) for released versions and their changes.
