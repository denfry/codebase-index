# Response Contract

Load this reference when interpreting a retrieval packet or handling a weak
result.

## Ranked results

Each result can contain:

- `rank`
- `path`
- `line_start` / `line_end`
- `symbols`
- `score`
- `reason`
- `snippet`
- `skeletonized`
- `elided_lines`

`recommended_reads` is the read plan. Start with its first one to three entries
and use exact line ranges.

`pagination.has_more` and `pagination.next_offset` indicate additional results.
Prefer a more specific command or a larger token budget before paging.

## Freshness

The `index` object is part of the evidence contract:

```text
exists=false                           → index
stale=true, files_changed_since_build<20 → update
stale=true, files_changed_since_build≥20 → full index
stale=false                            → proceed
```

Repeat the original query after rebuilding or updating.

## Weak results

Fallback is allowed only when:

- results are empty;
- confidence is low;
- graph coverage is partial;
- the requested information is not represented by the index.

Use `fallback_suggestions.ripgrep` first. Otherwise construct one narrow Grep
pattern from the most distinctive symbol, error, or path in the question.
Avoid a full-repository scan unless targeted fallback also fails.

If several queries are weak:

```bash
codebase-index stats --json
codebase-index doctor
```

Report the limitation instead of inventing certainty.

## Answer examples

High confidence:

```text
Session validation is implemented in `src/auth/session.py:44`.
The request middleware calls it from `src/http/auth.py:18`.
```

Partial graph:

```text
The index found no graph-backed callers, but coverage for Lua is partial.
A targeted text search still finds two call sites in …
```

Inferred chain:

```text
The route-to-service link is parser-extracted; the service-to-model link is
heuristic, so the final hop should be verified before refactoring.
```
