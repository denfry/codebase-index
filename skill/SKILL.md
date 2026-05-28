---
name: codebase-index
description: >-
  Use FIRST for ANY question about THIS project's code — where something is implemented, how a
  feature works, what files to change, who calls/references a symbol, what breaks if X changes,
  tracing data flow, debugging an error in this repo, or explaining the architecture. Searches a
  fast local index and returns the exact files + line ranges to read, instead of scanning the repo.
  Trigger words: where is, how does, find, references to, who calls, impact, what breaks, trace,
  explain, architecture, this codebase, this project, this repo.
allowed-tools:
  - Bash(codebase-index search:*)
  - Bash(codebase-index explain:*)
  - Bash(codebase-index symbol:*)
  - Bash(codebase-index refs:*)
  - Bash(codebase-index impact:*)
  - Bash(codebase-index stats:*)
  - Bash(codebase-index update:*)
  - Bash(codebase-index index:*)
  - Grep
  - Glob
---

# codebase-index

Local-first code search for **this** project. Before answering a codebase question, query the local
index to find the smallest set of files/line ranges to read — do **not** scan the whole repo first.

`$ARGUMENTS` is the user's natural-language question.

## When to use

Use this skill **before reading files** whenever the user asks about this project's code:
- "where is X / find X / locate the X function"
- "how does X work / explain the X flow"
- "what breaks if I change X / what depends on X" (impact)
- "find references to X / who calls X"
- "trace the data flow of X"
- "why is this error happening" (paste of an error/stack trace)
- "explain the architecture / give me an overview"

Do **not** use it for: editing files, running the app, or non-code questions.

## How to call the CLI

Always go through the bundled wrapper so the right binary is used:

```bash
"${CLAUDE_SKILL_DIR}/scripts/cbx" explain "$ARGUMENTS" --json
```

Pick the subcommand by intent (the CLI also auto-detects, so `explain` is a safe default):

| User intent | Command |
|---|---|
| general / "how does it work" / unsure | `explain "$ARGUMENTS" --json` |
| keyword / "where is" | `search "$ARGUMENTS" --json` |
| a specific symbol name | `symbol "<name>" --json` |
| "who calls / references" | `refs "<name>" --json` |
| "what breaks if I change" | `impact "<file-or-symbol>" --json` |

Use `--json` for parsing; drop it if you want to show the user a readable table.

## Step-by-step

1. **Run the index query** for `$ARGUMENTS` using the command above.
2. **Check the `index` block** in the response:
   - `exists: false` → run `"${CLAUDE_SKILL_DIR}/scripts/cbx" index` once, then re-run the query.
   - `stale: true` with few changes → run `"${CLAUDE_SKILL_DIR}/scripts/cbx" update`, then re-run.
   - Otherwise proceed.
3. **Read the results** and decide what to open next (see interpretation below).
4. **Read ONLY the `recommended_reads` ranges** with the Read tool (use `offset`/`limit` to read
   just those lines). Do not open whole files unless a snippet shows you must.
5. **Answer** with file:line citations.
6. **Fallback** (see below) only if confidence is low or results are empty.

## Token efficiency rules (important)

- Trust the index. Read the **fewest** files needed — start with rank 1–3 only.
- Read **line ranges**, not whole files. Use the `line_start`/`line_end` from results with Read's
  `offset` and `limit`.
- The provided `snippet` may already answer the question — re-read a file only if you need more.
- Prefer `explain`/`search` over manual Grep/Glob; those are the expensive fallback, not step 1.
- Don't re-run the query with trivially reworded text; refine with `symbol`/`refs`/`impact` instead.

## Interpreting the output

Each result has: `rank`, `path`, `line_start`–`line_end`, `symbols`, `score`, `reason`, `snippet`.
The top-level has `intent`, `confidence`, `recommended_reads`, and `fallback_suggestions`.

- **`recommended_reads`** = the precise list of `{path, line_start, line_end}` to open next. This is
  your read plan.
- **`reason`** explains why a result ranked (e.g. "exact symbol match · 4 callers"). Use it to pick.
- **`confidence`**:
  - `high` → read recommended ranges and answer directly.
  - `medium` → read them; optionally confirm one detail with a single Grep.
  - `low` → use the fallback.

## Fallback behavior

Fall back to built-in search **only** when: results are empty, `confidence` is `low`, or the user
asks for something the index clearly doesn't cover.

1. Use `fallback_suggestions.ripgrep` patterns from the response, e.g. run them via Grep.
2. If still nothing, Glob for likely paths, then Grep within them.
3. As a last resort, broaden the search — but tell the user the index was weak here (it may need a
   rebuild: `"${CLAUDE_SKILL_DIR}/scripts/cbx" index`).

Never start with a full-repo scan when the index exists and is fresh.

## Examples

```bash
# "where is auth token refresh implemented?"
"${CLAUDE_SKILL_DIR}/scripts/cbx" search "auth token refresh" --json

# "what breaks if I change the User model?"
"${CLAUDE_SKILL_DIR}/scripts/cbx" impact "User" --json

# "who calls send_email?"
"${CLAUDE_SKILL_DIR}/scripts/cbx" refs "send_email" --json
```

Then Read only the returned line ranges and answer with citations like `src/auth/token.py:88-134`.
