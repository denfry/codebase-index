# FAQ: codebase-index for AI Coding Agents

`codebase-index` is a local-first codebase indexing tool that gives Claude Code,
Codex CLI, and OpenCode Cursor-like code search without sending source to the cloud.
This page answers the most common questions about installing, running, and trusting it.

## How do I install codebase-index?

`codebase-index` is distributed from **GitHub, not PyPI**. Install it in one command
with `pipx` (isolated) or `pip`, pinned to a release tag for reproducibility:

```bash
pipx install "git+https://github.com/denfry/codebase-index.git@v1.1.0"
```

Then run `codebase-index init` inside your project and `codebase-index index` to build
the first index. In Claude Code you can instead install the plugin
(`/plugin install codebase-index@codebase-index`), which provisions an isolated venv on
first run. See [QUICKSTART.md](QUICKSTART.md) and [INSTALLATION.md](INSTALLATION.md) for
every install path.

## Is this a Cursor replacement?

No. `codebase-index` is not a replacement for Cursor or any IDE. It is a **local retrieval layer** for Claude Code that provides Cursor-like codebase awareness. You still use Claude Code (or any AI coding agent) as your primary interface; this skill makes it smarter about finding the right files.

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

## Why not MCP?

MCP (Model Context Protocol) is a great standard for tool integration, and an MCP bridge is planned (M10 on the roadmap). However:

- MCP adds complexity for a tool that works well as a local CLI
- Not all AI agents support MCP yet
- The Claude Code Skill interface is simpler and more direct for this use case
- The MCP bridge will be an **optional** addition, not a replacement

## Can I use it with other agents?

Yes. While optimized for Claude Code, the CLI is agent-agnostic:

- Any agent that can run shell commands can use `codebase-index`
- JSON output (`--json`) is parseable by any tool
- The skill is specific to Claude Code, but the underlying CLI is not

Future plans include an MCP server (M10) for broader agent compatibility.

## How do I reset the index?

```bash
# Delete the cache
codebase-index clean

# Or manually
rm -rf .claude/cache/codebase-index/

# Rebuild from scratch
codebase-index index
```

## What languages are supported?

Currently supported for symbol extraction:

- Python (full support)
- JavaScript (full support)
- TypeScript (full support)

All languages are supported for FTS5 lexical search regardless of language support.

Symbol extraction for additional languages (Go, Java, Rust, C/C++, Ruby, PHP) is planned.

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

Yes — `codebase-index` is released as **v1.1.0**. Indexing, hybrid search, Tree-sitter
symbols and references, graph impact analysis, optional local embeddings, post-tool-use
hooks, and watch mode are all implemented, tested, and shipped:

- Graph expansion / impact analysis — shipped
- Optional local embeddings (`sqlite-vec`) — shipped (opt-in)
- Post-tool-use hooks + watch mode — shipped
- MCP bridge — planned, not yet released

See [CHANGELOG.md](../CHANGELOG.md) for released versions and [ROADMAP.md](../ROADMAP.md)
for the full milestone plan.

## How do I contribute?

See [CONTRIBUTING.md](../CONTRIBUTING.md) for development setup, testing, and PR guidelines.
