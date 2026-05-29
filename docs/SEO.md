# SEO Plan

Repository SEO strategy for `codebase-index`.

## Repository Metadata

### Repository Name

```
claude-code-codebase-index-skill
```

Rationale: Contains primary keywords ("claude code", "codebase index", "skill") for GitHub search.

### GitHub About Description

```
Local-first Claude Code Skill for Cursor-like codebase indexing, hybrid code search, symbol lookup, and token-efficient project context.
```

### GitHub Topics

```
claude-code, claude-code-skill, claude-skills, ai-coding, codebase-indexing, semantic-code-search, code-search, rag, codebase-rag, tree-sitter, sqlite, fts5, developer-tools, ai-agents, cursor-alternative, context-engineering, token-optimization, local-first, python, cli
```

### Website

Leave blank initially. Can be set to GitHub Pages docs site later.

## README SEO Strategy

### First 150 Words

The opening paragraph must contain these keywords naturally:

- Claude Code Skill
- codebase indexing
- local-first
- Cursor-like indexing
- token-efficient context
- semantic code search
- AST symbol search

### Searchable Headings

Use these headings in the README (already implemented):

1. "Claude Code Skill for Codebase Indexing" (hero section)
2. "Cursor-like Project Indexing for Claude Code" (problem/solution)
3. "Token-Efficient Codebase Search" (features)
4. "Local-First Semantic Code Search" (how it works)
5. "How Codebase Index Works" (pipeline)

### Keyword Density

Each primary keyword should appear 1-3 times naturally:

| Keyword | Target Count | Sections |
|---|---|---|
| Claude Code Skill | 3-5 | Hero, features, installation |
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
![Python](https://img.shields.io/badge/python-3.10+-blue.svg)
![CI](https://github.com/<OWNER>/claude-code-codebase-index-skill/actions/workflows/ci.yml/badge.svg)
![Claude Code Skill](https://img.shields.io/badge/Claude%20Code%20Skill-yes-green.svg)
![Local First](https://img.shields.io/badge/local--first-yes-green.svg)
![No Telemetry](https://img.shields.io/badge/no%20telemetry-yes-green.svg)
![No Network](https://img.shields.io/badge/no%20network%20by%20default-yes-green.svg)
![SQLite](https://img.shields.io/badge/database-SQLite-blue.svg)
![Tree-sitter](https://img.shields.io/badge/parsing-Tree--sitter-orange.svg)
```

## Social Preview Image

Create `assets/social-preview.png`:

- **Dimensions:** 1280x640 (GitHub recommended)
- **Background:** Dark theme (#0d1117 or similar)
- **Text:** "codebase-index — Cursor-like indexing for Claude Code"
- **Elements:** Terminal screenshot or code snippet graphic
- **Style:** Clean, minimal, professional

## Launch Checklist

- [ ] Create v0.1.0 release with release notes
- [ ] Add all GitHub topics (see list above)
- [ ] Set repository description in About section
- [ ] Upload social preview image
- [ ] Ensure README first 150 words contain target keywords
- [ ] Verify all badges render correctly
- [ ] Submit to awesome Claude Code skills lists
- [ ] Submit to awesome AI coding tools lists
- [ ] Post announcement on:
  - X/Twitter
  - Reddit (r/LocalLLaMA, r/ClaudeAI, r/artificial)
  - Hacker News (Show HN)
  - Dev.to
- [ ] Add demo GIF or terminal recording to README
- [ ] Ensure comparison page is complete
- [ ] Ensure security model page is complete
- [ ] Tag release on GitHub

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
- MCP Server Directory (for future MCP bridge)
- PyPI (package listing)

### Communities
- Claude Code Discord
- AI Coding Tools communities
- Developer tool forums

## Release Announcement Template

```
🚀 codebase-index v0.1.0

A local-first Claude Code Skill that gives Claude Cursor-like codebase awareness.

Instead of scanning your whole repo, Claude searches a local hybrid index (FTS5 + symbols + graph) and reads only the relevant line ranges.

Features:
- Local-first, no network by default
- SQLite + FTS5 full-text search
- Tree-sitter symbol extraction
- Token-efficient retrieval packets
- Secret redaction
- Respects .gitignore

Install: pip install codebase-index
GitHub: https://github.com/<OWNER>/claude-code-codebase-index-skill
```

## Social Post Template

```
Gave Claude Code Cursor-like codebase awareness.

codebase-index builds a local hybrid index so Claude finds the right files without scanning your whole repo.

- FTS5 + symbols + graph search
- No network by default
- Token-efficient output

pip install codebase-index
```
