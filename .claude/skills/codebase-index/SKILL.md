---
name: codebase-index
description: Use before answering repository questions about architecture, implementation, symbols, references, dependencies, refactoring impact, data flow, or bugs. Query the local hybrid index first so the agent reads only evidence-bearing file:line ranges instead of scanning the repository, and verify evidence gathered earlier before relying on it.
allowed-tools: Bash(codebase-index search *), Bash(codebase-index explain *), Bash(codebase-index architecture *), Bash(codebase-index symbol *), Bash(codebase-index refs *), Bash(codebase-index impact *), Bash(codebase-index diff-impact *), Bash(codebase-index path *), Bash(codebase-index describe *), Bash(codebase-index verify *), Bash(codebase-index graph *), Bash(codebase-index stats *), Bash(codebase-index doctor *), Bash(codebase-index update *), Bash(codebase-index index *), Bash(cbx *), Read, Grep, Glob
---

# Codebase Index

Use the local index before reading repository files.

The operating principle is **Find → Trace → Verify → Predict**:

- **Find** the implementation with ranked retrieval.
- **Trace** behavior through definitions, callers, dependencies, and paths.
- **Verify** that evidence you already hold is still true before relying on it.
- **Predict** change impact while preserving an explicit evidence trail.

## Route the question

| Intent | Command |
|---|---|
| Where is X implemented? | `codebase-index search "X" --session <tag> --json` |
| How does X work? | `codebase-index explain "X" --session <tag> --json` |
| What is this codebase? | `codebase-index architecture --json` |
| Find a named symbol | `codebase-index symbol "X" --json` |
| Who calls or references X? | `codebase-index refs "X" --json` |
| What changes if X changes? | `codebase-index impact "X" --json` |
| What does my current diff affect? | `codebase-index diff-impact --json` |
| How are X and Y connected? | `codebase-index path "X" "Y" --json` |
| Describe X and its neighborhood | `codebase-index describe "X" --json` |
| Is what I read earlier still true? | `codebase-index verify --session <tag> --json` |
| Produce a human graph | `codebase-index graph "X" --output <path>` |

Use `search --mode symbol` for exact symbol work, `--mode fts` for text and
error messages, and the default `hybrid` mode for mixed questions. Use pure
`vector` mode only when embeddings are enabled and exact vocabulary is unknown.

Read [references/commands.md](references/commands.md) only when command options
or routing remain unclear.

## Evidence protocol

1. Pick one session tag for this conversation (for example `auth-fix-1`) and
   pass `--session <tag>` to every `search` and `explain`.
2. Run the best-matching command with `--json`.
3. Check `index` before trusting the payload:
   - missing → run `codebase-index index`, then repeat;
   - stale with fewer than 20 changed files → run `codebase-index update`;
   - stale with 20 or more changed files → run `codebase-index index`;
   - fresh → continue.
4. Start with ranks 1–3. Read only `recommended_reads` line ranges.
5. Trace one additional hop only when the question requires behavior,
   ownership, or impact.
6. Before answering or editing from evidence gathered earlier in the task, run
   `codebase-index verify --session <tag> --json` and reread anything whose
   state is not `valid` or `relocated`.
7. Answer with `file:line` evidence and state uncertainty explicitly.

Do not open whole files when a line range is available. A snippet may already
be sufficient. `skeletonized: true` means the response intentionally folded
unrelated body lines; read the supplied range when the missing body matters.

## Evidence memory

- `reused: true` with `snippet: null` — this session already received that
  exact text and its source is unchanged. Use your earlier copy; if you can no
  longer see it, Read the range.
- `memory.invalidated` — evidence this session received has changed since.
  Treat your earlier copy as wrong and reread before relying on it.
- `stale: true` — the index is older than the file. Run `codebase-index update`
  or Read the range.
- A tag belongs to one context. Never give it to a subagent or another
  conversation. Start a new tag after the context is cleared or compacted, or
  whenever earlier snippets are no longer visible to you.

Verdict states and citing evidence in notes: [references/memory.md](references/memory.md).

## Confidence contract

- **high** — answer from the indexed evidence.
- **medium** — read the recommended ranges and confirm the key claim with one
  targeted lookup if necessary.
- **low** or no results — follow `fallback_suggestions`, then use a narrow
  Grep/Glob fallback.

On `refs` and `impact`, inspect `coverage`. If `coverage.partial` is true, an
empty result is inconclusive; confirm with targeted Grep before saying that
nothing references the target.

Edges carry `confidence`:

- `extracted` — exact parser evidence;
- `inferred` — heuristic resolution;
- `ambiguous` — unresolved or non-unique.

Never present an inferred or ambiguous chain as certain.

## Answer contract

Structure repository answers around:

1. **Answer** — the direct conclusion.
2. **Evidence** — the minimum supporting `file:line` references.
3. **Confidence** — only when evidence is partial, inferred, stale, or missing.
4. **Next check** — only when another check would materially reduce uncertainty.

Do not narrate every search step. Do not claim absence from a partial graph.
Do not replace evidence with a generated HTML graph.

For payload fields and failure handling, read
[references/response-contract.md](references/response-contract.md).
