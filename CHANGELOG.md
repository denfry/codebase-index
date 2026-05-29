# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2026-05-29

### Added
- Local-first codebase index exposed as a Claude Code Skill + `codebase-index` CLI.
- `index` / `update`: discovery with layered ignore rules, secret/binary/size gates, and
  incremental re-index (M1, M8).
- `search`: FTS5 lexical + hybrid retrieval with RRF fusion, intent detection, token budgeting,
  confidence scoring, and fallback suggestions (M2, M4).
- `symbol` / `refs`: tree-sitter symbol extraction and reference lookup across supported languages
  with line-based fallback (M3).
- `impact`: dependency/call-graph blast-radius analysis (M5).
- Optional, opt-in local embeddings / `sqlite-vec` vector backend, gated behind `embeddings.enabled`
  and SECURITY.md rules (M6).
- `init`: materializes the bundled skill template, resolved `config.json`, and `.gitignore` rules;
  end-to-end freshness contract so the skill triggers `update`/`index` (M7).
- Hooks example + `watch` mode for keeping the index fresh without blocking the edit loop (M8).
- `doctor`, `stats`, `clean` diagnostics/maintenance commands.

[Unreleased]: https://github.com/denfry/codebase-index/compare/v0.1.0...HEAD
[0.1.0]: https://github.com/denfry/codebase-index/releases/tag/v0.1.0
