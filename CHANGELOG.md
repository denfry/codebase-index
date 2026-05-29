# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- SQLite + FTS5 storage layer with schema migration support
- Tree-sitter symbol extraction for Python, JavaScript, TypeScript
- Hybrid retrieval: FTS5 lexical search + symbol match + path match
- Token-budgeted retrieval packets with ranked results
- Secret redaction for snippets (private keys, AWS keys, assigned secrets)
- Path-based ignore matching (`.gitignore`, `.codeindexignore`, `.claudeignore`)
- Built-in denylist for secrets, binaries, generated files, dependency directories
- Incremental indexing with file hash tracking
- CLI commands: `init`, `index`, `search`, `symbol`, `refs`, `impact`, `stats`, `doctor`, `clean`
- Claude Code Skill (`skill/SKILL.md`) for automatic skill selection
- JSON and Markdown output renderers
- Pydantic config models with project root discovery
- Test suite with fixture-based sample repository

### Planned
- Dependency and call graph expansion
- Optional local embeddings with `sqlite-vec`
- Optional hooks for post-tool-use auto-update
- MCP bridge for external tool integration
- Live file watching for incremental reindexing

## [0.1.0] - 2026-05-29

### Added
- Initial repository scaffolding
- Architecture design and database schema
- Module skeletons for all core components
- Claude Code Skill draft
- Test fixtures and initial test suite
