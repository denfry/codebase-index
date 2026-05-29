# Skill Design

How the `codebase-index` Claude Code Skill works and how to extend it.

## Overview

The skill is defined in `skill/SKILL.md` with YAML frontmatter that Claude Code uses for automatic skill selection.

## Frontmatter

```yaml
---
name: codebase-index
description: Use this skill before answering questions about a repository's architecture, implementation locations, symbols, references, dependencies, refactoring impact, data flow, bugs, or where something is implemented.
allowed-tools: Bash(python *), Bash(python3 *), Bash(codebase-index *), Bash(cbx *), Read, Grep, Glob
---
```

### name

The skill identifier. Must be unique within `.claude/skills/`.

### description

Used by Claude Code's automatic skill selection. Should clearly state:
- **When** to use the skill (before answering codebase questions)
- **What** it does (searches a local hybrid index)
- **Why** it's better than scanning (reads only relevant files)

### allowed-tools

Restricts which tools Claude can use while executing this skill:

| Tool | Purpose |
|---|---|
| `Bash(codebase-index *)` | Run CLI commands |
| `Bash(cbx *)` | Run wrapper scripts |
| `Read` | Read specific line ranges from recommended files |
| `Grep` | Fallback search when index is weak |
| `Glob` | Fallback path discovery |

**Explicitly not allowed:** `Write`, `Edit`, `Bash` (unscoped), or any destructive commands.

## Skill Workflow

```
User asks codebase question
         ↓
Skill auto-selected by Claude Code
         ↓
Claude runs: codebase-index search "query" --json
         ↓
Parse JSON response:
  - Check index.exists / index.stale
  - Read recommended_reads line ranges
  - Check confidence level
         ↓
Answer with citations
         ↓
If confidence low → fallback to Grep/Glob
```

## Freshness Contract

The skill checks index freshness before using results:

1. **`index.exists: false`** → Run `codebase-index index` (full build)
2. **`index.stale: true`** with few changes → Run `codebase-index update` (incremental)
3. **`index.stale: true`** with many changes → Run `codebase-index index` (full rebuild)
4. **Fresh** → Use results directly

## Token Efficiency Rules

The skill enforces token-efficient behavior:

- Read **line ranges**, not whole files
- Start with top 1-3 results only
- Trust the `snippet` field — it may already answer the question
- Use `symbol`/`refs`/`impact` for refinement, not reworded searches
- Fallback to Grep/Glob only when confidence is low

## Extending the Skill

### Adding New Commands

If you add a new CLI command, update:

1. `skill/SKILL.md` — add the command to the intent table
2. `skill/SKILL.md` — add to `allowed-tools` if needed
3. `skill/examples/basic-usage.md` — add usage example

### Custom Wrapper Scripts

The `cbx` wrapper scripts (`skill/scripts/cbx`, `skill/scripts/cbx.ps1`) ensure the correct binary is used. To extend:

1. Add the new subcommand to the allowed list in the wrapper
2. Update `allowed-tools` in `SKILL.md`

### Hooks

Configure automatic index updates in `.codeindex.json`:

```json
{
  "hooks": {
    "post_tool_use": {
      "enabled": true,
      "events": ["Write", "Edit"],
      "command": "codebase-index update --quiet"
    }
  }
}
```

This keeps the index fresh without manual intervention.

## Skill Selection Triggers

The skill is selected when the user's question contains:

- Location queries: "where is", "find", "locate"
- Explanation queries: "how does", "explain", "what does"
- Reference queries: "who calls", "references to", "depends on"
- Impact queries: "what breaks", "impact", "blast radius"
- Architecture queries: "architecture", "overview", "structure"
- Debugging: error messages, stack traces, "why is this error"
