---
name: codebase-index
description: Use this skill before answering questions about a repository's architecture, implementation locations, symbols, references, dependencies, refactoring impact, data flow, bugs, or where something is implemented. It searches a local hybrid codebase index so Claude reads only the most relevant files instead of scanning the entire project.
allowed-tools: Bash(python *), Bash(python3 *), Bash(codebase-index *), Bash(cbx *), Read, Grep, Glob
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
| "how does X work" / "explain X" / "walk me through" | `codebase-index explain "$QUERY" --json` |
| overview / architecture | `codebase-index explain "architecture overview" --token-budget 3000 --json` |
| general / unsure | `codebase-index search "$QUERY" --json` |
| keyword / "where is" | `codebase-index search "$QUERY" --json` |
| a specific symbol name | `codebase-index symbol "<name>" --json` |
| "who calls / references" | `codebase-index refs "<name>" --json` |
| "what breaks if I change" | `codebase-index impact "<file-or-symbol>" --json` |
| visual graph / "open graph" | `codebase-index graph "<file-or-symbol>" --open` |

`explain` has a higher default token budget (2200) and HOW_IT_WORKS intent weights — use it whenever the question is about understanding behavior or flow.

For `search`, pick a `--mode` when the intent is clear:
- `--mode symbol` — pure symbol lookups (faster, no FTS noise)
- `--mode fts` — text/keyword queries where symbol names don't matter
- `--mode hybrid` — default; best for mixed queries

Natural-language kind words such as `method`, `function`, `class`, `interface`,
`enum`, and `type` constrain the symbol retriever inside `search`.

Use `--json` for programmatic parsing; omit for human-readable output.
Search/read commands auto-build the index when it is missing; still check
freshness and run `update`/`index` when responses report stale data.

## Step-by-step workflow

1. **Query the index** using the appropriate subcommand for `$QUERY`.
2. **Check index freshness** in the response:
   - `index.exists: false` → run `codebase-index index` first, then re-query.
   - `index.stale: true`, `files_changed_since_build < 20` → run `codebase-index update`, then re-query.
   - `index.stale: true`, `files_changed_since_build ≥ 20` → run `codebase-index index` (full rebuild).
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
- `snippet` — compact code excerpt (may already answer the question); `null` means budget was spent — read via `recommended_reads` instead

Top-level fields:

- `recommended_reads` — the precise `{path, line_start, line_end}` list to open next. This is your read plan.
- `confidence` — `high` (answer directly), `medium` (read + optionally confirm with one Grep), `low` (use fallback).
- `fallback_suggestions` — ripgrep patterns and paths to try if the index is weak.

## Token efficiency rules

- Trust the index. Read the **fewest** files needed — start with rank 1-3 only.
- Read **line ranges**, not whole files. Use `line_start`/`line_end` with Read's `offset`/`limit`.
- The `snippet` may already answer the question — re-read only if you need more context.
- Prefer `search`/`symbol`/`refs`/`impact`/`explain` over manual Grep/Glob — those are expensive fallbacks, not step 1.
- Don't re-run the query with trivially reworded text; refine with a different subcommand instead.
- For broad questions (`confidence: low`, architecture, data-flow), raise the budget: `--token-budget 3000`.
- Test files are demoted in ranking by default. Include "test" in the query to surface them.

## Fallback behavior

Fall back to built-in search **only** when: results are empty, `confidence` is `low`, or the user asks for something the index clearly doesn't cover.

0. If confidence is consistently low across queries, run diagnostics first:
   ```bash
   codebase-index stats --json    # check coverage and symbol counts per language
   codebase-index doctor          # surface config or security issues
   ```
   Low symbol counts for a language may mean the index needs a full rebuild: `codebase-index index`.

1. Use `fallback_suggestions.ripgrep` patterns from the response via Grep.
2. If still nothing, Glob for likely paths, then Grep within them.
3. As a last resort, broaden the search — but tell the user the index was weak here (it may need a rebuild: `codebase-index index`).

Never start with a full-repo scan when the index exists and is fresh.

## Examples

```bash
# "how does the auth flow work?"
codebase-index explain "auth flow" --json

# "explain the overall architecture"
codebase-index explain "architecture overview" --token-budget 3000 --json

# "where is auth token refresh implemented?"
codebase-index search "auth token refresh" --json

# "what breaks if I change the User model?"
codebase-index impact "User" --json

# "who calls send_email?"
codebase-index refs "send_email" --json

# "find the AuthService class"
codebase-index symbol "AuthService" --json

# precise symbol search (faster, no FTS noise)
codebase-index search "AuthService" --mode symbol --json

# generate and open an HTML graph around a file or symbol
codebase-index graph "User" --direction both --depth 2 --open
```

Then Read only the returned line ranges and answer with citations.
