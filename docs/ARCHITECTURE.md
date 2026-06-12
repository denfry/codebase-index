# Architecture

## 1. Overview

`codebase-index` is a **local-first** code intelligence layer for AI coding agents. In `1.3.0`
it has two shipped faces:

1. **A Claude Code Skill** (`.claude/skills/codebase-index/SKILL.md`) that Claude auto-invokes for
   codebase questions. The skill is thin: it tells Claude *when* to search, *how* to call the CLI,
   and *how to interpret* the compact results.
2. **A Python CLI** (`codebase-index` / `cbx`) that does the real work: indexing and retrieval.

`init` can also write Codex CLI and OpenCode instruction packages. MCP is exposed through the
stdio server command `codebase-index mcp --root <repo>`; see [MCP.md](MCP.md).

The design goal is **token efficiency**: Claude should read the *minimum* set of file/line ranges
needed to answer, guided by a pre-built index, rather than scanning the repository.

```
┌──────────────────────────────────────────────────────────────────────┐
│ Claude Code                                                            │
│                                                                        │
│  user question ──▶ /codebase-index skill (SKILL.md)                    │
│                        │  builds a CLI call from $ARGUMENTS            │
│                        ▼                                               │
│                 ${CLAUDE_SKILL_DIR}/scripts/cbx  search/explain/...    │
└────────────────────────┬───────────────────────────────────────────┬─┘
                         │ JSON / compact Markdown                    │
                         ▼                                            │
┌──────────────────────────────────────────────────────────────┐    │
│ codebase_index CLI                                             │    │
│                                                                │    │
│  retrieval ──┬─ path  ─┐                                       │    │
│              ├─ symbol  │                                       │    │
│              ├─ fts5    ├─▶ RRF fusion ─▶ rerank ─▶ graph      │    │
│              ├─ vector  │                          expansion   │    │
│              └─ graph  ─┘                  ─▶ token-budgeted    │    │
│                                               output           │    │
│        ▲                                                       │    │
│        │ reads                                                 │    │
│  ┌─────┴───────────────────────────────────────────────────┐  │    │
│  │ storage: .claude/cache/codebase-index/index.sqlite       │  │    │
│  │   files · chunks · symbols · edges · summaries · fts · vec│  │    │
│  └──────────────────────────────────────────────────────────┘  │    │
│        ▲ writes                                                │    │
│  indexer ◀─ parsers (tree-sitter / line-chunk) ◀─ discovery   │    │
└────────────────────────────────────────────────────────────────┘    │
                                                              fallback ─┘
                                            (ripgrep/Grep/Glob when index weak)
```

## 2. Two-layer separation

| Layer | Lives in | Responsibility | Committed to git? |
|---|---|---|---|
| Skill | `.claude/skills/codebase-index/` | Prompt logic, CLI wrappers | Yes (team shares it) |
| CLI | installed package `codebase_index` | Indexing + retrieval engine | No (it's a dependency) |
| Cache | `.claude/cache/codebase-index/` | The actual index DB + config + logs | **No** (gitignored) |

The skill never contains heavy logic — it only orchestrates CLI calls and interprets output. This
keeps the prompt small and lets the engine evolve without editing the skill.

## 3. Repository layout

```
codebase-index/
├── README.md / LICENSE / CHANGELOG.md / CONTRIBUTING.md / SECURITY.md / ROADMAP.md
├── pyproject.toml               # hatch dynamic version <- src/codebase_index/__init__.py
├── requirements.lock            # pinned install spec for the plugin bootstrap
├── install.sh / install.ps1     # multi-CLI installer (drives adapters/ + lib/)
├── adapters/                    # per-CLI install logic (claude/codex/opencode, sh + ps1)
├── lib/                         # shared shell helpers for the installer
├── bin/                         # plugin wrappers (cbx resolves the provisioned venv)
├── scripts/                     # bootstrap.sh/.ps1, release_smoke.py, sync_skill_copies.py
├── hooks/                       # plugin hooks.json (SessionStart bootstrap)
├── .claude-plugin/              # plugin manifest + marketplace catalog
├── .github/                     # CI (lint, skill-sync gate, OS/Python test matrix), release
├── docs/                        # this file + installation/retrieval/schema/security/faq
├── skill/                       # installer source package (SKILL.md, scripts, examples)
├── skills/codebase-index/       # plugin skill copy (generated — scripts/sync_skill_copies.py)
├── .claude/ .codex/ .opencode/  # committed installed copies (generated — same script)
├── examples/                    # sample queries, configs, hooks
├── tests/                       # pytest suite + fixtures (sample_repo, multilang)
└── src/codebase_index/
    ├── cli.py                   # Typer app: all commands (delegates to service.py)
    ├── service.py               # shared CLI/MCP service layer: paths, search sessions, stats
    ├── config.py                # config load/merge/validate (pydantic)
    ├── models.py                # shared pydantic result models
    ├── doctor.py                # config/security diagnostics
    ├── scaffold.py              # init: skill + config + gitignore + MCP client configs
    ├── skill_update.py          # skill auto-update/rollback with version stamps
    ├── discovery/               # walker.py, ignore.py, classify.py
    ├── parsers/                 # treesitter.py, languages.py, line_chunker.py,
    │                            #   symbol_chunks.py, base.py
    ├── indexer/                 # pipeline.py (full + incremental build), freshness.py,
    │                            #   doc_chunks.py
    ├── graph/                   # builder.py (edge resolution), expand.py (impact),
    │                            #   export.py (HTML graph)
    ├── storage/                 # db.py (pragmas, schema, version guard), schema.sql, repo.py
    ├── retrieval/               # intent.py, searchers.py, fusion.py, rerank.py,
    │                            #   budget.py, pipeline.py, types.py
    ├── embeddings/              # backend.py, noop.py (default), local.py, external.py — opt-in
    ├── output/                  # markdown.py, json.py, redact.py
    ├── watch/                   # watcher.py (optional, watchdog-based)
    ├── mcp/                     # server.py (stdio MCP over the same service layer)
    └── skill_template/          # canonical skill source shipped in the wheel
```

The committed skill copies (`skill/`, `skills/`, `.claude/`, `.codex/`, `.opencode/`) are
generated from `src/codebase_index/skill_template/` by `scripts/sync_skill_copies.py`;
CI fails if they drift (`--check`).

## 4. Module responsibilities

- **discovery** — Walk the repo, apply layered ignore rules, classify each file (language, binary,
  size, secret-likelihood). Produces a list of `(path, lang, hash, mtime)` candidates. Hard refuses
  to emit secret/binary/build/dependency/huge files.
- **parsers** — Convert an eligible file into (a) **chunks** (text spans with line ranges) and
  (b) **symbols** (functions/classes/methods/etc. with kind, name, line range, signature, scope).
  Tree-sitter when a grammar exists; line-based chunker otherwise.
- **graph/builder** — From AST, extract `imports`, `calls`, `references`, `extends/implements`, and
  resolve them to target symbols/files where possible. Unresolved edges are kept as soft text refs.
- **indexer/pipeline** — Drives a build: discovery → parse (process pool on large repos) → store
  chunks/symbols → build graph → FTS sync → (optional) embeddings. `update_index` re-processes
  only files whose (mtime, size, sha256) fingerprint changed; `freshness.py` reports staleness.
- **storage** — Owns the SQLite DB, pragmas (WAL, foreign keys), the schema version guard
  (a future-versioned index asks for a rebuild rather than guessing), and typed accessors.
  FTS5 virtual tables and (optional) `sqlite-vec` vector tables live here.
- **retrieval** — The query path. `intent.py` classifies the query; `searchers.py` runs the
  relevant retrievers; `fusion.py` merges them with RRF; `rerank.py` reorders; `graph.expand`
  pulls in related nodes; `budget.py` trims to a token budget.
- **embeddings** — Opt-in only. A `Backend` protocol so vector providers are pluggable. Default is
  `noop` (disabled). Local models supported; external APIs require explicit config + a warning.
- **output** — Two renderers: compact Markdown (for Claude) and JSON (for tools/tests). Both carry
  the same fields (query, freshness, confidence, results, recommended reads, fallbacks).
- **watch** — Optional `watchdog`-based live updater (debounced, async). Not required.

## 5. CLI contract

All commands accept `--json` (machine output), `--root <path>` (project root, default = cwd
upward to nearest `.git`/`.claude`), and `--quiet`. Search-family commands accept
`--limit N`, `--token-budget N`, and `--no-fallback`.

| Command | Args / flags | Exit behavior | Output |
|---|---|---|---|
| `init` | `--force`, `--with-hooks` | Scaffolds skill dir + `config.json` + gitignore lines | summary |
| `index` | `--rebuild` | Full build; errors non-zero on fatal | progress + `stats` |
| `update` | `--since <git-ref>`, `--all` | Incremental; no-op if nothing changed | changed-file count |
| `search` | `"<query>"`, `--limit`, `--token-budget`, `--mode hybrid\|fts\|symbol\|vector` | 0 even if empty | ranked results |
| `symbol` | `"<name>"`, `--kind`, `--exact` | 0; empty list allowed | symbol defs |
| `refs` | `"<symbol>"`, `--kind callers\|all` | 0 | reference sites |
| `impact` | `"<file-or-symbol>"`, `--depth N`, `--direction up\|down\|both` | 0 | affected files ranked |
| `explain` | `"<query>"`, `--token-budget` | 0 | intent-aware bundle |
| `stats` | — | 0 | counts, coverage %, freshness |
| `doctor` | `--strict` | non-zero if unsafe config found | findings list |
| `clean` | `--yes`, `--all` | resets index DB (`--all` wipes cache dir) | removed-count |
| `watch` | `--debounce ms` | long-running | event log |

The skill only ever calls the **read-only** family (`search`, `symbol`, `refs`, `impact`,
`explain`, `stats`) plus `update`. It never calls `clean` or `init`. See SECURITY.md.

### Freshness contract

Every search-family response includes an `index` block:

```json
{ "index": { "exists": true, "stale": false, "files_changed_since_build": 0,
             "built_at": "2026-05-28T10:00:00Z", "head_commit": "abc1234" } }
```

If `exists=false` → skill runs `index`. If `stale=true` and cheap → skill runs `update` first.

## 6. Data flow: a single question

1. User asks a codebase question in Claude Code.
2. Claude invokes `/codebase-index <question>`; SKILL.md maps it to `explain`/`search`.
3. CLI checks freshness → maybe `update`.
4. `intent.py` classifies the query → selects searchers + graph strategy.
5. Searchers return candidate lists → RRF fusion → rerank → graph expansion.
6. `budget.py` trims to the token budget → `output/markdown` renders.
7. Claude reads **only** the `recommended_reads` ranges, then answers with citations.
8. If confidence is low, Claude falls back to Grep/Glob as the skill instructs.

## 7. Performance principles

- SQLite in WAL mode; FTS5 for lexical; prepared statements; single connection per CLI call.
- Incremental by default — only changed files (by content hash) are re-parsed.
- Parse work is parallelizable per file (process pool) but writes are serialized.
- Vector search is optional and isolated behind the `embeddings` extra; base install stays light.

## 8. MCP server

The same `retrieval` + `storage` layers are wrapped in a stdio MCP server exposing tools like
`search_code`, `find_symbol`, `find_refs`, `impact_of`, `explain_code`, `index_stats`, and
`healthcheck`.

Current implementation:

- `src/codebase_index/mcp/server.py` is a thin adapter over `retrieval/`, `storage/`, and
  `indexer/freshness.py`.
- `codebase-index mcp --root <repo>` runs the stdio server.
- JSON payloads include `schema_version`.
- [MCP.md](MCP.md) provides config templates for Claude Desktop, Claude Code, Cursor, VS Code,
  Zed, and Windsurf.
- `healthcheck` lets MCP clients distinguish "server running", "index missing",
  "index stale", and "unsafe config".
- Follow-up: progressive or paged results for large queries so agents can stop after enough
  context.

## 9. Code intelligence graph roadmap

The current graph is an import/call/reference/inheritance graph. It is useful for `refs`,
bounded graph expansion, and `impact`, but it is not yet a full framework-aware code intelligence
graph.

High-value schema extensions:

- HTTP route -> handler -> service -> repository -> model
- test -> fixture -> implementation
- interface/trait -> implementation
- config key -> consumer
- migration -> model -> query
- event producer -> event consumer
- DI container / framework wiring
- frontend component -> hook/store/api client
- error string/log message -> throw site -> handler

These should be modeled as typed edges with source spans, confidence, and resolver provenance so
agents can trust precise edges while treating heuristic framework edges as suggestions.
