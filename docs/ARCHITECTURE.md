# Architecture

## 1. Overview

`codebase-index` is a **local-first** code intelligence layer for Claude Code. It has two faces:

1. **A Claude Code Skill** (`.claude/skills/codebase-index/SKILL.md`) that Claude auto-invokes for
   codebase questions. The skill is thin: it tells Claude *when* to search, *how* to call the CLI,
   and *how to interpret* the compact results.
2. **A Python CLI** (`codebase-index` / `cbx`) that does the real work: indexing and retrieval.

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
├── README.md
├── pyproject.toml
├── .gitignore
├── docs/
│   ├── ARCHITECTURE.md          # this file
│   ├── RETRIEVAL.md             # retrieval pipeline + intent detection
│   ├── SCHEMA.md                # SQLite/FTS5 schema
│   ├── SECURITY.md              # security model
│   ├── INSTALLATION.md          # install + configure + hooks
│   └── ROADMAP.md               # milestones M0–M9
├── skill/                       # canonical source of the skill (copied on `init`)
│   ├── SKILL.md
│   └── scripts/
│       ├── cbx                  # POSIX wrapper -> resolves CLI, passes args
│       └── cbx.ps1              # Windows PowerShell wrapper
├── src/
│   └── codebase_index/
│       ├── __init__.py
│       ├── cli.py               # Typer app: all commands
│       ├── config.py            # config load/merge/validate (pydantic)
│       ├── models.py            # shared dataclasses/pydantic result models
│       ├── discovery/           # file walking + ignore rules + file classification
│       │   ├── __init__.py
│       │   ├── walker.py
│       │   ├── ignore.py        # .gitignore/.cursorignore/.claudeignore/.codeindexignore
│       │   └── classify.py      # language detection, binary/secret/size gates
│       ├── parsers/             # turn files into chunks + symbols
│       │   ├── __init__.py
│       │   ├── base.py          # Parser protocol
│       │   ├── treesitter.py    # AST symbol extraction
│       │   ├── line_chunker.py  # fallback chunking
│       │   └── languages.py     # grammar registry + node→symbol maps
│       ├── indexer/             # orchestration of a build/update
│       │   ├── __init__.py
│       │   ├── pipeline.py      # full + incremental build
│       │   ├── incremental.py   # hash/mtime/git change detection
│       │   └── summarize.py     # file/module/package summaries
│       ├── graph/               # import/call/reference/dependency edges
│       │   ├── __init__.py
│       │   ├── builder.py       # extract edges from AST + resolve targets
│       │   └── expand.py        # graph expansion + impact (blast radius)
│       ├── storage/             # SQLite persistence
│       │   ├── __init__.py
│       │   ├── db.py            # connection, pragmas, migrations
│       │   ├── schema.sql       # DDL (mirrors docs/SCHEMA.md)
│       │   └── repo.py          # typed read/write accessors
│       ├── retrieval/           # the search engine
│       │   ├── __init__.py
│       │   ├── intent.py        # query intent classification
│       │   ├── searchers.py     # path/symbol/fts/vector searchers
│       │   ├── fusion.py        # Reciprocal Rank Fusion
│       │   ├── rerank.py        # feature-based reranking
│       │   └── budget.py        # token budgeting of results
│       ├── embeddings/          # OPTIONAL, opt-in vector backend
│       │   ├── __init__.py
│       │   ├── backend.py       # pluggable Backend protocol
│       │   ├── local.py         # sentence-transformers / local model
│       │   └── noop.py          # default: disabled
│       ├── output/              # rendering results
│       │   ├── __init__.py
│       │   ├── markdown.py      # compact Markdown for Claude
│       │   └── json.py          # machine JSON
│       ├── watch/               # OPTIONAL live indexing
│       │   ├── __init__.py
│       │   └── watcher.py
│       └── skill_template/      # packaged copy of skill/ shipped in the wheel
│           ├── SKILL.md
│           └── scripts/
├── tests/
│   ├── fixtures/                # tiny sample repos
│   ├── test_discovery.py
│   ├── test_ignore.py
│   ├── test_parsers.py
│   ├── test_storage.py
│   ├── test_retrieval.py
│   ├── test_graph.py
│   └── test_cli.py
└── examples/
    ├── hooks/settings.json      # optional PostToolUse auto-update hook
    ├── config.example.json
    └── queries.md               # example questions → commands
```

## 4. Module responsibilities

- **discovery** — Walk the repo, apply layered ignore rules, classify each file (language, binary,
  size, secret-likelihood). Produces a list of `(path, lang, hash, mtime)` candidates. Hard refuses
  to emit secret/binary/build/dependency/huge files.
- **parsers** — Convert an eligible file into (a) **chunks** (text spans with line ranges) and
  (b) **symbols** (functions/classes/methods/etc. with kind, name, line range, signature, scope).
  Tree-sitter when a grammar exists; line-based chunker otherwise.
- **graph/builder** — From AST, extract `imports`, `calls`, `references`, `extends/implements`, and
  resolve them to target symbols/files where possible. Unresolved edges are kept as soft text refs.
- **indexer/pipeline** — Drives a build: discovery → parse → store chunks/symbols → build graph →
  summaries → FTS sync → (optional) embeddings. `incremental.py` decides what to re-process.
- **storage** — Owns the SQLite DB, pragmas (WAL, foreign keys), migrations, and typed accessors.
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
| `clean` | `--yes` | removes cache | confirmation |
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

## 8. Future extension: MCP server (NOT required)

The same `retrieval` + `storage` layers can be wrapped in an MCP server exposing tools like
`search_code`, `find_symbol`, `impact_of`. This is **explicitly out of scope for v1** — the skill
+ CLI path is the supported workflow. An MCP wrapper would reuse `retrieval/` unchanged and add
`src/codebase_index/mcp/server.py`. Documented here only so the architecture stays MCP-ready.
