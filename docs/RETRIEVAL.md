# Retrieval Pipeline

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
[4] rerank  ── query↔candidate features: name co-occurrence, symbol, path, source role, centrality
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
- **FTS** — FTS5 `bm25()` over the `fts_chunks` virtual table (chunk text + symbol names +
  summaries indexed). Query-time camelCase/snake_case splitting, small down-weighted synonym
  expansion, and soft coverage scoring make natural-language questions robust without weakening
  exact terms.
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
Most terms are bounded tiebreakers, so they reorder near-neighbours rather than overruling
retrieval. The exception is name co-occurrence, which is deliberately large enough to move a
candidate several places — see below for why, and for the evidence that it should.

| Feature | Effect | Intuition |
|---|---:|---|
| Query terms co-occurring in one name | ≤ +1.80 | several query terms in one name is qualitatively better evidence than one term matched well |
| Exact symbol match | +0.20 | the user named a specific symbol |
| Symbol definition kind | +0.05 | a `def`/`class` outranks an incidental mention |
| Symbol name among query terms | +0.05 | the name was asked for, not just matched |
| Path term match | +0.05 | the user supplied a location clue |
| Graph centrality (`in_degree`) | ≤ +0.08 | `log1p`-damped, so a god class cannot dominate |
| Reference-count fallback | ≤ +0.04 | for names too common to resolve a precise `in_degree` |
| Source role prior | −0.25…+0.08 | see below |
| Generated, or test on a non-test query | −0.15 | supporting evidence, not the answer |

### Name co-occurrence (`retrieval/features.py`)

Every retriever scores each query term independently, and RRF sums those independent verdicts. That
structure cannot distinguish a candidate which matched **one** query term very well from one which
matched **three** terms in a single name — and on the 1.9.0 benchmark that confusion was the single
largest reranking loss. Two measured examples, both ranked wrong by 1.9.0:

| Query | 1.9.0 winner | correct answer, ranked below it |
|---|---|---|
| "graph resolution + traversal accessors" | `graph/retrieval.py` (`graph`) | `test_graph_accessors_resolve_and_walk` (`graph` + `accessors` + `resolve`) |
| "greedy token budgeting with redaction" | `output/redact.py` (`redact`) | `retrieval/budget.py` (`budget` + `token`) |

The fix is an interaction term, not another per-term bonus. Let `zone(d)` be the identifier
components of the candidate's *name* — file basename plus symbol, camel/snake split — and `m` the
number of salient query terms appearing in it:

```
cooccurrence(d) = max(0, m - 1) / (n_terms - 1)          # 0 when m < 2
score(d)       += w · cooccurrence(d) · (scale if demoted else 1)
```

Only terms **beyond the first** earn credit: a single matched term is already fully paid for by the
retriever that surfaced the candidate, so crediting it again would merely re-weight lexical
matching, which is not what was missing. Directories are excluded from the zone —
`src/main/java/net/...` is shared by hundreds of files, so it adds co-occurrence noise to all of
them and evidence to none.

`w = 1.8` sits in the interior of a plateau. Pooled MRR rises to ≈1.8 and then flattens, and past
that point per-query wins stay flat while losses nearly double (37W/19L at 1.8 against 39W/32L at
4.0), because a larger bonus turns the feature into the primary sort key and reduces fusion to a
tiebreak. Every value in 1.0–4.0 leaves all eight benchmark corpora at or above 1.9.0.

`scale = 0.5` discounts — rather than withholds — the bonus for test and generated sources. Test
function names are descriptive sentences (`test_compactor_output_is_redacted`), so they harvest
query-term co-occurrences that real identifiers never do, and a bonus reaching +1.8 is not
counterbalanced by a flat −0.15 demotion calibrated when the largest name bonus was +0.05. The
value was chosen by splitting the benchmark on whether its *own ground truth* is a test: across the
261 queries whose answer is not a test, the gain is flat at +0.020 MRR for every scale, so the
entire aggregate difference between 0.5 and 1.0 comes from the 159 test-answer queries — an
artifact of mining ground truth from commits, which touch tests. 0.5 is the only setting that
improves both partitions.

Variants that were measured and **rejected**, each failing to beat this one on held-out
repositories: idf weighting of the matched terms (pool-local and corpus-wide); substring instead of
component matching; prefix/stem-tolerant matching (`redact`/`redacted`); ordered-subsequence
matching; term proximity within the chunk body; body-text coverage; zone-size ("tightness")
normalisation; and restricting the zone to the filename or the symbol alone. A pairwise logistic
ranker fitted over 19 candidate features selected this one, and forward selection found no second
feature clearing the noise floor — so one feature ships, not a model.

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

## 6. Diversity, page packing, and duplicate control

`retrieval.diversity` provides bounded MMR selection and SimHash near-duplicate suppression.

### Page packing (`max_per_file`)

The agent's unit of decision is "which file do I open", so a 10-result page that spends three
slots on three regions of one file offers seven choices, not ten. Measured across eight
repositories, 1.9.0's page held **7.1 distinct files** on average, and of the queries whose answer
was in the candidate pool but missing from the page, 45 of 57 had it sitting past rank 10 — crowded
out by repeat hits rather than by better candidates.

`max_per_file = 1` keeps one hit per file in place and pushes the rest to the tail. Nothing is
dropped, so a file with several relevant regions still surfaces them below the first page. The
parameter is monotone over 1–5 (1 > 2 > 3 > 4 > 5), so this is a plateau boundary rather than a
fitted peak: recall@10 +0.045 and nDCG@10 +0.015 against 1.9.0's value of 3, at unchanged token
cost, with no metric and no corpus regressing.

### MMR

MMR is disabled in the shipped default: it moved no ranking metric on the benchmark and roughly
doubled p50 latency. Callers that need broader snippet coverage can enable
`RetrievalTuning(mmr=True)`.

### Duplicate suppression

SimHash duplicate suppression stays on, but on noise grounds rather than ranking grounds: it moves
MRR by −0.0016 (p=0.006) and takes the duplicate rate of returned snippets to ~0%. The over-fetch
that feeds selection is an explicit `candidate_pool_multiplier` rather than an implicit side effect
of enabling dedup — an earlier ablation credited dedup with a quality win that was really the wider
pool doing the work.

Only the leading 2000 characters of a candidate body decide duplication. Fingerprinting whole chunk
bodies made this the most expensive stage of the query path — 42% of it on the Java corpus — to
answer a question the first ~50 lines already answer: two chunks that agree for 2000 characters are
the same snippet. The bound leaves recall, duplicate rate and useful-context identical and MRR
within −0.0003 (p=0.51). Combined with a rewritten operator scan in the tokeniser (1.71× faster,
bit-identical output), duplicate control costs roughly half what it did in 1.9.0.

## 7. Token budgeting (`retrieval/budget.py`)

Results are trimmed to fit `--token-budget` (default per intent, e.g. 1500 tokens):

1. Always include result metadata (path, line range, symbol, reason) — cheap.
2. Greedily attach snippets to the highest-ranked results until budget is hit.
3. Snippets are trimmed to the relevant line range (± a few context lines), not whole functions.
4. Lower-ranked results become **`recommended_reads`** (path + range, no snippet) so Claude can
   choose to read them itself.
5. Snippet text passes through secret redaction (see SECURITY.md) before emission.

The point: Claude gets enough to decide, and a precise list of what to read next — never a dump.

## 8. Confidence & fallback

A `confidence` score (high/medium/low) is derived from: top RRF score, score gap between #1 and #2,
number of agreeing retrievers, and whether a symbol matched exactly.

- **high** → Claude reads `recommended_reads` and answers.
- **medium** → Claude reads, but may verify with one Grep.
- **low** → skill instructs Claude to **fall back** to `ripgrep`/Grep/Glob with suggested patterns
  emitted in `fallback_suggestions` (derived from query terms + detected symbols).

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

## 10. Ranking diagnostics (`--explain`)

Every result already carries a `reason` string, but diagnosing *why the ranking was wrong* needs
the order before reranking as well as after. `search(..., explain=True)` adds a `diagnostics`
block containing the pre-rerank candidate pool and the final order, each with per-candidate
source, symbol, score and retriever agreement. Building it costs about thirty dict literals per
query — measured at −0.8ms p50, i.e. inside the noise of a 40ms query — and nothing is allocated
when the flag is off.

This is what the evaluation harness uses to compute the **oracle** metrics, and it is what turns
"MRR is low" into an actionable decomposition:

| Metric | Question it answers |
|---|---|
| `oracle` | what MRR a *perfect* reranker would score over the pool actually generated |
| `1 - oracle` | the share of queries only better **recall** can ever fix |
| `eff` = MRR / oracle | the share of achievable ranking quality actually delivered |

At 1.9.0 that split read `oracle = 0.902`, `MRR = 0.577`, `eff = 0.639`: a third of the answers
already sitting in the candidate pool were ranked below something else, an error mode roughly
three times larger than the remaining 0.098 of recall headroom. That measurement is why 1.10.0
spent its effort on the reranker instead of adding retrievers.
