# Roadmap

`codebase-index` is developed in milestone-driven slices. Each milestone delivers a runnable, testable feature.

## Milestones

### M0 — Repository Packaging ✅
- Polished README, documentation, badges, issue templates, CI workflows.
- MIT license, changelog, code of conduct, contributing guide.
- Claude Code Skill directory structure.
- **Exit:** Repository is ready for public listing and awesome-list submissions.

### M1 — SQLite + FTS5 Index ✅
- SQLite database with FTS5 virtual table for full-text search.
- File discovery with layered ignore rules (`.gitignore`, `.codeindexignore`, built-in denylist).
- Incremental indexing with file hash tracking.
- **Exit:** `codebase-index index` populates the database; secrets and binaries are excluded.

### M2 — Tree-sitter Symbol Extraction
- AST-based symbol extraction for Python, JavaScript, TypeScript.
- Symbol-aligned chunking with gap windows.
- `symbol` and `refs` commands for intra-file symbol lookup.
- **Exit:** `codebase-index symbol "AuthService"` returns symbol definitions and references.

### M3 — Hybrid Retrieval
- Combined search: path match + symbol match + FTS5 + optional vector search.
- Reciprocal Rank Fusion (RRF) for result merging.
- Confidence scoring and fallback suggestions.
- **Exit:** `codebase-index search "query"` returns ranked results from multiple retrievers.

### M4 — Graph Expansion
- Dependency, import, call, and inheritance edge extraction.
- Graph-based result expansion (related files, callers, callees).
- `impact` command for blast radius analysis.
- **Exit:** `codebase-index impact "src/auth/AuthService.ts"` shows affected files and symbols.

### M5 — Token-Budgeted Retrieval Packets
- Ranked retrieval packets with file paths, line ranges, snippets, and "next files to read".
- Token budget enforcement (configurable max output size).
- Compact Markdown and JSON output formats.
- **Exit:** Claude reads only the recommended line ranges, not entire files.

### M6 — Optional Local Embeddings
- `sqlite-vec` integration for vector similarity search.
- Local embedding models (sentence-transformers) as default.
- External embedding APIs behind explicit opt-in with warnings.
- **Exit:** Semantic queries improve recall when embeddings are enabled.

### M7 — Optional Hooks
- Post-tool-use hook for automatic index updates.
- `--with-hooks` flag and hook configuration.
- `doctor` reports enabled hooks and their status.
- **Exit:** Index stays fresh automatically after file edits.

### M8 — Optional MCP Bridge
- Model Context Protocol wrapper for external tool integration.
- MCP server exposing `search`, `symbol`, `refs`, `impact` as tools.
- Compatible with Claude Desktop, Cursor, and other MCP clients.
- **Exit:** `codebase-index` can be used as an MCP tool by any MCP-compatible client.

### M9 — Public Release
- Comprehensive test suite with coverage targets.
- Performance benchmarks on medium-sized repositories.
- PyPI package publication.
- GitHub release with tagged version.
- Awesome-list submissions (Claude Code skills, AI coding tools).
- **Exit:** `pipx install codebase-index` works on a clean machine.

---

See [CHANGELOG.md](CHANGELOG.md) for released versions and their changes.
