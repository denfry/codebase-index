# Retrieval Pipeline

The retrieval engine turns a natural-language or symbolic query into a **compact, ranked,
token-budgeted** set of file/line ranges for Claude to read. It is hybrid: multiple independent
retrievers run, their results are fused, reranked, expanded via the graph, then trimmed.

```
query
  │
  ▼
[1] intent detection ──────────────┐
  │                                │ selects retrievers + weights + graph strategy
  ▼                                ▼
[2] retrievers (run in parallel)
     ├─ exact path        (glob/path LIKE)
     ├─ symbol            (symbols table, exact + fuzzy)
     ├─ FTS keyword       (FTS5 bm25 over chunks + symbols + summaries)
     └─ vector  (opt-in)  (sqlite-vec / local embeddings)
  │
  ▼
[3] rank fusion  ── Reciprocal Rank Fusion (RRF) across retriever result lists
  │
  ▼
[4] rerank  ── feature-based score (symbol-kind, path proximity, recency, centrality)
  │
  ▼
[5] graph expansion  ── pull in imports/callers/callees per intent (bounded)
  │
  ▼
[6] token budgeting  ── greedy fill under --token-budget; snippets trimmed + secret-redacted
  │
  ▼
ranked results + recommended_reads + fallback_suggestions
```

## 1. Intent detection (`retrieval/intent.py`)

Cheap, rule-first classifier (regex/keyword heuristics; optionally a tiny local model later). Each
intent maps to a retriever mix, a graph strategy, and an output shape.

| Intent | Trigger examples | Retriever emphasis | Graph strategy |
|---|---|---|---|
| `locate_impl` | "where is X implemented", "find the X function" | symbol > path > fts | none / defs only |
| `how_it_works` | "how does X work", "explain X flow" | fts + symbol + vector | expand callees 1–2 hops |
| `impact` | "what breaks if I change X", "what depends on X" | symbol + path | expand callers/importers (up) |
| `find_refs` | "find references to X", "who calls X" | symbol | edges where target=X |
| `data_flow` | "trace data flow of X", "where does X get set" | symbol + fts | follow assignments/calls both ways |
| `debug_error` | pasted stack trace / "error: ...", "why does X fail" | fts (error string) + symbol | expand around match |
| `architecture` | "explain the architecture", "high-level overview" | summaries + graph centrality | package/module summaries |
| `keyword` | fallback when nothing matches above | fts + vector | none |

Each intent also sets a **default token budget** and whether to return module/package summaries
instead of code (e.g. `architecture` returns summaries first).

## 2. Retrievers (`retrieval/searchers.py`)

All retrievers return a uniform `Candidate(id, kind, path, line_start, line_end, symbol, score,
source)` list so fusion is source-agnostic.

- **Path** — exact and glob path matches (`src/auth/*.py`, `auth.py`). Highest precision; surfaced
  first when the query clearly names a path.
- **Symbol** — query against `symbols` (name exact, prefix, then fuzzy/trigram). Carries `kind`
  (function/class/method/...) and signature. Primary for `locate_impl` / `find_refs`.
- **FTS** — FTS5 `bm25()` over the `fts_chunks` virtual table (chunk text + symbol names +
  summaries indexed). Tokenizer is code-aware (splits camelCase/snake_case). Primary lexical signal.
- **Vector** *(opt-in)* — cosine similarity over chunk embeddings via `sqlite-vec`. Only runs if
  `embeddings.enabled = true`. Adds semantic recall for paraphrased queries. Absent → pipeline
  degrades gracefully to FTS+symbol.

## 3. Rank fusion (`retrieval/fusion.py`)

**Reciprocal Rank Fusion** combines the per-retriever ranked lists without needing comparable raw
scores:

```
RRF(d) = Σ_r  w_r / (k + rank_r(d))        # k ≈ 60, w_r = per-intent retriever weight
```

- Robust to scale differences between BM25 and cosine.
- Per-intent weights `w_r` let `locate_impl` favor the symbol list and `how_it_works` favor FTS.
- Ties broken by rerank features (next step).

## 4. Reranking (`retrieval/rerank.py`)

A lightweight, explainable feature score (no external model required) layered on the fused order:

| Feature | Intuition |
|---|---|
| symbol-kind match | a `def`/`class` outranks an incidental mention |
| path proximity | files near a query-named path score higher |
| graph centrality | high in/out-degree nodes matter more for `architecture` |
| recency | recently changed files (git mtime) slightly boosted |
| exact-name bonus | exact symbol-name match dominates fuzzy |
| test/generated penalty | test files and generated code demoted unless asked |

The reranker also produces the human-readable **`reason`** string per result
(e.g. *"exact symbol match · called by 4 sites · in src/auth/"*).

## 5. Graph expansion (`graph/expand.py`)

After reranking, pull in *related* nodes per the intent's graph strategy, bounded by `--depth`
(default 1–2) and a node cap:

- `impact` → walk **up** edges (callers, importers) = blast radius.
- `how_it_works` → walk **down** edges (callees, imported defs) = mechanism.
- `find_refs` → direct reverse edges only.
- `data_flow` → both directions along call/assignment edges.

Expanded nodes are merged into results with a discounted score so seeds stay on top.

## 6. Token budgeting (`retrieval/budget.py`)

Results are trimmed to fit `--token-budget` (default per intent, e.g. 1500 tokens):

1. Always include result metadata (path, line range, symbol, reason) — cheap.
2. Greedily attach snippets to the highest-ranked results until budget is hit.
3. Snippets are trimmed to the relevant line range (± a few context lines), not whole functions.
4. Lower-ranked results become **`recommended_reads`** (path + range, no snippet) so Claude can
   choose to read them itself.
5. Snippet text passes through secret redaction (see SECURITY.md) before emission.

The point: Claude gets enough to decide, and a precise list of what to read next — never a dump.

## 7. Confidence & fallback

A `confidence` score (high/medium/low) is derived from: top RRF score, score gap between #1 and #2,
number of agreeing retrievers, and whether a symbol matched exactly.

- **high** → Claude reads `recommended_reads` and answers.
- **medium** → Claude reads, but may verify with one Grep.
- **low** → skill instructs Claude to **fall back** to `ripgrep`/Grep/Glob with suggested patterns
  emitted in `fallback_suggestions` (derived from query terms + detected symbols).

## 8. Output payload (shared by Markdown + JSON)

```jsonc
{
  "query": "where is auth token refresh implemented",
  "intent": "locate_impl",
  "index": { "exists": true, "stale": false, "built_at": "...", "head_commit": "abc1234" },
  "confidence": "high",
  "results": [
    {
      "rank": 1,
      "path": "src/auth/token.py",
      "line_start": 88, "line_end": 134,
      "symbols": ["refresh_access_token"],
      "score": 0.91,
      "reason": "exact symbol match · 4 callers · in src/auth/",
      "snippet": "def refresh_access_token(...):\n    ..."
    }
  ],
  "recommended_reads": [
    { "path": "src/auth/token.py", "line_start": 88, "line_end": 134 },
    { "path": "src/auth/middleware.py", "line_start": 40, "line_end": 72 }
  ],
  "fallback_suggestions": {
    "ripgrep": ["rg -n \"refresh_access_token\" src/", "rg -n \"token.*refresh\""]
  }
}
```

The Markdown renderer (`output/markdown.py`) prints the same data as a tight table + fenced
snippets so it's compact in Claude's context. See SKILL.md for how Claude is told to read it.
