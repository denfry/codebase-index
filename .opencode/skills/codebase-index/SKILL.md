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

1. **Classify the question** using the research modes below to pick the first command. This is only a starting hint: when you run `search`, the response carries the tool's own `intent` classification — trust it over your manual guess if they disagree.
2. **Query the index** using the appropriate subcommand for `$QUERY`.
3. **Check index freshness** in the response:
   - `index.exists: false` -> run `codebase-index index` first, then re-query.
   - `index.stale: true` with few changes -> run `codebase-index update`, then re-query.
   - Otherwise proceed with results.
4. **Read question-specific evidence** from `recommended_reads`, starting with the smallest set that can answer the question.
5. **Validate coverage** with the coverage gate before answering.
6. **Answer with citations** using file:line references (for example, `src/auth/token.py:88-134`).
7. **Fallback** only when confidence handling allows it.

## Research modes

Choose the lightest mode that fits the user's question. Do not optimize for a benchmark repository; optimize for the user's actual intent.

Only `search` returns `intent`, `confidence`, and `recommended_reads` (see "Response shapes by subcommand"). When you want those signals, lead with `search` and use `symbol`/`refs`/`impact` as targeted follow-ups.

| User intent | Primary command | Required evidence |
|---|---|---|
| "where is X" / locate implementation | `codebase-index search "$QUERY" --json` or `codebase-index symbol "<name>" --json` | The defining file/range and one citation. |
| "who calls X" / references | `codebase-index refs "<name>" --json` | Call sites or a clear statement that none were found. |
| "how does X work" / trace a flow | `codebase-index search "$QUERY" --json` plus `refs` for the entry point when needed | Entry point, core logic, and main consumers. |
| "trace the data flow of X" | `codebase-index search "$QUERY" --json`, then `refs`/`impact` to follow where the value is set and consumed | Where the value is produced, the path it travels, and where it is read. |
| "what breaks if I change X" / refactoring impact | `codebase-index impact "<file-or-symbol>" --json` (add `--direction up\|down\|both` to scope dependents vs. dependencies) plus `refs` for important symbols when needed | Direct dependents, likely failure modes, and confidence level. |
| architecture / overview | 2-4 targeted `search` queries around the main nouns | Main modules, boundaries, and the parts not inspected. |
| bug / stack trace | `search` exact error text or symbol names, then `refs` if a caller chain matters | Faulting location, input path, and likely cause. |

## Token-budgeted output interpretation

The index returns a **ranked retrieval packet** with:

- `rank` - result position (start with 1-3)
- `path` - file path
- `line_start` / `line_end` - exact line range to read
- `symbols` - symbols found in this range
- `score` - relevance score
- `reason` - why this result ranked (for example, "exact symbol match, 4 callers")
- `snippet` - compact code excerpt (may already answer the question)

Top-level fields (on `search`):

- `intent` - the tool's own classification of the question (`locate_impl`, `how_it_works`, `impact`, `find_refs`, `data_flow`, `debug_error`, `architecture`, `keyword`). Use it to confirm or correct your manual research-mode guess.
- `recommended_reads` - the precise `{path, line_start, line_end}` list to open next. This is the read plan, not a prison.
- `confidence` - how much validation is needed before answering.
- `fallback_suggestions` - ripgrep patterns and paths to try if the index is weak.

## Response shapes by subcommand

`intent`, `confidence`, `recommended_reads`, and `fallback_suggestions` are returned **only by `search`**. The other subcommands return their own shapes with no read plan or confidence — judge sufficiency from the returned entries directly:

- `search` -> `results[]` plus the top-level fields above.
- `symbol` -> `symbols[]`: each has `name`, `kind`, `path`, `line_start`, `line_end`, `signature`. The match itself is the answer.
- `refs` -> `sites[]`: each has `path`, `line`, `kind`. The list of call sites is the answer (an empty list means "no references found").
- `impact` -> `nodes[]` (`kind`, `path`, `name`, `distance`, `via_edge`) plus a ranked `files[]`. Dependents/dependencies are the answer.

## Confidence handling

- `high`: Trust the ranking, read only the key ranges needed for the selected research mode, then answer.
- `medium`: Read the key ranges, then run one targeted `refs`, `impact`, `symbol`, or fallback `rg` check if the answer depends on callers, configuration, or side effects.
- `low`: Use `fallback_suggestions` and say that the index was weak. If fallback also fails, state the uncertainty instead of inventing a complete answer.

High confidence does not mean "read nothing." Medium confidence does not mean "scan the repo." Match validation to the question's risk.

`confidence` is only present on `search` responses. For `symbol`/`refs`/`impact`, there is no confidence field — judge whether the returned `symbols`/`sites`/`nodes` actually answer the question, and run `search` (or a fallback `rg`) if they look incomplete.

## Coverage gate

Before answering, verify that the evidence matches the question:

- Location questions: did you identify the defining file/range?
- Flow questions: did you inspect the entry point, core logic, and at least one consumer or exit path?
- Impact questions: did you inspect direct dependents and name likely failure modes?
- Config/data questions: did you inspect where values are loaded and where they are consumed?
- Architecture questions: did you name the boundaries and explicitly say which areas were not inspected?
- Bug questions: did you connect the observed symptom to a source path and a sink or caller path?

For direct `symbol`/`refs`/`impact` answers, the evidence is the returned `symbols`/`sites`/`nodes` themselves, not `recommended_reads` (those subcommands do not return a read plan).

If the gate fails, run one more targeted index query before falling back to Grep/Glob.

## Token efficiency rules

- Trust the index. Read the **fewest** files needed for the selected research mode.
- Start with rank 1-3 and the returned `recommended_reads`.
- Read **line ranges**, not whole files. Use `line_start`/`line_end` with Read's `offset`/`limit`.
- The `snippet` may already answer a narrow location question; re-read only if citations or surrounding logic are needed.
- Prefer `search`/`symbol`/`refs`/`impact` over manual Grep/Glob. Those are targeted validation tools, not expensive fallbacks.
- Do not re-run the query with trivially reworded text. Refine with a different subcommand or a more specific symbol.

## Fallback behavior

Fall back to built-in search **only** when results are empty, `confidence` is `low`, the coverage gate fails after one more targeted index query, or the user asks for something the index clearly does not cover.

1. Use `fallback_suggestions.ripgrep` patterns from the response via Grep.
2. If still nothing, Glob for likely paths, then Grep within them.
3. As a last resort, broaden the search, but tell the user the index was weak here. It may need a rebuild with `codebase-index index`.

Never start with a full-repo scan when the index exists and is fresh.

## Examples

Command reference:

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

### Worked example: a flow question (`search`)

Question: "how does auth token refresh work?"

```bash
codebase-index search "auth token refresh" --json
```

The response carries `"intent": "how_it_works"`, `"confidence": "medium"`, and a
`recommended_reads` list, for example `[{path: "src/auth/token.py", line_start: 88, line_end: 134}]`.
Because intent is `how_it_works` and confidence is `medium`: Read that range, then run one
targeted `refs "refresh_token"` to confirm the main consumer. Coverage gate (flow): entry
point + core logic + one consumer covered. Answer with a citation like
`src/auth/token.py:88-134`.

### Worked example: an impact question (`impact`)

Question: "what breaks if I change the User model?"

```bash
codebase-index impact "User" --json
```

The response has **no** `confidence` or `recommended_reads` — it returns `nodes[]`
(each with `distance` and `via_edge`) and a ranked `files[]`. Judge coverage from the
nodes: list the `distance: 1` dependents and the edge that links them, name the likely
failure modes, and state the affected files. If the nodes look incomplete, run
`refs "User"` or a fallback `rg` before answering.

Then Read only the returned line ranges and answer with citations.
