# Retrieval Pipeline

How `codebase-index` finds and ranks relevant code for a query.

## Overview

The retrieval pipeline combines multiple search strategies into a single ranked result set.

```
User query
    ↓
Intent detection (keyword / symbol / impact / general)
    ↓
┌─────────────────────────────────────────┐
│           Parallel Retrievers            │
├─────────────────────────────────────────┤
│ 1. Exact symbol match                   │
│ 2. Path-based search                    │
│ 3. SQLite FTS5 lexical search           │
│ 4. Vector search (optional embeddings)  │
│ 5. Graph expansion (from seed results)  │
└─────────────────────────────────────────┘
    ↓
Reciprocal Rank Fusion (RRF)
    ↓
Reranking (boosts for symbol match, recency, file type)
    ↓
Token budget enforcement
    ↓
Ranked retrieval packet with confidence score
```

## 1. Exact Symbol Match

**Trigger:** Query matches a known symbol name exactly or with minor variation.

**Process:**
- Look up the symbol in the `symbols` table
- Return the definition file and line range
- Include all reference locations from the `edges` table

**Score boost:** Highest priority — exact symbol matches are ranked first.

## 2. Path-Based Search

**Trigger:** Query contains file path fragments or recognizable path patterns.

**Process:**
- Match query terms against file paths in the `files` table
- Use substring matching with path segment awareness

**Score boost:** Moderate — path matches indicate the user knows where to look.

## 3. SQLite FTS5 Lexical Search

**Trigger:** General keyword queries.

**Process:**
- Build an FTS5 query from the user's text
- Tokenize: split `snake_case`, expand `camelCase` at query time
- Search the `fts_chunks` virtual table
- Return matching chunks with BM25-style scores

**Score:** Based on FTS5 rank — higher for more term matches and rarer terms.

## 4. Vector Search (Optional)

**Trigger:** Enabled when `embeddings.backend` is not "noop".

**Process:**
- Embed the query using the configured backend
- Search `vec_chunks` for nearest neighbors
- Return chunks with cosine similarity scores

**Score:** Cosine similarity (0.0 to 1.0).

## 5. Graph Expansion

**Trigger:** After initial results are found.

**Process:**
- For each seed result, traverse the dependency/call graph
- Find related files: callers, callees, imports, inheritors
- Add related files with a decay factor (distance from seed)

**Score:** Decreases with graph distance — direct connections score higher.

## Reciprocal Rank Fusion (RRF)

Combines results from multiple retrievers:

```
RRF_score(d) = Σ (1 / (k + rank_r(d)))
```

Where:
- `k` is a constant (default 60)
- `rank_r(d)` is the rank of document `d` in retriever `r`
- Sum is over all retrievers that returned `d`

This ensures documents that appear in multiple retrievers rank higher.

## Reranking

After fusion, apply additional boosts:

| Factor | Boost | Rationale |
|---|---|---|
| Exact symbol match | +0.3 | User named a specific symbol |
| File type relevance | +0.1 | `.ts` for TypeScript queries, etc. |
| Recency | +0.05 | Recently modified files may be more relevant |
| File size | -0.05 per 10KB | Prefer focused files over large ones |

## Confidence Score

The final confidence score (0.0 to 1.0) determines how Claude should proceed:

| Confidence | Meaning | Action |
|---|---|---|
| 0.8 - 1.0 | High | Read recommended ranges and answer directly |
| 0.5 - 0.8 | Medium | Read ranges; optionally confirm with one Grep |
| 0.0 - 0.5 | Low | Use fallback suggestions (ripgrep, Glob) |

## Token Budget Enforcement

The output is capped at a configurable token budget:

1. Results are sorted by final score
2. Snippets are included until the budget is reached
3. Remaining results are listed without snippets
4. The `recommended_reads` field contains only the most critical line ranges

Default budget: 2000 tokens (configurable in `.codeindex.json`).

## Fallback Suggestions

When confidence is low, the pipeline generates fallback strategies:

- **ripgrep patterns:** Extracted keywords from the query, formatted for `rg`
- **likely paths:** Common directories to search based on query terms
- **broaden query:** Suggestions for rewording the query

These are included in the response so Claude can fall back gracefully.
