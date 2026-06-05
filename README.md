# codebase-index: Local Codebase Indexing for AI Coding Agents

`codebase-index` is a local-first codebase indexing tool that helps Claude Code,
Codex CLI, OpenCode, and other AI coding agents find relevant files, symbols, and
references without scanning an entire repository.

[![License](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Python](https://img.shields.io/badge/python-3.11+-blue.svg)](https://www.python.org/)
[![CI](https://github.com/denfry/codebase-index/actions/workflows/ci.yml/badge.svg)](https://github.com/denfry/codebase-index/actions)
[![Claude Code Skill](https://img.shields.io/badge/Claude%20Code%20Skill-yes-green.svg)](skill/SKILL.md)
[![Codex CLI](https://img.shields.io/badge/Codex%20CLI-supported-green.svg)](#which-ai-clis-does-codebase-index-support)
[![OpenCode](https://img.shields.io/badge/OpenCode-supported-green.svg)](#which-ai-clis-does-codebase-index-support)
[![MCP](https://img.shields.io/badge/MCP-stdio%20server-green.svg)](docs/MCP.md)
[![Local First](https://img.shields.io/badge/local--first-yes-green.svg)](#safety-and-privacy)
[![No Telemetry](https://img.shields.io/badge/no%20telemetry-yes-green.svg)](#safety-and-privacy)
[![No Network By Default](https://img.shields.io/badge/no%20network%20by%20default-yes-green.svg)](#safety-and-privacy)
[![SQLite](https://img.shields.io/badge/database-SQLite-blue.svg)](docs/DATABASE_SCHEMA.md)
[![Tree-sitter](https://img.shields.io/badge/parsing-Tree--sitter-orange.svg)](docs/ARCHITECTURE.md)

## What Is codebase-index?

**codebase-index is a private, offline retrieval layer for AI code search.** It
builds a SQLite index of your repository, extracts symbols with Tree-sitter,
ranks matches with hybrid retrieval, and returns compact file:line ranges that
an AI coding agent can read instead of opening broad file sets.

Use it when you want Cursor-like codebase awareness in terminal-based AI tools
while keeping source code, snippets, and search metadata on your machine.

## Start Here (First Time on GitHub)

If you are opening this repository for the first time, follow this order:

1. [Quick Start (5 minutes)](docs/QUICKSTART.md)
2. [Installation Guide](docs/INSTALLATION.md)
3. [Benchmarks](docs/BENCHMARKS.md)
4. [How the skill works](skill/SKILL.md)
5. [MCP server](docs/MCP.md)
6. [FAQ](docs/FAQ.md)

If you only need the shortest path, run:

```bash
pip install "codebase-index @ git+https://github.com/denfry/codebase-index.git@v1.2.0"
cd your-project
codebase-index init            # prompts for Claude Code / Codex CLI / OpenCode
codebase-index index
codebase-index search "where is authentication implemented?"
```

## Project Status

**`1.2.0` is released.** The current release includes repository discovery,
SQLite FTS5 storage, Tree-sitter symbols and references, hybrid ranking, graph
impact analysis, token-budgeted retrieval packets, optional local embeddings,
hooks/watch support, multi-CLI installation, MCP server support, and a tested
GitHub-only `pipx` install path.

The `1.2.0` release adds HTML graph export, auto-indexing search commands, and
updated skill resources while keeping GitHub-only distribution and requiring Python 3.11 or newer.
See [CHANGELOG.md](CHANGELOG.md) and
[docs/ROADMAP.md](docs/ROADMAP.md).

MCP is now available as a stdio server via `codebase-index mcp --root <repo>`.
It exposes `healthcheck`, `search_code`, `find_symbol`, `find_refs`,
`impact_of`, `explain_code`, and `index_stats`; see [docs/MCP.md](docs/MCP.md).

```
You:   "Where is user authentication implemented?"
Agent: searches local index (symbols + FTS5 + graph)
       reads only 3 ranked files instead of scanning 60
       answers with citations: src/auth/AuthService.ts:12-148
```

---

## How Do I Install codebase-index?

For most users, install the package from the tagged GitHub release and run
`init` inside the repository you want to index:

```bash
pip install "codebase-index @ git+https://github.com/denfry/codebase-index.git@v1.2.0"
cd your-project
codebase-index init            # choose Claude Code, Codex CLI, OpenCode, or all
codebase-index index
```

In a non-interactive script, pass a target explicitly:

```bash
codebase-index init --target auto      # install into detected AI CLIs
codebase-index init --target codex     # write AGENTS.md + Codex resources
codebase-index init --target claude    # write .claude/skills/codebase-index
codebase-index init --target opencode  # write OpenCode command + agent files
```

### Install as a Claude Code plugin

One command in Claude Code:

```
/plugin marketplace add denfry/codebase-index
/plugin install codebase-index@codebase-index
```

Or just ask: "install the codebase-index plugin".

**What happens on first run:** when a session starts, a `SessionStart` hook
(`scripts/bootstrap.sh` / `.ps1`) creates a private Python virtual environment under
`~/.claude/plugins/data/codebase-index-*/venv` and installs the pinned
`codebase-index` package (from `requirements.lock`) into it — using `uv` if present,
otherwise `python -m venv` + `pip`. It reinstalls only when the lock file changes.
Nothing is installed globally; uninstalling the plugin removes the data directory.

**Prerequisite:** Python 3.11+ on your PATH. The first install needs network access to
fetch the package; later sessions are offline. The skill builds its index on
your first codebase question, so there is no manual `index` step.

**Distribution note:** the plugin bootstrap installs the pinned requirement from
`requirements.lock`. In `1.2.0`, that lock points at the tagged GitHub release
instead of PyPI. You can override it with `CBX_INSTALL_SPEC` when testing a local
checkout or a different Git ref.

## What Problem Does codebase-index Solve?

AI coding agents struggle with large repositories when they rely on broad file
reads, grep output, or user-provided context. `codebase-index` gives those agents
a ranked local retrieval packet before they read source files.

- **Token waste** — Scanning entire files or running broad grep/glob queries burns through the context window on irrelevant content.
- **No symbol awareness** — Standard search can't distinguish a function definition from a call, or a class from a variable.
- **No ranking** — Grep returns all matches with no relevance ordering. The agent must read everything.
- **No context** — Grep doesn't know which files are related or what to read next.
- **Cloud dependency** — External code indexing services send your proprietary code to remote servers.

Developers get Cursor-like codebase awareness in Claude Code, Codex CLI, and
OpenCode without leaving the terminal or sending code to a remote indexing
service.

## How Does codebase-index Work?

`codebase-index` builds a local hybrid index that combines:

- **Symbol search** — Tree-sitter AST parsing extracts classes, functions, methods, and variables across the supported code-language set.
- **Full-text search** — SQLite FTS5 for fast lexical search across code chunks.
- **Path search** — File path matching for location-aware queries.
- **Optional semantic search** — Vector embeddings for similarity-based retrieval (opt-in, local by default).
- **Dependency graph** — Import, call, and reference edges for impact analysis and graph expansion.
- **Token-budgeted output** — Ranked retrieval packets with specific line ranges, not whole files.

The AI agent reads only the recommended files and line ranges, not the entire
repository.

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

## Installation Options

If you are new to this repo, start with [docs/QUICKSTART.md](docs/QUICKSTART.md).  
If you want all install options and troubleshooting, use [docs/INSTALLATION.md](docs/INSTALLATION.md).

**Multi-CLI installer (Claude Code + Codex CLI + OpenCode):** one command via
`install.sh` / `install.ps1` — see [docs/installer.md](docs/installer.md).

```bash
# macOS / Linux
curl -fsSL https://raw.githubusercontent.com/denfry/codebase-index/main/install.sh | sh
```
```powershell
# Windows PowerShell
irm https://raw.githubusercontent.com/denfry/codebase-index/main/install.ps1 | iex
```

### Option 1: Install from a tagged GitHub release

```bash
cd your-project
pip install "codebase-index @ git+https://github.com/denfry/codebase-index.git@v1.2.0"
codebase-index init
codebase-index index
```

### Python version compatibility

`codebase-index` requires Python 3.11 or newer.

If `codebase-index init --target opencode` fails with:

```text
ModuleNotFoundError: No module named 'importlib.resources.abc'; 'importlib.resources' is not a package
```

the `pipx` environment was likely created with an older Python version. Reinstall `codebase-index` using Python 3.11+ explicitly:

```powershell
pipx uninstall codebase-index
py -0p
pipx install --python "<path-to-python-3.11-or-newer>\python.exe" "git+https://github.com/denfry/codebase-index.git@v1.2.0"
```

For example:

```powershell
pipx install --python "C:\Users\you\AppData\Local\Programs\Python\Python312\python.exe" "git+https://github.com/denfry/codebase-index.git@v1.2.0"
```

Then run initialization again:

```powershell
codebase-index init --target opencode
codebase-index index
```


### Option 2: Install with pipx from GitHub

```bash
pipx install "git+https://github.com/denfry/codebase-index.git@v1.2.0"
cd your-project
codebase-index init --target auto
codebase-index index
```

### Option 3: Install from source

```bash
git clone https://github.com/denfry/codebase-index.git
cd codebase-index
pip install -e ".[dev]"
```

### Distribution roadmap

PyPI, `uvx`, Homebrew, signed release checksums, and SBOMs are important for a
tool that reads entire repositories, but they are not all verified as shipped in
`1.2.0`. Target install story:

```bash
uvx codebase-index init
pipx install codebase-index
brew install denfry/tap/codebase-index
```

### Verify the install

```bash
codebase-index doctor
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

## How Does Retrieval Flow Through codebase-index?

```
User question
    ↓
CLI instructions or skill
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
Agent reads only the recommended line ranges
    ↓
Answer with precise file:line citations
```

## Features

- [x] **Local-first indexing** — All data stays on your machine
- [x] **No network by default** — Zero external API calls out of the box
- [x] **Respects ignore files** — `.gitignore`, `.claudeignore`, `.codeindexignore`
- [x] **SQLite storage** — Fast, reliable, single-file database
- [x] **FTS5 lexical search** — Full-text search with code-aware tokenization
- [x] **Tree-sitter AST parsing** — Tier-A symbol extraction for Python, JavaScript, TypeScript, Java, Go, Rust, C, C++, C#, Ruby, PHP, and Kotlin; Tier-B generic extraction for code languages with a loadable grammar such as Lua
- [x] **Symbol extraction** — Classes, functions, methods, variables with line ranges
- [x] **Incremental indexing** — Only changed files are re-indexed
- [x] **Token-budgeted output** — Configurable max output size
- [x] **Secret redaction** — Masks keys, tokens, and credentials in snippets
- [x] **Optional embeddings** — Local or remote vector search (opt-in)
- [x] **Optional hooks/watch** — Auto-update index after file edits
- [x] **Multi-CLI setup** — Claude Code, Codex CLI, and OpenCode instructions
- [x] **MCP server** — stdio MCP tools for search, symbols, refs, impact, explain, health, and stats

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

## How Does codebase-index Compare?

| Feature | Manual grep/read | Cursor indexing | Aider repo-map | codebase-index |
|---|---|---|---|---|
| Symbol awareness | No | Yes | Yes, summarized repo map | Yes, queryable symbols |
| Result ranking | No | Yes | Yes, graph-ranked map | Yes, hybrid-ranked results |
| Token-efficient | No | Yes | Partial | Yes |
| Local-first | Yes | Yes | Yes | Yes |
| No network | Yes | Yes | Yes | Yes |
| Works with Claude Code | Manual | No | No | Native skill |
| Works with Codex CLI | Manual | No | No | AGENTS.md package |
| Works with OpenCode | Manual | No | No | Command + agent files |
| MCP interface | Manual | No | No | stdio MCP server |
| Open source | N/A | No | Yes | Yes (MIT) |
| Dependency graph | No | Partial | File-level graph ranking | Import/call/reference graph |
| Secret redaction | No | No | No | Yes |

**Honest positioning:**

- This is **not** a full IDE or a replacement for Cursor.
- This is **not** a cloud service — it's local-first.
- This **is** a local retrieval layer that makes AI coding agents better at finding the right files.

See [docs/COMPARISON.md](docs/COMPARISON.md) for a detailed comparison.

## Benchmark Results

There are three benchmark surfaces today:

1. **Public benchmark suite** in `tests/benchmark_public.py`: reproducible
   multi-language fixture with Recall@1/3/5, MRR, nDCG, answer-correctness proxy,
   token economy, language breakdown, freshness latency, graph tasks, and scale counters.
2. **Smoke benchmark** on `sample_repo`: validates the CLI is fast and stable on
   a tiny fixture, but it is not evidence of production retrieval quality.
3. **Honest benchmark** on a real Java repository: `tests/benchmark_honest.py`
   compares codebase-index against a disciplined `rg` + read-window baseline on
   10 realistic questions. Results are documented in
   [tests/benchmark_honest_RESULTS.md](tests/benchmark_honest_RESULTS.md).

Run the public suite:

```bash
python tests/benchmark_public.py --workdir .tmp-public-benchmark
```

Current honest benchmark headline:

| Metric | Result |
|---|---|
| Repo | 303 Java files, ~55k LOC |
| Retrieval quality | recall@3: 70% index vs 40% `rg` baseline |
| Token economy | ~13x fewer answer tokens than `rg` + 80-line windows |
| Verified language impact | Java symbols fixed from 0 to 3,543 symbols |

The public suite now has the metric framework. It still needs larger public or
documented external repos for 10k/100k/1M LOC scale claims and deeper framework
graph tasks. See [docs/BENCHMARKS.md](docs/BENCHMARKS.md).

## Repository Layout

```
├── skill/              # Source instruction package (SKILL.md, scripts, examples)
├── skills/             # Plugin skill copy
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

## Which AI CLIs Does codebase-index Support?

`codebase-index init` can install instructions for three AI coding CLIs:

| CLI | Files written by `init` | Best command |
|---|---|---|
| Claude Code | `.claude/skills/codebase-index/` | `codebase-index init --target claude` |
| Codex CLI | `AGENTS.md` + `.codex/skills/codebase-index/` | `codebase-index init --target codex` |
| OpenCode | `.opencode/commands/` + `.opencode/agents/` + resources | `codebase-index init --target opencode` |

Use `codebase-index init --target auto` to install into detected CLIs, or
`codebase-index init --target all` to write every supported integration.

### Claude Code Integration

The Claude Code skill is defined in [`skill/SKILL.md`](skill/SKILL.md) with
YAML frontmatter for automatic selection.

Example `.claude/CLAUDE.md`:

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

## FAQ

### Is this a Cursor replacement?

No. `codebase-index` is not a replacement for Cursor or any IDE. It is a
local retrieval layer for terminal AI coding agents. You still use Claude Code,
Codex CLI, OpenCode, or another agent as your primary interface.

### Does it send my code anywhere?

No. By default, `codebase-index` is completely local-first and offline. All indexing, storage, and search happen on your machine. External embeddings are opt-in only and require explicit configuration.

### Does it work without embeddings?

Yes. The default configuration disables embeddings entirely (`backend = "noop"`). Search uses SQLite FTS5, Tree-sitter symbol extraction, path matching, and graph expansion. Embeddings are an optional enhancement.

### Does it support large repositories?

Yes. The index is incremental — only changed files are re-indexed. SQLite with FTS5 handles large datasets efficiently. Generated files, dependencies, and binaries are excluded automatically.

### Why not just use Grep?

Grep returns all matches with no ranking, no symbol awareness, and no context about related files. `codebase-index` combines lexical search with symbol extraction and graph expansion to return **ranked, contextual results** with specific line ranges to read.

### Does it support MCP?

Yes. Run `codebase-index mcp --root <repo>` to expose the local index over stdio
MCP. See [docs/MCP.md](docs/MCP.md) for tools and client config templates.

### Can I use it with other agents?

Yes. The CLI is agent-agnostic. Any agent that can run shell commands can use
`codebase-index`, and JSON output (`--json`) is parseable by other tools.

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
git clone https://github.com/denfry/codebase-index.git
cd codebase-index
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
| M3 | ✅ Done | Hybrid retrieval |
| M4 | ✅ Done | Graph expansion |
| M5 | ✅ Done | Token-budgeted retrieval packets |
| M6 | ✅ Done | Optional local embeddings |
| M7 | ✅ Done | Claude Code Skill packaging |
| M7.5 | ✅ Done | One-command plugin install |
| M8 | ✅ Done | Hooks + watch mode |
| M9 | ✅ Done | Public release |

## License

[MIT](LICENSE)
