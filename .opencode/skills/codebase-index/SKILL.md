---
name: codebase-index
description: Use this skill before answering questions about a repository's architecture, implementation locations, symbols, references, dependencies, refactoring impact, data flow, bugs, or where something is implemented. It searches a local hybrid codebase index so Claude reads only the most relevant files instead of scanning the entire project.
---

# Codebase Index

Use this skill first for codebase questions.

Never scan the entire repository before searching the index.

## When to use

Invoke this skill **before reading any files** when the user asks about this project's code:

- "where is X implemented" / "find X" / "locate the X function"
- "how does X work" / "explain the X flow"
- "what breaks if I change X" / "what depends on X" (impact analysis)
- "who calls X" / "references to X"
- "trace the data flow of X"
- "why is this error happening" (error/stack trace)
- "explain the architecture" / "give me an overview"
- Any question about symbols, files, dependencies, or refactoring scope

Do **not** use it for: editing files, running the application, or non-code questions.

## How to call the CLI

Use the `codebase-index` CLI directly, or the bundled `cbx` wrapper:

```bash
codebase-index search "$QUERY" --json
```

Pick the subcommand by intent:

| User intent | Command |
|---|---|
| general / "how does it work" / unsure | `codebase-index search "$QUERY" --json` |
| keyword / "where is" | `codebase-index search "$QUERY" --json` |
| a specific symbol name | `codebase-index symbol "<name>" --json` |
| "who calls / references" | `codebase-index refs "<name>" --json` |
| "what breaks if I change" | `codebase-index impact "<file-or-symbol>" --json` |
| overview / architecture | `codebase-index search "$QUERY" --json` |

Use `--json` for programmatic parsing; omit for human-readable output.

## Step-by-step workflow

1. **Query the index** using the appropriate subcommand for `$QUERY`.
2. **Check index freshness** in the response:
   - `index.exists: false` → run `codebase-index index` first, then re-query.
   - `index.stale: true` with few changes → run `codebase-index update`, then re-query.
   - Otherwise proceed with results.
3. **Read ONLY the `recommended_reads`** — use the Read tool with `offset`/`limit` to read the exact line ranges returned. Do not open whole files.
4. **Answer** with file:line citations (e.g., `src/auth/token.py:88-134`).
5. **Fallback** only if confidence is low or results are empty (see below).

## Token-budgeted output interpretation

The index returns a **ranked retrieval packet** with:

- `rank` — result position (start with 1-3)
- `path` — file path
- `line_start` / `line_end` — exact line range to read
- `symbols` — symbols found in this range
- `score` — relevance score
- `reason` — why this result ranked (e.g., "exact symbol match, 4 callers")
- `snippet` — compact code excerpt (may already answer the question)

Top-level fields:

- `recommended_reads` — the precise `{path, line_start, line_end}` list to open next. This is your read plan.
- `confidence` — `high` (answer directly), `medium` (read + optionally confirm with one Grep), `low` (use fallback).
- `fallback_suggestions` — ripgrep patterns and paths to try if the index is weak.

## Token efficiency rules

- Trust the index. Read the **fewest** files needed — start with rank 1-3 only.
- Read **line ranges**, not whole files. Use `line_start`/`line_end` with Read's `offset`/`limit`.
- The `snippet` may already answer the question — re-read only if you need more context.
- Prefer `search`/`symbol`/`refs`/`impact` over manual Grep/Glob — those are expensive fallbacks, not step 1.
- Don't re-run the query with trivially reworded text; refine with a different subcommand instead.

## Fallback behavior

Fall back to built-in search **only** when: results are empty, `confidence` is `low`, or the user asks for something the index clearly doesn't cover.

1. Use `fallback_suggestions.ripgrep` patterns from the response via Grep.
2. If still nothing, Glob for likely paths, then Grep within them.
3. As a last resort, broaden the search — but tell the user the index was weak here (it may need a rebuild: `codebase-index index`).

Never start with a full-repo scan when the index exists and is fresh.

## Examples

```bash
# "where is auth token refresh implemented?"
codebase-index search "auth token refresh" --json

# "what breaks if I change the User model?"
codebase-index impact "User" --json

# "who calls send_email?"
codebase-index refs "send_email" --json

# "find the AuthService class"
codebase-index symbol "AuthService" --json
```

Then Read only the returned line ranges and answer with citations.
