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

### M2 — Tree-sitter Symbol Extraction ✅
- AST-based symbol extraction, now expanded beyond the original Python/JavaScript/TypeScript
  set to the Tier-A languages listed in `docs/LANGUAGES.md`.
- Symbol-aligned chunking with gap windows.
- `symbol` and `refs` commands for intra-file symbol lookup.
- **Exit:** `codebase-index symbol "AuthService"` returns symbol definitions and references.

### M3 — Hybrid Retrieval ✅
- Combined search: path match + symbol match + FTS5 + optional vector search.
- Reciprocal Rank Fusion (RRF) for result merging.
- Confidence scoring and fallback suggestions.
- **Exit:** `codebase-index search "query"` returns ranked results from multiple retrievers.

### M4 — Graph Expansion ✅
- Dependency, import, call, and inheritance edge extraction.
- Graph-based result expansion (related files, callers, callees).
- `impact` command for blast radius analysis.
- **Exit:** `codebase-index impact "src/auth/AuthService.ts"` shows affected files and symbols.

### M5 — Token-Budgeted Retrieval Packets ✅
- Ranked retrieval packets with file paths, line ranges, snippets, and "next files to read".
- Token budget enforcement (configurable max output size).
- Compact Markdown and JSON output formats.
- **Exit:** Claude reads only the recommended line ranges, not entire files.

### M6 — Optional Local Embeddings ✅
- `sqlite-vec` integration for vector similarity search.
- Local embedding models (sentence-transformers) as default.
- External embedding APIs behind explicit opt-in with warnings.
- **Exit:** Semantic queries improve recall when embeddings are enabled.

### M7 — Multi-CLI skill packaging ✅
- `init --target claude|codex|opencode|auto|all`.
- Claude Code skill, Codex instructions/resources, OpenCode command/agent files.
- **Exit:** AI CLI setup can be generated from the package without hand-copying files.

### M8 — Optional Hooks + Watch Mode ✅
- Post-tool-use hook for automatic index updates.
- `--with-hooks` flag and hook configuration.
- `doctor` reports enabled hooks and their status.
- **Exit:** Index stays fresh automatically after file edits.

### M9 — Public Release ✅
- Comprehensive test suite with coverage targets.
- Performance benchmarks on medium-sized repositories.
- GitHub release with tagged version.
- Release pipeline readiness for PyPI trusted publishing.
- Awesome-list submissions (Claude Code skills, AI coding tools).
- **Exit:** tagged GitHub install works on a clean machine.

### M10 — Distribution hardening
- Publish `codebase-index` to PyPI after trusted publishing is configured and verified.
- Verify `pipx install codebase-index`, `uvx codebase-index init`, and `uv tool install codebase-index`.
- Add Homebrew tap formula: `brew install denfry/tap/codebase-index`.
- Publish signed release checksums and SBOMs for release artifacts.
- **Exit:** users do not need GitHub URL installs for the standard path, and artifacts have a clear supply-chain story.

### M11 — First-class MCP server ✅
- Model Context Protocol wrapper for external tool integration.
- MCP server exposing `healthcheck`, `search_code`, `find_symbol`, `find_refs`,
  `impact_of`, `explain_code`, and `index_stats`.
- Versioned JSON schema and golden tests for every tool output.
- **Exit:** `codebase-index mcp --root <repo>` can be used by any MCP-compatible client.

### M11.5 — MCP hardening
- Ready-to-copy configs verified against Claude Desktop, Claude Code, Cursor, VS Code, Zed,
  and Windsurf current versions.
- Golden snapshots for every tool output.
- Paging or progressive result support for large repositories.

### M12 — Public benchmark suite ✅
- Shipped reproducible public benchmark script: `tests/benchmark_public.py`.
- Retrieval quality: Recall@1/3/5, MRR, nDCG.
- Agent usefulness: answer-correctness proxy on the public fixture.
- Token economy versus grep-window baseline.
- Language-specific results, freshness latency after edits, graph tasks, and scale counters.

### M12.5 — Real-repo benchmark expansion
- 10k, 100k, 1M LOC repository targets.
- Real-world Python, TypeScript, Java, Go, Rust, C#, PHP repos.
- Human-reviewed answer correctness on real codebase questions.
- Token economy versus repo-map style context and vanilla agent exploration.
- Framework graph tasks: route -> handler -> service -> DB, migrations, config consumers, CI/infra.

### M13 — Code intelligence graph
- Framework-aware typed edges beyond import/call/reference.
- Routes, tests/fixtures, config consumers, migrations, event flows, DI wiring,
  frontend component flows, and error/log-message traces.
- Edge confidence and resolver provenance so agents can distinguish precise
  edges from heuristics.

---

See [CHANGELOG.md](CHANGELOG.md) for released versions and their changes.
