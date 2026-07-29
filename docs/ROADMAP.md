# Roadmap

`codebase-index` is becoming the evidence layer between a coding agent and a
repository: **Find implementations, Trace behavior, Predict change impact.**

This document separates shipped capability from forward work. Roadmap entries
are not product claims until they appear under `[Unreleased]` or a tagged
release in `CHANGELOG.md`.

## Shipped foundation

### Find

- Local SQLite FTS5, path, and symbol retrieval.
- Hybrid ranking and optional embeddings.
- Intent-aware `search` and `explain`.
- Token-budgeted, skeletonized snippets and exact recommended reads.
- Freshness, confidence, pagination, and targeted fallbacks.

### Trace

- Tree-sitter symbols across the documented language tiers.
- Import, call, reference, and inheritance edges.
- `refs`, `path`, `describe`, and architecture community analysis.
- Human HTML graphs plus GraphML, DOT, and Neo4j exports.
- Edge confidence: `extracted`, `inferred`, and `ambiguous`.

### Predict

- Directional, depth-bounded `impact` analysis.
- Diff-aware impact aggregation over tracked working-tree changes.
- Graph-coverage honesty for partially supported languages.
- Diagnostics that surface stale indexes and incomplete graph extraction.

### Delivery and trust

- CLI, Claude Code plugin/skill, Codex CLI, OpenCode, and stdio MCP.
- Shared CLI/MCP service layer and versioned MCP payloads.
- Local and network-free default path with no telemetry.
- Secret exclusion and output redaction.
- Incremental update, watch hooks, doctor, skill update, and rollback.
- PyPI and `pipx` installation.

## Now — prove and simplify

The current priority is to make existing power obvious, measurable, and easy to
invoke.

- [ ] Publish 10k and 100k LOC public-repository benchmark runs with raw logs.
- [ ] Add task-level agent evaluation: success rate, tokens, files read, time,
      and citation correctness.
- [ ] Verify MCP setup against current releases of each documented client.
- [ ] Add progressive/paged MCP retrieval for large repositories.
- [ ] Complete `uvx` and clean-machine install verification on every CI OS.
- [ ] Publish signed checksums and an SBOM with releases.

## Next — task-native context

- [ ] Add a high-level task-context packet that groups implementation,
      configuration, tests, and dependencies under one token budget.
- [x] Add diff-aware file impact analysis over tracked working-tree changes.
- [ ] Extend diff impact from files to exact changed symbols and line spans.
- [ ] Rank likely affected tests separately from general dependents.
- [ ] Surface public API and configuration-contract changes.
- [ ] Produce a concise evidence summary suitable for code review agents.

These features must compose existing retrieval and graph primitives instead of
creating a second ranking implementation.

## Then — framework-aware traces

- [ ] Typed route → handler → service → repository → model edges.
- [ ] Test → implementation edges.
- [ ] Configuration → consumer edges.
- [ ] Migration → model edges.
- [ ] Dependency-injection and event/queue registration edges.
- [ ] Source spans, extractor identity, and confidence on every typed edge.

Framework edges ship behind a hand-labelled graph benchmark. Unsupported
framework wiring must remain clearly marked as partial rather than silently
treated as absent.

## Later

- Additional language and config/IaC extraction where real usage justifies it.
- Faster indexing and lower-memory builds for very large single repositories.
- Homebrew or equivalent package-manager distribution.
- Multi-root workspace context if it can preserve the local-first trust model.

Org-wide hosted search, an IDE, autonomous code editing, and opaque cloud
indexing are not current product goals.

## Quality gates

A roadmap item is ready to ship only when:

1. CLI and MCP behavior share the same service implementation.
2. JSON contracts have regression tests.
3. retrieval or graph changes pass a labelled evaluation with no unexplained
   quality regression;
4. security gates and the network-free default remain intact;
5. documentation distinguishes measured capability from inference;
6. installed skill copies pass `scripts/sync_skill_copies.py --check`.
