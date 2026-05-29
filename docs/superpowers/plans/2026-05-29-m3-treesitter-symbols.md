# M3 — Tree-sitter Symbol Extraction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `codebase-index symbol "<name>"` and `codebase-index refs "<name>"` work for supported languages by extracting symbol definitions (and intra-file call edges) via tree-sitter, with symbol-aligned chunks; unsupported/unparseable files fall back to the M2 line chunker.

**Architecture:** A per-language registry (`parsers/languages.py`) holds tree-sitter query strings for definitions and calls plus a capture→kind map. `parsers/treesitter.py` runs those queries to produce `Symbol` defs (kind, qualified name, signature, docstring, parent), intra-file `Edge`s (call sites), and symbol-aligned `Chunk`s (one per top-level symbol + gap windows for top-level code). The indexer picks the tree-sitter parser when a grammar is registered, else the M2 line chunker. Storage gains `symbols`/`edges` accessors. Retrieval gains `symbol_lookup` and `refs_lookup`; the CLI wires `symbol` and `refs`. Cross-file edge resolution, imports/inheritance, graph degrees, and `impact` stay in M5.

**Tech Stack:** Python 3.10+, `tree-sitter` + `tree-sitter-language-pack` (already in base deps), stdlib `sqlite3`, pydantic v2, Typer, pytest. Builds on M1 (storage/discovery/pipeline) and M2 (chunks/FTS/searchers/output).

**Scope decision — supported languages:** M3 delivers the engine plus **Python, JavaScript, and TypeScript** (the languages present in `tests/fixtures/sample_repo/`), so every task is testable against real fixtures. The registry is built so each additional ROADMAP language (Go, Java, Rust, C/C++, Ruby, PHP) is added by appending one `LangSpec` with its query strings — captured as a repeatable recipe in Task 10. Unsupported languages keep the M2 line-chunk + FTS behavior, so nothing regresses.

**Depends on:** M1, M2. This plan extends `storage/repo.py`, `indexer/pipeline.py`, `output/*`, `retrieval/searchers.py`, `models.py`, and `cli.py`; it does not recreate them.

---

## File Structure

| File | Create/Modify | Responsibility |
|---|---|---|
| `src/codebase_index/parsers/base.py` | Modify | Add `Edge` dataclass + `edges` field on `ParseResult`. |
| `src/codebase_index/parsers/languages.py` | Create | `LangSpec` registry: ts grammar name, defs/calls query strings, capture→kind map; `is_supported`, `spec_for`. |
| `src/codebase_index/parsers/treesitter.py` | Create | Parse text → symbols + edges + symbol-aligned chunks. Defensive tree-sitter API adapter. |
| `src/codebase_index/storage/repo.py` | Modify | `replace_symbols` (two-pass parent), `replace_edges`, `symbols_by_name`, `refs_for_name`, `count_symbols`, `count_edges`; extend `replace_chunks` with symbol-id mapping. |
| `src/codebase_index/indexer/pipeline.py` | Modify | Pick parser by language; populate symbols/edges/symbol-aligned chunks; resolve edge targets intra-file. Track counts. |
| `src/codebase_index/models.py` | Modify | Add `SymbolDef`/`SymbolResponse`, `RefSite`/`RefsResponse`. |
| `src/codebase_index/retrieval/searchers.py` | Modify | Add `symbol_lookup` and `refs_lookup` (reuse `_freshness`). |
| `src/codebase_index/output/json.py` | Modify | Make `render` accept any pydantic model. |
| `src/codebase_index/output/markdown.py` | Modify | Add `render_symbols` and `render_refs`. |
| `src/codebase_index/cli.py` | Modify | Wire `symbol` and `refs` commands. |
| `tests/fixtures/sample_repo/src/auth/token.py` | Modify | Add an intra-file caller of `refresh_access_token` for refs tests. |
| `tests/test_languages.py` | Create | Registry lookups + every registered query compiles against its grammar. |
| `tests/test_treesitter.py` | Create | Symbols/edges/chunks extracted from py & ts snippets. |
| `tests/test_storage.py` | Modify | symbol/edge accessors + chunk symbol-id linkage. |
| `tests/test_pipeline.py` | Modify | `build_index` populates symbols/edges; reindex idempotent. |
| `tests/test_symbol_refs.py` | Create | `symbol_lookup`/`refs_lookup` over the fixture. |
| `tests/test_symbol_cli.py` | Create | `symbol`/`refs` CLI end-to-end. |

**Conventions:** `from __future__ import annotations`; all SQL in `storage/repo.py`; `--json` stays plain.

---

## Task 1: Languages registry + query compilation guard

**Files:**
- Modify: `src/codebase_index/parsers/base.py`
- Create: `src/codebase_index/parsers/languages.py`
- Test: `tests/test_languages.py`

- [ ] **Step 1: Pin the installed tree-sitter API (manual, one-time)**

Run:

```bash
pip install -e .
python - <<'PY'
import tree_sitter, tree_sitter_language_pack as p
print("tree_sitter", tree_sitter.__version__)
lang = p.get_language("python")
q = lang.query("(function_definition name: (identifier) @name) @def.function")
parser = p.get_parser("python")
tree = parser.parse(b"def foo():\n    pass\n")
m = q.matches(tree.root_node)
print("matches type:", type(m), "sample:", m)
root = tree.root_node
print("start_point type:", type(root.start_point), root.start_point)
PY
```

Note in your scratch notes whether `q.matches(...)` returns a list of `(pattern_index, dict[str, list[Node]])` and whether `start_point` is a tuple or a `Point` (has `.row`). The adapter in Task 1/Step 3 handles both; this step just confirms which path runs.

- [ ] **Step 2: Write the failing test**

```python
# tests/test_languages.py
from __future__ import annotations

import pytest
from tree_sitter_language_pack import get_language

from codebase_index.parsers.languages import LANGS, is_supported, spec_for


def test_supported_set():
    assert is_supported("python")
    assert is_supported("typescript")
    assert is_supported("javascript")
    assert not is_supported("cobol")
    assert spec_for("ruby") is None


@pytest.mark.parametrize("lang", sorted(LANGS))
def test_every_query_compiles_against_its_grammar(lang):
    spec = spec_for(lang)
    grammar = get_language(spec.ts_name)
    # compilation raises if a node type / field is wrong for this grammar version
    grammar.query(spec.defs_query)
    grammar.query(spec.calls_query)
```

- [ ] **Step 3: Write minimal implementation**

Add to `src/codebase_index/parsers/base.py`:

```python
# src/codebase_index/parsers/base.py  — add Edge + edges field

@dataclass
class Edge:
    edge_type: str                 # 'call' (M3); import/extends/... arrive in M5
    callee_name: str               # raw target identifier
    line: int                      # 1-based line of the call site
    src_symbol_index: Optional[int] = None  # enclosing symbol (None => file-level)


@dataclass
class ParseResult:
    chunks: list[Chunk] = field(default_factory=list)
    symbols: list[Symbol] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)
```

> Replace the existing `ParseResult` definition; keep `Chunk`, `Symbol`, and the `Parser` protocol.

Create `src/codebase_index/parsers/languages.py`:

```python
# src/codebase_index/parsers/languages.py
"""Per-language tree-sitter specs: grammar name + def/call queries + kind map.

Capture naming convention: a definition pattern is captured as `@def.<kind>`
(e.g. @def.function, @def.class, @def.method, @def.interface, @def.enum,
@def.type) with the name node captured as `@name`. Call patterns capture the
callee identifier as `@callee`. Adding a language = appending one LangSpec.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

# Container kinds: a function defined inside one of these becomes a 'method'.
CONTAINER_KINDS = {"class", "interface", "enum"}


@dataclass(frozen=True)
class LangSpec:
    name: str          # our language id (matches discovery.classify)
    ts_name: str       # tree-sitter-language-pack grammar name
    defs_query: str
    calls_query: str


_PYTHON = LangSpec(
    name="python",
    ts_name="python",
    defs_query="""
        (function_definition name: (identifier) @name) @def.function
        (class_definition    name: (identifier) @name) @def.class
    """,
    calls_query="""
        (call function: (identifier) @callee)
        (call function: (attribute attribute: (identifier) @callee))
    """,
)

# JavaScript: arrow/function-expression consts count as functions.
_JS_DEFS = """
    (function_declaration name: (identifier) @name) @def.function
    (class_declaration    name: (identifier) @name) @def.class
    (method_definition    name: (property_identifier) @name) @def.method
    (variable_declarator  name: (identifier) @name value: (arrow_function)) @def.function
    (variable_declarator  name: (identifier) @name value: (function_expression)) @def.function
"""
_JS_CALLS = """
    (call_expression function: (identifier) @callee)
    (call_expression function: (member_expression property: (property_identifier) @callee))
"""

_JAVASCRIPT = LangSpec(
    name="javascript", ts_name="javascript", defs_query=_JS_DEFS, calls_query=_JS_CALLS,
)

# TypeScript: class names are type_identifier; adds interface/enum/type.
_TS_DEFS = """
    (function_declaration name: (identifier) @name) @def.function
    (class_declaration    name: (type_identifier) @name) @def.class
    (method_definition    name: (property_identifier) @name) @def.method
    (variable_declarator  name: (identifier) @name value: (arrow_function)) @def.function
    (interface_declaration name: (type_identifier) @name) @def.interface
    (enum_declaration      name: (identifier) @name) @def.enum
    (type_alias_declaration name: (type_identifier) @name) @def.type
"""
_TYPESCRIPT = LangSpec(
    name="typescript", ts_name="typescript", defs_query=_TS_DEFS, calls_query=_JS_CALLS,
)

LANGS: dict[str, LangSpec] = {
    s.name: s for s in (_PYTHON, _JAVASCRIPT, _TYPESCRIPT)
}


def is_supported(lang: Optional[str]) -> bool:
    return lang in LANGS


def spec_for(lang: Optional[str]) -> Optional[LangSpec]:
    return LANGS.get(lang) if lang else None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_languages.py -v`
Expected: PASS. **If a `grammar.query(...)` raises**, the node type/field name differs in the installed grammar version — inspect a sample with `parser.parse(b"...").root_node` and `.children`/`repr`, then correct the query string. This is the intended early-failure point for grammar drift.

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/parsers/base.py src/codebase_index/parsers/languages.py tests/test_languages.py
git commit -m "feat(parsers): tree-sitter language registry (py/js/ts) with query compile guard"
```

---

## Task 2: Tree-sitter parser — symbols

**Files:**
- Create: `src/codebase_index/parsers/treesitter.py`
- Test: `tests/test_treesitter.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_treesitter.py
from __future__ import annotations

from codebase_index.parsers.treesitter import parse_file

PY = '''\
"""mod doc"""
import os


def refresh_access_token(refresh_token):
    """Exchange refresh for access."""
    return "access-" + refresh_token


class User:
    def __init__(self, name):
        self.name = name
'''


def test_python_symbols():
    pr = parse_file("python", PY)
    by_name = {s.name: s for s in pr.symbols}
    assert "refresh_access_token" in by_name
    fn = by_name["refresh_access_token"]
    assert fn.kind == "function"
    assert fn.line_start == 5
    assert fn.signature.startswith("def refresh_access_token(")
    assert "Exchange refresh" in (fn.docstring or "")

    assert by_name["User"].kind == "class"
    # __init__ is a method whose parent is User
    init = by_name["__init__"]
    assert init.kind == "method"
    assert init.qualified == "User.__init__"


TS = '''\
export function bootstrap(): void {
  start();
}

export class Service {
  run(): void {}
}

interface Options { x: number; }
'''


def test_typescript_symbols():
    pr = parse_file("typescript", TS)
    kinds = {s.name: s.kind for s in pr.symbols}
    assert kinds["bootstrap"] == "function"
    assert kinds["Service"] == "class"
    assert kinds["run"] == "method"
    assert kinds["Options"] == "interface"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_treesitter.py -v`
Expected: FAIL — `ModuleNotFoundError: codebase_index.parsers.treesitter`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/codebase_index/parsers/treesitter.py
"""Tree-sitter parsing: text -> symbols (+ edges + symbol-aligned chunks).

Defensive against tree-sitter API drift: handles `Query.matches` returning a
list of (pattern_index, dict) and `Point` being either a tuple or an object
with `.row`.
"""

from __future__ import annotations

from typing import Optional

from tree_sitter_language_pack import get_language, get_parser

from .base import Edge, ParseResult, Symbol
from .languages import CONTAINER_KINDS, LangSpec, spec_for


class UnsupportedLanguage(Exception):
    pass


def _row(point) -> int:
    return point.row if hasattr(point, "row") else point[0]


def _text(node) -> str:
    return node.text.decode("utf-8", errors="ignore")


def _matches(query, root):
    """Yield {capture_name: node} dicts, one per match (first node per capture)."""
    for _pattern_index, caps in query.matches(root):
        flat: dict[str, object] = {}
        for cap_name, nodes in caps.items():
            if nodes:
                flat[cap_name] = nodes[0] if isinstance(nodes, list) else nodes
        yield flat


def _kind_from_capture(caps: dict) -> Optional[tuple[str, object]]:
    for cap_name, node in caps.items():
        if cap_name.startswith("def."):
            return cap_name.split(".", 1)[1], node
    return None


def _signature(def_node) -> str:
    return _text(def_node).splitlines()[0].strip().rstrip("{").strip()


def _python_docstring(def_node) -> Optional[str]:
    body = def_node.child_by_field_name("body")
    if body is None:
        return None
    for stmt in body.named_children:
        if stmt.type == "expression_statement" and stmt.named_children:
            s = stmt.named_children[0]
            if s.type == "string":
                return _text(s).strip().strip('"').strip("'").strip()
        break  # only the first statement can be a docstring
    return None


def parse_file(lang: str, text: str) -> ParseResult:
    spec = spec_for(lang)
    if spec is None:
        raise UnsupportedLanguage(lang)
    grammar = get_language(spec.ts_name)
    parser = get_parser(spec.ts_name)
    tree = parser.parse(text.encode("utf-8"))
    root = tree.root_node

    symbols = _extract_symbols(spec, grammar, root, lang)
    from .symbol_chunks import build_chunks  # local import avoids cycle
    edges = _extract_edges(spec, grammar, root, symbols)
    chunks = build_chunks(text, symbols)
    return ParseResult(chunks=chunks, symbols=symbols, edges=edges)


# -- symbols -------------------------------------------------------------
class _Sym:
    __slots__ = ("symbol", "start_byte", "end_byte", "def_node")

    def __init__(self, symbol: Symbol, def_node) -> None:
        self.symbol = symbol
        self.start_byte = def_node.start_byte
        self.end_byte = def_node.end_byte
        self.def_node = def_node


def _extract_symbols(spec: LangSpec, grammar, root, lang: str) -> list[Symbol]:
    query = grammar.query(spec.defs_query)
    raw: list[_Sym] = []
    for caps in _matches(query, root):
        kind_node = _kind_from_capture(caps)
        name_node = caps.get("name")
        if kind_node is None or name_node is None:
            continue
        kind, def_node = kind_node
        sym = Symbol(
            name=_text(name_node),
            kind=kind,
            line_start=_row(def_node.start_point) + 1,
            line_end=_row(def_node.end_point) + 1,
            signature=_signature(def_node),
            docstring=_python_docstring(def_node) if lang == "python" else None,
        )
        raw.append(_Sym(sym, def_node))

    # resolve parent by smallest strict container; relabel function->method
    raw.sort(key=lambda r: (r.start_byte, -(r.end_byte)))
    for i, r in enumerate(raw):
        parent = _enclosing(raw, r)
        if parent is not None:
            r.symbol.parent_index = raw.index(parent)
            if r.symbol.kind == "function" and parent.symbol.kind in CONTAINER_KINDS:
                r.symbol.kind = "method"
            r.symbol.qualified = f"{_qualified(parent)}.{r.symbol.name}"
        else:
            r.symbol.qualified = r.symbol.name
    return [r.symbol for r in raw]


def _enclosing(raw: list[_Sym], child: _Sym) -> Optional[_Sym]:
    best: Optional[_Sym] = None
    for other in raw:
        if other is child:
            continue
        if other.start_byte <= child.start_byte and other.end_byte >= child.end_byte \
                and (other.end_byte - other.start_byte) > (child.end_byte - child.start_byte):
            if best is None or (other.end_byte - other.start_byte) < (best.end_byte - best.start_byte):
                best = other
    return best


def _qualified(r: _Sym) -> str:
    return r.symbol.qualified or r.symbol.name


# -- edges ---------------------------------------------------------------
def _extract_edges(spec: LangSpec, grammar, root, symbols: list[Symbol]) -> list[Edge]:
    query = grammar.query(spec.calls_query)
    edges: list[Edge] = []
    for caps in _matches(query, root):
        callee = caps.get("callee")
        if callee is None:
            continue
        line = _row(callee.start_point) + 1
        edges.append(Edge(
            edge_type="call",
            callee_name=_text(callee),
            line=line,
            src_symbol_index=_enclosing_symbol_index(symbols, line),
        ))
    return edges


def _enclosing_symbol_index(symbols: list[Symbol], line: int) -> Optional[int]:
    best_idx: Optional[int] = None
    best_span = None
    for idx, s in enumerate(symbols):
        if s.line_start <= line <= s.line_end:
            span = s.line_end - s.line_start
            if best_span is None or span < best_span:
                best_span, best_idx = span, idx
    return best_idx
```

> The `symbol_chunks.build_chunks` import is implemented in Task 3 — this task's tests touch only
> `pr.symbols`, so create a temporary stub `src/codebase_index/parsers/symbol_chunks.py` with
> `def build_chunks(text, symbols): return []` to make Task 2 pass, then replace it in Task 3.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_treesitter.py -v`
Expected: PASS (2 tests). If a capture name/field mismatches the grammar, fix the query in `languages.py` (Task 1).

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/parsers/treesitter.py src/codebase_index/parsers/symbol_chunks.py tests/test_treesitter.py
git commit -m "feat(parsers): tree-sitter symbol extraction (kind/parent/signature/docstring)"
```

---

## Task 3: Symbol-aligned chunking

**Files:**
- Create/Replace: `src/codebase_index/parsers/symbol_chunks.py`
- Test: `tests/test_treesitter.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_treesitter.py  (append)
from codebase_index.parsers.symbol_chunks import build_chunks
from codebase_index.parsers.base import Symbol


def test_symbol_body_chunks_link_symbols():
    text = "import os\n\n\ndef a():\n    return 1\n\n\ndef b():\n    return 2\n"
    symbols = [
        Symbol(name="a", kind="function", line_start=4, line_end=5),
        Symbol(name="b", kind="function", line_start=8, line_end=9),
    ]
    chunks = build_chunks(text, symbols)
    bodies = [c for c in chunks if c.kind == "symbol_body"]
    assert len(bodies) == 2
    assert bodies[0].symbol_index == 0 and bodies[0].line_start == 4
    assert bodies[1].symbol_index == 1
    # a gap window covers the top-of-file import region (lines 1..3)
    gaps = [c for c in chunks if c.kind == "window"]
    assert any(g.line_start == 1 for g in gaps)


def test_no_symbols_falls_back_to_windows():
    text = "x = 1\ny = 2\n"
    chunks = build_chunks(text, [])
    assert chunks and all(c.kind == "window" for c in chunks)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_treesitter.py::test_symbol_body_chunks_link_symbols -v`
Expected: FAIL — current stub returns `[]`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/codebase_index/parsers/symbol_chunks.py
"""Symbol-aligned chunking: one chunk per top-level symbol body, plus line-window
chunks for the gaps between symbols (imports / top-level code) so FTS coverage
stays complete. Falls back to plain windows when there are no symbols."""

from __future__ import annotations

from .base import Chunk, Symbol
from .line_chunker import chunk_text, estimate_tokens

_GAP_WINDOW = 80
_GAP_OVERLAP = 0


def build_chunks(text: str, symbols: list[Symbol]) -> list[Chunk]:
    if not text.strip():
        return []
    if not symbols:
        return chunk_text(text, window_lines=80, overlap_lines=10)

    lines = text.splitlines()
    n = len(lines)
    # top-level symbols only (no parent), sorted by position
    top = sorted(
        [s for s in symbols if s.parent_index is None],
        key=lambda s: s.line_start,
    )

    chunks: list[Chunk] = []
    cursor = 1  # 1-based next uncovered line
    for s in top:
        sym_index = symbols.index(s)
        if s.line_start > cursor:
            chunks.extend(_gap(lines, cursor, s.line_start - 1))
        body = "\n".join(lines[s.line_start - 1:s.line_end])
        chunks.append(Chunk(
            line_start=s.line_start, line_end=s.line_end,
            content=body, token_est=estimate_tokens(body),
            kind="symbol_body", symbol_index=sym_index,
        ))
        cursor = max(cursor, s.line_end + 1)
    if cursor <= n:
        chunks.extend(_gap(lines, cursor, n))
    return chunks


def _gap(lines: list[str], start: int, end: int) -> list[Chunk]:
    """Window-chunk lines [start, end] (1-based inclusive)."""
    segment = "\n".join(lines[start - 1:end])
    if not segment.strip():
        return []
    out: list[Chunk] = []
    for c in chunk_text(segment, window_lines=_GAP_WINDOW, overlap_lines=_GAP_OVERLAP):
        out.append(Chunk(
            line_start=start + c.line_start - 1,
            line_end=start + c.line_end - 1,
            content=c.content, token_est=c.token_est, kind="window",
        ))
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_treesitter.py -v`
Expected: PASS (4 tests total).

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/parsers/symbol_chunks.py tests/test_treesitter.py
git commit -m "feat(parsers): symbol-aligned chunking with gap windows"
```

---

## Task 4: Storage — symbol/edge accessors + chunk symbol-id linkage

**Files:**
- Modify: `src/codebase_index/storage/repo.py`
- Test: `tests/test_storage.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_storage.py  (append)
from codebase_index.parsers.base import Edge, Symbol


def test_replace_symbols_resolves_parents(tmp_path):
    db = _open(tmp_path)
    fid = repo.upsert_file(
        db.conn, path="m.py", lang="python", size_bytes=1, sha256="h",
        mtime_ns=1, git_status=None, parser="treesitter", indexed_at="t", is_generated=False,
    )
    ids = repo.replace_symbols(db.conn, fid, [
        Symbol(name="User", kind="class", line_start=1, line_end=10, qualified="User"),
        Symbol(name="__init__", kind="method", line_start=2, line_end=4,
               qualified="User.__init__", parent_index=0),
    ])
    assert len(ids) == 2
    rows = {r["name"]: r for r in repo.symbols_by_name(db.conn, "__init__")}
    assert rows["__init__"]["parent_id"] == ids[0]
    assert repo.count_symbols(db.conn) == 2
    db.close()


def test_replace_chunks_with_symbol_ids(tmp_path):
    db = _open(tmp_path)
    fid = repo.upsert_file(
        db.conn, path="m.py", lang="python", size_bytes=1, sha256="h",
        mtime_ns=1, git_status=None, parser="treesitter", indexed_at="t", is_generated=False,
    )
    sids = repo.replace_symbols(db.conn, fid, [
        Symbol(name="a", kind="function", line_start=1, line_end=2, qualified="a"),
    ])
    from codebase_index.parsers.base import Chunk
    repo.replace_chunks(db.conn, fid, [
        Chunk(line_start=1, line_end=2, content="def a(): pass", token_est=3,
              kind="symbol_body", symbol_index=0),
    ], symbol_ids=sids)
    row = repo.chunks_for_file(db.conn, fid)[0]
    assert row["symbol_id"] == sids[0]
    assert row["kind"] == "symbol_body"
    db.close()


def test_replace_edges_and_refs_for_name(tmp_path):
    db = _open(tmp_path)
    fid = repo.upsert_file(
        db.conn, path="m.py", lang="python", size_bytes=1, sha256="h",
        mtime_ns=1, git_status=None, parser="treesitter", indexed_at="t", is_generated=False,
    )
    sids = repo.replace_symbols(db.conn, fid, [
        Symbol(name="target", kind="function", line_start=1, line_end=2, qualified="target"),
        Symbol(name="caller", kind="function", line_start=4, line_end=6, qualified="caller"),
    ])
    repo.replace_edges(db.conn, fid, [
        {"edge_type": "call", "src_kind": "symbol", "src_id": sids[1],
         "dst_kind": "symbol", "dst_id": sids[0], "dst_name": "target",
         "line": 5, "resolved": 1},
    ])
    assert repo.count_edges(db.conn) == 1
    sites = repo.refs_for_name(db.conn, "target")
    assert len(sites) == 1 and sites[0]["line"] == 5 and sites[0]["path"] == "m.py"
    db.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_storage.py -v`
Expected: FAIL — `AttributeError: module 'repo' has no attribute 'replace_symbols'`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/codebase_index/storage/repo.py` (add `from ..parsers.base import Edge, Symbol` and `from typing import Any` to imports):

```python
# src/codebase_index/storage/repo.py  (append)

def replace_symbols(conn: sqlite3.Connection, file_id: int, symbols: "Sequence[Symbol]") -> list[int]:
    """Delete a file's symbols, insert the new set, resolve parent links in a
    second pass. Returns inserted ids in the same order as `symbols`."""
    conn.execute("DELETE FROM symbols WHERE file_id = ?", (file_id,))
    ids: list[int] = []
    for s in symbols:
        cur = conn.execute(
            """
            INSERT INTO symbols
                (file_id, name, qualified, kind, line_start, line_end, signature,
                 parent_id, docstring, in_degree, out_degree)
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL, ?, 0, 0)
            """,
            (file_id, s.name, s.qualified, s.kind, s.line_start, s.line_end,
             s.signature, s.docstring),
        )
        ids.append(int(cur.lastrowid))
    for s, sid in zip(symbols, ids):
        if s.parent_index is not None:
            conn.execute("UPDATE symbols SET parent_id = ? WHERE id = ?",
                         (ids[s.parent_index], sid))
    return ids


def symbols_by_name(
    conn: sqlite3.Connection, name: str, *, kind: Optional[str] = None, exact: bool = True
) -> list[sqlite3.Row]:
    sql = """
        SELECT s.*, f.path AS path
        FROM symbols s JOIN files f ON f.id = s.file_id
        WHERE s.name {op} ?
    """.format(op="=" if exact else "LIKE")
    params: list[Any] = [name if exact else f"{name}%"]
    if kind:
        sql += " AND s.kind = ?"
        params.append(kind)
    sql += " ORDER BY s.name, f.path, s.line_start"
    return conn.execute(sql, params).fetchall()


def count_symbols(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0])


def replace_edges(conn: sqlite3.Connection, file_id: int, edges: "Sequence[dict[str, Any]]") -> int:
    conn.execute("DELETE FROM edges WHERE file_id = ?", (file_id,))
    conn.executemany(
        """
        INSERT INTO edges
            (edge_type, src_kind, src_id, dst_kind, dst_id, dst_name, file_id, line, resolved)
        VALUES
            (:edge_type, :src_kind, :src_id, :dst_kind, :dst_id, :dst_name, :file_id, :line, :resolved)
        """,
        [{**e, "file_id": file_id} for e in edges],
    )
    return len(edges)


def count_edges(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0])


def refs_for_name(conn: sqlite3.Connection, name: str) -> list[sqlite3.Row]:
    """Call sites targeting `name` (intra-file edges) with their file + line."""
    return conn.execute(
        """
        SELECT e.line AS line, f.path AS path, e.edge_type AS edge_type,
               e.resolved AS resolved, e.src_id AS src_id, e.src_kind AS src_kind
        FROM edges e JOIN files f ON f.id = e.file_id
        WHERE e.dst_name = ? AND e.edge_type = 'call'
        ORDER BY f.path, e.line
        """,
        (name,),
    ).fetchall()
```

Modify the existing `replace_chunks` to accept and apply a symbol-id mapping:

```python
# src/codebase_index/storage/repo.py  — replace replace_chunks

def replace_chunks(
    conn: sqlite3.Connection,
    file_id: int,
    chunks: "Sequence[Chunk]",
    symbol_ids: "Optional[Sequence[int]]" = None,
) -> int:
    """Delete a file's chunks then insert the new set. If a chunk carries a
    `symbol_index` and `symbol_ids` is provided, link it to that symbol id."""
    conn.execute("DELETE FROM chunks WHERE file_id = ?", (file_id,))

    def _sid(c: "Chunk") -> Optional[int]:
        if c.symbol_index is not None and symbol_ids is not None:
            return symbol_ids[c.symbol_index]
        return None

    conn.executemany(
        """
        INSERT INTO chunks (file_id, line_start, line_end, kind, symbol_id, content, token_est)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        [
            (file_id, c.line_start, c.line_end, c.kind, _sid(c), c.content, c.token_est)
            for c in chunks
        ],
    )
    return len(chunks)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_storage.py -v`
Expected: PASS (all storage tests).

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/storage/repo.py tests/test_storage.py
git commit -m "feat(storage): symbol/edge accessors + chunk symbol-id linkage"
```

---

## Task 5: Indexer — populate symbols, edges, symbol-aligned chunks

**Files:**
- Modify: `src/codebase_index/indexer/pipeline.py`
- Modify: `tests/fixtures/sample_repo/src/auth/token.py` (add a caller)
- Test: `tests/test_pipeline.py` (append)

- [ ] **Step 1: Add an intra-file caller to the fixture**

Append to `tests/fixtures/sample_repo/src/auth/token.py`:

```python


def login(refresh_token: str) -> str:
    """Calls refresh_access_token so refs/impact tests have an edge."""
    return refresh_access_token(refresh_token)
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_pipeline.py  (append)
def test_build_populates_symbols_and_edges(sample_repo, tmp_path):
    cfg = Config()
    cfg.root = str(sample_repo)
    db = Database(tmp_path / "index.sqlite").open()
    stats = build_index(cfg, db, root=sample_repo)

    assert stats.symbols > 0
    assert _repo.count_symbols(db.conn) == stats.symbols
    # the symbol exists with the right kind
    defs = _repo.symbols_by_name(db.conn, "refresh_access_token")
    assert any(r["kind"] == "function" and r["path"] == "src/auth/token.py" for r in defs)
    # login() calls refresh_access_token -> a resolved intra-file edge exists
    sites = _repo.refs_for_name(db.conn, "refresh_access_token")
    assert any(s["path"] == "src/auth/token.py" and s["resolved"] == 1 for s in sites)
    db.close()


def test_symbol_body_chunks_linked(sample_repo, tmp_path):
    cfg = Config()
    cfg.root = str(sample_repo)
    db = Database(tmp_path / "index.sqlite").open()
    build_index(cfg, db, root=sample_repo)
    linked = db.conn.execute(
        "SELECT COUNT(*) FROM chunks WHERE symbol_id IS NOT NULL"
    ).fetchone()[0]
    assert linked > 0
    db.close()


def test_reindex_symbols_idempotent(sample_repo, tmp_path):
    cfg = Config()
    cfg.root = str(sample_repo)
    db = Database(tmp_path / "index.sqlite").open()
    s1 = build_index(cfg, db, root=sample_repo)
    s2 = build_index(cfg, db, root=sample_repo)
    assert s1.symbols == s2.symbols and s1.chunks == s2.chunks
    db.close()
```

- [ ] **Step 3: Write minimal implementation**

In `src/codebase_index/indexer/pipeline.py`: add `symbols`/`edges` to `BuildStats`, import the parsers, and replace the per-file chunk step with a parser-selecting routine.

```python
# src/codebase_index/indexer/pipeline.py  — modify

from ..parsers import languages
from ..parsers.base import ParseResult
from ..parsers.line_chunker import chunk_text
from ..parsers.treesitter import parse_file


@dataclass
class BuildStats:
    indexed: int = 0
    deleted: int = 0
    total_bytes: int = 0
    chunks: int = 0
    symbols: int = 0
    edges: int = 0
```

Replace the chunking block inside the `for cand in walk(...)` loop (the part after `file_id = repo.upsert_file(...)`):

```python
        text = _read_text(cand.path)
        pr = _parse(cand.lang, text, config)

        sym_ids = repo.replace_symbols(conn, file_id, pr.symbols)
        repo.replace_chunks(conn, file_id, pr.chunks, symbol_ids=sym_ids)
        edge_rows = _resolve_edges(pr, sym_ids, file_id)
        repo.replace_edges(conn, file_id, edge_rows)

        stats.chunks += len(pr.chunks)
        stats.symbols += len(pr.symbols)
        stats.edges += len(edge_rows)

        seen.add(cand.rel_path)
        stats.indexed += 1
        stats.total_bytes += cand.size_bytes
```

Add these helpers near `_read_text`:

```python
def _parse(lang, text: str, config: Config) -> ParseResult:
    if lang and languages.is_supported(lang):
        try:
            return parse_file(lang, text)
        except Exception:
            # UnsupportedLanguage OR any grammar/parse failure -> safe line-chunk
            # fallback. A bad file must never abort the whole index build.
            pass
    chunks = chunk_text(
        text, window_lines=config.chunk.window_lines, overlap_lines=config.chunk.overlap_lines
    )
    return ParseResult(chunks=chunks, symbols=[], edges=[])


def _resolve_edges(pr: ParseResult, sym_ids: list[int], file_id: int) -> list[dict]:
    """Resolve each call edge's target against same-file symbol names (intra-file).
    Unresolved targets keep dst_name with resolved=0 (M5 resolves cross-file)."""
    name_to_id = {s.name: sym_ids[i] for i, s in enumerate(pr.symbols)}
    rows: list[dict] = []
    for e in pr.edges:
        src_id = sym_ids[e.src_symbol_index] if e.src_symbol_index is not None else file_id
        src_kind = "symbol" if e.src_symbol_index is not None else "file"
        dst_id = name_to_id.get(e.callee_name)
        rows.append({
            "edge_type": e.edge_type,
            "src_kind": src_kind, "src_id": src_id,
            "dst_kind": "symbol" if dst_id is not None else None,
            "dst_id": dst_id,
            "dst_name": e.callee_name,
            "line": e.line,
            "resolved": 1 if dst_id is not None else 0,
        })
    return rows
```

> Catching `Exception` in `_parse` is deliberate: a malformed file or a grammar edge case must
> never abort a whole index build — it degrades to line chunks. The narrower `UnsupportedLanguage`
> is listed first for clarity.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_pipeline.py -v`
Expected: PASS (M1/M2 pipeline tests + 3 new).

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/indexer/pipeline.py tests/test_pipeline.py tests/fixtures/sample_repo/src/auth/token.py
git commit -m "feat(indexer): populate symbols/edges/symbol-aligned chunks via tree-sitter"
```

---

## Task 6: Models — symbol & refs responses

**Files:**
- Modify: `src/codebase_index/models.py`
- Test: covered by Task 7 (`tests/test_symbol_refs.py`)

- [ ] **Step 1: Write the implementation (no standalone test; exercised in Task 7)**

Append to `src/codebase_index/models.py`:

```python
# src/codebase_index/models.py  (append)

class SymbolDef(BaseModel):
    name: str
    qualified: Optional[str] = None
    kind: str
    path: str
    line_start: int
    line_end: int
    signature: Optional[str] = None


class SymbolResponse(BaseModel):
    query: str
    index: IndexFreshness
    symbols: list[SymbolDef] = []


class RefSite(BaseModel):
    path: str
    line: int
    kind: str  # 'definition' | 'call'


class RefsResponse(BaseModel):
    query: str
    index: IndexFreshness
    sites: list[RefSite] = []
```

- [ ] **Step 2: Verify import**

Run: `python -c "from codebase_index.models import SymbolResponse, RefsResponse; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 3: Commit**

```bash
git add src/codebase_index/models.py
git commit -m "feat(models): SymbolResponse + RefsResponse"
```

---

## Task 7: Retrieval — `symbol_lookup` + `refs_lookup`

**Files:**
- Modify: `src/codebase_index/retrieval/searchers.py`
- Test: `tests/test_symbol_refs.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_symbol_refs.py
from __future__ import annotations

from codebase_index.config import Config
from codebase_index.indexer.pipeline import build_index
from codebase_index.retrieval.searchers import refs_lookup, symbol_lookup
from codebase_index.storage.db import Database


def _indexed(sample_repo, tmp_path):
    cfg = Config()
    cfg.root = str(sample_repo)
    db = Database(tmp_path / "index.sqlite").open()
    build_index(cfg, db, root=sample_repo)
    return db


def test_symbol_lookup_exact(sample_repo, tmp_path):
    db = _indexed(sample_repo, tmp_path)
    resp = symbol_lookup(db.conn, "refresh_access_token", kind=None, exact=True)
    assert resp.symbols
    s = resp.symbols[0]
    assert s.path == "src/auth/token.py" and s.kind == "function"
    assert resp.index.exists is True
    db.close()


def test_symbol_lookup_kind_filter_and_prefix(sample_repo, tmp_path):
    db = _indexed(sample_repo, tmp_path)
    resp = symbol_lookup(db.conn, "User", kind="class", exact=True)
    assert any(s.name == "User" and s.kind == "class" for s in resp.symbols)
    db.close()


def test_refs_lookup_includes_call_and_def(sample_repo, tmp_path):
    db = _indexed(sample_repo, tmp_path)
    resp = refs_lookup(db.conn, "refresh_access_token", kind="all")
    kinds = {s.kind for s in resp.sites}
    assert "call" in kinds      # login() call site
    assert "definition" in kinds  # the def itself
    callers = refs_lookup(db.conn, "refresh_access_token", kind="callers")
    assert callers.sites and all(s.kind == "call" for s in callers.sites)
    db.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_symbol_refs.py -v`
Expected: FAIL — `ImportError: cannot import name 'symbol_lookup'`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/codebase_index/retrieval/searchers.py` (add the model imports):

```python
# src/codebase_index/retrieval/searchers.py  (append)
from ..models import RefSite, RefsResponse, SymbolDef, SymbolResponse


def symbol_lookup(
    conn: sqlite3.Connection, name: str, *, kind: Optional[str], exact: bool
) -> SymbolResponse:
    rows = repo.symbols_by_name(conn, name, kind=kind, exact=exact)
    symbols = [
        SymbolDef(
            name=r["name"], qualified=r["qualified"], kind=r["kind"], path=r["path"],
            line_start=r["line_start"], line_end=r["line_end"], signature=r["signature"],
        )
        for r in rows
    ]
    return SymbolResponse(query=name, index=_freshness(conn), symbols=symbols)


def refs_lookup(conn: sqlite3.Connection, name: str, *, kind: str) -> RefsResponse:
    sites: list[RefSite] = []
    for r in repo.refs_for_name(conn, name):
        sites.append(RefSite(path=r["path"], line=r["line"], kind="call"))
    if kind == "all":
        for d in repo.symbols_by_name(conn, name, exact=True):
            sites.append(RefSite(path=d["path"], line=d["line_start"], kind="definition"))
    sites.sort(key=lambda s: (s.path, s.line))
    return RefsResponse(query=name, index=_freshness(conn), sites=sites)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_symbol_refs.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/retrieval/searchers.py tests/test_symbol_refs.py
git commit -m "feat(retrieval): symbol_lookup + refs_lookup"
```

---

## Task 8: Output — symbol & refs renderers

**Files:**
- Modify: `src/codebase_index/output/json.py`
- Modify: `src/codebase_index/output/markdown.py`
- Test: `tests/test_output.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_output.py  (append)
from codebase_index.models import IndexFreshness, RefSite, RefsResponse, SymbolDef, SymbolResponse
from codebase_index.output import markdown as md_out
from codebase_index.output import json as json_out
import json as _json


def _fresh():
    return IndexFreshness(exists=True, stale=False, built_at="t")


def test_json_render_accepts_symbol_response():
    resp = SymbolResponse(query="User", index=_fresh(), symbols=[
        SymbolDef(name="User", kind="class", path="src/models/user.py",
                  line_start=4, line_end=6, signature="class User:"),
    ])
    data = _json.loads(json_out.render(resp))
    assert data["symbols"][0]["name"] == "User"


def test_markdown_render_symbols():
    resp = SymbolResponse(query="User", index=_fresh(), symbols=[
        SymbolDef(name="User", kind="class", path="src/models/user.py",
                  line_start=4, line_end=6, signature="class User:"),
    ])
    text = md_out.render_symbols(resp)
    assert "User" in text and "src/models/user.py" in text and "class" in text


def test_markdown_render_refs():
    resp = RefsResponse(query="f", index=_fresh(), sites=[
        RefSite(path="a.py", line=10, kind="call"),
        RefSite(path="a.py", line=2, kind="definition"),
    ])
    text = md_out.render_refs(resp)
    assert "a.py" in text and "10" in text and "definition" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_output.py -v`
Expected: FAIL — `AttributeError: module has no attribute 'render_symbols'`.

- [ ] **Step 3: Write minimal implementation**

Generalize `src/codebase_index/output/json.py`:

```python
# src/codebase_index/output/json.py
"""Machine-readable JSON renderer for any response model."""

from __future__ import annotations

from pydantic import BaseModel


def render(resp: BaseModel) -> str:
    return resp.model_dump_json(indent=2)
```

Append to `src/codebase_index/output/markdown.py`:

```python
# src/codebase_index/output/markdown.py  (append)
from ..models import RefsResponse, SymbolResponse


def render_symbols(resp: SymbolResponse) -> str:
    lines = [f"**symbol:** {resp.query}  ·  **matches:** {len(resp.symbols)}", ""]
    if not resp.symbols:
        return "\n".join(lines + ["_No symbol definitions found._", ""]).rstrip() + "\n"
    lines.append("| kind | name | location | signature |")
    lines.append("|------|------|----------|-----------|")
    for s in resp.symbols:
        sig = (s.signature or "").replace("|", "\\|")
        qn = s.qualified or s.name
        lines.append(f"| {s.kind} | `{qn}` | `{s.path}:{s.line_start}-{s.line_end}` | `{sig}` |")
    return "\n".join(lines).rstrip() + "\n"


def render_refs(resp: RefsResponse) -> str:
    lines = [f"**refs:** {resp.query}  ·  **sites:** {len(resp.sites)}", ""]
    if not resp.sites:
        return "\n".join(lines + ["_No references found._", ""]).rstrip() + "\n"
    lines.append("| kind | location |")
    lines.append("|------|----------|")
    for s in resp.sites:
        lines.append(f"| {s.kind} | `{s.path}:{s.line}` |")
    return "\n".join(lines).rstrip() + "\n"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_output.py -v`
Expected: PASS (M2 output tests + 3 new).

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/output/json.py src/codebase_index/output/markdown.py tests/test_output.py
git commit -m "feat(output): symbol + refs renderers; generalize json.render"
```

---

## Task 9: CLI — wire `symbol` and `refs`

**Files:**
- Modify: `src/codebase_index/cli.py` (the `symbol` and `refs` commands)
- Test: `tests/test_symbol_cli.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_symbol_cli.py
from __future__ import annotations

import json

from typer.testing import CliRunner

from codebase_index.cli import app

runner = CliRunner()


def _index(sample_repo):
    assert runner.invoke(app, ["--root", str(sample_repo), "index"]).exit_code == 0


def test_symbol_command_json(sample_repo):
    _index(sample_repo)
    res = runner.invoke(
        app, ["--root", str(sample_repo), "--json", "symbol", "refresh_access_token"]
    )
    assert res.exit_code == 0, res.output
    data = json.loads(res.output)
    assert any(s["path"] == "src/auth/token.py" for s in data["symbols"])


def test_refs_command_callers(sample_repo):
    _index(sample_repo)
    res = runner.invoke(
        app, ["--root", str(sample_repo), "--json", "refs", "refresh_access_token", "--kind", "callers"]
    )
    assert res.exit_code == 0, res.output
    data = json.loads(res.output)
    assert data["sites"] and all(s["kind"] == "call" for s in data["sites"])


def test_symbol_missing_index(tmp_path):
    empty = tmp_path / "empty"
    (empty / ".git").mkdir(parents=True)
    res = runner.invoke(app, ["--root", str(empty), "--json", "symbol", "anything"])
    assert res.exit_code == 0
    data = json.loads(res.output)
    assert data["index"]["exists"] is False and data["symbols"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_symbol_cli.py -v`
Expected: FAIL — `symbol`/`refs` still print `not implemented`; `json.loads` raises.

- [ ] **Step 3: Write minimal implementation**

Replace the `symbol` and `refs` commands in `src/codebase_index/cli.py`:

```python
# src/codebase_index/cli.py  — replace `symbol`

@app.command()
def symbol(
    ctx: typer.Context,
    name: str = typer.Argument(...),
    kind: Optional[str] = typer.Option(None, "--kind", help="Filter by symbol kind."),
    exact: bool = typer.Option(False, "--exact"),
) -> None:
    """Locate a symbol definition by name."""
    from .config import load
    from .models import IndexFreshness, SymbolResponse
    from .output import json as json_out
    from .output import markdown as md_out
    from .retrieval.searchers import symbol_lookup
    from .storage.db import Database

    is_json = bool(ctx.obj and ctx.obj.get("json"))
    cfg = load(ctx.obj.get("root") if ctx.obj else None)
    db_path = Path(cfg.root) / ".claude" / "cache" / "codebase-index" / "index.sqlite"

    if not db_path.exists():
        empty = SymbolResponse(query=name, index=IndexFreshness(exists=False, stale=False), symbols=[])
        typer.echo(json_out.render(empty) if is_json else md_out.render_symbols(empty))
        raise typer.Exit(code=0)

    with Database(db_path) as db:
        resp = symbol_lookup(db.conn, name, kind=kind, exact=exact)
    typer.echo(json_out.render(resp) if is_json else md_out.render_symbols(resp))


# src/codebase_index/cli.py  — replace `refs`

@app.command()
def refs(
    ctx: typer.Context,
    symbol_name: str = typer.Argument(...),
    kind: str = typer.Option("all", "--kind", help="callers|all"),
) -> None:
    """Find references / callers of a symbol (intra-file in M3)."""
    from .config import load
    from .models import IndexFreshness, RefsResponse
    from .output import json as json_out
    from .output import markdown as md_out
    from .retrieval.searchers import refs_lookup
    from .storage.db import Database

    is_json = bool(ctx.obj and ctx.obj.get("json"))
    cfg = load(ctx.obj.get("root") if ctx.obj else None)
    db_path = Path(cfg.root) / ".claude" / "cache" / "codebase-index" / "index.sqlite"

    if not db_path.exists():
        empty = RefsResponse(
            query=symbol_name, index=IndexFreshness(exists=False, stale=False), sites=[]
        )
        typer.echo(json_out.render(empty) if is_json else md_out.render_refs(empty))
        raise typer.Exit(code=0)

    with Database(db_path) as db:
        resp = refs_lookup(db.conn, symbol_name, kind=kind)
    typer.echo(json_out.render(resp) if is_json else md_out.render_refs(resp))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_symbol_cli.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/cli.py tests/test_symbol_cli.py
git commit -m "feat(cli): wire symbol and refs commands"
```

---

## Task 10: Full suite, lint, manual smoke, roadmap + language recipe

**Files:**
- Modify: `docs/ROADMAP.md` (mark M3 done; scope note)
- Modify: `docs/ARCHITECTURE.md` or a new `docs/LANGUAGES.md` (the add-a-language recipe)

- [ ] **Step 1: Run the whole suite**

Run: `pytest -v`
Expected: all M0–M3 tests PASS.

- [ ] **Step 2: Lint + type-check**

Run: `ruff check src tests` and `mypy src/codebase_index`
Expected: clean. Note: `tree_sitter`/`tree_sitter_language_pack` may lack type stubs — if mypy
complains, add `[[tool.mypy.overrides]]` with `module = ["tree_sitter_language_pack.*"]` and
`ignore_missing_imports = true` to `pyproject.toml`.

- [ ] **Step 3: Manual smoke on this repo**

Run:

```bash
pip install -e .
codebase-index --root . index
codebase-index --root . symbol build_index
codebase-index --root . refs build_index --kind all
codebase-index --root . --json symbol Config --kind class
```

Expected: `symbol build_index` locates it in `indexer/pipeline.py` with a signature; `refs` shows
the call site(s) inside `cli.py`; unsupported-language files (e.g. `.md`) still index as windows.

- [ ] **Step 4: Document the add-a-language recipe**

Create `docs/LANGUAGES.md`:

```markdown
# Adding a language to symbol extraction

1. Confirm `discovery/classify.py::LANG_BY_EXT` maps the extension to a language id, and
   `TREESITTER_LANGS` includes it.
2. Confirm `tree_sitter_language_pack.get_language("<grammar>")` works for the grammar name.
3. Append a `LangSpec` to `parsers/languages.py::LANGS` with:
   - `defs_query`: one pattern per definition kind, captured as `@def.<kind>` with the name node
     captured as `@name`. Kinds: function|method|class|interface|enum|type|var.
   - `calls_query`: capture the callee identifier as `@callee`.
4. Add a fixture file under `tests/fixtures/sample_repo/` and a case in `tests/test_treesitter.py`.
5. Run `pytest tests/test_languages.py` — the compile-guard test catches wrong node types/fields.

Node type names vary by grammar version; inspect with
`get_parser("<grammar>").parse(b"...").root_node` and adjust captures.
```

Then edit `docs/ROADMAP.md`:
- Change the M3 heading to `## M3 — Tree-sitter symbol extraction ✅`.
- Append: *"Shipped languages: Python, JavaScript, TypeScript. Go/Java/Rust/C/C++/Ruby/PHP follow the recipe in docs/LANGUAGES.md. refs is intra-file (call sites + defs); cross-file resolution is M5."*

- [ ] **Step 5: Commit**

```bash
git add docs/ROADMAP.md docs/LANGUAGES.md pyproject.toml
git commit -m "docs: mark M3 complete + add-a-language recipe"
```

---

## Acceptance Criteria (M3 exit)

- `codebase-index index` populates `symbols` (name, qualified, kind, line range, signature,
  Python docstrings, parent links) for Python/JS/TS files, and intra-file `call` edges resolved
  against same-file definitions.
- Chunks for supported files are symbol-aligned (`kind='symbol_body'`, linked via `symbol_id`),
  with gap windows covering top-level/import regions so FTS coverage stays complete.
- `codebase-index symbol "<name>"` returns matching definitions (exact/prefix, `--kind` filter)
  with file/line/signature; `--json` parses.
- `codebase-index refs "<name>" --kind callers|all` returns intra-file call sites (and defs for
  `all`); a missing index returns `index.exists = false`.
- Unsupported or unparseable files degrade safely to line-window chunks; a parse error never aborts
  the build.
- Every registered tree-sitter query compiles against its grammar (guard test); full `pytest` green;
  `ruff` clean; base install network-free.

## Deferred to later milestones (explicitly NOT in M3)

- Cross-file edge resolution, import/extends/implements edges, graph in/out-degree denormalization,
  and `impact` (M5).
- Intent detection, RRF fusion across path/symbol/fts, reranking, `explain` (M4).
- Embeddings / vector search (M6).
- Languages beyond Python/JS/TS — added incrementally via `docs/LANGUAGES.md`.
- Broad (non-call) reference extraction — M3 covers call sites + definitions; richer references
  ride on the M5 graph builder.
- Full staleness detection / incremental `update` (M8).
