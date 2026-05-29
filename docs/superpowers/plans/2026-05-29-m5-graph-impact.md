# M5 — Graph Edges + Impact Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `codebase-index impact "<file-or-symbol>"` returns a sensible blast radius (affected files/symbols, ranked, up/down/both, bounded by `--depth`) by extracting **import** and **inheritance** edges on top of M3's call edges, resolving every edge's target **cross-file**, and denormalizing graph degrees onto `symbols`.

**Architecture:** Edge *extraction* stays per-file in the parser (M3 already emits intra-file `call` edges; M5 adds `import` edges from import statements and `extends`/`implements` edges from class headers, all flowing through the existing `Edge` dataclass and pipeline path). Edge *resolution* becomes a global post-pass: after every file is indexed, `graph/builder.py` resolves each still-unresolved edge against the full repo (symbol targets by unique name; import targets by module→file-suffix match) and recomputes `symbols.in_degree`/`out_degree`. `graph/expand.py` then does a bounded BFS over the resolved `edges` table — incoming edges for `up` (who depends on the target), outgoing for `down` (what the target depends on) — and ranks the affected files. The CLI `impact` command wires it through the same `--json`/Markdown renderers as `symbol`/`refs`.

**Tech Stack:** Python 3.10+, stdlib `sqlite3`, `tree-sitter` + `tree-sitter-language-pack` (base deps), pydantic v2, Typer, pytest. Builds on M1 (storage/discovery/pipeline), M2 (chunks/FTS/output), and M3 (parsers/languages, symbols, intra-file call edges, `symbol`/`refs`).

**Scope decision — shipped behavior:** M5 delivers cross-file resolution + `impact` for the M3 languages (**Python, JavaScript, TypeScript**). Import/inheritance edge *queries* are exercised end-to-end for **Python** (the only cross-file fixture), with the same `LangSpec` slot wired for JS/TS so adding their queries is one string each (recorded in the language recipe). Symbol-target edges resolve only on an **unambiguous** (exactly-one-definition) name match — ambiguous names are left unresolved rather than guessed, keeping the graph free of false edges. This is documented and tested.

**Depends on:** M1, M2, **M3** (this plan assumes `parsers/languages.py`, `parsers/treesitter.py`, the `Edge` dataclass in `parsers/base.py`, the `symbols`/`edges` storage accessors, `retrieval/searchers.py`, and the `symbol`/`refs` CLI commands from the M3 plan are already implemented). It extends those files; it does not recreate them.

---

## File Structure

| File | Create/Modify | Responsibility |
|---|---|---|
| `src/codebase_index/parsers/languages.py` | Modify | Add `imports_query` to `LangSpec`; Python/JS/TS import + inheritance patterns (captures `@import.module`, `@extends.base`, `@implements.iface`). |
| `src/codebase_index/parsers/treesitter.py` | Modify | Extract import + inheritance edges via `imports_query` (capture-prefix → edge_type), appended to the M3 call edges. |
| `src/codebase_index/storage/repo.py` | Modify | Graph SQL: `unresolved_edges`, `resolve_edge`, `symbol_id_for_unique_name`, `files_with_suffix`, `file_by_path`, `symbols_in_file`, `incoming_edges`, `outgoing_edges`, `recompute_degrees`, `count_resolved_edges`. |
| `src/codebase_index/graph/builder.py` | Create | `build_graph(conn)` = `resolve_edges(conn)` (symbol-by-name + import-module→file) then `recompute_degrees(conn)`. |
| `src/codebase_index/graph/expand.py` | Create | `walk_impact(...)` bounded BFS + target resolution; `impact_lookup(...)` → `ImpactResponse`. |
| `src/codebase_index/indexer/pipeline.py` | Modify | Add `edges_resolved` to `BuildStats`; call `build_graph(conn)` after the walk loop. |
| `src/codebase_index/models.py` | Modify | Add `ImpactNode` + `ImpactResponse`. |
| `src/codebase_index/output/markdown.py` | Modify | Add `render_impact`. |
| `src/codebase_index/cli.py` | Modify | Replace the `impact` stub; add `ctx` + freshness/empty-index handling. |
| `tests/fixtures/sample_repo/src/api/service.py` | Create | Cross-file fixture: imports + call + subclass of `User` / `refresh_access_token`. |
| `tests/test_languages.py` | Modify | Compile `imports_query` for every registered grammar. |
| `tests/test_treesitter.py` | Modify | Import + inheritance edges extracted from a Python snippet. |
| `tests/test_storage.py` | Modify | New graph accessors over a synthetic DB. |
| `tests/test_graph.py` | Create | `build_graph` resolution + degrees; `walk_impact`/`impact_lookup` up/down/both. |
| `tests/test_impact_cli.py` | Create | `impact` CLI end-to-end (json + markdown + empty index). |

**Conventions (unchanged from M3):** `from __future__ import annotations` at the top of every module; **all SQL lives in `storage/repo.py`**; `--json` output stays plain (no decoration).

---

## Task 1: Language queries — import + inheritance edges

**Files:**
- Modify: `src/codebase_index/parsers/languages.py`
- Modify: `tests/test_languages.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_languages.py`:

```python
# tests/test_languages.py  (append)
def test_every_imports_query_compiles_against_its_grammar():
    from tree_sitter_language_pack import get_language

    from codebase_index.parsers.languages import LANGS, spec_for

    for lang in sorted(LANGS):
        spec = spec_for(lang)
        # imports_query must exist and compile (raises on a wrong node type/field)
        get_language(spec.ts_name).query(spec.imports_query)


def test_python_imports_query_has_module_and_base_captures():
    from codebase_index.parsers.languages import spec_for

    q = spec_for("python").imports_query
    assert "@import.module" in q
    assert "@extends.base" in q
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_languages.py::test_python_imports_query_has_module_and_base_captures -v`
Expected: FAIL — `AttributeError: 'LangSpec' object has no attribute 'imports_query'`.

- [ ] **Step 3: Write minimal implementation**

In `src/codebase_index/parsers/languages.py`, add the field to `LangSpec` (keep the existing fields and `frozen=True`):

```python
# src/codebase_index/parsers/languages.py  — extend LangSpec
@dataclass(frozen=True)
class LangSpec:
    name: str
    ts_name: str
    defs_query: str
    calls_query: str
    imports_query: str = ""   # M5: import + inheritance edges (capture-prefixed)
```

Add the query strings and attach them to each spec. Capture convention: `@import.module`
(module path text for an import edge, src = the file), `@extends.base` / `@implements.iface`
(base/interface identifier for an inheritance edge, src = the enclosing class symbol).

```python
# src/codebase_index/parsers/languages.py  — add query bodies

_PY_IMPORTS = """
    (import_from_statement module_name: (dotted_name) @import.module)
    (import_statement name: (dotted_name) @import.module)
    (class_definition superclasses: (argument_list (identifier) @extends.base))
"""

# JS/TS: ES module specifier is a string literal; class heritage gives the base name.
_JS_IMPORTS = """
    (import_statement source: (string (string_fragment) @import.module))
    (class_declaration (class_heritage (extends_clause value: (identifier) @extends.base)))
"""

_TS_IMPORTS = """
    (import_statement source: (string (string_fragment) @import.module))
    (class_declaration (class_heritage
        (extends_clause value: (identifier) @extends.base)))
    (class_declaration (class_heritage
        (implements_clause (type_identifier) @implements.iface)))
"""
```

Then add `imports_query=` to each of the three existing `LangSpec(...)` calls. The M3 file already
has them as, e.g.:

```python
_PYTHON = LangSpec(
    name="python", ts_name="python",
    defs_query=""" ... M3 def patterns ... """,
    calls_query=""" ... M3 call patterns ... """,
)
```

Edit each call to append the new keyword argument only — do **not** touch the existing
`defs_query`/`calls_query` literals:

```python
_PYTHON = LangSpec(
    name="python", ts_name="python",
    defs_query=""" ... M3 def patterns (unchanged) ... """,
    calls_query=""" ... M3 call patterns (unchanged) ... """,
    imports_query=_PY_IMPORTS,
)
# likewise: _JAVASCRIPT gets imports_query=_JS_IMPORTS, _TYPESCRIPT gets imports_query=_TS_IMPORTS
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_languages.py -v`
Expected: PASS. **If a `.query(...)` raises**, the node type/field differs in the installed
grammar version — inspect with `get_parser("<grammar>").parse(b"...").root_node` and fix the
pattern (e.g. JS string-import internals vary: try `source: (string) @import.module` and strip
quotes in Task 2 if `string_fragment` is absent).

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/parsers/languages.py tests/test_languages.py
git commit -m "feat(parsers): import + inheritance edge queries (py/js/ts)"
```

---

## Task 2: Tree-sitter — extract import + inheritance edges

**Files:**
- Modify: `src/codebase_index/parsers/treesitter.py`
- Modify: `tests/test_treesitter.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_treesitter.py`:

```python
# tests/test_treesitter.py  (append)
PY_GRAPH = '''\
from auth.token import refresh_access_token
from models.user import User


class AdminUser(User):
    def renew(self, refresh_token):
        return refresh_access_token(refresh_token)
'''


def test_python_import_and_inheritance_edges():
    pr = parse_file("python", PY_GRAPH)
    by_type = {}
    for e in pr.edges:
        by_type.setdefault(e.edge_type, []).append(e)

    # two import edges, module path captured verbatim, file-level (no enclosing symbol)
    modules = sorted(e.callee_name for e in by_type["import"])
    assert modules == ["auth.token", "models.user"]
    assert all(e.src_symbol_index is None for e in by_type["import"])

    # one extends edge, base = User, enclosing symbol = AdminUser
    extends = by_type["extends"]
    assert len(extends) == 1
    base = extends[0]
    assert base.callee_name == "User"
    admin_idx = next(i for i, s in enumerate(pr.symbols) if s.name == "AdminUser")
    assert base.src_symbol_index == admin_idx

    # M3 call edge still present (renew -> refresh_access_token)
    assert any(e.edge_type == "call" and e.callee_name == "refresh_access_token"
               for e in pr.edges)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_treesitter.py::test_python_import_and_inheritance_edges -v`
Expected: FAIL — `KeyError: 'import'` (no import/inheritance edges emitted yet).

- [ ] **Step 3: Write minimal implementation**

In `src/codebase_index/parsers/treesitter.py`, add a graph-edge extractor and call it from
`parse_file`. Reuse the M3 helpers `_matches`, `_text`, `_row`, `_enclosing_symbol_index`.

```python
# src/codebase_index/parsers/treesitter.py  — add

_EDGE_PREFIXES = {"import.": "import", "extends.": "extends", "implements.": "implements"}


def _extract_graph_edges(spec, grammar, root, symbols) -> "list[Edge]":
    if not spec.imports_query:
        return []
    query = grammar.query(spec.imports_query)
    edges: list[Edge] = []
    for caps in _matches(query, root):
        for cap_name, node in caps.items():
            edge_type = next(
                (et for pfx, et in _EDGE_PREFIXES.items() if cap_name.startswith(pfx)),
                None,
            )
            if edge_type is None:
                continue
            line = _row(node.start_point) + 1
            # import edges are file-level; inheritance edges hang off the enclosing class
            src_idx = None if edge_type == "import" else _enclosing_symbol_index(symbols, line)
            edges.append(Edge(
                edge_type=edge_type,
                callee_name=_text(node).strip().strip('"').strip("'"),
                line=line,
                src_symbol_index=src_idx,
            ))
    return edges
```

Then, in `parse_file`, extend the edge list (the M3 body builds `edges` from `_extract_edges`):

```python
# src/codebase_index/parsers/treesitter.py  — inside parse_file, after edges = _extract_edges(...)
    edges = _extract_edges(spec, grammar, root, symbols)
    edges.extend(_extract_graph_edges(spec, grammar, root, symbols))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_treesitter.py -v`
Expected: PASS (M3 cases + the new one). If JS/TS string-import internals differ from the Task 1
query, this Python-only test still passes; fix JS/TS later via the recipe.

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/parsers/treesitter.py tests/test_treesitter.py
git commit -m "feat(parsers): extract import + inheritance edges"
```

---

## Task 3: Storage — graph accessors

**Files:**
- Modify: `src/codebase_index/storage/repo.py`
- Modify: `tests/test_storage.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_storage.py` (reuses the `_open` helper + `repo` import already in that file
from M1/M3):

```python
# tests/test_storage.py  (append)
def _seed_two_files(db):
    from codebase_index.parsers.base import Symbol

    fid_a = repo.upsert_file(
        db.conn, path="src/auth/token.py", lang="python", size_bytes=1, sha256="a",
        mtime_ns=1, git_status=None, parser="treesitter", indexed_at="t", is_generated=False,
    )
    fid_b = repo.upsert_file(
        db.conn, path="src/api/service.py", lang="python", size_bytes=1, sha256="b",
        mtime_ns=1, git_status=None, parser="treesitter", indexed_at="t", is_generated=False,
    )
    a_syms = repo.replace_symbols(db.conn, fid_a, [
        Symbol(name="refresh_access_token", kind="function", line_start=1, line_end=2,
               qualified="refresh_access_token"),
    ])
    b_syms = repo.replace_symbols(db.conn, fid_b, [
        Symbol(name="renew", kind="function", line_start=5, line_end=6, qualified="renew"),
    ])
    return fid_a, fid_b, a_syms[0], b_syms[0]


def test_graph_accessors_resolve_and_walk(tmp_path):
    db = _open(tmp_path)
    fid_a, fid_b, target_id, caller_id = _seed_two_files(db)

    # one unresolved cross-file call edge + one unresolved import edge
    repo.replace_edges(db.conn, fid_b, [
        {"edge_type": "call", "src_kind": "symbol", "src_id": caller_id,
         "dst_kind": None, "dst_id": None, "dst_name": "refresh_access_token",
         "line": 6, "resolved": 0},
        {"edge_type": "import", "src_kind": "file", "src_id": fid_b,
         "dst_kind": None, "dst_id": None, "dst_name": "auth.token",
         "line": 1, "resolved": 0},
    ])

    assert len(repo.unresolved_edges(db.conn)) == 2
    assert repo.symbol_id_for_unique_name(db.conn, "refresh_access_token") == target_id
    assert repo.symbol_id_for_unique_name(db.conn, "nope") is None
    suffix_rows = repo.files_with_suffix(db.conn, "auth/token.py")
    assert [r["id"] for r in suffix_rows] == [fid_a]
    assert repo.file_by_path(db.conn, "src/api/service.py")["id"] == fid_b

    # resolve both edges, recompute degrees
    repo.resolve_edge(db.conn, repo.unresolved_edges(db.conn)[0]["id"], "symbol", target_id)
    repo.recompute_degrees(db.conn)
    assert repo.count_resolved_edges(db.conn) == 1
    rows = repo.incoming_edges(db.conn, "symbol", target_id)
    assert rows and rows[0]["src_id"] == caller_id
    out = repo.outgoing_edges(db.conn, "symbol", caller_id)
    assert out and out[0]["dst_id"] == target_id
    assert [r["id"] for r in repo.symbols_in_file(db.conn, fid_a)] == [target_id]
    db.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_storage.py::test_graph_accessors_resolve_and_walk -v`
Expected: FAIL — `AttributeError: module 'repo' has no attribute 'unresolved_edges'`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/codebase_index/storage/repo.py`:

```python
# src/codebase_index/storage/repo.py  (append — graph accessors)

def unresolved_edges(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id, edge_type, dst_name FROM edges "
        "WHERE resolved = 0 AND dst_name IS NOT NULL ORDER BY id"
    ).fetchall()


def resolve_edge(conn: sqlite3.Connection, edge_id: int, dst_kind: str, dst_id: int) -> None:
    conn.execute(
        "UPDATE edges SET dst_kind = ?, dst_id = ?, resolved = 1 WHERE id = ?",
        (dst_kind, dst_id, edge_id),
    )


def symbol_id_for_unique_name(conn: sqlite3.Connection, name: str) -> "Optional[int]":
    """Return the symbol id iff exactly one definition has this name, else None."""
    rows = conn.execute(
        "SELECT id FROM symbols WHERE name = ? LIMIT 2", (name,)
    ).fetchall()
    return int(rows[0]["id"]) if len(rows) == 1 else None


def files_with_suffix(conn: sqlite3.Connection, suffix: str) -> list[sqlite3.Row]:
    """Files whose repo-relative path ends with `suffix` (POSIX separators)."""
    return conn.execute(
        "SELECT id, path FROM files WHERE path = ? OR path LIKE ? ORDER BY length(path), path",
        (suffix, f"%/{suffix}"),
    ).fetchall()


def file_by_path(conn: sqlite3.Connection, path: str) -> "Optional[sqlite3.Row]":
    return conn.execute("SELECT id, path FROM files WHERE path = ?", (path,)).fetchone()


def symbols_in_file(conn: sqlite3.Connection, file_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT id, name, kind, line_start, in_degree FROM symbols "
        "WHERE file_id = ? ORDER BY line_start",
        (file_id,),
    ).fetchall()


def incoming_edges(conn: sqlite3.Connection, kind: str, node_id: int) -> list[sqlite3.Row]:
    """Resolved edges pointing AT (kind,node_id): the dependents/callers/importers."""
    return conn.execute(
        "SELECT id, edge_type, src_kind, src_id, file_id, line FROM edges "
        "WHERE resolved = 1 AND dst_kind = ? AND dst_id = ?",
        (kind, node_id),
    ).fetchall()


def outgoing_edges(conn: sqlite3.Connection, kind: str, node_id: int) -> list[sqlite3.Row]:
    """Resolved edges originating FROM (kind,node_id): the dependencies/callees."""
    return conn.execute(
        "SELECT id, edge_type, dst_kind, dst_id, file_id, line FROM edges "
        "WHERE resolved = 1 AND src_kind = ? AND src_id = ?",
        (kind, node_id),
    ).fetchall()


def recompute_degrees(conn: sqlite3.Connection) -> None:
    """Denormalize in/out degree onto symbols from resolved symbol-to-symbol edges."""
    conn.execute(
        "UPDATE symbols SET "
        "out_degree = (SELECT COUNT(*) FROM edges "
        "  WHERE resolved = 1 AND src_kind = 'symbol' AND src_id = symbols.id), "
        "in_degree = (SELECT COUNT(*) FROM edges "
        "  WHERE resolved = 1 AND dst_kind = 'symbol' AND dst_id = symbols.id)"
    )


def count_resolved_edges(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM edges WHERE resolved = 1").fetchone()[0])
```

> `Optional` is already imported in `repo.py` (M3). If not, add `from typing import Optional`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_storage.py -v`
Expected: PASS (all storage tests).

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/storage/repo.py tests/test_storage.py
git commit -m "feat(storage): graph resolution + traversal accessors"
```

---

## Task 4: Graph builder — resolve edges + denormalize degrees

**Files:**
- Create: `src/codebase_index/graph/builder.py`
- Test: `tests/test_graph.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_graph.py
from __future__ import annotations

from codebase_index.graph.builder import build_graph
from codebase_index.parsers.base import Symbol
from codebase_index.storage import repo
from codebase_index.storage.db import Database


def _db(tmp_path):
    return Database(tmp_path / "index.sqlite").open()


def _seed(db):
    fid_a = repo.upsert_file(
        db.conn, path="src/auth/token.py", lang="python", size_bytes=1, sha256="a",
        mtime_ns=1, git_status=None, parser="treesitter", indexed_at="t", is_generated=False,
    )
    fid_b = repo.upsert_file(
        db.conn, path="src/api/service.py", lang="python", size_bytes=1, sha256="b",
        mtime_ns=1, git_status=None, parser="treesitter", indexed_at="t", is_generated=False,
    )
    a = repo.replace_symbols(db.conn, fid_a, [
        Symbol(name="refresh_access_token", kind="function", line_start=1, line_end=2,
               qualified="refresh_access_token"),
    ])
    b = repo.replace_symbols(db.conn, fid_b, [
        Symbol(name="renew", kind="function", line_start=5, line_end=6, qualified="renew"),
    ])
    repo.replace_edges(db.conn, fid_b, [
        {"edge_type": "call", "src_kind": "symbol", "src_id": b[0],
         "dst_kind": None, "dst_id": None, "dst_name": "refresh_access_token",
         "line": 6, "resolved": 0},
        {"edge_type": "import", "src_kind": "file", "src_id": fid_b,
         "dst_kind": None, "dst_id": None, "dst_name": "auth.token",
         "line": 1, "resolved": 0},
        # ambiguous / unknown symbol target stays unresolved
        {"edge_type": "call", "src_kind": "symbol", "src_id": b[0],
         "dst_kind": None, "dst_id": None, "dst_name": "does_not_exist",
         "line": 7, "resolved": 0},
    ])
    return fid_a, fid_b, a[0], b[0]


def test_build_graph_resolves_symbol_and_import_edges(tmp_path):
    db = _db(tmp_path)
    fid_a, fid_b, target_id, caller_id = _seed(db)
    res = build_graph(db.conn)

    assert res["resolved"] == 2          # call + import; the unknown stays unresolved
    assert res["unresolved"] == 1

    # the cross-file call now points at the real symbol
    inc = repo.incoming_edges(db.conn, "symbol", target_id)
    assert any(r["src_id"] == caller_id and r["edge_type"] == "call" for r in inc)
    # the import edge points file -> file
    finc = repo.incoming_edges(db.conn, "file", fid_a)
    assert any(r["src_id"] == fid_b and r["edge_type"] == "import" for r in finc)

    # degrees denormalized
    target = db.conn.execute(
        "SELECT in_degree, out_degree FROM symbols WHERE id = ?", (target_id,)
    ).fetchone()
    assert target["in_degree"] == 1 and target["out_degree"] == 0
    db.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_graph.py::test_build_graph_resolves_symbol_and_import_edges -v`
Expected: FAIL — `ModuleNotFoundError: codebase_index.graph.builder`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/codebase_index/graph/builder.py
"""Global graph pass: resolve unresolved edges against the whole repo and
denormalize symbol degrees.

Runs once after all files are indexed (it needs the complete symbol/file tables).
Symbol-target edges (call/reference/extends/implements) resolve only on an
UNAMBIGUOUS name match — if two definitions share a name, the edge is left
unresolved rather than guessed. Import edges resolve their module path to a file
by POSIX path-suffix match (e.g. 'auth.token' -> '%/auth/token.py').
"""

from __future__ import annotations

import sqlite3
from typing import Optional

from ..storage import repo

_SYMBOL_EDGE_TYPES = {"call", "reference", "extends", "implements"}


def build_graph(conn: sqlite3.Connection) -> dict[str, int]:
    resolved = resolve_edges(conn)
    repo.recompute_degrees(conn)
    total_unresolved = len(repo.unresolved_edges(conn))
    return {"resolved": resolved, "unresolved": total_unresolved}


def resolve_edges(conn: sqlite3.Connection) -> int:
    resolved = 0
    for edge in repo.unresolved_edges(conn):
        name = edge["dst_name"]
        if edge["edge_type"] == "import":
            file_id = _module_to_file_id(conn, name)
            if file_id is not None:
                repo.resolve_edge(conn, edge["id"], "file", file_id)
                resolved += 1
        elif edge["edge_type"] in _SYMBOL_EDGE_TYPES:
            sym_id = repo.symbol_id_for_unique_name(conn, name)
            if sym_id is not None:
                repo.resolve_edge(conn, edge["id"], "symbol", sym_id)
                resolved += 1
    return resolved


def _module_to_file_id(conn: sqlite3.Connection, module: str) -> Optional[int]:
    """Resolve a dotted/slashed module path to a unique file id, or None."""
    base = module.replace(".", "/").strip("/")
    if not base:
        return None
    for suffix in (f"{base}.py", f"{base}.ts", f"{base}.js",
                   f"{base}/__init__.py", f"{base}/index.ts", f"{base}/index.js"):
        rows = repo.files_with_suffix(conn, suffix)
        if len(rows) == 1:
            return int(rows[0]["id"])
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_graph.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/graph/builder.py tests/test_graph.py
git commit -m "feat(graph): cross-file edge resolution + degree denormalization"
```

---

## Task 5: Indexer — run the graph pass after the build

**Files:**
- Modify: `src/codebase_index/indexer/pipeline.py`
- Create: `tests/fixtures/sample_repo/src/api/service.py`
- Modify: `tests/test_pipeline.py`

- [ ] **Step 1: Add the cross-file fixture**

Create `tests/fixtures/sample_repo/src/api/service.py`:

```python
"""Service layer (fixture) - exercises cross-file edges for impact tests."""

from auth.token import refresh_access_token
from models.user import User


class AdminUser(User):
    """Subclass of User; imported-from edge target for impact tests."""

    def renew(self, refresh_token: str) -> str:
        return refresh_access_token(refresh_token)
```

This yields, after indexing: import edges `service.py -> auth/token.py` and
`service.py -> models/user.py`; an `extends` edge `AdminUser -> User`; and a cross-file `call`
edge `renew -> refresh_access_token`.

- [ ] **Step 2: Write the failing test**

Append to `tests/test_pipeline.py` (reuses the `sample_repo` fixture + `Config`, `Database`,
`build_index`, `_repo` imports present from M1/M3):

```python
# tests/test_pipeline.py  (append)
def test_build_resolves_cross_file_edges_and_degrees(sample_repo, tmp_path):
    cfg = Config()
    cfg.root = str(sample_repo)
    db = Database(tmp_path / "index.sqlite").open()
    stats = build_index(cfg, db, root=sample_repo)

    assert stats.edges_resolved > 0
    assert _repo.count_resolved_edges(db.conn) == stats.edges_resolved

    # the cross-file call to refresh_access_token is resolved to its definition
    target = _repo.symbol_id_for_unique_name(db.conn, "refresh_access_token")
    assert target is not None
    inc = _repo.incoming_edges(db.conn, "symbol", target)
    assert any(r["edge_type"] == "call" for r in inc)

    # User gains an inheritance dependent (AdminUser) -> in_degree >= 1
    user_id = _repo.symbol_id_for_unique_name(db.conn, "User")
    deg = db.conn.execute(
        "SELECT in_degree FROM symbols WHERE id = ?", (user_id,)
    ).fetchone()["in_degree"]
    assert deg >= 1

    # models/user.py is imported by service.py (file -> file import edge)
    user_file = _repo.file_by_path(db.conn, "src/models/user.py")
    fimp = _repo.incoming_edges(db.conn, "file", user_file["id"])
    assert any(r["edge_type"] == "import" for r in fimp)
    db.close()


def test_reindex_graph_idempotent(sample_repo, tmp_path):
    cfg = Config()
    cfg.root = str(sample_repo)
    db = Database(tmp_path / "index.sqlite").open()
    s1 = build_index(cfg, db, root=sample_repo)
    s2 = build_index(cfg, db, root=sample_repo)
    assert s1.edges == s2.edges and s1.edges_resolved == s2.edges_resolved
    db.close()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_pipeline.py::test_build_resolves_cross_file_edges_and_degrees -v`
Expected: FAIL — `AttributeError: 'BuildStats' object has no attribute 'edges_resolved'`.

- [ ] **Step 4: Write minimal implementation**

In `src/codebase_index/indexer/pipeline.py`, add the field and run the graph pass once after the
walk loop. Add the import near the other parser imports:

```python
# src/codebase_index/indexer/pipeline.py  — add import
from ..graph.builder import build_graph
```

Extend `BuildStats` (the M3 dataclass already has `chunks`, `symbols`, `edges`):

```python
@dataclass
class BuildStats:
    indexed: int = 0
    deleted: int = 0
    total_bytes: int = 0
    chunks: int = 0
    symbols: int = 0
    edges: int = 0
    edges_resolved: int = 0
```

After the `for cand in walk(...)` loop finishes (and before/where the function commits and returns
`stats`), run the global graph pass:

```python
    # M5: resolve cross-file edge targets + denormalize degrees once the whole
    # repo is indexed (intra-file targets were already resolved during the loop).
    graph = build_graph(conn)
    stats.edges_resolved = graph["resolved"]
```

> Place this after the loop and any prune/delete step, but before the final `conn.commit()` so the
> resolution + degree updates land in the same transaction. If the pipeline commits per-file, add
> a final `conn.commit()` after `build_graph`.

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_pipeline.py -v`
Expected: PASS (M1–M3 pipeline tests + 2 new).

- [ ] **Step 6: Commit**

```bash
git add src/codebase_index/indexer/pipeline.py tests/test_pipeline.py tests/fixtures/sample_repo/src/api/service.py
git commit -m "feat(indexer): run graph resolution pass after build"
```

---

## Task 6: Models — impact response

**Files:**
- Modify: `src/codebase_index/models.py`
- Test: exercised in Task 7/Task 8

- [ ] **Step 1: Write the implementation**

Append to `src/codebase_index/models.py`:

```python
# src/codebase_index/models.py  (append)

class ImpactNode(BaseModel):
    kind: str                       # 'file' | 'symbol'
    path: str
    name: Optional[str] = None      # symbol name (None for file nodes)
    line_start: Optional[int] = None
    distance: int                   # BFS hops from the target (1 = direct)
    via_edge: Optional[str] = None  # edge_type that linked it (import|call|extends|...)


class ImpactResponse(BaseModel):
    target: str
    direction: str                  # 'up' | 'down' | 'both'
    depth: int
    index: IndexFreshness
    nodes: list[ImpactNode] = []
    files: list[str] = []           # distinct affected files, ranked
```

- [ ] **Step 2: Verify import**

Run: `python -c "from codebase_index.models import ImpactResponse, ImpactNode; print('ok')"`
Expected: prints `ok`.

- [ ] **Step 3: Commit**

```bash
git add src/codebase_index/models.py
git commit -m "feat(models): ImpactNode + ImpactResponse"
```

---

## Task 7: Graph expand — bounded BFS + `impact_lookup`

**Files:**
- Create: `src/codebase_index/graph/expand.py`
- Test: `tests/test_graph.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_graph.py`:

```python
# tests/test_graph.py  (append)
from codebase_index.config import Config
from codebase_index.graph.expand import impact_lookup, walk_impact
from codebase_index.indexer.pipeline import build_index


def _indexed(sample_repo, tmp_path):
    cfg = Config()
    cfg.root = str(sample_repo)
    db = Database(tmp_path / "index.sqlite").open()
    build_index(cfg, db, root=sample_repo)
    return db


def test_impact_up_of_file_finds_importer_and_subclass(sample_repo, tmp_path):
    db = _indexed(sample_repo, tmp_path)
    resp = impact_lookup(db.conn, "src/models/user.py", depth=2, direction="up")
    assert resp.direction == "up" and resp.index.exists is True
    # service.py imports user.py and AdminUser subclasses User -> both surface
    assert "src/api/service.py" in resp.files
    assert any(n.via_edge == "import" for n in resp.nodes)
    db.close()


def test_impact_up_of_symbol_finds_caller(sample_repo, tmp_path):
    db = _indexed(sample_repo, tmp_path)
    resp = impact_lookup(db.conn, "refresh_access_token", depth=2, direction="up")
    # renew() in service.py calls it
    assert "src/api/service.py" in resp.files
    assert any(n.name == "renew" and n.via_edge == "call" for n in resp.nodes)
    db.close()


def test_impact_down_of_symbol_lists_dependencies(sample_repo, tmp_path):
    db = _indexed(sample_repo, tmp_path)
    resp = impact_lookup(db.conn, "renew", depth=1, direction="down")
    # renew depends on refresh_access_token
    assert any(n.name == "refresh_access_token" for n in resp.nodes)
    db.close()


def test_depth_bounds_traversal(sample_repo, tmp_path):
    db = _indexed(sample_repo, tmp_path)
    deep = walk_impact(db.conn, "src/models/user.py", depth=2, direction="up")
    shallow = walk_impact(db.conn, "src/models/user.py", depth=1, direction="up")
    assert all(n.distance <= 1 for n in shallow)
    assert all(n.distance <= 2 for n in deep)
    db.close()


def test_impact_missing_target_returns_empty(sample_repo, tmp_path):
    db = _indexed(sample_repo, tmp_path)
    resp = impact_lookup(db.conn, "no_such_thing", depth=2, direction="both")
    assert resp.nodes == [] and resp.files == []
    db.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_graph.py -k impact -v`
Expected: FAIL — `ModuleNotFoundError: codebase_index.graph.expand`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/codebase_index/graph/expand.py
"""Impact analysis: bounded BFS over the resolved edge graph.

Direction semantics:
  up   -> dependents (who is affected if the target changes): incoming edges.
  down -> dependencies (what the target relies on): outgoing edges.
  both -> union of the two.

Target resolution: an exact file path -> a file node (seeded together with all
symbols defined in that file, so importers AND subclassers surface). Otherwise a
symbol name -> all symbol nodes with that name. A path suffix is the last resort.
"""

from __future__ import annotations

import sqlite3
from collections import deque
from typing import Optional

from ..models import ImpactNode, ImpactResponse, IndexFreshness
from ..storage import repo


def _freshness(conn: sqlite3.Connection) -> IndexFreshness:
    return IndexFreshness(
        exists=True,
        stale=False,
        built_at=repo.get_meta(conn, "built_at"),
        head_commit=repo.get_meta(conn, "head_commit"),
    )


def _seed_nodes(conn: sqlite3.Connection, target: str) -> list[tuple[str, int]]:
    """Resolve a target string to one or more (kind, id) start nodes."""
    frow = repo.file_by_path(conn, target)
    if frow is not None:
        seeds = [("file", int(frow["id"]))]
        seeds += [("symbol", int(s["id"])) for s in repo.symbols_in_file(conn, int(frow["id"]))]
        return seeds

    sym_rows = repo.symbols_by_name(conn, target, exact=True)
    if sym_rows:
        return [("symbol", int(r["id"])) for r in sym_rows]

    suffix = repo.files_with_suffix(conn, target)
    if len(suffix) == 1:
        fid = int(suffix[0]["id"])
        return [("file", fid)] + [
            ("symbol", int(s["id"])) for s in repo.symbols_in_file(conn, fid)
        ]
    return []


def _neighbors(conn, kind, node_id, direction):
    """Yield (next_kind, next_id, edge_type) for the requested direction(s)."""
    if direction in ("up", "both"):
        for e in repo.incoming_edges(conn, kind, node_id):
            yield e["src_kind"], int(e["src_id"]), e["edge_type"]
    if direction in ("down", "both"):
        for e in repo.outgoing_edges(conn, kind, node_id):
            if e["dst_id"] is not None:
                yield e["dst_kind"], int(e["dst_id"]), e["edge_type"]


def _node_meta(conn, kind, node_id) -> Optional[ImpactNode]:
    if kind == "file":
        row = conn.execute("SELECT path FROM files WHERE id = ?", (node_id,)).fetchone()
        if row is None:
            return None
        return ImpactNode(kind="file", path=row["path"], distance=0)
    row = conn.execute(
        "SELECT s.name AS name, s.line_start AS line_start, f.path AS path "
        "FROM symbols s JOIN files f ON f.id = s.file_id WHERE s.id = ?",
        (node_id,),
    ).fetchone()
    if row is None:
        return None
    return ImpactNode(kind="symbol", path=row["path"], name=row["name"],
                      line_start=row["line_start"], distance=0)


def walk_impact(
    conn: sqlite3.Connection, target: str, *, depth: int, direction: str
) -> list[ImpactNode]:
    seeds = _seed_nodes(conn, target)
    if not seeds:
        return []
    visited: set[tuple[str, int]] = set(seeds)
    queue: deque[tuple[str, int, int]] = deque((k, i, 0) for k, i in seeds)
    out: list[ImpactNode] = []

    while queue:
        kind, node_id, dist = queue.popleft()
        if dist >= depth:
            continue
        for nk, nid, etype in _neighbors(conn, kind, node_id, direction):
            if (nk, nid) in visited:
                continue
            visited.add((nk, nid))
            meta = _node_meta(conn, nk, nid)
            if meta is None:
                continue
            meta.distance = dist + 1
            meta.via_edge = etype
            out.append(meta)
            queue.append((nk, nid, dist + 1))
    return out


def impact_lookup(
    conn: sqlite3.Connection, target: str, *, depth: int, direction: str
) -> ImpactResponse:
    nodes = walk_impact(conn, target, depth=depth, direction=direction)
    # rank distinct affected files by nearest hop, then by name for determinism
    best: dict[str, int] = {}
    for n in nodes:
        if n.path not in best or n.distance < best[n.path]:
            best[n.path] = n.distance
    files = sorted(best, key=lambda p: (best[p], p))
    return ImpactResponse(
        target=target, direction=direction, depth=depth,
        index=_freshness(conn), nodes=nodes, files=files,
    )
```

> `walk_impact` seeds from the target's own nodes and never re-emits them (they're pre-added to
> `visited`), so the start file/symbol is excluded from results. `repo.get_meta` and
> `repo.symbols_by_name` already exist (M1/M3).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_graph.py -v`
Expected: PASS (builder tests + 5 impact tests).

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/graph/expand.py tests/test_graph.py
git commit -m "feat(graph): bounded impact BFS + impact_lookup"
```

---

## Task 8: Output — impact renderer

**Files:**
- Modify: `src/codebase_index/output/markdown.py`
- Modify: `tests/test_output.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_output.py`:

```python
# tests/test_output.py  (append)
def test_markdown_render_impact():
    from codebase_index.models import ImpactNode, ImpactResponse, IndexFreshness
    from codebase_index.output import markdown as md_out

    resp = ImpactResponse(
        target="src/models/user.py", direction="up", depth=2,
        index=IndexFreshness(exists=True, stale=False, built_at="t"),
        nodes=[
            ImpactNode(kind="file", path="src/api/service.py", distance=1, via_edge="import"),
            ImpactNode(kind="symbol", path="src/api/service.py", name="AdminUser",
                       line_start=5, distance=1, via_edge="extends"),
        ],
        files=["src/api/service.py"],
    )
    text = md_out.render_impact(resp)
    assert "src/models/user.py" in text          # the target
    assert "src/api/service.py" in text           # affected file
    assert "AdminUser" in text and "extends" in text
    assert "up" in text


def test_markdown_render_impact_empty():
    from codebase_index.models import ImpactResponse, IndexFreshness
    from codebase_index.output import markdown as md_out

    resp = ImpactResponse(
        target="nope", direction="both", depth=2,
        index=IndexFreshness(exists=True, stale=False), nodes=[], files=[],
    )
    text = md_out.render_impact(resp)
    assert "No impact" in text or "0" in text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_output.py -k impact -v`
Expected: FAIL — `AttributeError: module has no attribute 'render_impact'`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/codebase_index/output/markdown.py`:

```python
# src/codebase_index/output/markdown.py  (append)
from ..models import ImpactResponse


def render_impact(resp: ImpactResponse) -> str:
    header = (f"**impact:** `{resp.target}`  ·  **direction:** {resp.direction}  ·  "
              f"**depth:** {resp.depth}  ·  **affected files:** {len(resp.files)}")
    lines = [header, ""]
    if not resp.nodes:
        return "\n".join(lines + ["_No impact found (target unknown or no edges)._", ""]).rstrip() + "\n"
    lines.append("| dist | via | kind | node | location |")
    lines.append("|------|-----|------|------|----------|")
    for n in sorted(resp.nodes, key=lambda x: (x.distance, x.path, x.line_start or 0)):
        loc = f"{n.path}:{n.line_start}" if n.line_start else n.path
        node_name = f"`{n.name}`" if n.name else "—"
        lines.append(f"| {n.distance} | {n.via_edge or ''} | {n.kind} | {node_name} | `{loc}` |")
    return "\n".join(lines).rstrip() + "\n"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_output.py -v`
Expected: PASS (M2/M3 output tests + 2 new).

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/output/markdown.py tests/test_output.py
git commit -m "feat(output): impact renderer"
```

---

## Task 9: CLI — wire `impact`

**Files:**
- Modify: `src/codebase_index/cli.py` (replace the `impact` stub)
- Test: `tests/test_impact_cli.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_impact_cli.py
from __future__ import annotations

import json

from typer.testing import CliRunner

from codebase_index.cli import app

runner = CliRunner()


def _index(sample_repo):
    assert runner.invoke(app, ["--root", str(sample_repo), "index"]).exit_code == 0


def test_impact_command_json_up(sample_repo):
    _index(sample_repo)
    res = runner.invoke(
        app,
        ["--root", str(sample_repo), "--json", "impact", "src/models/user.py",
         "--direction", "up", "--depth", "2"],
    )
    assert res.exit_code == 0, res.output
    data = json.loads(res.output)
    assert data["direction"] == "up"
    assert "src/api/service.py" in data["files"]


def test_impact_command_markdown(sample_repo):
    _index(sample_repo)
    res = runner.invoke(
        app, ["--root", str(sample_repo), "impact", "refresh_access_token", "--direction", "up"]
    )
    assert res.exit_code == 0, res.output
    assert "impact:" in res.output and "refresh_access_token" in res.output


def test_impact_missing_index(tmp_path):
    empty = tmp_path / "empty"
    (empty / ".git").mkdir(parents=True)
    res = runner.invoke(app, ["--root", str(empty), "--json", "impact", "anything"])
    assert res.exit_code == 0
    data = json.loads(res.output)
    assert data["index"]["exists"] is False and data["files"] == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_impact_cli.py -v`
Expected: FAIL — `impact` still prints `not implemented`; `json.loads` raises.

- [ ] **Step 3: Write minimal implementation**

Replace the `impact` command in `src/codebase_index/cli.py`:

```python
# src/codebase_index/cli.py  — replace `impact`

@app.command()
def impact(
    ctx: typer.Context,
    target: str = typer.Argument(..., help="File path or symbol name."),
    depth: int = typer.Option(2, "--depth"),
    direction: str = typer.Option("up", "--direction", help="up|down|both"),
) -> None:
    """Blast radius: what is affected if `target` changes (graph walk)."""
    from .config import load
    from .graph.expand import impact_lookup
    from .models import ImpactResponse, IndexFreshness
    from .output import json as json_out
    from .output import markdown as md_out
    from .storage.db import Database

    is_json = bool(ctx.obj and ctx.obj.get("json"))
    cfg = load(ctx.obj.get("root") if ctx.obj else None)
    db_path = Path(cfg.root) / ".claude" / "cache" / "codebase-index" / "index.sqlite"

    if not db_path.exists():
        empty = ImpactResponse(
            target=target, direction=direction, depth=depth,
            index=IndexFreshness(exists=False, stale=False), nodes=[], files=[],
        )
        typer.echo(json_out.render(empty) if is_json else md_out.render_impact(empty))
        raise typer.Exit(code=0)

    with Database(db_path) as db:
        resp = impact_lookup(db.conn, target, depth=depth, direction=direction)
    typer.echo(json_out.render(resp) if is_json else md_out.render_impact(resp))
```

> `json_out.render` was generalized in M3 to accept any pydantic model, so it renders
> `ImpactResponse` unchanged.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_impact_cli.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/cli.py tests/test_impact_cli.py
git commit -m "feat(cli): wire impact command"
```

---

## Task 10: Full suite, lint, manual smoke, roadmap + recipe

**Files:**
- Modify: `docs/ROADMAP.md` (mark M5 done)
- Modify: `docs/LANGUAGES.md` (add the import/inheritance query rows)

- [ ] **Step 1: Run the whole suite**

Run: `pytest -v`
Expected: all M0–M5 tests PASS.

- [ ] **Step 2: Lint + type-check**

Run: `ruff check src tests` and `mypy src/codebase_index`
Expected: clean.

- [ ] **Step 3: Manual smoke on this repo**

```bash
pip install -e .
codebase-index --root . index
codebase-index --root . impact src/codebase_index/storage/repo.py --direction up --depth 2
codebase-index --root . --json impact build_index --direction down
codebase-index --root . impact Config --direction up
```

Expected: `impact` on `repo.py` lists modules that import it (e.g. `pipeline.py`, `searchers.py`,
`expand.py`); `impact build_index --direction down` lists what it calls; `impact Config` shows its
dependents. Unknown targets return an empty, well-formed response (exit 0).

- [ ] **Step 4: Update docs**

Edit `docs/ROADMAP.md`:
- Change the M5 heading to `## M5 — Graph edges + impact ✅`.
- Append under it: *"Shipped: import + inheritance edges (Python end-to-end; JS/TS query slots
  wired), cross-file resolution by unambiguous symbol name / module→file suffix, in/out-degree
  denormalization, and `impact` (up/down/both, depth-bounded). Ambiguous symbol names are left
  unresolved by design."*

Append to `docs/LANGUAGES.md` (created in M3) a new section:

```markdown
## Graph edges (M5)

Each `LangSpec` also carries an `imports_query` capturing:
- `@import.module` — the imported module path text (an `import` edge; src = the file).
- `@extends.base` — a base class identifier (an `extends` edge; src = the enclosing class).
- `@implements.iface` — an implemented interface (an `implements` edge; src = the class).

Cross-file resolution runs once after indexing (`graph/builder.py`): symbol-target edges resolve
on an *unambiguous* name match; `import` edges resolve their module path to a file by POSIX
suffix (`auth.token` → `%/auth/token.py`, then `__init__`/`index` variants). To add a language:
fill its `imports_query`, add a fixture importing/subclassing across files, and assert edges in
`tests/test_graph.py`.
```

- [ ] **Step 5: Commit**

```bash
git add docs/ROADMAP.md docs/LANGUAGES.md
git commit -m "docs: mark M5 complete + graph-edge language recipe"
```

---

## Acceptance Criteria (M5 exit)

- `codebase-index index` extracts `import` and `extends`/`implements` edges in addition to M3 call
  edges, and a global post-pass resolves cross-file targets: symbol edges to a uniquely-named
  definition, import edges to a file by module→path-suffix match.
- `symbols.in_degree`/`out_degree` are denormalized from resolved symbol-to-symbol edges.
- `codebase-index impact "<file-or-symbol>" --direction up|down|both --depth N` returns a bounded,
  ranked blast radius on the fixtures: `impact src/models/user.py --direction up` surfaces
  `src/api/service.py` (importer) and the `AdminUser` subclass; `impact refresh_access_token
  --direction up` surfaces its caller `renew`; `--direction down` lists dependencies.
- `--depth` bounds BFS hops; a missing index returns `index.exists = false`; an unknown target
  returns an empty, well-formed response with exit 0.
- `--json` parses for `impact`; Markdown renders a compact table.
- Re-indexing is idempotent (`edges`/`edges_resolved` stable); ambiguous symbol names stay
  unresolved (no false edges); full `pytest` green; `ruff` clean; base install network-free.

## Deferred to later milestones (explicitly NOT in M5)

- Vector/embedding edges or semantic expansion (M6).
- Wiring graph expansion into `search`/`explain` ranking + RRF fusion + rerank (M4 — orthogonal;
  M5 ships `impact` as its own command, not folded into hybrid search).
- Richer reference edges beyond call/import/inheritance (e.g. type usages, attribute access,
  decorator targets); cross-package module resolution heuristics beyond suffix match.
- Disambiguating same-named symbols via scope/import context (M5 deliberately skips ambiguous
  targets rather than guessing).
- Incremental graph maintenance on `update` — M5 rebuilds the graph pass on each full `index`
  (incremental `update` is M8).
- JS/TS import/inheritance edges end-to-end (query slots are wired; add fixtures + queries via the
  `docs/LANGUAGES.md` recipe).
```

