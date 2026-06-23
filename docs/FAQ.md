# FAQ

`codebase-index` is a local-first codebase indexing tool that gives Claude Code,
Codex CLI, and OpenCode Cursor-like code search without sending source to the cloud.
This page answers the most common questions about installing, running, and trusting it.

## How do I install codebase-index?

`codebase-index` is distributed from **GitHub, not PyPI**. Install it in one command
with `pipx` (isolated) or `pip`, pinned to a release tag for reproducibility:

```bash
pipx install "git+https://github.com/denfry/codebase-index.git@v1.5.0"
```

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

The stdio MCP server exposes:

- `healthcheck`
- `search_code`
- `find_symbol`
- `find_refs`
- `impact_of`
- `explain_code`
- `index_stats`

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
4. **Configuration** — `extra_ignore` patterns in `.codeindex.json`

## Is it production-ready?

Yes — `codebase-index` is released as **v1.5.0**. The core indexing and search
functionality is implemented and tested. The current `1.5.0` package includes:

- Hybrid FTS/path/symbol/vector retrieval
- Import/call/reference graph expansion and `impact`
- Optional local embeddings, with external embeddings gated behind explicit opt-in
- Hooks and watch mode for freshness
- Multi-CLI setup for Claude Code, Codex CLI, and OpenCode

Known gaps: the public benchmark suite is still small, the MCP server needs
verified client-specific docs and progressive/paged results, and the graph is
closer to an import/call/reference graph than a full framework-aware code
intelligence graph.

See [ROADMAP.md](../ROADMAP.md) for the full milestone plan.

## How do I contribute?

See [CONTRIBUTING.md](../CONTRIBUTING.md) for development setup, testing, and PR guidelines.
