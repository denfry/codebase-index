# Skill Design

How the `codebase-index` Claude Code Skill works and how to extend it.

## Overview

The skill is defined in `skill/SKILL.md` with YAML frontmatter that agent
clients use for automatic selection. The primary file is intentionally a short
operating protocol; detailed command and payload material lives in
`skill/references/` and is loaded only when needed.

## Frontmatter

```yaml
---
name: codebase-index
description: Use before answering repository questions about architecture, implementation, symbols, references, dependencies, refactoring impact, data flow, or bugs. Query the local hybrid index first so the agent reads only evidence-bearing file:line ranges instead of scanning the repository.
allowed-tools: Bash(codebase-index search *), Bash(codebase-index explain *), Bash(codebase-index architecture *), Bash(codebase-index symbol *), Bash(codebase-index refs *), Bash(codebase-index impact *), Bash(codebase-index diff-impact *), Bash(codebase-index path *), Bash(codebase-index describe *), Bash(codebase-index graph *), Bash(codebase-index stats *), Bash(codebase-index doctor *), Bash(codebase-index update *), Bash(codebase-index index *), Bash(cbx *), Read, Grep, Glob
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

**Explicitly not allowed:** `Write`, `Edit`, `Bash` (unscoped),
`codebase-index *` (unscoped), `python -m codebase_index *`, or destructive
and scaffolding commands such as `clean`, `init`, and `watch`.

## Skill Workflow

```
User asks codebase question
         ↓
Skill auto-selected by Claude Code
         ↓
Route intent: Find / Trace / Predict
         ↓
Parse JSON response:
  - Check index.exists / index.stale
  - Read recommended_reads line ranges
  - Check confidence level
         ↓
Answer + file:line evidence
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

## Progressive References

`SKILL.md` links two optional resources:

- `references/commands.md` — command options, graph commands, health commands,
  and query examples.
- `references/response-contract.md` — payload fields, freshness handling,
  partial-coverage behavior, and answer examples.

Do not move the core evidence or freshness protocol out of `SKILL.md`; agents
need those rules on every invocation. Keep detailed option lists and examples in
references so they do not consume context on routine searches.

## Answer Contract

The skill asks agents to return:

1. the direct answer;
2. the minimum supporting `file:line` evidence;
3. confidence only when evidence is partial, inferred, stale, or missing;
4. a next check only when it materially reduces uncertainty.

This prevents tool narration from displacing the actual engineering answer and
prevents partial graph coverage from being presented as proof of absence.

## Extending the Skill

### Adding New Commands

If you add a new CLI command, update:

1. `skill/SKILL.md` — add the command to the intent table
2. `skill/references/commands.md` — document detailed options and examples
3. `skill/SKILL.md` — add to `allowed-tools` if needed
4. Both safe wrappers — add the subcommand only if it is read-only or a
   freshness operation
5. Run `python scripts/sync_skill_copies.py`

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
