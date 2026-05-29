# codebase-index

> A local-first **Claude Code Skill** for Cursor-like codebase indexing, hybrid code search, symbol lookup, and token-efficient project context.

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.10+-blue.svg)](https://www.python.org/)
[![CI](https://github.com/<OWNER>/claude-code-codebase-index-skill/actions/workflows/ci.yml/badge.svg)](https://github.com/<OWNER>/claude-code-codebase-index-skill/actions)
[![Claude Code Skill](https://img.shields.io/badge/Claude%20Code%20Skill-yes-green.svg)](skill/SKILL.md)
[![Local First](https://img.shields.io/badge/local--first-yes-green.svg)](#safety-and-privacy)
[![No Telemetry](https://img.shields.io/badge/no%20telemetry-yes-green.svg)](#safety-and-privacy)
[![No Network By Default](https://img.shields.io/badge/no%20network%20by%20default-yes-green.svg)](#safety-and-privacy)
[![SQLite](https://img.shields.io/badge/database-SQLite-blue.svg)](docs/DATABASE_SCHEMA.md)
[![Tree-sitter](https://img.shields.io/badge/parsing-Tree--sitter-orange.svg)](docs/ARCHITECTURE.md)

```
You:    "Where is user authentication implemented?"
Claude: → searches local index (symbols + FTS5 + graph)
        → reads only 3 ranked files (≈400 lines) instead of scanning 60
        → answers with citations: src/auth/AuthService.ts:12-148
```

---

## Install as a Claude Code plugin

One command in Claude Code:

```
/plugin marketplace add your-org/codebase-index
/plugin install codebase-index@codebase-index
```

Or just ask: "install the codebase-index plugin".

**What happens on first run:** when a session starts, a `SessionStart` hook
(`scripts/bootstrap.sh` / `.ps1`) creates a private Python virtual environment under
`~/.claude/plugins/data/codebase-index-*/venv` and installs the pinned
`codebase-index` package (from `requirements.lock`) into it — using `uv` if present,
otherwise `python -m venv` + `pip`. It reinstalls only when the pinned version changes.
Nothing is installed globally; uninstalling the plugin removes the data directory.

**Prerequisite:** Python 3.10+ on your PATH. The first install needs network access to
fetch the package; later sessions are offline. The skill builds its index on your first
codebase question — no manual `index` step.

## Claude Code Skill for Codebase Indexing

`codebase-index` is a **Claude Code Skill** that gives Claude Cursor-like codebase awareness. When you ask a question about your project, Claude searches a local hybrid index instead of scanning the entire repository. The skill returns compact, ranked retrieval packets with files, symbols, line ranges, snippets, and "next files to read" — helping Claude answer codebase questions with far fewer tokens.

## The Problem

Claude Code faces real challenges when working with large codebases:

- **Token waste** — Scanning entire files or running broad grep/glob queries burns through the context window on irrelevant content.
- **No symbol awareness** — Standard search can't distinguish a function definition from a call, or a class from a variable.
- **No ranking** — Grep returns all matches with no relevance ordering. Claude must read everything.
- **No context** — Grep doesn't know which files are related or what to read next.
- **Cloud dependency** — External code indexing services send your proprietary code to remote servers.

Developers want Cursor-like codebase awareness inside Claude Code — without leaving their workflow or sending code to a server.

## The Solution

`codebase-index` builds a **local hybrid index** that combines:

- **Symbol search** — Tree-sitter AST parsing extracts classes, functions, methods, and variables.
- **Full-text search** — SQLite FTS5 for fast lexical search across code chunks.
- **Path search** — File path matching for location-aware queries.
- **Optional semantic search** — Vector embeddings for similarity-based retrieval (opt-in, local by default).
- **Dependency graph** — Import, call, and reference edges for impact analysis and graph expansion.
- **Token-budgeted output** — Ranked retrieval packets with specific line ranges, not whole files.

Claude reads only the recommended files, not the entire repository.

## Quick Demo

```bash
/codebase-index "where is user authentication implemented?"
```

Expected output:

```
Top matches:
┌──────┬──────────────────────────┬──────────────────────────┬───────┬──────────────────────────────┐
│ Rank │ Path                     │ Symbols                  │ Score │ Reason                       │
├──────┼──────────────────────────┼──────────────────────────┼───────┼──────────────────────────────┤
│    1 │ src/auth/AuthService.ts  │ AuthService, login       │  0.92 │ exact symbol match           │
│    2 │ src/routes/auth.ts       │ loginHandler, logout     │  0.78 │ FTS match · 4 callers        │
│    3 │ src/middleware/auth.ts   │ requireAuth              │  0.65 │ path match · FTS match       │
└──────┴──────────────────────────┴──────────────────────────┴───────┴──────────────────────────────┘

Recommended reads:
  1. src/auth/AuthService.ts:12-148
     reason: matched AuthService, login(), validatePassword()
  2. src/routes/auth.ts:20-91
     reason: /login route calls AuthService.login()
  3. src/middleware/auth.ts:5-42
     reason: auth middleware validates sessions
```

## Installation

### Option 1: Clone as a Claude Code Skill

```bash
cd your-project
git clone https://github.com/<OWNER>/claude-code-codebase-index-skill.git .claude/skills/codebase-index
cd .claude/skills/codebase-index
pip install -e .
python -m codebase_index doctor
```

### Option 2: Install as a Python Package

```bash
# Using pip
pip install codebase-index

# Using pipx (isolated)
pipx install codebase-index

# From source
git clone https://github.com/<OWNER>/claude-code-codebase-index-skill.git
cd claude-code-codebase-index-skill
pip install -e ".[dev]"
```

### Option 3: Run Doctor

```bash
python -m codebase_index doctor
```

See [docs/INSTALLATION.md](docs/INSTALLATION.md) for the full guide, including optional extras (embeddings, watch mode) and troubleshooting.

## Usage

```bash
# Initialize the index for your project
codebase-index init

# Build the index
codebase-index index

# Search for something
codebase-index search "where is authentication implemented?"

# Look up a specific symbol
codebase-index symbol "AuthService"

# Find callers and references
codebase-index refs "AuthService.login"

# Analyze impact of a change
codebase-index impact "src/auth/AuthService.ts"

# View index statistics
codebase-index stats

# Run diagnostics
codebase-index doctor
```

Add `--json` to any command for machine-readable output.

## How Codebase Index Works

```
User question
    ↓
Claude Code Skill (SKILL.md)
    ↓
Hybrid retrieval
    ├─ Path search
    ├─ Symbol search (Tree-sitter AST)
    ├─ SQLite FTS5 full-text search
    ├─ Optional embeddings (vector search)
    └─ Graph expansion (callers, imports, references)
    ↓
Ranked retrieval packet
    ↓
Claude reads only the recommended line ranges
    ↓
Answer with precise file:line citations
```

## Features

- [x] **Local-first indexing** — All data stays on your machine
- [x] **No network by default** — Zero external API calls out of the box
- [x] **Respects ignore files** — `.gitignore`, `.claudeignore`, `.codeindexignore`
- [x] **SQLite storage** — Fast, reliable, single-file database
- [x] **FTS5 lexical search** — Full-text search with code-aware tokenization
- [x] **Tree-sitter AST parsing** — Symbol extraction for Python, JavaScript, TypeScript
- [x] **Symbol extraction** — Classes, functions, methods, variables with line ranges
- [x] **Incremental indexing** — Only changed files are re-indexed
- [x] **Token-budgeted output** — Configurable max output size
- [x] **Secret redaction** — Masks keys, tokens, and credentials in snippets
- [ ] **Optional embeddings** — Local or remote vector search (planned)
- [ ] **Optional hooks** — Auto-update index after file edits (planned)
- [ ] **Optional MCP wrapper** — Model Context Protocol bridge (planned)

## Safety and Privacy

`codebase-index` is designed with privacy as a first principle:

- **No telemetry** — No usage data, analytics, or crash reports are collected or transmitted.
- **No external API calls by default** — All indexing, storage, and search happen locally.
- **Does not index sensitive files** — `.env`, private keys, certificates, tokens, and credential files are excluded before parsing.
- **Respects ignore files** — `.gitignore`, `.claudeignore`, `.codeindexignore`, and `.cursorignore` are all honored.
- **Index stored locally** — SQLite database in `.claude/cache/codebase-index/` (gitignored by default).
- **Optional embeddings are local by default** — External embedding APIs require explicit opt-in with warnings.
- **Secret redaction** — Snippets are scrubbed for AWS keys, private keys, JWTs, bearer tokens, and connection strings before output.

See [docs/SECURITY_MODEL.md](docs/SECURITY_MODEL.md) for the full security model and threat analysis.

## Comparison

| Feature | Manual Grep/Read | Cursor Indexing | Aider repo-map | codebase-index |
|---|---|---|---|---|
| Symbol awareness | No | Yes | No | Yes |
| Result ranking | No | Yes | No | Yes |
| Token-efficient | No | Yes | Partial | Yes |
| Local-first | Yes | Yes | Yes | Yes |
| No network | Yes | Yes | Yes | Yes |
| Works with Claude Code | Manual | No | No | Native (Skill) |
| Open source | N/A | No | Yes | Yes (MIT) |
| Dependency graph | No | Partial | No | Planned |
| Secret redaction | No | No | No | Yes |

**Honest positioning:**

- This is **not** a full IDE or a replacement for Cursor.
- This is **not** a cloud service — it's local-first.
- This **is** a local retrieval layer that makes Claude Code smarter about finding the right files.

See [docs/COMPARISON.md](docs/COMPARISON.md) for a detailed comparison.

## Benchmark Results

Measured on `sample_repo` (Python + TypeScript + Markdown fixture, 5 simple queries):

| Metric | Value |
|---|---|
| Cold indexed search | ~1ms |
| Warm indexed search | ~1ms |
| Index build time | ~86ms |
| Database size | 4.0 KB |
| Output compression | 11.8x smaller output vs grep |
| Top-3 recall | 100% |

> **Note:** Warm indexed search: ~1ms on test fixture. Real repos: expect 5-50ms depending on size and query complexity.

## Repository Layout

```
├── skill/              # Claude Code Skill (SKILL.md, scripts, examples)
├── skills/             # Plugin skill (byte-identical copy of skill/)
├── src/codebase_index/ # Python package (CLI, indexer, retrieval, storage)
├── docs/               # Documentation (architecture, schema, security, FAQ)
├── examples/           # Sample queries, retrieval output, demo project
├── tests/              # Test suite with fixture repositories
├── bin/                # Plugin CLI wrappers (cbx, codebase-index)
├── scripts/            # Bootstrap scripts (bootstrap.sh, bootstrap.ps1)
├── hooks/              # Plugin hooks (hooks.json)
├── .claude-plugin/     # Plugin manifest + marketplace catalog
├── .github/            # Issue templates, CI workflows, PR template
├── README.md           # This file
├── LICENSE             # MIT License
├── CHANGELOG.md        # Release history
├── CONTRIBUTING.md     # Contributor guide
├── SECURITY.md         # Security policy
├── ROADMAP.md          # Development milestones
├── requirements.lock   # Pinned install spec for bootstrap
└── pyproject.toml      # Package configuration
```

## Configuration

Create `.codeindex.json` in your project root:

```json
{
  "index": {
    "max_file_bytes": 1048576,
    "chunk_size": 500,
    "chunk_overlap": 50
  },
  "embeddings": {
    "backend": "noop",
    "allow_external": false
  }
}
```

### Ignore Files

- `.codeindexignore` — Tool-specific ignore patterns (highest priority)
- `.gitignore` — Standard git ignore patterns
- `.claudeignore` — Claude-specific ignore patterns

### Cache Location

```
.claude/cache/codebase-index/
├── index.sqlite   # SQLite database with FTS5
└── config.json    # Resolved configuration
```

## Claude Code Integration

The skill is defined in [`skill/SKILL.md`](skill/SKILL.md) with YAML frontmatter for automatic selection.

### Example `.claude/CLAUDE.md`

```markdown
## Codebase Questions

Before answering any question about this project's code:
1. Use the codebase-index skill to search the local index first.
2. Read only the recommended line ranges — do not scan entire files.
3. Answer with file:line citations.
```

### Optional Hooks

Configure automatic index updates in `.codeindex.json`:

```json
{
  "hooks": {
    "post_tool_use": {
      "enabled": true,
      "events": ["Write", "Edit"],
      "command": "codebase-index update --quiet"
    }
  }
}
```

See [skill/examples/](skill/examples/) for full examples.

## Keywords

`codebase-index` is a local-first Claude Code Skill for codebase indexing, semantic code search, token-efficient context retrieval, AST-based symbol search, and Cursor-like project awareness inside Claude Code. It provides hybrid code search combining SQLite FTS5 lexical search, Tree-sitter symbol extraction, and optional vector embeddings — all running locally with no network by default.

## FAQ

### Is this a Cursor replacement?

No. `codebase-index` is not a replacement for Cursor or any IDE. It is a **local retrieval layer** for Claude Code that provides Cursor-like codebase awareness. You still use Claude Code as your primary interface; this skill makes it smarter about finding the right files.

### Does it send my code anywhere?

No. By default, `codebase-index` is completely local-first and offline. All indexing, storage, and search happen on your machine. External embeddings are opt-in only and require explicit configuration.

### Does it work without embeddings?

Yes. The default configuration disables embeddings entirely (`backend = "noop"`). Search uses SQLite FTS5, Tree-sitter symbol extraction, path matching, and graph expansion. Embeddings are an optional enhancement.

### Does it support large repositories?

Yes. The index is incremental — only changed files are re-indexed. SQLite with FTS5 handles large datasets efficiently. Generated files, dependencies, and binaries are excluded automatically.

### Why not just use Grep?

Grep returns all matches with no ranking, no symbol awareness, and no context about related files. `codebase-index` combines lexical search with symbol extraction and graph expansion to return **ranked, contextual results** with specific line ranges to read.

### Why not MCP?

MCP is a great standard and a bridge is planned (M8 on the roadmap). However, the Claude Code Skill interface is simpler and more direct for this use case. The MCP bridge will be an **optional** addition.

### Can I use it with other agents?

Yes. While optimized for Claude Code, the CLI is agent-agnostic. Any agent that can run shell commands can use `codebase-index`. JSON output (`--json`) is parseable by any tool.

### How do I reset the index?

```bash
codebase-index clean
# Or manually: rm -rf .claude/cache/codebase-index/
codebase-index index
```

## Contributing

We welcome contributions! See [CONTRIBUTING.md](CONTRIBUTING.md) for the full guide.

Quick start:

```bash
git clone https://github.com/<OWNER>/claude-code-codebase-index-skill.git
cd claude-code-codebase-index-skill
pip install -e ".[dev]"
pytest
ruff check src/ tests/
```

## Roadmap

See [ROADMAP.md](ROADMAP.md) for the full milestone plan.

| Milestone | Status | Description |
|---|---|---|
| M0 | ✅ Done | Repository packaging |
| M1 | ✅ Done | SQLite + FTS5 index |
| M2 | ✅ Done | Tree-sitter symbol extraction |
| M3 | Planned | Hybrid retrieval |
| M4 | Planned | Graph expansion |
| M5 | ✅ Done | Token-budgeted retrieval packets |
| M6 | ✅ Done | Optional local embeddings |
| M7 | ✅ Done | Claude Code Skill packaging |
| M7.5 | ✅ Done | One-command plugin install |
| M8 | Planned | Hooks + watch mode |
| M9 | Planned | Public release |

## License

[MIT](LICENSE)
