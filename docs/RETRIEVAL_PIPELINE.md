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
│ 5. Graph expansion (explicit opt-in)   │
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

**Trigger:** General keyword and natural-language queries.

**Process:**
- Parse identifiers into camelCase/PascalCase/snake_case subtokens.
- Add a small, explicit synonym/inflection vocabulary at lower weight.
- Use OR groups for soft matching, then require bounded term coverage and rank
  by original-term coverage plus BM25.
- Quote every FTS term so query punctuation cannot inject MATCH operators.

**Score:** Coverage is the primary signal; BM25 is a bounded tie-break.

## 4. Vector Search (Optional)

**Trigger:** Enabled when `embeddings.backend` is not "noop".

**Process:**
- Embed the query using the configured backend
- Search `vec_chunks` for nearest neighbors
- Return chunks with cosine similarity scores

**Score:** Cosine similarity (0.0 to 1.0).

> **Indexing note:** chunk embeddings are reused across rebuilds via a content-addressed
> `vec_cache` (keyed by model + content SHA-256), so only new or changed chunks are re-embedded.
> See [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md) and [SCHEMA.md](SCHEMA.md) for details.

## 5. Graph Expansion

**Trigger:** `RetrievalTuning(graph_source=True)` and an intent plan with a
graph strategy. It is disabled in the shipped default because the reproducible
self-repository ablation reduced direct-hit MRR.

**Process:**
- Seed from lexical/symbol candidates already found in SQLite.
- Traverse only indexed, resolved edges with bounded depth and node count.
- Follow `up` (callers/importers), `down` (callees/imports), or `both`
  according to the intent plan.
- Apply distance decay and preserve edge confidence in the candidate reason.

Graph expansion is an opt-in context-discovery signal, not a replacement for
direct lexical or symbol evidence.

## 6. Diversity and duplicate control

SimHash suppresses near-duplicate snippets independently of MMR. It does not move
ranking metrics; it earns its place by taking the duplicate rate of returned
snippets from ~1.6% to ~0%. Bounded Maximal Marginal Relevance is available
through `RetrievalTuning(mmr=True)`; the shipped default keeps relevance-only
ordering because MMR moved no metric and roughly doubled p50 latency.

The over-fetch that feeds these selection stages is `candidate_pool_multiplier`
(default 2), an explicit knob rather than a side effect of enabling dedup.

## 7. Reciprocal Rank Fusion (RRF)

Combines ranked lists from the enabled retrievers:

```
RRF_score(d) = Σ_r w_r · k / (k + rank_r(d))
```

The implementation multiplies textbook RRF by `k` so fusion and bounded rerank
bonuses share a comparable scale; ordering is unchanged.

Where:
- `k` is a constant (default 60)
- `rank_r(d)` is the rank of document `d` in retriever `r`
- `w_r` is the intent/tuning weight for retriever `r`

Candidates are keyed by `(path, line-bucket)`, so co-located hits merge. Because a
symbol definition and a lexical hit in the same file are often *not* co-located,
each candidate additionally receives — at `file_agreement_weight` (0.4) — the RRF
mass of every retriever that found its file at a different locator. Retrievers
already counted at that locator are excluded, so nothing double-counts. Without
this, two retrievers agreeing on a file produced two weak candidates instead of one
strong one, and cross-source agreement never affected the score.

## 8. Reranking

After fusion, apply explainable query↔candidate boosts and penalties. All but the
first are bounded tiebreakers; the co-occurrence term is deliberately larger,
because it is the only signal that can see an *interaction* between query terms
rather than another independent per-term match.

| Factor | Effect | Rationale |
|---|---:|---|
| Query terms co-occurring in one name | up to +1.80 | Several query terms in one filename/symbol beats one term matched well; RRF sums per-term evidence and cannot see this |
| Exact symbol match | +0.20 | User named a specific symbol |
| Symbol definition kind | +0.05 | Prefer actionable definitions |
| Path term match | +0.05 | User supplied a location clue |
| Degree / reference evidence | up to +0.08 | Stable structural tiebreaker |
| Implementation source prior | +0.08 | Prefer source over prose/tests |
| Documentation source prior | -0.20 | Prose describing a feature outmatches the code lexically |
| Generated/vendor/build | -0.25 | Suppress low-value derived code |
| Test path on non-test query | -0.06 | Keep tests as supporting evidence |

The co-occurrence bonus is halved for test and generated sources: descriptive test
function names (`test_compactor_output_is_redacted`) are word bags that collect
query-term matches real identifiers never do. See `retrieval/features.py` and
[RETRIEVAL.md](RETRIEVAL.md) §4 for the measurement behind both numbers.

## 8a. Page packing

Selection keeps **one hit per file** on the page and pushes further hits from the
same file to the tail. The agent decides at file granularity, so three regions of
one file occupy three of ten slots while offering one choice. Nothing is dropped;
recall@10 improves because distinct files now fit.

## 9. Confidence

Confidence is categorical (`high`, `medium`, `low`) and is derived from
exact-symbol evidence, multi-retriever agreement, score separation, and result
count. Exact symbol matches are `high`, including a single-result response.

| Confidence | Action |
|---|---|
| `high` | Read recommended ranges and answer directly |
| `medium` | Read ranges; optionally confirm with one Grep |
| `low` | Use fallback suggestions (ripgrep, Glob) |

## 10. Token Budget Enforcement

The output is capped at a configurable token budget:

1. Results are sorted by final score
2. Snippets are included until the budget is reached
3. Remaining results are listed without snippets
4. The `recommended_reads` field contains only the most critical line ranges

Default budget: 1500 tokens (configurable in `.codeindex.json`).

## 11. Fallback Suggestions

When confidence is low, the pipeline generates fallback strategies:

- **ripgrep patterns:** Extracted keywords from the query, formatted for `rg`
- **likely paths:** Common directories to search based on query terms
- **broaden query:** Suggestions for rewording the query

These are included in the response so Claude can fall back gracefully.
