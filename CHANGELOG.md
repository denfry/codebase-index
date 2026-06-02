# Changelog

All notable changes to this project are documented here. The format is based on
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/), and this project adheres to
[Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [1.1.0] - 2026-06-02

### Added
- **MCP server** (`codebase-index mcp`): exposes the full retrieval layer as six MCP tools —
  `search_code`, `find_symbol`, `find_refs`, `impact_of`, `explain_code`, `index_stats` —
  so any MCP-capable editor (Cursor, Claude Desktop, VS Code, Zed, Windsurf) can query the
  index directly without subprocess CLI calls, matching Cursor's built-in codebase-indexing UX.
- **`codebase-index-mcp`** standalone entry point for use as a bare MCP server binary.
- **Multi-client `init`**: `--target` now accepts five MCP clients in addition to the three
  skill targets. Each writes the correct JSON config format and merges without overwriting
  other servers already present:
  - `cursor` → `.cursor/mcp.json`
  - `windsurf` → `.windsurf/mcp.json`
  - `vscode` → `.vscode/mcp.json` (with `type: stdio`)
  - `zed` → `.zed/settings.json` (with `context_servers`)
  - `claude-desktop` → platform-specific `claude_desktop_config.json`
- `detect_mcp_targets()` auto-detects installed MCP clients during `--target auto`.
- New optional dependency group `mcp` (`pip install codebase-index[mcp]`).

### Fixed
- `recommended_reads` was empty for queries where all results had short symbol-signature
  snippets (`token_est < 40`). Added `_MIN_USEFUL_TOKENS = 40` threshold: snippets below
  it are still shown as previews but the result is also added to `recommended_reads` so
  Claude always receives an explicit read plan.

### Changed
- Distribution is now **GitHub-only**: the package is no longer published to PyPI.
  `requirements.lock` and all install docs install `codebase-index` from the GitHub
  release tarball pinned to a tag (`@v1.1.0`); `pipx install "git+https://..."` is the
  recommended one-command path. The bootstrap still honors `CBX_INSTALL_SPEC` to
  override the install source for local/dev installs.
- Removed the PyPI trusted-publishing job from the release workflow; tagged GitHub
  releases (with attached build artifacts) are the sole distribution channel.

## [1.0.2] - 2026-05-29

### Added
- Added `codebase-index init --target claude|codex|opencode|auto|all`, with an
  interactive Rich target picker for terminal use.
- Added project scaffolding for Codex CLI (`AGENTS.md` + resources) and OpenCode
  (command, agent, and resources), while preserving the Claude Code skill path.

### Changed
- Refreshed README positioning and SEO structure around local codebase indexing for
  AI coding agents, including Claude Code, Codex CLI, and OpenCode.
- Updated quickstart and installation docs for multi-CLI initialization.

## [1.0.1] - 2026-05-29

### Fixed
- Pinned `tree-sitter` and `tree-sitter-language-pack` in package metadata and the plugin
  bootstrap lock so CI and local installs use the same grammars.
- Regenerated CLI golden snapshots against the pinned grammar set.

## [1.0.0] - 2026-05-29

### Fixed
- Multi-language tree-sitter symbol extraction. Previously a repo of 303 Java files produced
  **0 symbols**, silently disabling `symbol`/`refs`/`impact`. Java now yields 3,543 symbols;
  Go/Rust/C/C++/C#/Ruby/PHP/Kotlin plus a Tier-B generic path are covered.

### Added
- Symbol-aware retrieval ranking: candidates are scored by how many query terms their
  camelCase/underscore-split name covers, so multi-word concepts land on multi-word symbols.
  recall@3 against objective ground truth improved 20% → 70% (vs 40% for a disciplined grep agent)
  while using ~13× fewer tokens to answer.
- Parse guardrails with `parse_failed` / `treesitter_zero_symbols` counters and `doctor` reporting
  to lock symbol extraction against silent regression.
- Multi-CLI installer for Claude Code / Codex / OpenCode.
- Honest benchmark harness (`tests/benchmark_honest.py`) comparing the index against a no-skill
  grep agent on a real repository.

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

[Unreleased]: https://github.com/denfry/codebase-index/compare/1.0.2...HEAD
[1.0.2]: https://github.com/denfry/codebase-index/compare/1.0.1...1.0.2
[1.0.1]: https://github.com/denfry/codebase-index/compare/1.0.0...1.0.1
[1.0.0]: https://github.com/denfry/codebase-index/compare/v0.1.0...1.0.0
[0.1.0]: https://github.com/denfry/codebase-index/releases/tag/v0.1.0
