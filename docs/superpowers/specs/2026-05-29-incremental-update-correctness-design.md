# Incremental Update Correctness — Design

**Date:** 2026-05-29
**Status:** Approved (brainstorming)
**Sub-project:** A of a 4-part "perfect the indexing" effort (A: incremental
correctness · B: more languages · C: search/ranking quality · D: large-repo
performance). This spec covers **A only**.

## Problem

`update_index` (`src/codebase_index/indexer/pipeline.py:218`) is the engine
behind the freshness contract and the `PostToolUse` hook that runs after every
`Write`/`Edit`. For a changed file it currently does **only** line-chunking:

```python
file_chunks = chunk_text(_read_text(cand.path), ...)
repo.replace_chunks(conn, file_id, file_chunks)   # no symbol_ids
```

Compared to the full `build_index` per-file path, the incremental path skips:

1. **Symbols** — `replace_symbols` is never called, so stale symbols from the
   previous full build remain in the `symbols` table with outdated line ranges.
2. **Chunk↔symbol linkage** — `replace_chunks` is called without `symbol_ids`,
   so every chunk's `symbol_id` becomes `NULL` (symbol-aligned chunks are lost).
3. **Edges** — `replace_edges` is never called, so import/call/inheritance edges
   go stale.
4. **Doc chunks** — `extract_doc_chunks` is never run for the changed file.
5. **Graph degrees / cross-file resolution** — `build_graph` is never re-run, so
   `in_degree`/`out_degree` and resolved-edge state drift.
6. **Embeddings** — changed chunks keep stale vectors (or none).

**Net effect:** the index degrades after every hook-triggered `update`. A full
`build_index` is correct; the incremental path is not.

Existing `tests/test_update.py` only asserts chunk content, fingerprints, and
pruning — none assert symbol/edge freshness, which is why the bug went unnoticed.

## Approach

**Chosen:** extract the full per-file indexing work into one shared routine used
by **both** `build_index` and `update_index`. A single source of truth makes
drift between the two paths impossible by construction.

Rejected alternatives:
- *Duplicate the full per-file logic into `update_index`* — reintroduces two
  copies to maintain; the same class of bug returns on the next change.
- *Delegate `update` to `build_index` for changed files* — `build_index` walks
  the whole tree and prunes globally; scoping it cleanly is harder than sharing
  a per-file routine.

## Design

### Component 1 — shared per-file indexing

New function:

```python
def _index_file(conn, cand, config, now, stats) -> None
```

Encapsulates what the `build_index` loop body currently does
(`pipeline.py:55-85`):

- `repo.upsert_file(...)`
- `text = _read_text(cand.path)`
- `outcome = _parse(cand.lang, cand.parser, text, config)`
- `symbol_ids = repo.replace_symbols(conn, file_id, parse_result.symbols)`
- `repo.replace_chunks(conn, file_id, parse_result.chunks, symbol_ids=symbol_ids)`
- doc chunks via `extract_doc_chunks` + `repo.append_chunks`
- `edge_rows = _resolve_edges(...)` + `repo.replace_edges(...)`
- increments **all** `BuildStats` fields it touches: `chunks`, `symbols`,
  `edges`, `parse_failed`, `treesitter_zero_symbols`, `indexed`, `total_bytes`.

Both `build_index` and `update_index` call `_index_file` for each file they
decide to (re)index. `build_index`'s loop becomes a thin wrapper; `update_index`
calls it in place of the current line-chunk-only block.

### Component 2 — finalize on update

After the `update_index` walk loop, when at least one file was reindexed
(`stats.indexed > 0`):

- `graph = build_graph(conn)` → set `stats.edges_resolved` (same as build).
- if `config.embeddings.enabled`: `stats.vectors = _embed_chunks(config, db, conn)`
  (same as build).

When `stats.indexed == 0` (no-op update), **both** heavy operations are skipped,
preserving the current cheap no-op fast path. Incremental optimization of the
graph rebuild and embedding pass (avoid recomputing the whole DB) is explicitly
deferred to sub-project D.

### Data flow

```
walk → (per file to index) _index_file → [after loop, if indexed>0] build_graph + embed → commit
```

Identical to `build_index`; the only difference is the filter deciding which
files are touched (mtime/sha fast-path, `--since` scope, `--all`).

### Scope interactions (unchanged behavior, confirmed correct)

- `--since <ref>`: only scoped files are reindexed; `build_graph` still runs
  globally — correct, since edge resolution is cross-file.
- `--all`: forces re-hash even when mtime matches; each reindexed file flows
  through `_index_file`.
- content-identical touch (sha matches): still just bumps mtime and counts as
  skipped — no symbol change, so no reindex needed.
- `watch` mode: unaffected; it coalesces edits into one debounced `update`.

### Error handling

The `_parse` contract is preserved: parse errors are counted in `parse_failed` /
`treesitter_zero_symbols`, never swallowed, with line-chunk fallback. No new
exceptions are introduced.

## Testing (TDD)

New tests in `tests/test_update.py` (each would fail against the current bug):

1. After editing a file, `symbols` reflect the new content — old symbols gone,
   new symbols present with correct line ranges.
2. Chunks of the edited file regain a non-`NULL` `symbol_id` (symbol alignment
   restored).
3. Edges of the edited file are rebuilt; `stats.edges_resolved` is recomputed.
4. Doc chunks are refreshed on edit.
5. With embeddings enabled, vectors for changed chunks are recomputed.
6. No-op `update` (no changes) does **not** run `build_graph` / embed — fast
   path preserved (assert via stats or spy).
7. Regression: the existing 4 `test_update.py` tests stay green.

## Out of scope (other sub-projects)

- B: additional tree-sitter languages.
- C: ranking/intent/snippet quality.
- D: incremental graph + embedding recomputation, large-repo performance.
