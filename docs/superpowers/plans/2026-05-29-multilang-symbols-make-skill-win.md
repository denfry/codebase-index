# Make the skill actually win — language-agnostic symbol extraction

> **For agentic workers:** REQUIRED SUB-SKILL — use `superpowers:test-driven-development`
> for every task below (write the failing test first, then the implementation). Steps use
> checkbox (`- [ ]`) format; check them off as you go. Do **not** mark a task done until its
> acceptance test passes *and* the honest benchmark (Task 7) confirms no regression.

## Why this plan exists

The honest benchmark (`tests/benchmark_honest.py`, run against the 55k-LOC Java repo
`NewTowny`) showed the skill's headline advantage — symbol awareness — is **dead on every
language except Python/JS/TS**. Measured facts from that run:

- 303 Java files indexed → **0 Java symbols** extracted. All 101 symbols came from JS/Next.js.
- `search` for Java symbols returns empty; `confidence` is `low`/`medium` on every query.
- On a fair, symmetric token comparison the skill is only ~3.3× better than a disciplined
  `rg`+window agent (and part of that is a file-density artifact, not retrieval quality);
  top-3 file overlap between index and grep is just 0.40/3.

In short: on Java — and on **Go, Rust, C, C++, C#, Ruby, PHP, Kotlin, …** — the skill silently
degrades to "FTS over 80-line line-chunks." `symbol` / `refs` / `impact` do nothing. That is the
whole value proposition, gone.

## Root cause (with citations)

Two registries disagree, and the gap is swallowed silently:

1. `src/codebase_index/discovery/classify.py:32-43` — `_TREE_SITTER_LANGS` claims
   `go, java, rust, c, cpp, ruby, php` are tree-sitter-parsed, so `parser_for()` labels those
   files `"treesitter"` in the DB.
2. `src/codebase_index/parsers/languages.py:92` — `LANGS` only registers
   `python, javascript, typescript`. There is **no spec** for any other language.
3. `src/codebase_index/indexer/pipeline.py:131-142` — `_parse()` only calls tree-sitter when
   `languages.is_supported(lang)` (i.e. only the 3 above). Everything else falls to
   `chunk_text(...)` with `symbols=[], edges=[]`.
4. `pipeline.py:135` — `except Exception: pass` swallows **any** parse failure, so a broken or
   missing language path looks identical to success. "0 symbols" never raised an alarm.

So the file's `parser` column says `treesitter` for Java while no symbols are ever produced.

## Goal

The skill produces useful symbols, references, and impact graphs for **any** source language a
tree-sitter grammar exists for, and degrades *gracefully and visibly* (never silently) for
everything else. Token/answer-quality wins must be re-verified, not assumed.

## Design: three tiers + two guardrails

**Tier A — first-class `LangSpec`** (hand-tuned `defs`/`calls`/`imports` queries; best symbols
+ graph edges). Today: Python/JS/TS. Add the common compiled/back-end languages.

**Tier B — generic tree-sitter extraction.** For any grammar `tree_sitter_language_pack`
provides but we have *not* hand-tuned, walk the tree and harvest definition-like nodes
generically (node `type` ending in `declaration`/`definition`/`_item`/`_specifier` that has a
child of an identifier-like type). Produces symbols (and intra-file call edges where a generic
`call`/`invocation` node exists), even without a bespoke query. This is what makes "any
language" true instead of "the 11 we listed."

**Tier C — line-chunk + FTS.** Config/data/prose/unknown files (yaml, json, md, toml, txt, …).
Already implemented in `_parse()`; keep it as the floor. It is fine that these have no symbols.

**Guardrail 1 — single source of truth.** `classify` must not be able to claim a language is
tree-sitter-parsed unless an extraction path (Tier A or B) actually exists. Derive one registry
from the other, and add a test that fails if they ever diverge again.

**Guardrail 2 — no silent parse failures.** `_parse()` must count parse errors and
files-with-zero-symbols-but-treesitter-parser, and surface them in `stats`/`doctor`. A
tree-sitter file that yields zero symbols is a yellow flag, not a success.

---

## Task 1 — Reproduce the failure as a test (RED)

**Files:** `tests/test_multilang_symbols.py` (new), `tests/fixtures/` (small Java + Go + Rust samples)

- [ ] Add tiny fixtures: `sample.java` (a class with 2 methods + a constructor), `sample.go`
      (a package with 2 funcs + a struct + a method), `sample.rs` (a struct + impl with 2 fns).
- [ ] Write a parametrized test that calls `parse_file(lang, text)` for `java`, `go`, `rust` and
      asserts symbols are extracted (expected names present, correct `kind`, plausible line
      ranges). It MUST fail today (Java/Go/Rust → empty or `UnsupportedLanguage`).
- [ ] Write a test asserting **registry consistency**: every lang in
      `classify._TREE_SITTER_LANGS` resolves to a working extraction path (Tier A spec OR Tier B
      generic) — i.e. `parse_file` on a minimal sample yields ≥1 symbol. This locks Guardrail 1.

## Task 2 — Add Tier-A `LangSpec`s for the common languages

**File:** `src/codebase_index/parsers/languages.py`

- [ ] Add `LangSpec`s for at least: `java`, `go`, `rust`, `c`, `cpp`, `csharp`, `ruby`, `php`,
      `kotlin`. Use the correct tree-sitter node types per grammar, e.g.:
   - **Java:** `class_declaration`, `interface_declaration`, `enum_declaration`,
     `record_declaration`, `method_declaration`, `constructor_declaration`;
     calls = `method_invocation` (field `name`); imports = `import_declaration`,
     `superclass`, `super_interfaces`.
   - **Go:** `function_declaration`, `method_declaration`, `type_declaration`
     (struct/interface); calls = `call_expression`; imports = `import_spec`.
   - **Rust:** `function_item`, `struct_item`, `enum_item`, `trait_item`, `impl_item`,
     `mod_item`; calls = `call_expression`/`macro_invocation`; imports = `use_declaration`.
- [ ] Register every new spec in `LANGS` (`languages.py:92`).
- [ ] Verify each `ts_name` actually loads via `tree_sitter_language_pack.get_language(...)`
      (it ships these grammars). Add a test that `get_language(spec.ts_name)` succeeds for every
      spec in `LANGS`.

## Task 3 — Teach the extractor the new node kinds

**File:** `src/codebase_index/parsers/treesitter.py`

- [ ] Extend `_definition_kind()` (`:98-122`) to map the Java/Go/Rust/… node types to kinds
      (`class`/`interface`/`enum`/`method`/`function`/`struct`/`trait`/`module`). Add the new
      container kinds to `CONTAINER_KINDS` in `languages.py:8` (e.g. `struct`, `trait`, `impl`,
      `record`) so method/qualified-name nesting works.
- [ ] Extend `_callee_node()` (`:218-230`) to recognize `method_invocation` (Java) and the
      generic `call_expression` callee shapes used by Go/Rust/C so intra-file call edges work.
- [ ] Confirm `_signature()` (`:125`) produces a sane one-liner for brace languages (it strips a
      trailing `{` already — verify for Go/Rust).

## Task 4 — Tier-B generic fallback for untuned grammars

**File:** `src/codebase_index/parsers/treesitter.py` (+ `languages.py`)

- [ ] Add a generic extraction path used when `spec_for(lang)` is None but a grammar exists:
      walk the tree, treat any node whose `type` ends in
      `{declaration, definition, _item, _specifier}` and that has an identifier-like named child
      as a symbol; kind = a coarse mapping (contains `class`/`struct`/`enum`/`interface`/`trait`
      → that; else `function`). Emit symbols with line ranges; edges optional.
- [ ] Change `parse_file()` (`:19-22`): instead of raising `UnsupportedLanguage` when
      `spec is None`, try the generic path if `get_language(lang)` resolves; only raise when no
      grammar exists at all.
- [ ] Add `is_supported()` semantics: a language is "supported" if it has a Tier-A spec **or** a
      loadable grammar for Tier B. Update `languages.is_supported` accordingly (and ensure
      `pipeline._parse` gate at `:132` uses the new definition).

## Task 5 — Reconcile the registries (Guardrail 1)

**Files:** `classify.py`, `languages.py`

- [ ] Make `classify._TREE_SITTER_LANGS` derive from / be validated against the set of languages
      with an extraction path, so the two can't drift. Either generate one from the other, or add
      the Task-1 consistency test to CI as the enforcement.
- [ ] Broaden `_LANG_BY_SUFFIX` (`classify.py:8-30`) to cover the new languages' extensions
      (`.kt`, `.kts`, `.cs`, `.rb`, `.php`, `.cxx`, `.hh`, `.go` already present, …). Unknown
      extensions still fall through to Tier C — that's correct.

## Task 6 — Stop swallowing parse failures (Guardrail 2)

**File:** `src/codebase_index/indexer/pipeline.py`

- [ ] In `_parse()` (`:131-142`), stop using a bare `except Exception: pass`. Catch narrowly,
      record a `parse_failed` counter and a `treesitter_zero_symbols` counter (tree-sitter file
      that produced 0 symbols), and keep the line-chunk fallback for resilience.
- [ ] Surface these counters in `BuildStats` and in the `stats` / `doctor` CLI output
      (`src/codebase_index/.../cli`), so "0 symbols on a 300-file Java repo" is visible, not
      hidden. `doctor` should warn when a tree-sitter language has files but ~0 symbols.

## Task 7 — Re-verify with the honest benchmark + an answer-quality gate

**Files:** `tests/benchmark_honest.py` (extend), `tests/benchmark_honest_RESULTS.md` (update)

The token comparison alone is not enough (see RESULTS.md caveats: 0.40/3 overlap means cost
without verified correctness). Add a **ground-truth answer-quality** check:

- [ ] For ~10 queries per language (Java, Go, and one Tier-B language), record the
      ground-truth file(s)/symbol(s) that contain the answer. Measure **recall@3**: did the
      index's top-3 `recommended_reads` include the ground-truth location?
- [ ] Report, per language: index recall@3 vs `rg`+window recall@3, alongside the existing
      symmetric token numbers. The skill "wins" only when recall@3 is **≥** the grep baseline
      *and* tokens are lower — not on tokens alone.
- [ ] Re-run against `NewTowny`; confirm Java symbols are now non-zero (`codebase-index stats`
      should show hundreds of Java symbols) and that `symbol "TownManager"` / `refs` / `impact`
      return results. Update `benchmark_honest_RESULTS.md` with the new honest numbers and delete
      the "symbols are dead" caveat once it no longer holds.

## Acceptance criteria (definition of "as it should be")

- [x] `parse_file` extracts symbols for Java, Go, Rust, C/C++, C#, Ruby, PHP, Kotlin (Tier A) and
      for at least one untuned-but-grammar-available language (Tier B = `lua`).
- [x] Registry-consistency test passes: no language is labeled `treesitter` without a working
      extraction path (`tests/test_multilang_symbols.py`, both directions).
- [x] No silent parse failures: `stats`/`doctor` report parse-failure and zero-symbol counts
      (`BuildStats.parse_failed`, `treesitter_zero_symbols`; `doctor` `symbol_extraction` finding).
- [x] On `NewTowny`: Java symbol count > 0 — **3,543 Java symbols** across 303 files;
      `symbol`/`refs`/`impact` return real Java results.
- [x] **MET (after a follow-on ranking fix the user approved).** Honest benchmark recall@3: index
      **70 % (7/10)** vs grep **40 % (4/10)**, using ~13× fewer tokens to answer (full plan ~422
      vs rg+window 5,604). The fix made the symbol retriever score by camelCase/underscore
      coverage of all query terms (so "religion manager" → `ReligionManager`, not bare
      `Religion`). Numbers + analysis in `benchmark_honest_RESULTS.md`; locked by
      `tests/test_symbol_ranking.py`. Remaining headroom = high-`in_degree` god-class tiebreak
      tuning (follow-up).
- [x] Tier C (yaml/json/md/unknown) still indexes via line-chunk + FTS — no regression
      (`test_multilang_build_extracts_symbols_without_failures` indexes `config.yaml` with 0
      symbols and 0 failures).

## Out of scope

- Cross-file/global call-graph resolution beyond what `_resolve_edges` already does per file.
- Embeddings/semantic ranking changes — separate concern.
- Hand-tuning Tier-B languages into Tier A; that's incremental follow-up, one language at a time.
