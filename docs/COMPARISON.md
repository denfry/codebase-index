# Comparison

How `codebase-index` compares to other code search and context tools.

## Overview

| Tool | Type | Scope | Search Method | Setup |
|---|---|---|---|---|
| codebase-index | Claude Code Skill | Local project | Hybrid (FTS5 + symbols + graph) | `pip install` |
| Cursor indexing | IDE feature | Local project | Proprietary index | Built into IDE |
| Continue | IDE extension | Local project | LLM-based + RAG | Extension install |
| Aider repo-map | CLI tool | Local project | File map + grep | `pip install` |
| Sourcegraph Cody | Cloud service | Any repo | Cloud index | Account + config |
| Serena/MCP tools | MCP server | Local project | Varied | MCP config |
| Manual grep/Read | Manual | Local project | Regex | Built-in |

## Detailed Comparison

### codebase-index (this project)

**What it is:** A local-first Claude Code Skill that builds a hybrid index (FTS5 + symbols + graph) for token-efficient codebase questions.

**Strengths:**
- Local-first — no code leaves your machine by default
- Symbol-aware — understands classes, functions, methods, not just text
- Token-efficient — returns ranked line ranges, not whole files
- Works with Claude Code's automatic skill selection
- Open source, MIT licensed
- Respects `.gitignore`, `.codeindexignore`, and other ignore files
- Secret redaction in output

**Limitations:**
- Not a full IDE — requires Claude Code or manual CLI use
- Symbol extraction limited to Python, JS/TS (more planned)
- Requires initial indexing time
- No GUI — CLI and skill interface only

**Best for:** Developers using Claude Code who want Cursor-like codebase awareness without leaving their workflow.

### Cursor Indexing

**What it is:** Built-in codebase indexing in the Cursor IDE.

**Strengths:**
- Seamless IDE integration
- Automatic indexing on file save
- Good symbol and semantic search
- No separate installation

**Limitations:**
- Requires switching to Cursor IDE
- Proprietary indexing algorithm
- Not available for Claude Code or other agents
- Index not portable

**Best for:** Developers already using Cursor as their primary IDE.

### Continue

**What it is:** An open-source IDE extension for AI coding assistance.

**Strengths:**
- Works with multiple LLM providers
- IDE integration (VS Code, JetBrains)
- Codebase RAG capabilities

**Limitations:**
- Requires IDE extension installation
- RAG quality depends on embedding model
- Not designed specifically for Claude Code
- Heavier setup than a CLI skill

**Best for:** Developers wanting AI assistance across multiple IDEs and LLM providers.

### Aider repo-map

**What it is:** A file map feature in the Aider pair programming tool.

**Strengths:**
- Simple file map generation
- Works with any LLM
- Lightweight

**Limitations:**
- No symbol extraction
- No ranking or relevance scoring
- File map can be large for big projects
- Not a search tool — more of a context injection

**Best for:** Aider users who need basic project context for LLM conversations.

### Sourcegraph Cody

**What it is:** A cloud-based AI coding assistant with enterprise-grade code search.

**Strengths:**
- Enterprise-scale search across many repositories
- Powerful code intelligence
- Good IDE integration

**Limitations:**
- Requires cloud account and potentially paid plan
- Code is sent to Sourcegraph's servers
- Overkill for individual developers
- Not available offline

**Best for:** Enterprise teams with large codebases needing cross-repository search.

### Serena / MCP Tools

**What it is:** MCP servers that expose code search and analysis as tools.

**Strengths:**
- Standard protocol (MCP)
- Works with any MCP-compatible client
- Extensible tool surface

**Limitations:**
- Requires MCP server setup and configuration
- Not all AI agents support MCP yet
- Variable quality depending on implementation

**Best for:** Teams standardizing on MCP for tool integration.

### Manual Grep / Read

**What it is:** Using built-in search tools (ripgrep, grep) and file reading.

**Strengths:**
- No setup required
- Works everywhere
- Full control over search patterns

**Limitations:**
- No symbol awareness
- No ranking — all matches are equal
- Token-inefficient — Claude reads many irrelevant results
- No context about related files
- Manual effort to synthesize results

**Best for:** Quick one-off searches when the index isn't available.

## Positioning

`codebase-index` is:
- **Not** a replacement for Cursor or any IDE
- **Not** a cloud service — it's local-first
- **Not** an MCP-only tool — it's a Claude Code Skill first
- **A retrieval layer** that makes Claude Code smarter about finding the right files

Think of it as giving Claude Code the codebase awareness that Cursor provides, but as a local, open, and agent-agnostic tool.
