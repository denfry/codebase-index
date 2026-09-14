# FAQ

`codebase-index` is a local-first codebase indexing tool that gives Claude Code,
Codex CLI, and OpenCode Cursor-like code search without sending source to the cloud.
This page answers the most common questions about installing, running, and trusting it.

## How do I install codebase-index?

`codebase-index` is published on **PyPI**. Install it in one command with `pip`
or `pipx` (isolated):

```bash
pip install codebase-index        # or: pipx install codebase-index
```

To pin an exact version: `pip install codebase-index==1.9.0`. To try an unreleased
commit, install from git: `pip install "codebase-index @ git+https://github.com/denfry/codebase-index.git@main"`.

Then run `codebase-index init` inside your project and `codebase-index index` to build
the first index. In Claude Code you can instead install the plugin
(`/plugin install codebase-index@codebase-index`), which provisions an isolated venv on
first run. See [QUICKSTART.md](QUICKSTART.md) and [INSTALLATION.md](INSTALLATION.md) for
every install path.

## Is this a Cursor replacement?

No. `codebase-index` is not a replacement for Cursor or any IDE. It is a **local retrieval layer** for Claude Code, Codex CLI, OpenCode, and other terminal agents. You still use your AI coding agent as the primary interface; this tool makes it better at finding the right files.

## Does it send my code anywhere?

No. By default, `codebase-index` is completely local-first and offline. All indexing, storage, and search happen on your machine. The only exception is if you explicitly enable external embeddings in your configuration, which requires:

1. Setting `embeddings.allow_external = true`
2. Providing an API key via environment variable
3. Acknowledging warnings from `doctor` and `index`

Without all three, no code leaves your machine.

## Does it work without embeddings?

Yes. The default configuration disables embeddings entirely (`backend = "noop"`). Search uses:

- SQLite FTS5 for full-text lexical search
- Tree-sitter for symbol extraction and matching
- Path-based search for file location queries
- Dependency graph expansion for related files

Embeddings are an optional enhancement that can improve recall for semantic queries.

## Does it support large repositories?

Yes. The index is incremental — only changed files are re-indexed. The SQLite database handles large datasets efficiently with FTS5 virtual tables. However:

- Initial indexing of very large repositories (100K+ files) may take several minutes
- The index size scales with the number of source files (not dependencies or generated files, which are excluded)
- You can configure `max_file_bytes` and use `.codeindexignore` to limit scope

## Why not just use Grep?

Grep is great for exact string matching but has limitations:

- **No symbol awareness** — Grep can't distinguish a function definition from a call
- **No ranking** — Grep returns all matches with no relevance ordering
- **No context** — Grep doesn't know which files are related or what to read next
- **Token-inefficient** — Claude would need to read many irrelevant matches

`codebase-index` combines lexical search with symbol extraction, path matching, and graph expansion to return **ranked, contextual results** with specific line ranges to read.

## Does it support MCP?

Yes. Run:

```bash
codebase-index mcp --root /path/to/repo
```

The stdio MCP server exposes eleven tools (`src/codebase_index/mcp/server.py`):

- `healthcheck`, `index_stats`
- `search_code`, `explain_code`, `find_symbol`, `find_refs`
- `impact_of`, `impact_of_diff`
- `architecture_overview`, `path_between`, `describe_symbol`

See [MCP.md](MCP.md) for schema and client config templates.

## Can I use it with other agents?

Yes. The CLI is agent-agnostic:

- Any agent that can run shell commands can use `codebase-index`
- JSON output (`--json`) is parseable by any tool
- `init` can write setup files for Claude Code, Codex CLI, and OpenCode
- MCP clients can use `codebase-index mcp --root <repo>`

## How do I reset the index?

```bash
# Reset the index database (default — keeps resolved config and skill backups)
codebase-index clean

# Wipe the whole per-project cache directory
codebase-index clean --all

# Or manually
rm -rf .claude/cache/codebase-index/

# Rebuild from scratch
codebase-index index
```

`clean` never touches the installed skill (it lives in `.claude/skills/`, not the
cache). Add `--yes` to skip the confirmation prompt in scripts.

## What languages are supported?

Tier-A symbol extraction currently covers:

- Python
- JavaScript / JSX
- TypeScript / TSX
- Java
- Go
- Rust
- C
- C++
- C#
- Ruby
- PHP
- Kotlin

Lua exercises the Tier-B generic Tree-sitter path. Markdown, JSON, YAML, TOML,
SQL, and other text/config files still get FTS5 lexical chunks, but not
schema-aware code-intelligence extraction yet.

Important gaps for AI codebase search include Swift, Dart, Scala, Elixir,
Clojure, Objective-C, Vue/Svelte component parsing, SQL schema-aware parsing,
Terraform, Dockerfile, Gradle/Maven/npm config files, migrations, routes, CI,
and infrastructure files.

## Where is the index stored?

The index is stored in:

```
.claude/cache/codebase-index/index.sqlite
```

This directory is in the default `.gitignore` and should never be committed.

## Can I exclude specific directories?

Yes. Use any of these methods:

1. **`.codeindexignore`** — Tool-specific ignore file (highest priority)
2. **`.gitignore`** — Standard git ignore file
3. **`.claudeignore`** — Claude-specific ignore file
4. **Configuration** — `extra_ignore` patterns in
   `.claude/cache/codebase-index/config.json` (written by `init`; see
   `examples/config.example.json`)

## Is it production-ready?

Yes, with the caveats below. The current line is **1.9.x** (see
[CHANGELOG.md](../CHANGELOG.md)). It ships:

- Hybrid FTS5 / path / symbol retrieval with optional local embeddings; rank fusion that
  scores cross-retriever agreement at file level; evidence-calibrated source priors,
  lexical expansion, and fuzzy identifier fallback (1.8.0, 1.9.0).
- Tree-sitter symbols for twelve Tier-A languages; import / call / reference /
  inheritance graph with per-edge confidence; `refs`, `path`, `describe`,
  `architecture`, `impact`, and diff-aware `diff-impact` (1.5.0, 1.7.0).
- Token-budgeted, skeletonized retrieval packets with bounded `recommended_reads`.
- CLI, Claude Code skill and plugin, Codex CLI and OpenCode resources, and a stdio MCP
  server sharing one service layer.
- A reproducible retrieval evaluation with leak-free git-derived ground truth,
  multi-corpus pooling, and paired significance tests; every 1.9.0 ranking change had
  to pass it.

Known gaps: the graph is import/call/reference-level rather than framework-aware, MCP
client configs are templates not yet verified against each client release, and there
is no LLM-driven task-level evaluation yet. See [ROADMAP.md](ROADMAP.md).

## How does it differ from Aider's repo-map, Cursor, or plain grep?

Grep is exact text matching with no ranking, symbol awareness or read plan. A repo map
is a query-independent context blob fed to one agent. Cursor is an IDE with its own
proprietary index. `codebase-index` is a queryable, local, scriptable retrieval and
graph layer any shell-capable or MCP agent can call. The trade-offs, including when
each alternative is the better choice, are in [COMPARISON.md](COMPARISON.md); the
measured comparison against grep-style and repo-map-style baselines is in
[BENCHMARKS.md](BENCHMARKS.md).

## How do I contribute?

See [CONTRIBUTING.md](../CONTRIBUTING.md) for development setup, testing, and PR guidelines.
