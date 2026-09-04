# Retrieval Pipeline

(`docs/RETRIEVAL_PIPELINE.md` was merged into this page.)

The retrieval engine turns a natural-language or symbolic query into a **compact, ranked,
token-budgeted** set of file/line ranges for Claude to read. It is hybrid: multiple independent
retrievers run, their results are fused and reranked, then trimmed. Graph expansion and MMR are
available as bounded opt-in signals; the shipped default prioritizes direct evidence.

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
[4] rerank  ── feature-based score (symbol-kind, path, source role, centrality)
  │
  ▼
[5] optional graph expansion  ── pull in imports/callers/callees per intent (bounded)
  │
  ▼
[6] diversity / duplicate filtering (MMR opt-in, SimHash duplicate guard)
  │
  ▼
[7] token budgeting  ── greedy fill under --token-budget; snippets trimmed + secret-redacted
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
- **Symbol** — query against `symbols` (exact, identifier parts, bounded fuzzy matching). Carries
  `kind` (function/class/method/...) and signature. Primary for `locate_impl` / `find_refs`.
  Fuzzy identifier matching (acronym / concatenation / edit distance) runs only as a **recall
  fallback**, when the precise lookup named no symbol and returned fewer than
  `fuzzy_fallback_min` rows. Measured over 305 queries on three repositories it moved no ranking
  metric while costing ~20% of query latency, so it is kept for typos and abbreviations but no
  longer runs when the query already spelled its identifier correctly.
- **FTS** — FTS5 `bm25()` over the `fts_chunks` virtual table (chunk text + symbol names
  indexed). Query-time camelCase/snake_case splitting, a small down-weighted synonym/inflection
  vocabulary, OR-groups for soft matching with bounded term coverage, and ranking by
  original-term coverage with BM25 as a tie-break make natural-language questions robust without
  weakening exact terms. Every FTS term is quoted so query punctuation cannot inject MATCH
  operators.
- **Vector** *(opt-in)* — cosine similarity over chunk embeddings via `sqlite-vec`. Only runs if
  `embeddings.enabled = true`. Adds semantic recall for paraphrased queries. Absent → pipeline
  degrades gracefully to FTS+symbol.

## 3. Rank fusion (`retrieval/fusion.py`)

**Reciprocal Rank Fusion** combines the per-retriever ranked lists without needing comparable raw
scores:

```
RRF(d) = Σ_r  w_r · k / (k + rank_r(d))    # k ≈ 60, w_r = per-intent retriever weight
```

- Robust to scale differences between BM25 and cosine.
- Per-intent weights `w_r` let `locate_impl` favor the symbol list and `how_it_works` favor FTS.
- Scaled by `k` so fused scores and the reranker's bounded bonuses share an O(1) scale. This is a
  monotonic rescale; fusion order is unchanged.
- Ties broken by rerank features (next step).

### Cross-locator file agreement

Fusion keys on `(path, line-bucket)`, not `(path, start, end)`, because different retrievers report
different line ranges for the same place. Bucketing alone was not enough: a symbol defined at line
40 and a lexical hit at line 120 are genuinely different locators, so a file that **two retrievers
agreed on** still fused as two separate candidates, each carrying one retriever's evidence — and
cross-source agreement, the entire point of RRF, never fired.

Each candidate therefore also receives, at weight `file_agreement_weight`, the RRF mass of every
retriever that found its *file* at some other locator:

```
score(d) = RRF(d) + α · Σ_{r ∉ sources(d)}  w_r · k / (k + best_rank_r(path(d)))
```

Retrievers already counted at the candidate's own locator are excluded, so nothing double-counts,
and the term is bounded by the same weights as fusion itself. `α = 0.4`; the 0.3–0.6 plateau peaks
there. Set `RetrievalTuning(file_agreement=False)` to recover plain locator-only RRF.

## 4. Reranking (`retrieval/rerank.py`)

A lightweight, explainable feature score (no external model required) layered on the fused order.
Every term is bounded, so reranking reorders near-neighbours rather than overruling retrieval:

| Feature | Effect | Intuition |
|---|---:|---|
| Exact symbol match | +0.20 | the user named a specific symbol |
| Symbol definition kind | +0.05 | a `def`/`class` outranks an incidental mention |
| Symbol name among query terms | +0.05 | the name was asked for, not just matched |
| Path term match | +0.05 | the user supplied a location clue |
| Graph centrality (`in_degree`) | ≤ +0.08 | `log1p`-damped, so a god class cannot dominate |
| Reference-count fallback | ≤ +0.04 | for names too common to resolve a precise `in_degree` |
| Source role prior | −0.25…+0.08 | see below |
| Generated, or test on a non-test query | −0.15 | supporting evidence, not the answer |

### Source role priors (`retrieval/priors.py`)

| Role | Prior | Rationale |
|---|---:|---|
| Implementation | +0.08 | the answer to a code question is usually code |
| Test | −0.06 | flips to +0.05 when the query or intent is test-oriented |
| Documentation | −0.20 | prose *about* a feature matches a natural-language question more literally than the code implementing it, so design notes and plans crowded out the modules they describe |
| Generated / vendor / build | −0.25 | never the answer; kept strictly below documentation |

The documentation prior deepened from −0.05 in 1.8.0. Because it only reorders prose relative to
code — never below other prose — documentation-seeking queries improved too (MRR 0.579 → 0.612).
At −0.35 that reverses and the `docs` category collapses, so the optimum is interior, not a
"more is better" knob. `MAX_ABS_PRIOR` caps every prior so this stays a tiebreaker.

The reranker also produces the human-readable **`reason`** string per result
(e.g. *"exact symbol match · 4 callers · in src/auth/"*).

## 5. Graph expansion (`graph/retrieval.py`; `graph/expand.py` for impact APIs)

Graph expansion runs only when the tuning enables `graph_source` and the intent plan requests a
graph strategy. It is disabled by default because the reproducible self-repository ablation
reduced direct-hit MRR when related nodes displaced lexical hits.

When enabled, it is bounded by depth and node cap:

- `impact` → walk **up** edges (callers, importers) = blast radius.
- `how_it_works` → walk **down** edges (callees, imported defs) = mechanism.
- `find_refs` → walk **up** edges to callers/importers.
- `data_flow` → walk **both** directions along call/assignment edges.

Expanded nodes retain edge confidence and receive distance-decayed scores so seeds stay on top.

## 6. Diversity and duplicate control

`retrieval.diversity` provides bounded MMR selection and SimHash near-duplicate suppression.

MMR is disabled in the shipped default: it moved no ranking metric on the benchmark and roughly
doubled p50 latency. Callers that need broader snippet coverage can enable
`RetrievalTuning(mmr=True)`.

SimHash duplicate suppression stays on, but on noise grounds rather than ranking grounds: it does
not move MRR, and it takes the duplicate rate of returned snippets from ~1.6% to ~0%. The
over-fetch that feeds selection is now an explicit `candidate_pool_multiplier` rather than an
implicit side effect of enabling dedup — an earlier ablation credited dedup with a quality win that
was really the wider pool doing the work.

## 7. Token budgeting (`retrieval/budget.py`)

Results are trimmed to fit `--token-budget` (default per intent, e.g. 1500 tokens):

1. Always include result metadata (path, line range, symbol, reason) — cheap.
2. Greedily attach snippets to the highest-ranked results until budget is hit.
3. Snippets are trimmed to the relevant line range (± a few context lines), not whole functions.
4. Lower-ranked results become **`recommended_reads`** (path + range, no snippet) so Claude can
   choose to read them itself. A read is capped at `retrieval.max_read_lines` (default 120): a
   symbol-aligned chunk can be a whole class, and the read plan should bill the agent for the
   definition head, not the body. Capped entries carry `truncated: true` and `line_end_full`.
5. Snippet text passes through secret redaction (see SECURITY.md) before emission.

The point: Claude gets enough to decide, and a precise list of what to read next — never a dump.

## 8. Confidence & fallback

A categorical `confidence` (high/medium/low) is derived from exact-symbol evidence,
multi-retriever agreement, score separation between #1 and #2, and result count. An exact symbol
match is `high`, including a single-result response.

- **high** → Claude reads `recommended_reads` and answers.
- **medium** → Claude reads, but may verify with one Grep.
- **low** → skill instructs Claude to **fall back** to `ripgrep`/Grep/Glob with suggested patterns
  emitted in `fallback_suggestions` (derived from query terms + detected symbols): `rg` patterns,
  likely paths, and query-broadening hints.

Default token budget: 1500 for `search`, 2200 for `explain`, configurable per project in
`.claude/cache/codebase-index/config.json` (`retrieval.token_budget`).

## 9. Output payload (shared by Markdown + JSON)

```jsonc
{
  "query": "where is auth token refresh implemented",
  "intent": "locate_impl",
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
