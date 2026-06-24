# Snippet Skeletonization & Content-Aware Rendering — Design

- **Date:** 2026-06-24
- **Status:** Approved (design); pending implementation plan
- **Author:** denfry (with Claude)
- **Inspiration:** [`headroomlabs-ai/headroom`](https://github.com/headroomlabs-ai/headroom) — its
  AST structure handler (`compression/handlers/code_handler.py`), `StructureMask`
  (`compression/masks.py`), and content-type routing (`compression/detector.py`).

## 1. Summary

Make retrieval snippets carry **structure, not bulk**. Today a result's `snippet` is the raw
text of a code chunk. This design transforms that text, at retrieval time, into a
**skeleton**: import/signature/class/type lines are kept, function/method bodies are elided to a
marker (`… 24 lines elided (read 88–134)`), and the line(s) that actually match the query are
always preserved (**focus skeleton**). The transform is content-aware — code, markdown, and
structured config each get an appropriate line classifier; everything else is left untouched.

The win is the skill's reason to exist: more relevant results fit in the same `token_budget`.
The transform is **reversible** — `recommended_reads` and each result's `line_start`/`line_end`
remain the path to the full body — and **lossless-safe** — it never produces a worse result than
today (guards fall back to the raw snippet).

This ports the *idea* at the heart of headroom (separate structural tokens from compressible
ones) but adapts it for a **retrieval** system rather than a generic compression middleware: we
preserve the matched line, we route by file extension instead of an ML detector, and we operate
at line granularity instead of token granularity.

## 2. Goals / Non-goals

**Goals**

- Reduce per-snippet token cost so `apply_budget` attaches snippets to **more** ranked results.
- Preserve the query-matching line(s) in every code snippet (focus skeleton).
- Route by content type: code → AST skeleton, markdown → heading skeleton, structured config →
  key skeleton, everything else → unchanged.
- Be reversible and never degrade output (raw fallback on any failure or non-win).
- Tell Claude what was compressed (`skeletonized`, `elided_lines`) and where to expand.

**Non-goals (YAGNI)**

- No ML content detector (Magika). We already know the path → `detect_language`.
- No index-time skeleton sidecar (storing skeletons in the DB). Retrieval-time only; revisit only
  if parsing cost ever shows up in profiling. tree-sitter parse of a small chunk is ~ms.
- No log-dedup renderer — a code index does not carry logs.
- No change to indexing, chunking, FTS, or vector storage. Recall is untouched.

## 3. Background — current snippet flow

`query → intent → retrievers → RRF fuse → rerank → budget → payload`
(`retrieval/pipeline.py:search`).

- `Candidate` (`retrieval/types.py`) carries `path`, `line_start`, `line_end`, `source`,
  `content`, `token_est`, plus graph/score fields.
- `content` is populated raw by two retrievers:
  - `fts_candidates` → `content = row["content"]` (a line-window chunk; **raw code**).
  - `vector_candidates` → `content = row["content"]` (chunk text; **raw code**).
  - `symbol_candidates` → `content = row["signature"]` (already one line; effectively
    pre-skeletonized — the size guard will skip it).
  - `path_candidates` → no content.
- `apply_budget` (`retrieval/budget.py`) greedily attaches `redact_snippet(c.content)` to the
  top-ranked results until `token_budget` is spent; the rest become `recommended_reads`.

The transform plugs in **at `apply_budget`**, between the raw `content` and the emitted `snippet`.
Index-time transformation is rejected: skeletonizing before storage would strip body text from
FTS/vector indexes and collapse recall.

Reused infrastructure (no new parsing stack):

- `discovery/classify.py:detect_language(path)` and `_TREE_SITTER_LANGS` — content-type routing.
- `parsers/treesitter.py:parse_file(lang, text)` → `Symbol`s with `line_start`, `line_end`,
  `signature`, `kind`, `parent_index` (already computes the signature line per def).
- `parsers/line_chunker.py:estimate_tokens` — recompute token cost of the skeleton.
- `output/redact.py:redact_snippet` — applied **after** skeletonization.

## 4. Design

### 4.1 Core abstraction: line-level structure mask

headroom marks **tokens** structural-vs-compressible (`StructureMask`). We port the idea to
**lines** — more robust for partial chunks and aligned with the line-range vocabulary used
everywhere else in the codebase.

New module `src/codebase_index/retrieval/skeleton.py`:

```python
@dataclass
class Compacted:
    text: str
    token_est: int
    elided_lines: int
    skeletonized: bool        # False => text is the original content (raw fallback / no win)

def classify_lines(content: str, *, lang: str | None,
                   query_terms: list[str], ctx_lines: int) -> list[bool]:
    """Return one bool per line: True = keep (structural or focus), False = elide."""

def render_skeleton(content: str, keep: list[bool], *, line_start: int) -> tuple[str, int]:
    """Collapse consecutive elided runs into a marker using ABSOLUTE file line numbers.
    Returns (skeleton_text, elided_line_count)."""

def compact(content: str, *, path: str, line_start: int,
            intent: Intent, query_terms: list[str],
            min_reduction: float) -> Compacted:
    """Full pipeline: route → classify → render → guard. Never raises."""
```

`render_skeleton` emits markers like `… 24 lines elided (read 88–134)` where `88–134` are
**absolute** file lines (`line_start` offset applied), so Claude can expand precisely with `Read`.

### 4.2 Content-type classifiers (feature №2)

Type from `detect_language(path)`:

- **Code** (`lang in _TREE_SITTER_LANGS`): `parse_file(lang, content)` → symbols.
  A line is `keep` if it is **outside** every function/method body (imports, class/interface
  headers, decorators, module-level statements) **or** it is a symbol's signature line(s).
  Function/method **bodies** are `elide`. Nested methods inside a class are handled naturally:
  the class header + each method signature stay, each method body elides.
  Parse failure / non-tree-sitter language → regex signature fallback (§5).
- **Markdown** (`markdown`): `keep` heading lines (`^#{1,6}\s`) + the first non-blank line of each
  section; elide long prose runs.
- **Structured** (`json`, `yaml`, `toml`, `ini`): `keep` key-introducing lines (per-family regex)
  and structural brackets; elide long value/array bodies.
- **Other** (`sql`, `terraform`, `hcl`, `dockerfile`, `make`, unknown/`None`): all `keep` →
  identical to the raw snippet (no transform).

### 4.3 Policy & focus

- **Focus is always on** when `query_terms` is non-empty: any line containing a query term is
  force-`keep`, plus `ctx_lines` of surrounding context. **A matched line is never elided.**
- **Intent tunes `ctx_lines`** (aggressiveness), not on/off:
  - `ARCHITECTURE`, `HOW_IT_WORKS`, `DATA_FLOW` → `ctx_lines = 0` (pure signatures; the *shape*
    is the answer).
  - `LOCATE_IMPL`, `KEYWORD`, `DEBUG_ERROR`, `IMPACT`, `FIND_REFS` → `ctx_lines = 2` (keep the
    matched line in context).
- **Savings guard:** adopt the skeleton only if it saves ≥ `min_reduction` (default `0.25`) of the
  estimated tokens; otherwise return the raw content with `skeletonized=False`. This alone makes
  the transform a no-op on already-minimal content (e.g. symbol-signature candidates), with no
  special-casing.

### 4.4 Budget integration

`apply_budget(candidates, *, token_budget, compactor=None)` gains an injected `compactor`
(dependency injection keeps `budget.py` decoupled and unit-testable):

```python
comp = compactor(c) if (compactor and c.content) else None
text = comp.text if comp else c.content
tok  = comp.token_est if comp else c.token_est
# fit `tok` against the budget; snippet = redact_snippet(text)
meta["skeletonized"] = bool(comp and comp.skeletonized)
meta["elided_lines"] = comp.elided_lines if comp else 0
meta["token_est"]    = tok                      # reflects the compacted size
```

`pipeline.search` builds the compactor once and passes it in:

```python
compactor = make_compactor(intent=plan.intent, query=query,
                           enabled=not raw, min_reduction=cfg_min_reduction)
all_results, all_recommended = apply_budget(ranked, token_budget=scaled_budget,
                                            compactor=compactor)
```

Because each compacted snippet costs fewer tokens, the greedy loop reaches **more** candidates
before exhausting `token_budget` — the concrete win.

### 4.5 Output schema additions

Each `results[]` entry gains:

- `skeletonized: bool` — true when the snippet is a skeleton.
- `elided_lines: int` — count of source lines folded away (`0` when not skeletonized).
- `token_est` — now reports the **compacted** estimate.

`recommended_reads` semantics are unchanged: a skeletonized snippet is still "useful" so it is not
forced into `recommended_reads`, but every result already carries `line_start`/`line_end`, so
expansion is always one `Read` away. No payload field is removed; consumers that ignore the new
fields keep working.

### 4.6 Surface: CLI / MCP / config / SKILL.md

- **CLI:** `--raw` flag on `search` / `explain` / `architecture` disables compaction. Default = on.
- **MCP** (`mcp/server.py`): add `raw: bool = false` to the search-family tools.
- **Config** (`config.py:RetrievalConfig`):
  - `compact_snippets: bool = True`
  - `compact_min_reduction: float = 0.25`
  These are retrieval-time fields — **not** added to `config_hash`, so no reindex is triggered.
- **SKILL.md:** document `skeletonized` / `elided_lines` (snippet may be signatures + matched
  lines with bodies elided; Read `line_start–line_end` to expand a body) and the `--raw` escape.

## 5. Error handling & safety guarantees

- **Never raises.** `compact` wraps classification; any exception → raw content,
  `skeletonized=False`.
- **Parse fallback chain:** tree-sitter parse → on failure or non-tree-sitter language, a
  regex signature detector (ports headroom's `_SIGNATURE_PATTERNS`) → on empty, raw content.
- **Preserve bias:** a line that cannot be attributed to a function/method body is kept. Partial
  window chunks (a body cut mid-function) therefore degrade to "keep more", never "elide the
  wrong thing".
- **Focus invariant:** a line containing a query term is never elided.
- **Savings guard:** never emit a skeleton that isn't meaningfully smaller (§4.3).
- **Redaction order:** skeletonize → `redact_snippet`. Bodies (where secrets usually live) are
  already dropped; surviving structural lines are still redacted.
- **Determinism:** no randomness, stable ordering — identical input yields identical output
  (required by golden tests).

## 6. Performance

The compactor runs only on candidates that actually receive a snippet (top handful per query,
bounded by `token_budget`). Each is a tree-sitter parse of a small chunk (~ms). Parsers are
created per call today; if profiling shows cost, adopt the thread-local parser-cache pattern
(headroom's `_get_parser`). No measurable impact expected for interactive use.

## 7. Testing strategy (TDD)

**Unit (`tests/test_skeleton.py`)**

- Code classifier: Python / TypeScript / Go samples → signatures kept, bodies elided,
  `elided_lines` exact.
- Focus: a body line containing a query term (+ context) survives; surrounding body elided.
- Markdown classifier: headings + first section line kept.
- Structured classifier: JSON / TOML key lines kept, long values elided.
- Fallback: unparseable content → raw, `skeletonized=False`; tree-sitter-absent path → regex.
- Savings guard: skeleton not ≥25% smaller → raw returned.
- `render_skeleton`: marker carries correct **absolute** line range; adjacent elide runs merge.
- Determinism: repeated calls byte-identical.

**Integration (`tests/test_budget.py`, `tests/test_pipeline.py`)**

- With a compactor, more candidates receive snippets at the same `token_budget` than without.
- `redact_snippet` still applied to skeletonized text.
- `skeletonized` / `elided_lines` / compacted `token_est` present and correct.
- Pagination and `recommended_reads` filtering unchanged.
- `--raw` / `compact_snippets=False` → byte-identical to pre-feature output (regression guard).

**Golden**

- One representative `search` payload captured before/after, asserting more results carry snippets
  and the matched line is present in each skeleton.

## 8. Rollout & backward compatibility

- Additive fields only; no field removed or renamed. Pre-feature consumers ignore the new keys.
- `--raw` and `compact_snippets=False` reproduce exact current behavior (escape hatch + test oracle).
- No schema migration, no reindex (config fields excluded from `config_hash`).
- CHANGELOG entry under a new minor version.

## 9. Resolved decisions

| Question | Decision |
|---|---|
| Index-time vs retrieval-time | Retrieval-time (index-time kills FTS/vector recall). |
| Signatures-only vs focus | Focus skeleton — matched line always preserved. |
| Default on vs opt-in | Default on, `--raw` escape (headroom-style: compress by default). |
| Content detector | `detect_language(path)` by extension — no ML detector. |
| Mask granularity | Lines, not tokens — robust for partial chunks, matches codebase idiom. |
| When to skip | Savings guard (≥25%) auto-skips minimal/signature content. |
```
