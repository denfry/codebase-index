# Snippet Skeletonization & Content-Aware Rendering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform retrieval snippets into focus skeletons (signatures + matched lines kept, function bodies elided) at retrieval time so more ranked results fit the token budget, reversibly and content-aware.

**Architecture:** A new `retrieval/skeleton.py` computes a per-line keep/elide mask (a line-granularity port of headroom's `StructureMask`), routed by `detect_language(path)`: code → AST signatures via the existing `parse_file`, markdown → headings, structured config → key lines, everything else untouched. A `compactor` callable is injected into `apply_budget`, which uses the compacted text + reduced token estimate when (and only when) it is a meaningful win; otherwise it falls back byte-identically to today's raw snippet. The flag threads CLI `--raw` / MCP `raw` → `service.search_payload` → `pipeline.search`.

**Tech Stack:** Python 3.11+, tree-sitter (`tree_sitter`, `tree_sitter_language_pack` — already core deps), Typer (CLI), FastMCP (MCP), pytest.

## Global Constraints

- Python ≥ 3.11 (repo floor); `from __future__ import annotations` at the top of every module.
- Never raise from the skeletonizer — any failure returns the raw snippet (`skeletonized=False`).
- Output additive only: no existing payload field renamed or removed.
- `compactor=None` / `compact=False` / `--raw` must reproduce **byte-identical** current output (regression oracle).
- Skeletonize **then** `redact_snippet` — never the reverse.
- Deterministic: identical input → identical output (no randomness, stable iteration).
- Retrieval-time only — no indexing, chunking, FTS, vector, or schema changes; new config fields stay out of `config_hash` (no reindex).
- Conventional-commit messages (`feat:`, `docs:`, `test:`); end each with the `Co-Authored-By` trailer shown in Step 5 of Task 1.

---

## File Structure

- **Create** `src/codebase_index/retrieval/skeleton.py` — the whole skeletonizer: `Compacted`, `render_skeleton`, `classify_lines` (+ per-type classifiers), `compact`, `make_compactor`. One responsibility: turn raw snippet text into a compacted snippet.
- **Create** `tests/test_skeleton.py` — unit tests for the skeletonizer.
- **Modify** `src/codebase_index/retrieval/budget.py` — inject the `compactor`.
- **Modify** `src/codebase_index/retrieval/pipeline.py` — build the compactor, pass it to `apply_budget`.
- **Modify** `src/codebase_index/config.py` — two `RetrievalConfig` fields.
- **Modify** `src/codebase_index/service.py` — thread `raw`.
- **Modify** `src/codebase_index/cli.py` — `--raw` on `search` and `explain`.
- **Modify** `src/codebase_index/mcp/server.py` — `raw` param on `search_code` and `explain_code`.
- **Modify** `tests/test_budget.py` — compactor integration tests.
- **Modify** `tests/test_pipeline_search.py` — end-to-end skeleton-on/off test.
- **Modify** `skill/SKILL.md`, `CHANGELOG.md` — docs.

> **Scope note vs. spec:** the spec named `architecture` among the `--raw` surfaces. `architecture_payload` returns cached graph analytics and emits **no snippets**, so `--raw` there would be a no-op. This plan scopes `--raw` to `search` and `explain` (the two commands that flow through `apply_budget`).

---

### Task 1: `render_skeleton` — collapse a keep/elide mask into text

**Files:**
- Create: `src/codebase_index/retrieval/skeleton.py`
- Test: `tests/test_skeleton.py`

**Interfaces:**
- Consumes: `from ..parsers.line_chunker import estimate_tokens` (existing: `estimate_tokens(text: str) -> int`).
- Produces:
  - `render_skeleton(content: str, keep: list[bool], *, line_start: int) -> tuple[str, int]` — returns `(skeleton_text, elided_line_count)`. Consecutive `False` lines collapse into one marker `... {n} lines elided (read {a}-{b})` where `a`/`b` are **absolute** file line numbers (`line_start` is the absolute line of `content`'s first line).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_skeleton.py
from codebase_index.retrieval.skeleton import render_skeleton


def test_render_collapses_elided_run_with_absolute_lines():
    content = "def f():\n    a = 1\n    b = 2\n    return a + b"
    keep = [True, False, False, False]
    text, elided = render_skeleton(content, keep, line_start=10)
    assert text == "def f():\n... 3 lines elided (read 11-13)"
    assert elided == 3


def test_render_all_keep_is_unchanged():
    content = "a\nb\nc"
    text, elided = render_skeleton(content, [True, True, True], line_start=1)
    assert text == content
    assert elided == 0


def test_render_merges_adjacent_runs_but_keeps_separated_ones():
    content = "h1\nx\nh2\ny\nz"
    keep = [True, False, True, False, False]
    text, elided = render_skeleton(content, keep, line_start=1)
    assert text == "h1\n... 1 lines elided (read 2-2)\nh2\n... 2 lines elided (read 4-5)"
    assert elided == 3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_skeleton.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'codebase_index.retrieval.skeleton'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/codebase_index/retrieval/skeleton.py
"""Retrieval-time snippet skeletonization (line-granularity StructureMask).

Turns a raw code/text snippet into a compact skeleton: signature/structural
lines are kept, function bodies (and other compressible runs) collapse into a
marker that points at the absolute line range to read for the full body. A
line-granularity port of headroom's StructureMask, adapted for a retrieval
system: the query-matching line is always preserved, routing is by file
extension, and the transform never makes output worse than the raw snippet.
"""

from __future__ import annotations

from ..parsers.line_chunker import estimate_tokens


def render_skeleton(
    content: str, keep: list[bool], *, line_start: int
) -> tuple[str, int]:
    """Collapse consecutive ``keep=False`` lines into one elision marker.

    ``line_start`` is the absolute file line number of ``content``'s first line,
    so markers cite the real range to ``Read``. Returns (text, elided_count).
    """
    lines = content.split("\n")
    if len(keep) != len(lines):
        # Defensive: mask/line mismatch must never corrupt output.
        return content, 0

    out: list[str] = []
    elided_total = 0
    i = 0
    n = len(lines)
    while i < n:
        if keep[i]:
            out.append(lines[i])
            i += 1
            continue
        run_start = i
        while i < n and not keep[i]:
            i += 1
        run_len = i - run_start
        elided_total += run_len
        a = line_start + run_start
        b = line_start + i - 1
        out.append(f"... {run_len} lines elided (read {a}-{b})")
    return "\n".join(out), elided_total
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_skeleton.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/retrieval/skeleton.py tests/test_skeleton.py
git commit -m "$(cat <<'EOF'
feat(skeleton): render_skeleton collapses keep/elide mask into markers

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 2: Code classifier + `compact` orchestration

**Files:**
- Modify: `src/codebase_index/retrieval/skeleton.py`
- Test: `tests/test_skeleton.py`

**Interfaces:**
- Consumes: `from ..discovery.classify import detect_language`; `from .parsers...` → actually `from ..parsers.treesitter import parse_file` and `from ..parsers.languages` is not needed (route via `detect_language` + a local code-language set); `render_skeleton`, `estimate_tokens` (Task 1).
- Produces:
  - `@dataclass class Compacted: text: str; token_est: int; elided_lines: int; skeletonized: bool`
  - `classify_lines(content: str, *, lang: str | None, query_terms: list[str], ctx_lines: int) -> list[bool]` — one bool per `content.split("\n")` line.
  - `compact(content: str, *, path: str, line_start: int, ctx_lines: int, query_terms: list[str], min_reduction: float) -> Compacted` — full pipeline; **never raises**.

> Design note vs. spec §4.1: `compact` takes the already-resolved `ctx_lines` (int), not `intent`. The intent→`ctx_lines` policy lives in `make_compactor` (Task 4), keeping `compact` pure and unit-testable.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_skeleton.py  (append)
from codebase_index.retrieval.skeleton import Compacted, compact


PY_SAMPLE = (
    "import os\n"
    "\n"
    "class Store:\n"
    "    def refresh(self, tok):\n"
    "        decoded = decode(tok)\n"
    "        validate(decoded)\n"
    "        return decoded\n"
    "    def revoke(self, tok):\n"
    "        self.blocklist.add(tok)\n"
    "        log('revoked')\n"
)


def test_code_skeleton_keeps_signatures_and_elides_bodies():
    r = compact(PY_SAMPLE, path="store.py", line_start=1,
                ctx_lines=0, query_terms=[], min_reduction=0.25)
    assert r.skeletonized is True
    assert "def refresh(self, tok):" in r.text
    assert "def revoke(self, tok):" in r.text
    assert "class Store:" in r.text
    assert "import os" in r.text
    assert "decoded = decode(tok)" not in r.text   # body elided
    assert r.elided_lines >= 3
    assert r.token_est < estimate_tokens_helper(PY_SAMPLE)


def estimate_tokens_helper(text):
    from codebase_index.parsers.line_chunker import estimate_tokens
    return estimate_tokens(text)


def test_focus_keeps_matched_body_line_and_context():
    r = compact(PY_SAMPLE, path="store.py", line_start=1,
                ctx_lines=1, query_terms=["blocklist"], min_reduction=0.25)
    assert "self.blocklist.add(tok)" in r.text       # matched line preserved
    assert "decoded = decode(tok)" not in r.text      # unrelated body still elided


def test_unparseable_or_unknown_type_falls_back_to_raw():
    blob = "%%% not code %%%\n@@@@@\n!!!!!"
    r = compact(blob, path="notes.bin", line_start=1,
                ctx_lines=0, query_terms=[], min_reduction=0.25)
    assert r.skeletonized is False
    assert r.text == blob
    assert r.elided_lines == 0


def test_savings_guard_returns_raw_when_not_enough_win():
    tiny = "def f(): pass"     # one line, nothing to elide
    r = compact(tiny, path="f.py", line_start=1,
                ctx_lines=0, query_terms=[], min_reduction=0.25)
    assert r.skeletonized is False
    assert r.text == tiny


def test_compact_is_deterministic():
    a = compact(PY_SAMPLE, path="store.py", line_start=1,
                ctx_lines=0, query_terms=[], min_reduction=0.25)
    b = compact(PY_SAMPLE, path="store.py", line_start=1,
                ctx_lines=0, query_terms=[], min_reduction=0.25)
    assert (a.text, a.token_est, a.elided_lines, a.skeletonized) == \
           (b.text, b.token_est, b.elided_lines, b.skeletonized)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_skeleton.py -v`
Expected: FAIL with `ImportError: cannot import name 'compact'`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/codebase_index/retrieval/skeleton.py`:

```python
from dataclasses import dataclass

# Languages we skeletonize via tree-sitter signatures. Mirrors
# discovery.classify._TREE_SITTER_LANGS (kept local to avoid a private import).
_CODE_LANGS = frozenset({
    "python", "typescript", "javascript", "go", "java", "rust",
    "c", "cpp", "csharp", "ruby", "php", "kotlin", "lua",
})
# Languages whose body opens at a line ending in ':' vs. one containing '{'.
_BRACE_LANGS = frozenset({
    "typescript", "javascript", "go", "java", "rust",
    "c", "cpp", "csharp", "php", "kotlin",
})
_MAX_SIG_SCAN = 5  # bound the multi-line-signature lookahead


@dataclass
class Compacted:
    text: str
    token_est: int
    elided_lines: int
    skeletonized: bool


def _raw(content: str) -> Compacted:
    return Compacted(text=content, token_est=estimate_tokens(content),
                     elided_lines=0, skeletonized=False)


def _signature_end(lines: list[str], start: int, lang: str | None, end: int) -> int:
    """0-based index of the last signature line for a def starting at ``start``.

    Scans forward (bounded) for the line that opens the body so multi-line
    signatures stay visible; defaults to ``start`` when nothing matches.
    """
    limit = min(end, start + _MAX_SIG_SCAN)
    for i in range(start, limit + 1):
        s = lines[i].strip()
        if lang in _BRACE_LANGS and "{" in s:
            return i
        if lang not in _BRACE_LANGS and s.endswith(":"):
            return i
    return start


def _classify_code(content: str, lines: list[str], lang: str) -> list[bool] | None:
    """Keep imports/signatures/headers; elide function & method bodies.

    Returns None when parsing yields no usable symbols (caller falls back).
    """
    from ..parsers.treesitter import parse_file

    try:
        result = parse_file(lang, content)
    except Exception:
        return None
    symbols = result.symbols
    if not symbols:
        return None

    n = len(lines)
    keep = [True] * n
    # Pass 1: elide the interior of every callable body.
    for sym in symbols:
        if sym.kind not in ("function", "method"):
            continue
        start0 = sym.line_start - 1
        end0 = sym.line_end - 1
        if not (0 <= start0 < n):
            continue
        end0 = min(end0, n - 1)
        sig_end = _signature_end(lines, start0, lang, end0)
        for i in range(sig_end + 1, end0 + 1):
            keep[i] = False
    # Pass 2: re-keep every symbol's signature line(s) (restores nested defs).
    for sym in symbols:
        start0 = sym.line_start - 1
        end0 = min(sym.line_end - 1, n - 1)
        if not (0 <= start0 < n):
            continue
        sig_end = _signature_end(lines, start0, lang, end0)
        for i in range(start0, sig_end + 1):
            keep[i] = True
    return keep


def _apply_focus(lines: list[str], keep: list[bool],
                 query_terms: list[str], ctx_lines: int) -> None:
    """Force-keep any line containing a query term, plus +/- ctx_lines."""
    if not query_terms:
        return
    n = len(lines)
    for i, line in enumerate(lines):
        low = line.lower()
        if any(t in low for t in query_terms):
            for j in range(max(0, i - ctx_lines), min(n, i + ctx_lines + 1)):
                keep[j] = True


def classify_lines(content: str, *, lang: str | None,
                   query_terms: list[str], ctx_lines: int) -> list[bool]:
    lines = content.split("\n")
    keep: list[bool] | None = None
    if lang in _CODE_LANGS:
        keep = _classify_code(content, lines, lang)
    if keep is None:
        keep = [True] * len(lines)        # unknown / parse miss -> keep all (raw)
    _apply_focus(lines, keep, query_terms, ctx_lines)
    return keep


def compact(content: str, *, path: str, line_start: int, ctx_lines: int,
            query_terms: list[str], min_reduction: float) -> Compacted:
    """Route -> classify -> render -> guard. Never raises; raw fallback on any miss."""
    if not content.strip():
        return _raw(content)
    try:
        from ..discovery.classify import detect_language
        lang = detect_language(path)
        keep = classify_lines(content, lang=lang,
                              query_terms=[t.lower() for t in query_terms],
                              ctx_lines=ctx_lines)
        if all(keep):
            return _raw(content)
        text, elided = render_skeleton(content, keep, line_start=line_start)
        if elided == 0:
            return _raw(content)
        new_tok = estimate_tokens(text)
        raw_tok = estimate_tokens(content)
        if new_tok > raw_tok * (1.0 - min_reduction):
            return _raw(content)          # not a meaningful win
        return Compacted(text=text, token_est=new_tok,
                         elided_lines=elided, skeletonized=True)
    except Exception:
        return _raw(content)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_skeleton.py -v`
Expected: PASS (all Task 1 + Task 2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/retrieval/skeleton.py tests/test_skeleton.py
git commit -m "$(cat <<'EOF'
feat(skeleton): code classifier + compact() with focus, guard, raw fallback

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 3: Markdown + structured-config classifiers

**Files:**
- Modify: `src/codebase_index/retrieval/skeleton.py`
- Test: `tests/test_skeleton.py`

**Interfaces:**
- Consumes: `classify_lines` routing from Task 2.
- Produces: routing additions inside `classify_lines` (no new public signature). Markdown (`markdown`) and structured (`json`, `yaml`, `toml`, `ini`) get keep-line heuristics.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_skeleton.py  (append)

MD_SAMPLE = (
    "# Title\n"
    "Intro line one.\n"
    "More prose that is not structural and should be dropped.\n"
    "Even more prose.\n"
    "## Section\n"
    "Section body line.\n"
    "Trailing prose to elide here too.\n"
)

JSON_SAMPLE = (
    '{\n'
    '  "name": "demo",\n'
    '  "description": "a long value that is mostly prose and can be elided away",\n'
    '  "nested": {\n'
    '    "key": "value"\n'
    '  }\n'
    '}\n'
)


def test_markdown_keeps_headings_and_first_section_line():
    r = compact(MD_SAMPLE, path="README.md", line_start=1,
                ctx_lines=0, query_terms=[], min_reduction=0.25)
    assert r.skeletonized is True
    assert "# Title" in r.text
    assert "## Section" in r.text
    assert "Intro line one." in r.text          # first line after heading kept
    assert "Even more prose." not in r.text


def test_structured_keeps_key_lines():
    r = compact(JSON_SAMPLE, path="pkg.json", line_start=1,
                ctx_lines=0, query_terms=["nested"], min_reduction=0.10)
    assert '"name": "demo"' in r.text
    assert '"nested"' in r.text                 # focus term line kept
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_skeleton.py::test_markdown_keeps_headings_and_first_section_line -v`
Expected: FAIL (markdown currently keeps all lines → `skeletonized is False`).

- [ ] **Step 3: Write minimal implementation**

In `skeleton.py`, add the classifiers and wire them into `classify_lines`:

```python
import re

_STRUCT_LANGS = frozenset({"json", "yaml", "toml", "ini"})
_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s")
_SECTION_RE = re.compile(r"^\s*\[.*\]\s*$")        # toml/ini section header
_KEY_RE = re.compile(r"[:=]")                       # key/value introducer
_BRACKET = {"{", "}", "[", "]", "{}", "[]", "},", "],"}


def _classify_markdown(lines: list[str]) -> list[bool]:
    keep = [False] * len(lines)
    for i, line in enumerate(lines):
        if _HEADING_RE.match(line):
            keep[i] = True
            # keep the first non-blank line of the section
            for j in range(i + 1, len(lines)):
                if lines[j].strip():
                    keep[j] = True
                    break
    return keep


def _classify_structured(lines: list[str]) -> list[bool]:
    keep = [False] * len(lines)
    for i, line in enumerate(lines):
        s = line.strip()
        if not s or s in _BRACKET or _SECTION_RE.match(s) or _KEY_RE.search(s):
            keep[i] = True
    return keep
```

Then modify `classify_lines` (replace the routing block from Task 2):

```python
def classify_lines(content: str, *, lang: str | None,
                   query_terms: list[str], ctx_lines: int) -> list[bool]:
    lines = content.split("\n")
    keep: list[bool] | None = None
    if lang in _CODE_LANGS:
        keep = _classify_code(content, lines, lang)
    elif lang == "markdown":
        keep = _classify_markdown(lines)
    elif lang in _STRUCT_LANGS:
        keep = _classify_structured(lines)
    if keep is None:
        keep = [True] * len(lines)
    _apply_focus(lines, keep, query_terms, ctx_lines)
    return keep
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_skeleton.py -v`
Expected: PASS (all skeleton tests).

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/retrieval/skeleton.py tests/test_skeleton.py
git commit -m "$(cat <<'EOF'
feat(skeleton): markdown heading + structured key classifiers

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 4: `make_compactor` factory (intent policy + query terms)

**Files:**
- Modify: `src/codebase_index/retrieval/skeleton.py`
- Test: `tests/test_skeleton.py`

**Interfaces:**
- Consumes: `compact` (Task 2); `from .types import Candidate, Intent`.
- Produces:
  - `make_compactor(*, intent: Intent, query: str, enabled: bool, min_reduction: float) -> Callable[[Candidate], Compacted] | None` — returns `None` when `enabled is False`; otherwise a closure mapping a `Candidate` (reads `.content`, `.path`, `.line_start`) to `Compacted`, with `ctx_lines` resolved from `intent` (`0` for shape-first intents, else `2`) and `query` tokenized once.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_skeleton.py  (append)
from codebase_index.retrieval.skeleton import make_compactor
from codebase_index.retrieval.types import Candidate, Intent


def _cand(content):
    return Candidate(path="store.py", line_start=1, line_end=10,
                     source="fts", score=1.0, content=content, token_est=99)


def test_make_compactor_disabled_returns_none():
    assert make_compactor(intent=Intent.KEYWORD, query="x",
                           enabled=False, min_reduction=0.25) is None


def test_make_compactor_shape_intent_uses_zero_context():
    comp = make_compactor(intent=Intent.ARCHITECTURE, query="blocklist",
                          enabled=True, min_reduction=0.25)
    r = comp(_cand(PY_SAMPLE))
    # ctx 0 => even a matched line's neighbours are not force-kept
    assert r.skeletonized is True


def test_make_compactor_locate_intent_keeps_matched_line():
    comp = make_compactor(intent=Intent.LOCATE_IMPL, query="blocklist",
                          enabled=True, min_reduction=0.25)
    r = comp(_cand(PY_SAMPLE))
    assert "self.blocklist.add(tok)" in r.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_skeleton.py::test_make_compactor_disabled_returns_none -v`
Expected: FAIL with `ImportError: cannot import name 'make_compactor'`.

- [ ] **Step 3: Write minimal implementation**

Append to `skeleton.py`:

```python
from typing import Callable, Optional

from .types import Candidate, Intent

# Shape-first intents want pure signatures (no context around matches).
_SHAPE_INTENTS = frozenset({Intent.ARCHITECTURE, Intent.HOW_IT_WORKS, Intent.DATA_FLOW})
_TERM_RE = re.compile(r"[A-Za-z0-9_]+")
_STOPWORDS = frozenset({
    "the", "a", "an", "is", "are", "how", "does", "do", "what", "where",
    "which", "to", "of", "in", "on", "for", "and", "or", "with", "from",
})


def _query_terms(query: str) -> list[str]:
    out: list[str] = []
    for t in _TERM_RE.findall(query):
        tl = t.lower()
        if len(tl) >= 3 and tl not in _STOPWORDS:
            out.append(tl)
    return list(dict.fromkeys(out))


def make_compactor(*, intent: Intent, query: str, enabled: bool,
                   min_reduction: float) -> Optional[Callable[[Candidate], Compacted]]:
    if not enabled:
        return None
    ctx_lines = 0 if intent in _SHAPE_INTENTS else 2
    terms = _query_terms(query)

    def _compact(c: Candidate) -> Compacted:
        return compact(c.content or "", path=c.path, line_start=c.line_start,
                       ctx_lines=ctx_lines, query_terms=terms,
                       min_reduction=min_reduction)

    return _compact
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_skeleton.py -v`
Expected: PASS (all skeleton tests).

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/retrieval/skeleton.py tests/test_skeleton.py
git commit -m "$(cat <<'EOF'
feat(skeleton): make_compactor factory with intent->context policy

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 5: Inject the compactor into `apply_budget`

**Files:**
- Modify: `src/codebase_index/retrieval/budget.py`
- Test: `tests/test_budget.py`

**Interfaces:**
- Consumes: `Compacted` and the `Callable[[Candidate], Compacted]` shape from Task 4.
- Produces: `apply_budget(candidates, *, token_budget, compactor=None) -> tuple[list[dict], list[dict]]`. New per-result keys `skeletonized: bool` and `elided_lines: int`; `token_est` reflects the compacted size. When `compactor is None` **or** a candidate's `Compacted.skeletonized is False`, behavior is byte-identical to today (uses `c.content` / `c.token_est`).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_budget.py  (append)
from codebase_index.retrieval.skeleton import Compacted


def test_compactor_lets_more_results_fit_budget():
    cands = [_c(f"f{i}.py", 1, 50, "x" * 4000, 1000) for i in range(5)]

    def fake_compactor(c):
        return Compacted(text="sig\n... 49 lines elided (read 2-50)",
                         token_est=10, elided_lines=49, skeletonized=True)

    no_comp, _ = apply_budget(cands, token_budget=1500)
    with_comp, _ = apply_budget(cands, token_budget=1500, compactor=fake_compactor)
    fit_no = sum(1 for r in no_comp if r["snippet"] is not None)
    fit_yes = sum(1 for r in with_comp if r["snippet"] is not None)
    assert fit_yes > fit_no
    assert all(r["skeletonized"] for r in with_comp if r["snippet"])
    assert all(r["elided_lines"] == 49 for r in with_comp if r["snippet"])


def test_compactor_output_is_still_redacted():
    secret = "key = 'AKIAIOSFODNN7EXAMPLE'\nbody line\nbody line"
    cand = _c("s.py", 1, 3, secret, 50)

    def fake_compactor(c):
        return Compacted(text=secret, token_est=50, elided_lines=0, skeletonized=True)

    results, _ = apply_budget([cand], token_budget=1000, compactor=fake_compactor)
    assert "AKIAIOSFODNN7EXAMPLE" not in results[0]["snippet"]


def test_none_compactor_is_unchanged_behavior():
    cands = [_c("a.py", 1, 5, "y" * 400, 100)]
    results, _ = apply_budget(cands, token_budget=1000, compactor=None)
    assert results[0]["skeletonized"] is False
    assert results[0]["elided_lines"] == 0
    assert results[0]["token_est"] == 100        # original, untouched
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_budget.py::test_compactor_lets_more_results_fit_budget -v`
Expected: FAIL with `TypeError: apply_budget() got an unexpected keyword argument 'compactor'`.

- [ ] **Step 3: Write minimal implementation**

Replace the body of `apply_budget` in `src/codebase_index/retrieval/budget.py`:

```python
from typing import Callable, Optional

from ..output.redact import redact_snippet
from .types import Candidate

_MIN_USEFUL_TOKENS = 40


def _meta(c: Candidate) -> dict:
    return {
        "path": c.path,
        "line_start": c.line_start,
        "line_end": c.line_end,
        "symbols": [c.symbol] if c.symbol else [],
        "score": round(c.score, 4),
        "reason": c.reason if c.reason else c.source,
        "token_est": c.token_est,
    }


def apply_budget(
    candidates: list[Candidate],
    *,
    token_budget: int,
    compactor: Optional[Callable[[Candidate], "object"]] = None,
) -> tuple[list[dict], list[dict]]:
    results: list[dict] = []
    recommended: list[dict] = []
    spent = 0

    for rank, c in enumerate(candidates, start=1):
        meta = _meta(c)
        meta["rank"] = rank
        meta["skeletonized"] = False
        meta["elided_lines"] = 0

        # Resolve the snippet text + cost. A compactor only changes anything
        # when it returns a real skeleton; otherwise we keep today's raw path.
        text = c.content
        cost = c.token_est
        if compactor is not None and c.content:
            comp = compactor(c)
            if getattr(comp, "skeletonized", False):
                text = comp.text
                cost = comp.token_est
                meta["skeletonized"] = True
                meta["elided_lines"] = comp.elided_lines

        snippet = None
        snippet_is_useful = False
        if text and spent + cost <= token_budget:
            snippet = redact_snippet(text)
            spent += cost
            meta["token_est"] = cost
            snippet_is_useful = cost >= _MIN_USEFUL_TOKENS

        if not snippet_is_useful:
            recommended.append(
                {"path": c.path, "line_start": c.line_start, "line_end": c.line_end}
            )
        meta["snippet"] = snippet
        results.append(meta)

    return results, recommended
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_budget.py -v`
Expected: PASS — existing tests (`test_snippets_stop_at_budget`, `test_secrets_are_redacted`, `test_metadata_always_present_even_when_budget_zero`) plus the three new ones.

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/retrieval/budget.py tests/test_budget.py
git commit -m "$(cat <<'EOF'
feat(budget): inject snippet compactor; emit skeletonized/elided_lines

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 6: Build the compactor in the pipeline + config knobs

**Files:**
- Modify: `src/codebase_index/config.py:24-29` (`RetrievalConfig`)
- Modify: `src/codebase_index/retrieval/pipeline.py` (`search`)
- Test: `tests/test_config.py`, `tests/test_pipeline_search.py`

**Interfaces:**
- Consumes: `make_compactor` (Task 4), `apply_budget(..., compactor=...)` (Task 5), `plan.intent`.
- Produces: `RetrievalConfig.compact_snippets: bool = True`, `RetrievalConfig.compact_min_reduction: float = 0.25`; `pipeline.search(..., compact: bool = True, compact_min_reduction: float = 0.25)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py  (append)
def test_retrieval_config_has_compaction_defaults():
    from codebase_index.config import Config
    cfg = Config()
    assert cfg.retrieval.compact_snippets is True
    assert cfg.retrieval.compact_min_reduction == 0.25


def test_compaction_fields_do_not_change_config_hash():
    from codebase_index.config import Config
    base = Config()
    h1 = base.config_hash()
    base.retrieval.compact_snippets = False          # retrieval-time only
    assert base.config_hash() == h1                  # no reindex triggered
```

```python
# tests/test_pipeline_search.py  (append — mirrors existing search-pipeline tests there)
def test_search_skeletonizes_by_default_and_raw_disables(tmp_path):
    # Reuse the module's existing index fixture/helper to build a small repo and
    # connection. Pseudocode for the assertion shape:
    #   payload_default = search(conn, "blocklist revoke", mode="hybrid",
    #                            limit=5, token_budget=1500, no_fallback=True)
    #   payload_raw     = search(conn, "blocklist revoke", mode="hybrid",
    #                            limit=5, token_budget=1500, no_fallback=True,
    #                            compact=False)
    #   assert any(r.get("skeletonized") for r in payload_default["results"])
    #   assert all(not r.get("skeletonized") for r in payload_raw["results"])
    ...
```

> Implementation note: `tests/test_pipeline_search.py` already constructs an indexed SQLite connection — follow its existing fixture (do not invent a new one). Fill the `...` with the two `search(...)` calls and the two assertions above.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config.py::test_retrieval_config_has_compaction_defaults -v`
Expected: FAIL with `AttributeError: 'RetrievalConfig' object has no attribute 'compact_snippets'`.

- [ ] **Step 3: Write minimal implementation**

In `src/codebase_index/config.py`, extend `RetrievalConfig`:

```python
class RetrievalConfig(BaseModel):
    default_mode: Literal["hybrid", "fts", "symbol", "vector"] = "hybrid"
    rrf_k: int = 60
    token_budget: int = 1500
    limit: int = 10
    compact_snippets: bool = True
    compact_min_reduction: float = 0.25
```

(`config_hash` already lists only indexing-relevant fields and does not include `retrieval`, so no change is needed there.)

In `src/codebase_index/retrieval/pipeline.py`, update `search`'s signature and the budget call:

```python
def search(
    conn: sqlite3.Connection,
    query: str,
    *,
    mode: str,
    limit: int,
    token_budget: int,
    no_fallback: bool,
    backend=None,
    root: Optional[Path] = None,
    config: Optional[Config] = None,
    offset: int = 0,
    compact: bool = True,
    compact_min_reduction: float = 0.25,
) -> dict:
```

Replace the `apply_budget(...)` call (currently `pipeline.py:151`) with:

```python
    from .skeleton import make_compactor

    compactor = make_compactor(
        intent=plan.intent, query=query,
        enabled=compact, min_reduction=compact_min_reduction,
    )
    all_results, all_recommended = apply_budget(
        ranked, token_budget=scaled_budget, compactor=compactor
    )
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_config.py tests/test_pipeline_search.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/config.py src/codebase_index/retrieval/pipeline.py tests/test_config.py tests/test_pipeline_search.py
git commit -m "$(cat <<'EOF'
feat(pipeline): build snippet compactor; add compact config knobs

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 7: Thread `--raw` / `raw` through service, CLI, and MCP

**Files:**
- Modify: `src/codebase_index/service.py:67-98` (`search_payload`)
- Modify: `src/codebase_index/cli.py:371-410` (`search`), `:478-499` (`explain`)
- Modify: `src/codebase_index/mcp/server.py:120-154` (`search_code`), `:236-264` (`explain_code`)
- Test: `tests/test_cli.py`, `tests/test_mcp_server.py`

**Interfaces:**
- Consumes: `pipeline.search(..., compact=..., compact_min_reduction=...)` (Task 6); `cfg.retrieval.compact_snippets`, `cfg.retrieval.compact_min_reduction` (Task 6).
- Produces: `service.search_payload(..., raw: bool = False)`; CLI `--raw` flag on `search`/`explain`; MCP `raw: bool = False` on `search_code`/`explain_code`. Effective enable = `cfg.retrieval.compact_snippets and not raw`.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_cli.py  (append — mirrors existing CliRunner tests in this file)
def test_search_raw_flag_present():
    from typer.testing import CliRunner
    from codebase_index.cli import app
    res = CliRunner().invoke(app, ["search", "--help"])
    assert res.exit_code == 0
    assert "--raw" in res.stdout
```

```python
# tests/test_mcp_server.py  (append — mirrors existing tool-signature tests)
def test_search_code_accepts_raw_param():
    import inspect
    from codebase_index.mcp import server
    assert "raw" in inspect.signature(server.search_code.fn).parameters
```

> Implementation note: `tests/test_mcp_server.py` already accesses tool functions; if its existing tests use a different accessor than `.fn` for a FastMCP tool, copy that accessor here instead.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_cli.py::test_search_raw_flag_present -v`
Expected: FAIL — `--raw` not in help output.

- [ ] **Step 3: Write minimal implementation**

**`service.py`** — add `raw` and compute the effective enable:

```python
def search_payload(
    db_path: Path,
    cfg: "Config",
    query: str,
    *,
    mode: str = "hybrid",
    limit: int = 10,
    offset: int = 0,
    token_budget: int = 1500,
    no_fallback: bool = False,
    backend: Any = None,
    raw: bool = False,
) -> dict:
    from .retrieval.pipeline import search as run_search
    from .storage.db import Database

    compact = cfg.retrieval.compact_snippets and not raw
    with Database(db_path) as db:
        if backend is not None and getattr(backend, "enabled", False):
            db.enable_vectors()
        return run_search(
            db.conn,
            query,
            mode=mode,
            limit=limit,
            offset=offset,
            token_budget=token_budget,
            no_fallback=no_fallback,
            backend=backend,
            root=Path(cfg.root),
            config=cfg,
            compact=compact,
            compact_min_reduction=cfg.retrieval.compact_min_reduction,
        )
```

**`cli.py`** — `search`: add the option and pass it through. Add after the `no_fallback` option (line 381):

```python
    raw: bool = typer.Option(
        False, "--raw",
        help="Disable snippet skeletonization; return full raw snippets.",
    ),
```

and in the `search_payload(...)` call add `raw=raw,`. For `explain`, add the same `raw` option and pass `raw=raw,` to its `search_payload(...)` call.

**`mcp/server.py`** — `search_code`: add `raw: bool = False,` to the signature (after `offset`), document it in the docstring (`raw: If true, return full raw snippets instead of skeletons.`), and pass `raw=raw,` into `search_payload(...)`. Do the same for `explain_code`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_cli.py tests/test_mcp_server.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/service.py src/codebase_index/cli.py src/codebase_index/mcp/server.py tests/test_cli.py tests/test_mcp_server.py
git commit -m "$(cat <<'EOF'
feat(cli,mcp): --raw / raw flag to disable snippet skeletonization

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 8: Document the contract — SKILL.md + CHANGELOG

**Files:**
- Modify: `skill/SKILL.md` (the "Token-budgeted output interpretation" section, ~lines 98-128)
- Modify: `CHANGELOG.md` (top, under a new Unreleased/next-minor heading)

**Interfaces:**
- Consumes: the `skeletonized` / `elided_lines` fields (Task 5) and the `--raw` flag (Task 7).
- Produces: documentation only.

- [ ] **Step 1: Update SKILL.md**

In the `## Token-budgeted output interpretation` list, after the `snippet` bullet (`SKILL.md:108`), add:

```markdown
- `skeletonized` — when `true`, the `snippet` is a **focus skeleton**: import/signature/class
  lines and the line(s) matching your query are kept; function bodies are collapsed to a marker
  like `... 24 lines elided (read 88-134)`. Read that line range (or the result's
  `line_start`/`line_end`) when you need a full body.
- `elided_lines` — how many source lines the skeleton folded away (`0` when not skeletonized).
```

In `## Token efficiency rules`, add a bullet:

```markdown
- Snippets are skeletonized by default to fit more results in the budget. The matched line is
  always preserved; pass `--raw` (CLI) or `raw: true` (MCP) on the rare occasion you need full
  bodies inline instead of reading the cited line range.
```

- [ ] **Step 2: Update CHANGELOG.md**

Add at the top of the changelog (under the standard next-version heading used by this repo):

```markdown
### Added
- **Snippet skeletonization & content-aware rendering.** Search/explain snippets are now focus
  skeletons — signatures and the query-matching line are kept while function bodies collapse to a
  `... N lines elided (read A-B)` marker — so more ranked results fit the same token budget.
  Content-aware (code via tree-sitter, markdown headings, structured-config keys), reversible via
  `recommended_reads`, and safe (raw fallback on any parse miss). New `skeletonized` /
  `elided_lines` result fields; new `retrieval.compact_snippets` / `retrieval.compact_min_reduction`
  config knobs (no reindex); disable per-call with `--raw` (CLI) or `raw: true` (MCP).
```

- [ ] **Step 3: Verify docs render and reference real fields**

Run: `python -m pytest tests/test_plugin_skill_parity.py -v`
Expected: PASS (skill text stays consistent across installed targets; if this test pins skill content, update its fixture as it directs).

- [ ] **Step 4: Commit**

```bash
git add skill/SKILL.md CHANGELOG.md
git commit -m "$(cat <<'EOF'
docs: document snippet skeletonization fields and --raw flag

Co-Authored-By: Claude Opus 4.8 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

### Task 9: Full-suite verification

**Files:** none (verification only).

- [ ] **Step 1: Run the whole test suite**

Run: `python -m pytest -q`
Expected: all pass (no regressions in `test_budget`, `test_pipeline_search`, `test_cli`, `test_mcp_server`, `test_output`, golden tests).

- [ ] **Step 2: Run the linters/type-checks the repo uses**

Run: `python -m ruff check src tests && python -m mypy src`
Expected: clean (match the repo's CI; fix any new findings in the touched files).

- [ ] **Step 3: Manual smoke check**

Run:
```bash
python -m codebase_index index
python -m codebase_index search "apply budget snippet" --json
python -m codebase_index search "apply budget snippet" --json --raw
```
Expected: the first JSON shows `"skeletonized": true` on at least one code result with an
`elided_lines > 0` and a `... N lines elided (read A-B)` marker in its snippet; the `--raw` run
shows `"skeletonized": false` everywhere with full snippet bodies.

---

## Self-Review

**1. Spec coverage**
- §4.1 core abstraction (`render_skeleton`, `classify_lines`, `compact`, `Compacted`) → Tasks 1, 2.
- §4.2 content-aware classifiers (code/markdown/structured/other) → Tasks 2, 3.
- §4.3 policy & focus (intent→ctx, focus invariant, savings guard) → Tasks 2, 4.
- §4.4 budget integration (`compactor` DI, reduced cost → more snippets) → Task 5.
- §4.5 output fields (`skeletonized`, `elided_lines`, compacted `token_est`) → Task 5.
- §4.6 surface (CLI `--raw`, MCP `raw`, config knobs, SKILL.md) → Tasks 6, 7, 8. *(architecture scoped out — no snippets; noted in File Structure.)*
- §5 error handling (never raises, fallback chain, preserve bias, focus invariant, redact order, determinism) → Tasks 2, 5; tests in Task 2.
- §7 testing → Tasks 1-9. §8 backward compat (`--raw`/`compact=False` identical) → Task 5 `test_none_compactor_is_unchanged_behavior`, Task 6 raw assertion.

**2. Placeholder scan** — the only `...` literals are: (a) the documented Python `def f(): pass`/marker strings, and (b) `tests/test_pipeline_search.py` Step 1, which is explicitly flagged as "fill using the file's existing index fixture" with the exact two calls + assertions to insert. No "TBD/handle edge cases/add validation" placeholders.

**3. Type consistency** — `compact(...)` is defined with `ctx_lines: int` in Task 2 and always called with `ctx_lines=` (Tasks 2, 4); `make_compactor(...)` signature matches its callers (Tasks 4, 6); `apply_budget(..., compactor=None)` matches Tasks 5, 6; `Compacted` fields (`text`, `token_est`, `elided_lines`, `skeletonized`) are read identically in Tasks 4, 5. `search_payload(..., raw=False)` matches CLI/MCP callers (Task 7). Intent members (`ARCHITECTURE`, `HOW_IT_WORKS`, `DATA_FLOW`, `LOCATE_IMPL`, `KEYWORD`) exist in `retrieval/types.py:Intent`.
