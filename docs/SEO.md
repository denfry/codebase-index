# SEO Plan

Repository SEO strategy for `codebase-index`.

## Repository Metadata

### Repository Name

```
codebase-index
```

Rationale: Matches the intended package name and primary product keyword.

### GitHub About Description

```
Local-first codebase indexing for Claude Code, Codex CLI, OpenCode & AI coding agents — hybrid FTS5 + Tree-sitter + graph search, fully offline.
```

### GitHub Topics

```
ai-agents, ai-coding, claude-code, cli, code-search, codebase-indexing, codex-cli, context-engineering, cursor-alternative, developer-tools, fts5, local-first, mcp, opencode, python, rag, semantic-code-search, sqlite, token-optimization, tree-sitter
```

GitHub caps topics at 20; this list is the live set (all 20 slots used). `codebase-rag`
is a swap candidate if a slot frees up.

### Website

Leave blank initially. Can be set to GitHub Pages docs site later.

## README SEO Strategy

### First 150 Words

The opening paragraph must contain these keywords naturally:

- AI coding agents
- codebase indexing
- local-first
- Cursor-like indexing
- token-efficient context
- semantic code search
- AST symbol search

### Searchable Headings

Use these headings in the README (already implemented):

1. "Local Codebase Indexing for AI Coding Agents" (hero section)
2. "What Is codebase-index?" (definition)
3. "What Problem Does codebase-index Solve?" (problem)
4. "How Does codebase-index Work?" (method)
5. "Which AI CLIs Does codebase-index Support?" (integration)

### Keyword Density

Each primary keyword should appear 1-3 times naturally:

| Keyword | Target Count | Sections |
|---|---|---|
| AI coding agents | 3-5 | Hero, features, installation |
| codebase indexing | 2-4 | Hero, problem, solution |
| local-first | 3-5 | Hero, features, security |
| Cursor-like | 2-3 | Problem, comparison |
| token-efficient | 2-3 | Solution, features |
| semantic code search | 1-2 | Features, how it works |
| AST symbol search | 1-2 | Features, architecture |
| hybrid code search | 1-2 | Solution, retrieval |
| Tree-sitter | 2-3 | Features, architecture |
| SQLite FTS5 | 1-2 | Architecture, database schema |

**Do not keyword-stuff.** Write naturally for humans first.

## Badges

Include shields.io badges in the README hero section:

```markdown
![License](https://img.shields.io/badge/license-MIT-blue.svg)
![Python](https://img.shields.io/badge/python-3.11+-blue.svg)
![CI](https://github.com/denfry/codebase-index/actions/workflows/ci.yml/badge.svg)
![Claude Code Skill](https://img.shields.io/badge/Claude%20Code%20Skill-yes-green.svg)
![Codex CLI](https://img.shields.io/badge/Codex%20CLI-supported-green.svg)
![OpenCode](https://img.shields.io/badge/OpenCode-supported-green.svg)
![MCP](https://img.shields.io/badge/MCP-stdio%20server-green.svg)
![Local First](https://img.shields.io/badge/local--first-yes-green.svg)
![No Telemetry](https://img.shields.io/badge/no%20telemetry-yes-green.svg)
![No Network](https://img.shields.io/badge/no%20network%20by%20default-yes-green.svg)
![SQLite](https://img.shields.io/badge/database-SQLite-blue.svg)
![Tree-sitter](https://img.shields.io/badge/parsing-Tree--sitter-orange.svg)
```

## Social Preview Image

Built and committed as `assets/social-preview.png` (1280×640). Regenerate with:

```bash
python scripts/gen_assets.py
```

This also builds `assets/demo.png` (1200×760), the static terminal still embedded
near the top of `README.md`.

- **Dimensions:** 1280×640 (GitHub recommended)
- **Background:** GitHub dark theme (#0d1117), accent glow
- **Text:** wordmark `codebase-index` + "Local codebase indexing for AI coding agents"
- **Elements:** terminal mock with a ranked search result + capability chips
- **Style:** clean, minimal, professional

> **Action still required:** the file in the repo is not the social card by itself.
> Upload it in **Settings → General → Social preview** so GitHub serves it as the
> `og:image` on X / Slack / Discord / LinkedIn. (`usesCustomOpenGraphImage` is
> currently `false`.)

## Launch Checklist

- [x] Create v1.3.0 release with release notes
- [x] Add all GitHub topics (20/20 slots used; see list above)
- [x] Set repository description in About section
- [ ] Upload social preview image (`assets/social-preview.png` built; must be uploaded in Settings → Social preview)
- [x] Ensure README first 150 words contain target keywords
- [x] Verify all badges render correctly
- [ ] Submit to awesome Claude Code skills lists
- [ ] Submit to awesome AI coding tools lists
- [ ] Post announcement on:
  - X/Twitter
  - Reddit (r/LocalLLaMA, r/ClaudeAI, r/artificial)
  - Hacker News (Show HN)
  - Dev.to
- [~] Add demo GIF or terminal recording to README (`assets/demo.png` static still built; animated GIF still pending)
- [x] Ensure comparison page is complete (`docs/COMPARISON.md`)
- [x] Ensure security model page is complete (`docs/SECURITY_MODEL.md`)
- [x] Tag release on GitHub (`v1.3.0`)

## Backlink Targets

Submit to these lists for backlinks and discoverability:

### Awesome Lists
- awesome-claude-code
- awesome-claude
- awesome-ai-coding-tools
- awesome-code-search
- awesome-developer-tools
- awesome-sqlite
- awesome-tree-sitter

### Directories
- Claude Skill Directory (if exists)
- MCP Server Directory after client config docs are verified
- PyPI package listing after distribution hardening is complete

### Communities
- Claude Code Discord
- AI Coding Tools communities
- Developer tool forums

## Release Announcement Template

```
codebase-index v1.3.0

A local-first codebase index for AI coding agents.

Instead of scanning your whole repo, Claude Code, Codex CLI, or OpenCode searches
a local hybrid index (FTS5 + symbols + graph) and reads only the relevant line ranges.

Features:
- Local-first, no network by default
- SQLite + FTS5 full-text search
- Tree-sitter symbol extraction
- Claude Code, Codex CLI, and OpenCode setup
- Token-efficient retrieval packets
- Secret redaction
- Respects .gitignore

Install: pip install "codebase-index @ git+https://github.com/denfry/codebase-index.git@v1.3.0"
GitHub: https://github.com/denfry/codebase-index
```

## Social Post Template

```
Gave Claude Code Cursor-like codebase awareness.

codebase-index builds a local hybrid index so Claude finds the right files without scanning your whole repo.

- FTS5 + symbols + graph search
- No network by default
- Token-efficient output

pip install "codebase-index @ git+https://github.com/denfry/codebase-index.git@v1.3.0"
```
