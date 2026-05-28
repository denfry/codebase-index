# codebase-index

> A local-first **Claude Code Skill** that gives Claude a fast, token-efficient index of your
> repository — like Cursor's local codebase index, but as a Skill + CLI you fully control.

When you ask Claude a question about your project, the `/codebase-index` skill searches a local
hybrid index (symbols + full-text + optional vectors + a dependency graph) and returns a compact,
ranked list of **exactly which files and line ranges to read next** — instead of Claude blindly
scanning the whole repo and burning tokens.

```
You:    "Where is auth token refresh implemented and what breaks if I change it?"
Claude: → runs `codebase-index explain "auth token refresh impact"`
        → reads only 3 ranked files (≈400 lines) instead of 60
        → answers with citations
```

---

## Why this exists

| Problem | This skill |
|---|---|
| Claude greps/globs the whole repo per question | Pre-built local index, sub-second lookups |
| Reading whole files wastes the context window | Returns line ranges + snippets, token-budgeted |
| "What breaks if I change X?" needs manual tracing | Dependency/call graph + `impact` command |
| Cloud indexers send your code to a server | **Local-first**, no network by default |

This is a **Skill, not a required MCP server**. Everything runs through
`.claude/skills/codebase-index/SKILL.md` + a bundled Python CLI (`codebase-index`). An MCP server is
documented only as a *future extension* (see [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md)).

## Quick start

```bash
# 1. Install the CLI (pipx recommended so it's isolated)
pipx install codebase-index            # or: pip install codebase-index

# 2. Install the skill into your project
codebase-index init                    # writes .claude/skills/codebase-index/ + .gitignore rules

# 3. Build the index
codebase-index index                   # full build into .claude/cache/codebase-index/index.sqlite

# 4. Use it in Claude Code
#    Just ask a codebase question — Claude auto-invokes the skill — or run explicitly:
/codebase-index where is the rate limiter configured
```

See [docs/INSTALLATION.md](docs/INSTALLATION.md) for details.

## What gets built

A per-project cache (never committed):

```
.claude/cache/codebase-index/
├── index.sqlite        # SQLite + FTS5: files, chunks, symbols, edges, summaries
├── config.json         # resolved config (languages, ignore rules, embeddings backend)
└── logs/               # indexing + query logs
```

## CLI at a glance

| Command | Purpose |
|---|---|
| `codebase-index init` | Scaffold skill + config + gitignore rules |
| `codebase-index index` | Full index build |
| `codebase-index update` | Incremental re-index (hash/mtime/git aware) |
| `codebase-index search "<q>"` | Hybrid ranked search |
| `codebase-index symbol "<name>"` | Locate a symbol definition |
| `codebase-index refs "<symbol>"` | Find references/callers |
| `codebase-index impact "<file/symbol>"` | Blast-radius via dep graph |
| `codebase-index explain "<q>"` | Intent-aware bundle for "how does X work" |
| `codebase-index stats` | Index size, coverage, freshness |
| `codebase-index doctor` | Diagnose config + security issues |
| `codebase-index clean` | Drop the cache |
| `codebase-index watch` | (optional) live incremental indexing |

Full contract: [docs/ARCHITECTURE.md#cli-contract](docs/ARCHITECTURE.md).

## Documentation

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — system overview, modules, CLI contract, MCP future
- [docs/RETRIEVAL.md](docs/RETRIEVAL.md) — hybrid retrieval pipeline, intent detection, rank fusion
- [docs/SCHEMA.md](docs/SCHEMA.md) — SQLite/FTS5 schema
- [docs/SECURITY.md](docs/SECURITY.md) — security model, secret redaction, ignore rules
- [docs/INSTALLATION.md](docs/INSTALLATION.md) — install, configure, hooks
- [docs/ROADMAP.md](docs/ROADMAP.md) — milestones M0–M9 and first implementation tasks

## Status

🚧 **Blueprint / scaffold (M0).** This repo currently contains the architecture, schema, SKILL.md
draft, and module skeletons. See [docs/ROADMAP.md](docs/ROADMAP.md) for what to implement next.

## License

MIT
