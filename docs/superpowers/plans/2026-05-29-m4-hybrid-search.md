# M4 — Hybrid Search & Ranking Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `codebase-index search` run multiple retrievers (path + symbol + FTS), fuse and rerank them, enforce a token budget, and emit a compact ranked payload that outranks any single retriever on the fixture queries.

**Architecture:** A thin orchestrator (`retrieval/pipeline.py`) runs three retrievers that each emit a uniform `Candidate`, fuses their ranked lists with Reciprocal Rank Fusion (`fusion.py`), applies an explainable feature reranker (`rerank.py`), greedily fills snippets under a token budget (`budget.py`), and derives `confidence` + `fallback_suggestions`. Intent detection (`intent.py`) picks per-query retriever weights and a default budget. Vector retrieval and graph expansion are intentionally **out of scope** (M6 and M5 respectively); the pipeline degrades gracefully to FTS+symbol+path.

**Tech Stack:** Python 3.12, Typer (CLI), SQLite + FTS5 (`bm25`), Pydantic (config), pytest. All SQL lives in `storage/repo.py`. No network dependencies.

---

## Assumptions & Grounding (read before starting)

These are verified facts about the existing tree the plan builds on:

- `storage/repo.py` already provides `fts_search(conn, match_query, *, limit)` returning rows with columns `chunk_id, path, line_start, line_end, content, token_est, bm25` (lower `bm25` = better). M4 adds `path_search` and `symbol_search` to the same module ("all SQL lives here").
- FTS auto-syncs from `chunks` via triggers in `storage/schema.sql`; inserting `chunks` rows is enough to make `fts_search` work.
- `output/redact.py` provides `redact_snippet(text: str) -> str`. All emitted snippet text MUST pass through it.
- `storage/db.py` exposes `Database(path)` as a context manager with a `.conn` attribute; opening it applies `schema.sql`.
- `config.load(root)` returns a `Config` with `retrieval.default_mode`, `retrieval.rrf_k`, `retrieval.token_budget`, `retrieval.limit`.
- `symbols` columns: `id, file_id, name, qualified, kind, line_start, line_end, signature, parent_id, docstring, in_degree, out_degree`.
- `files` columns include `path, lang, mtime_ns, is_generated, parser`.
- The indexer does **not** populate `symbols` (that is M3 pipeline wiring). Therefore M4 retrieval tests build a deterministic DB via a new `seeded_index` fixture that inserts `files`, `chunks`, and `symbols` rows directly. This keeps retrieval logic tested in isolation and makes the milestone exit criterion verifiable without depending on indexer internals.

**Exit criteria (from ROADMAP):** hybrid results outrank single-retriever results on the fixture queries; token budget enforced. Plus `confidence`, `fallback_suggestions`, `search --mode hybrid` (default), and `explain`.

---

## File Structure

| File | Responsibility | Status |
|---|---|---|
| `src/codebase_index/retrieval/types.py` | `Candidate`, `Intent`, `IntentPlan`, `Confidence` shared types | Create |
| `src/codebase_index/retrieval/intent.py` | rule-first query → `IntentPlan` (weights, budget, graph strategy) | Create |
| `src/codebase_index/storage/repo.py` | add `path_search`, `symbol_search` accessors | Modify |
| `src/codebase_index/retrieval/searchers.py` | path/symbol/FTS retrievers → `list[Candidate]` | Create |
| `src/codebase_index/retrieval/fusion.py` | RRF over per-source ranked lists | Create |
| `src/codebase_index/retrieval/rerank.py` | feature score + human-readable `reason` | Create |
| `src/codebase_index/retrieval/budget.py` | greedy snippet fill, trim, redact, `recommended_reads` | Create |
| `src/codebase_index/retrieval/pipeline.py` | orchestrate [1]→[6]; `confidence` + `fallback_suggestions` | Create |
| `src/codebase_index/output/json.py` | render payload to JSON string | Create |
| `src/codebase_index/output/markdown.py` | render payload to compact Markdown | Create |
| `src/codebase_index/cli.py` | fill `search` + `explain` bodies | Modify |
| `tests/conftest.py` | add `seeded_index` fixture | Modify |
| `tests/test_intent.py` … `tests/test_hybrid_ranking.py` | per-module + acceptance tests | Create |

---

## Task 1: Shared retrieval types

**Files:**
- Create: `src/codebase_index/retrieval/types.py`
- Test: `tests/test_retrieval_types.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_retrieval_types.py
from codebase_index.retrieval.types import Candidate, Intent, IntentPlan, Confidence


def test_candidate_dedup_key_ignores_source_and_score():
    a = Candidate(path="a.py", line_start=1, line_end=9, source="fts", score=0.5)
    b = Candidate(path="a.py", line_start=1, line_end=9, source="symbol", score=0.9)
    assert a.key() == b.key()


def test_intent_plan_weight_defaults_to_zero_for_missing_source():
    plan = IntentPlan(intent=Intent.KEYWORD, weights={"fts": 1.0}, token_budget=1500)
    assert plan.weight("symbol") == 0.0
    assert plan.weight("fts") == 1.0


def test_confidence_is_ordered():
    assert Confidence.HIGH.value == "high"
    assert {c.value for c in Confidence} == {"high", "medium", "low"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_retrieval_types.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'codebase_index.retrieval.types'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/codebase_index/retrieval/types.py
"""Shared retrieval types: the uniform candidate + intent plan."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional


class Intent(str, Enum):
    LOCATE_IMPL = "locate_impl"
    HOW_IT_WORKS = "how_it_works"
    IMPACT = "impact"
    FIND_REFS = "find_refs"
    DATA_FLOW = "data_flow"
    DEBUG_ERROR = "debug_error"
    ARCHITECTURE = "architecture"
    KEYWORD = "keyword"


class Confidence(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


@dataclass
class Candidate:
    """Source-agnostic retrieval hit. `source` in {"path","symbol","fts"}."""

    path: str
    line_start: int
    line_end: int
    source: str
    score: float
    kind: Optional[str] = None        # symbol kind or chunk kind
    symbol: Optional[str] = None
    content: Optional[str] = None     # snippet source text, if available
    token_est: int = 0
    in_degree: int = 0
    out_degree: int = 0
    is_generated: bool = False
    exact_symbol: bool = False        # set by the symbol searcher on exact-name match

    def key(self) -> tuple[str, int, int]:
        return (self.path, self.line_start, self.line_end)


@dataclass
class IntentPlan:
    intent: Intent
    weights: dict[str, float]
    token_budget: int
    graph_strategy: str = "none"          # consumed by M5; "none" for now
    summaries_first: bool = False

    def weight(self, source: str) -> float:
        return self.weights.get(source, 0.0)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_retrieval_types.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/retrieval/types.py tests/test_retrieval_types.py
git commit -m "feat(retrieval): shared Candidate and IntentPlan types"
```

---

## Task 2: Intent detection

**Files:**
- Create: `src/codebase_index/retrieval/intent.py`
- Test: `tests/test_intent.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_intent.py
import pytest

from codebase_index.retrieval.intent import detect_intent
from codebase_index.retrieval.types import Intent


@pytest.mark.parametrize(
    "query,expected",
    [
        ("where is refresh_access_token implemented", Intent.LOCATE_IMPL),
        ("find the User class", Intent.LOCATE_IMPL),
        ("how does token refresh work", Intent.HOW_IT_WORKS),
        ("what breaks if I change User", Intent.IMPACT),
        ("who calls refresh_access_token", Intent.FIND_REFS),
        ("find references to User", Intent.FIND_REFS),
        ("trace data flow of refresh_token", Intent.DATA_FLOW),
        ("Traceback (most recent call last): KeyError", Intent.DEBUG_ERROR),
        ("explain the architecture", Intent.ARCHITECTURE),
        ("leftpad", Intent.KEYWORD),
    ],
)
def test_detect_intent(query, expected):
    assert detect_intent(query).intent is expected


def test_locate_impl_favors_symbol_over_fts():
    plan = detect_intent("where is refresh_access_token implemented")
    assert plan.weight("symbol") > plan.weight("fts")


def test_architecture_returns_summaries_first():
    assert detect_intent("explain the architecture").summaries_first is True


def test_every_plan_has_positive_budget():
    assert detect_intent("anything").token_budget > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_intent.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'codebase_index.retrieval.intent'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/codebase_index/retrieval/intent.py
"""Cheap rule-first intent classifier (regex/keyword heuristics).

Each intent maps to retriever weights over {"path","symbol","fts"}, a default
token budget, and a graph strategy (consumed later by M5).
"""

from __future__ import annotations

import re

from .types import Intent, IntentPlan

# (compiled pattern, intent) — first match wins; order matters.
_RULES: list[tuple[re.Pattern[str], Intent]] = [
    (re.compile(r"traceback|stack ?trace|error:|exception|why does .* fail", re.I), Intent.DEBUG_ERROR),
    (re.compile(r"\b(who calls|find references|references to|callers of)\b", re.I), Intent.FIND_REFS),
    (re.compile(r"\b(what breaks|what depends on|impact of|affected if)\b", re.I), Intent.IMPACT),
    (re.compile(r"\b(data ?flow|where does .* get set|trace .* flow)\b", re.I), Intent.DATA_FLOW),
    (re.compile(r"\b(architecture|high-?level|overview|structure of)\b", re.I), Intent.ARCHITECTURE),
    (re.compile(r"\b(how does|how do|explain how|how .* works?)\b", re.I), Intent.HOW_IT_WORKS),
    (re.compile(r"\b(where is|find the|locate|implementation of|defined)\b", re.I), Intent.LOCATE_IMPL),
]

# weights over {"path","symbol","fts"} + budget + summaries flag, per RETRIEVAL.md §1.
_PLANS: dict[Intent, IntentPlan] = {
    Intent.LOCATE_IMPL: IntentPlan(Intent.LOCATE_IMPL, {"symbol": 1.0, "path": 0.7, "fts": 0.4}, 1500),
    Intent.HOW_IT_WORKS: IntentPlan(Intent.HOW_IT_WORKS, {"fts": 1.0, "symbol": 0.7, "path": 0.3}, 2200, graph_strategy="down"),
    Intent.IMPACT: IntentPlan(Intent.IMPACT, {"symbol": 1.0, "path": 0.6, "fts": 0.3}, 1800, graph_strategy="up"),
    Intent.FIND_REFS: IntentPlan(Intent.FIND_REFS, {"symbol": 1.0, "fts": 0.3, "path": 0.2}, 1500, graph_strategy="refs"),
    Intent.DATA_FLOW: IntentPlan(Intent.DATA_FLOW, {"symbol": 0.9, "fts": 0.8, "path": 0.3}, 2000, graph_strategy="both"),
    Intent.DEBUG_ERROR: IntentPlan(Intent.DEBUG_ERROR, {"fts": 1.0, "symbol": 0.6, "path": 0.3}, 1800),
    Intent.ARCHITECTURE: IntentPlan(Intent.ARCHITECTURE, {"fts": 0.6, "symbol": 0.4, "path": 0.5}, 2500, summaries_first=True),
    Intent.KEYWORD: IntentPlan(Intent.KEYWORD, {"fts": 1.0, "symbol": 0.6, "path": 0.5}, 1500),
}


def detect_intent(query: str) -> IntentPlan:
    for pattern, intent in _RULES:
        if pattern.search(query):
            return _PLANS[intent]
    return _PLANS[Intent.KEYWORD]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_intent.py -v`
Expected: PASS (all parametrized cases + 3 named tests pass)

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/retrieval/intent.py tests/test_intent.py
git commit -m "feat(retrieval): rule-first intent detection with per-intent weights"
```

---

## Task 3: Seeded DB fixture

**Files:**
- Modify: `tests/conftest.py`

- [ ] **Step 1: Write the failing test**

Add this test to a new file to prove the fixture works.

```python
# tests/test_seeded_index.py
from codebase_index.storage import repo


def test_seeded_index_has_files_chunks_symbols(seeded_index):
    conn = seeded_index.conn
    assert repo.count_files(conn) >= 3
    assert repo.count_chunks(conn) >= 3
    rows = repo.fts_search(conn, "token", limit=10)
    assert any("token.py" in r["path"] for r in rows)
    syms = conn.execute("SELECT name FROM symbols").fetchall()
    names = {r[0] for r in syms}
    assert {"refresh_access_token", "User"} <= names
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_seeded_index.py -v`
Expected: FAIL with `fixture 'seeded_index' not found`

- [ ] **Step 3: Write minimal implementation**

Append to `tests/conftest.py`:

```python
import sqlite3

from codebase_index.storage.db import Database


def _insert_file(conn: sqlite3.Connection, *, path: str, lang: str, mtime_ns: int,
                 is_generated: bool = False, parser: str = "treesitter") -> int:
    conn.execute(
        "INSERT INTO files (path, lang, size_bytes, sha256, mtime_ns, git_status, "
        "parser, indexed_at, is_generated) VALUES (?,?,?,?,?,?,?,?,?)",
        (path, lang, 100, "deadbeef", mtime_ns, "clean", parser, "2026-05-29T00:00:00Z",
         1 if is_generated else 0),
    )
    return int(conn.execute("SELECT id FROM files WHERE path = ?", (path,)).fetchone()[0])


def _insert_chunk(conn: sqlite3.Connection, file_id: int, *, line_start: int,
                  line_end: int, content: str, kind: str = "window") -> int:
    token_est = max(1, len(content) // 4)
    conn.execute(
        "INSERT INTO chunks (file_id, line_start, line_end, kind, symbol_id, content, "
        "token_est) VALUES (?,?,?,?,NULL,?,?)",
        (file_id, line_start, line_end, kind, content, token_est),
    )
    return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])


def _insert_symbol(conn: sqlite3.Connection, file_id: int, *, name: str, kind: str,
                   line_start: int, line_end: int, signature: str,
                   in_degree: int = 0, out_degree: int = 0) -> None:
    conn.execute(
        "INSERT INTO symbols (file_id, name, qualified, kind, line_start, line_end, "
        "signature, parent_id, docstring, in_degree, out_degree) "
        "VALUES (?,?,?,?,?,?,?,NULL,NULL,?,?)",
        (file_id, name, name, kind, line_start, line_end, signature, in_degree, out_degree),
    )


@pytest.fixture
def seeded_index(tmp_path) -> Database:
    """Deterministic in-tree index: files + chunks (+fts via triggers) + symbols.

    Retrieval logic is tested against this, not the indexer, so symbol coverage
    is independent of M3 pipeline wiring.
    """
    db = Database(tmp_path / "index.sqlite")
    conn = db.conn

    auth = _insert_file(conn, path="src/auth/token.py", lang="python", mtime_ns=5000)
    _insert_chunk(conn, auth, line_start=1, line_end=6,
                  content="def refresh_access_token(refresh_token):\n"
                          "    # exchange a refresh token for a new access token\n"
                          "    return mint(refresh_token)\n", kind="symbol_body")
    _insert_symbol(conn, auth, name="refresh_access_token", kind="function",
                   line_start=1, line_end=6,
                   signature="def refresh_access_token(refresh_token)", in_degree=4)

    user = _insert_file(conn, path="src/models/user.py", lang="python", mtime_ns=4000)
    _insert_chunk(conn, user, line_start=1, line_end=4,
                  content="class User:\n    def __init__(self, name):\n        self.name = name\n",
                  kind="symbol_body")
    _insert_symbol(conn, user, name="User", kind="class", line_start=1, line_end=4,
                   signature="class User", in_degree=9)

    # Decoy: mentions "token" a lot but defines no relevant symbol. FTS may rank it
    # high; symbol signal should let the fused result correct that.
    notes = _insert_file(conn, path="docs/notes.md", lang="markdown", mtime_ns=3000)
    _insert_chunk(conn, notes, line_start=1, line_end=3,
                  content="token token token refresh token access token notes about token\n")

    gen = _insert_file(conn, path="src/schema.generated.ts", lang="typescript",
                       mtime_ns=6000, is_generated=True)
    _insert_chunk(conn, gen, line_start=1, line_end=2,
                  content="export type Token = { refresh_access_token: string }\n")
    _insert_symbol(conn, gen, name="Token", kind="type", line_start=1, line_end=2,
                   signature="type Token")

    conn.commit()
    yield db
    db.close()
```

> If `Database` has no `close()`, replace `db.close()` with `db.conn.close()`. Verify by reading `storage/db.py` before running.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_seeded_index.py -v`
Expected: PASS (1 passed)

- [ ] **Step 5: Commit**

```bash
git add tests/conftest.py tests/test_seeded_index.py
git commit -m "test(retrieval): deterministic seeded_index fixture"
```

---

## Task 4: Path & symbol repo accessors

**Files:**
- Modify: `src/codebase_index/storage/repo.py`
- Test: `tests/test_repo_search.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_repo_search.py
from codebase_index.storage import repo


def test_path_search_matches_path_tokens(seeded_index):
    rows = repo.path_search(seeded_index.conn, "auth/token.py", limit=10)
    assert rows[0]["path"] == "src/auth/token.py"


def test_symbol_search_exact_beats_other(seeded_index):
    rows = repo.symbol_search(seeded_index.conn, "refresh_access_token", limit=10)
    assert rows[0]["name"] == "refresh_access_token"
    assert rows[0]["is_exact"] == 1


def test_symbol_search_prefix(seeded_index):
    rows = repo.symbol_search(seeded_index.conn, "refresh_acc", limit=10)
    assert any(r["name"] == "refresh_access_token" for r in rows)


def test_symbol_search_kind_filter(seeded_index):
    rows = repo.symbol_search(seeded_index.conn, "User", limit=10, kind="class")
    assert all(r["kind"] == "class" for r in rows)
    assert any(r["name"] == "User" for r in rows)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_repo_search.py -v`
Expected: FAIL with `AttributeError: module 'codebase_index.storage.repo' has no attribute 'path_search'`

- [ ] **Step 3: Write minimal implementation**

Append to `src/codebase_index/storage/repo.py`:

```python
def path_search(
    conn: sqlite3.Connection, query: str, *, limit: int
) -> list[sqlite3.Row]:
    """Match files whose path contains query tokens. Score = number of tokens hit."""
    tokens = [t for t in re.split(r"[\s/.\\]+", query.strip()) if t]
    if not tokens:
        return []
    score_expr = " + ".join(["(path LIKE ?)"] * len(tokens))
    like_args = [f"%{t}%" for t in tokens]
    return conn.execute(
        f"""
        SELECT id AS file_id, path, mtime_ns, is_generated,
               ({score_expr}) AS hits
        FROM files
        WHERE {' OR '.join(['path LIKE ?'] * len(tokens))}
        ORDER BY hits DESC, length(path) ASC
        LIMIT ?
        """,
        (*like_args, *like_args, limit),
    ).fetchall()


def symbol_search(
    conn: sqlite3.Connection,
    name: str,
    *,
    limit: int,
    kind: Optional[str] = None,
    exact: bool = False,
) -> list[sqlite3.Row]:
    """Symbol lookup: exact name first, then prefix, then substring (fuzzy)."""
    name = name.strip()
    if not name:
        return []
    kind_clause = "AND s.kind = :kind" if kind else ""
    name_clause = "s.name = :exact COLLATE NOCASE" if exact else (
        "(s.name = :exact COLLATE NOCASE "
        "OR s.name LIKE :prefix COLLATE NOCASE "
        "OR s.name LIKE :sub COLLATE NOCASE)"
    )
    return conn.execute(
        f"""
        SELECT s.name, s.kind, s.signature, s.line_start, s.line_end,
               s.in_degree, s.out_degree, f.path, f.mtime_ns, f.is_generated,
               (s.name = :exact COLLATE NOCASE) AS is_exact
        FROM symbols s
        JOIN files f ON f.id = s.file_id
        WHERE {name_clause} {kind_clause}
        ORDER BY is_exact DESC,
                 (s.name LIKE :prefix COLLATE NOCASE) DESC,
                 s.in_degree DESC
        LIMIT :limit
        """,
        {
            "exact": name,
            "prefix": f"{name}%",
            "sub": f"%{name}%",
            "kind": kind,
            "limit": limit,
        },
    ).fetchall()
```

Add `import re` to the top of `repo.py` if not already present (it is not in the M1 version — add it under `import sqlite3`).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_repo_search.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/storage/repo.py tests/test_repo_search.py
git commit -m "feat(storage): path_search and symbol_search accessors"
```

---

## Task 5: Retrievers

**Files:**
- Create: `src/codebase_index/retrieval/searchers.py`
- Test: `tests/test_searchers.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_searchers.py
from codebase_index.retrieval.searchers import (
    fts_candidates, path_candidates, symbol_candidates,
)


def test_fts_candidates_uniform_shape(seeded_index):
    cands = fts_candidates(seeded_index.conn, "token", limit=10)
    assert cands and all(c.source == "fts" for c in cands)
    assert all(c.content is not None and c.token_est > 0 for c in cands)


def test_symbol_candidates_exact_flagged(seeded_index):
    cands = symbol_candidates(seeded_index.conn, "refresh_access_token", limit=10)
    top = cands[0]
    assert top.symbol == "refresh_access_token"
    assert top.source == "symbol" and top.exact_symbol is True
    assert top.in_degree == 4


def test_path_candidates(seeded_index):
    cands = path_candidates(seeded_index.conn, "auth/token.py", limit=10)
    assert cands[0].path == "src/auth/token.py"
    assert cands[0].source == "path"


def test_symbol_candidates_empty_query(seeded_index):
    assert symbol_candidates(seeded_index.conn, "   ", limit=10) == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_searchers.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'codebase_index.retrieval.searchers'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/codebase_index/retrieval/searchers.py
"""Three retrievers, each emitting a uniform list[Candidate].

Vector retrieval (RETRIEVAL.md §2) is M6 and intentionally absent here; the
pipeline degrades to path+symbol+fts.
"""

from __future__ import annotations

import re
import sqlite3

from ..storage import repo
from .types import Candidate

# FTS5 MATCH is sensitive to punctuation; reduce a NL query to bare terms.
_TERM_RE = re.compile(r"[A-Za-z0-9_]+")


def _fts_match_query(query: str) -> str:
    terms = _TERM_RE.findall(query)
    # OR the terms so partial matches still surface; quote to avoid operator parsing.
    return " OR ".join(f'"{t}"' for t in terms)


def fts_candidates(conn: sqlite3.Connection, query: str, *, limit: int) -> list[Candidate]:
    match = _fts_match_query(query)
    if not match:
        return []
    out: list[Candidate] = []
    for row in repo.fts_search(conn, match, limit=limit):
        out.append(
            Candidate(
                path=row["path"],
                line_start=row["line_start"],
                line_end=row["line_end"],
                source="fts",
                score=-float(row["bm25"]),  # bm25: lower is better -> negate for "higher better"
                content=row["content"],
                token_est=int(row["token_est"]),
            )
        )
    return out


def symbol_candidates(
    conn: sqlite3.Connection, query: str, *, limit: int, kind: str | None = None
) -> list[Candidate]:
    # Pull the most symbol-like token (longest identifier) from a NL query.
    ids = _TERM_RE.findall(query)
    if not ids:
        return []
    name = max(ids, key=len)
    out: list[Candidate] = []
    rows = repo.symbol_search(conn, name, limit=limit, kind=kind)
    for rank, row in enumerate(rows):
        out.append(
            Candidate(
                path=row["path"],
                line_start=row["line_start"],
                line_end=row["line_end"],
                source="symbol",
                score=1.0 / (1 + rank),
                kind=row["kind"],
                symbol=row["name"],
                content=row["signature"],
                token_est=max(1, len(row["signature"] or "") // 4),
                in_degree=int(row["in_degree"]),
                out_degree=int(row["out_degree"]),
                is_generated=bool(row["is_generated"]),
                exact_symbol=bool(row["is_exact"]),
            )
        )
    return out


def path_candidates(conn: sqlite3.Connection, query: str, *, limit: int) -> list[Candidate]:
    out: list[Candidate] = []
    for rank, row in enumerate(repo.path_search(conn, query, limit=limit)):
        out.append(
            Candidate(
                path=row["path"],
                line_start=1,
                line_end=1,
                source="path",
                score=float(row["hits"]) / (1 + rank),
                is_generated=bool(row["is_generated"]),
            )
        )
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_searchers.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/retrieval/searchers.py tests/test_searchers.py
git commit -m "feat(retrieval): path/symbol/fts retrievers with uniform Candidate"
```

---

## Task 6: RRF fusion

**Files:**
- Create: `src/codebase_index/retrieval/fusion.py`
- Test: `tests/test_fusion.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_fusion.py
from codebase_index.retrieval.fusion import fuse
from codebase_index.retrieval.types import Candidate


def _c(path, src, score):
    return Candidate(path=path, line_start=1, line_end=2, source=src, score=score)


def test_fuse_merges_same_location_across_sources():
    fts = [_c("a.py", "fts", 0.9), _c("b.py", "fts", 0.5)]
    sym = [_c("a.py", "symbol", 0.8)]
    fused = fuse({"fts": fts, "symbol": sym}, weights={"fts": 1.0, "symbol": 1.0}, k=60)
    a = next(c for c in fused if c.path == "a.py")
    b = next(c for c in fused if c.path == "b.py")
    # a appears in both lists at rank 0 -> higher RRF than b (one list, rank 1)
    assert a.score > b.score


def test_weights_change_order():
    fts = [_c("doc.md", "fts", 0.9)]
    sym = [_c("code.py", "symbol", 0.9)]
    lists = {"fts": fts, "symbol": sym}
    fts_heavy = fuse(lists, weights={"fts": 1.0, "symbol": 0.1}, k=60)
    sym_heavy = fuse(lists, weights={"fts": 0.1, "symbol": 1.0}, k=60)
    assert fts_heavy[0].path == "doc.md"
    assert sym_heavy[0].path == "code.py"


def test_zero_weight_source_excluded():
    fused = fuse({"fts": [_c("a.py", "fts", 1.0)]}, weights={"fts": 0.0}, k=60)
    assert fused == []
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_fusion.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'codebase_index.retrieval.fusion'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/codebase_index/retrieval/fusion.py
"""Reciprocal Rank Fusion across per-source ranked candidate lists.

RRF(d) = Σ_r  w_r / (k + rank_r(d))   — robust to incomparable raw scores.
On merge, the candidate carrying the most signal (symbol > fts > path) is kept
as the representative so downstream rerank/snippet logic has the richest fields.
"""

from __future__ import annotations

from .types import Candidate

_SOURCE_RICHNESS = {"symbol": 3, "fts": 2, "path": 1}


def _richer(a: Candidate, b: Candidate) -> Candidate:
    return a if _SOURCE_RICHNESS.get(a.source, 0) >= _SOURCE_RICHNESS.get(b.source, 0) else b


def fuse(
    lists: dict[str, list[Candidate]],
    *,
    weights: dict[str, float],
    k: int,
) -> list[Candidate]:
    accum: dict[tuple, float] = {}
    rep: dict[tuple, Candidate] = {}
    agree: dict[tuple, set[str]] = {}

    for source, candidates in lists.items():
        w = weights.get(source, 0.0)
        if w <= 0.0:
            continue
        for rank, cand in enumerate(candidates):
            key = cand.key()
            accum[key] = accum.get(key, 0.0) + w / (k + rank)
            agree.setdefault(key, set()).add(source)
            rep[key] = _richer(rep[key], cand) if key in rep else cand

    fused: list[Candidate] = []
    for key, score in accum.items():
        c = rep[key]
        c.score = score
        # stash agreement count on the representative for confidence scoring
        c.kind = c.kind  # no-op; agreement carried via closure below
        fused.append(c)

    fused.sort(key=lambda c: c.score, reverse=True)
    # attach agreement count as an attribute for the pipeline (dynamic, dataclass-safe)
    for c in fused:
        c.agreeing_sources = len(agree[c.key()])  # type: ignore[attr-defined]
    return fused
```

> Note: `agreeing_sources` is set dynamically on the dataclass instance (Python allows this for non-slotted dataclasses). The pipeline reads it for confidence. If you prefer a declared field, add `agreeing_sources: int = 1` to `Candidate` in Task 1 and assign it here instead — either is acceptable; declared is cleaner.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_fusion.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/retrieval/fusion.py tests/test_fusion.py
git commit -m "feat(retrieval): reciprocal rank fusion with per-intent weights"
```

---

## Task 7: Reranking

**Files:**
- Create: `src/codebase_index/retrieval/rerank.py`
- Test: `tests/test_rerank.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_rerank.py
from codebase_index.retrieval.rerank import rerank
from codebase_index.retrieval.types import Candidate, Intent


def _c(path, src, score, **kw):
    return Candidate(path=path, line_start=1, line_end=2, source=src, score=score, **kw)


def test_exact_symbol_outranks_equal_fts():
    fts = _c("a.py", "fts", 0.5)
    sym = _c("b.py", "symbol", 0.5, symbol="X", kind="function", exact_symbol=True, in_degree=4)
    out = rerank([fts, sym], query="find X", intent=Intent.LOCATE_IMPL)
    assert out[0].path == "b.py"


def test_generated_files_demoted():
    plain = _c("real.py", "fts", 0.5)
    gen = _c("g.generated.ts", "fts", 0.55, is_generated=True)
    out = rerank([gen, plain], query="token", intent=Intent.KEYWORD)
    assert out[0].path == "real.py"


def test_reason_string_present():
    sym = _c("b.py", "symbol", 0.5, symbol="X", kind="function", exact_symbol=True, in_degree=4)
    out = rerank([sym], query="find X", intent=Intent.LOCATE_IMPL)
    assert out[0].reason and "exact symbol" in out[0].reason
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_rerank.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'codebase_index.retrieval.rerank'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/codebase_index/retrieval/rerank.py
"""Explainable feature reranker layered on the fused order (RETRIEVAL.md §4).

Adds a bounded bonus/penalty to the fused RRF score and produces a human-readable
`reason` per candidate. No external model. Graph centrality uses the denormalized
symbols.in_degree/out_degree; cross-node graph expansion is M5.
"""

from __future__ import annotations

import re

from .types import Candidate, Intent

_TERM_RE = re.compile(r"[A-Za-z0-9_]+")


def rerank(candidates: list[Candidate], *, query: str, intent: Intent) -> list[Candidate]:
    terms = {t.lower() for t in _TERM_RE.findall(query)}
    for c in candidates:
        bonus = 0.0
        reasons: list[str] = []

        if c.source == "symbol" and c.kind in {"function", "method", "class", "interface", "type"}:
            bonus += 0.05
        if c.exact_symbol:
            bonus += 0.20
            reasons.append("exact symbol match")
        if c.symbol and c.symbol.lower() in terms:
            bonus += 0.05

        # path proximity: query term appears in the path
        if any(t in c.path.lower() for t in terms):
            bonus += 0.05
            reasons.append(f"in {c.path.rsplit('/', 1)[0] or '.'}/")

        # graph centrality (denormalized)
        if c.in_degree:
            bonus += min(0.10, c.in_degree * 0.01)
            reasons.append(f"{c.in_degree} callers")
        if intent is Intent.ARCHITECTURE and (c.in_degree + c.out_degree):
            bonus += min(0.10, (c.in_degree + c.out_degree) * 0.005)

        # test/generated penalty (unless the query asked for it)
        wants_tests = "test" in terms or "tests" in terms
        if c.is_generated or (("test" in c.path.lower()) and not wants_tests):
            bonus -= 0.15
            reasons.append("generated/test demoted")

        c.score += bonus
        c.reason = " · ".join(reasons) if reasons else c.source  # type: ignore[attr-defined]

    candidates.sort(key=lambda c: c.score, reverse=True)
    return candidates
```

> Add `reason: str = ""` to `Candidate` in `types.py` (Task 1) for a declared field, or rely on the dynamic attribute as written. Declared is cleaner — if you add it, update the Task 1 dataclass and remove the `# type: ignore`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_rerank.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/retrieval/rerank.py tests/test_rerank.py
git commit -m "feat(retrieval): explainable feature reranker with reason strings"
```

---

## Task 8: Token budgeting

**Files:**
- Create: `src/codebase_index/retrieval/budget.py`
- Test: `tests/test_budget.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_budget.py
from codebase_index.retrieval.budget import apply_budget
from codebase_index.retrieval.types import Candidate


def _c(path, ls, le, content, token_est):
    c = Candidate(path=path, line_start=ls, line_end=le, source="fts",
                  score=1.0, content=content, token_est=token_est)
    c.reason = "x"  # type: ignore[attr-defined]
    return c


def test_snippets_stop_at_budget():
    cands = [_c(f"f{i}.py", 1, 5, "x" * 400, 100) for i in range(10)]
    results, recommended = apply_budget(cands, token_budget=250)
    with_snippet = [r for r in results if r["snippet"] is not None]
    assert sum(r["token_est"] for r in with_snippet) <= 250
    # the rest become recommended_reads (path + range, no snippet)
    assert recommended and all("snippet" not in r for r in recommended)


def test_secrets_are_redacted():
    secret = "aws_secret = 'AKIAIOSFODNN7EXAMPLE'"
    cands = [_c("s.py", 1, 2, secret, 20)]
    results, _ = apply_budget(cands, token_budget=1000)
    assert "AKIAIOSFODNN7EXAMPLE" not in results[0]["snippet"]


def test_metadata_always_present_even_when_budget_zero():
    cands = [_c("a.py", 1, 2, "content", 50)]
    results, recommended = apply_budget(cands, token_budget=0)
    assert results[0]["path"] == "a.py" and results[0]["snippet"] is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_budget.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'codebase_index.retrieval.budget'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/codebase_index/retrieval/budget.py
"""Greedy token budgeting (RETRIEVAL.md §6).

Metadata for every result is always emitted (cheap). Snippets are attached to the
highest-ranked results until the budget is hit; the remainder become
recommended_reads. All snippet text is secret-redacted before emission.
"""

from __future__ import annotations

from ..output.redact import redact_snippet
from .types import Candidate


def _meta(c: Candidate) -> dict:
    return {
        "path": c.path,
        "line_start": c.line_start,
        "line_end": c.line_end,
        "symbols": [c.symbol] if c.symbol else [],
        "score": round(c.score, 4),
        "reason": getattr(c, "reason", c.source),
        "token_est": c.token_est,
    }


def apply_budget(
    candidates: list[Candidate], *, token_budget: int
) -> tuple[list[dict], list[dict]]:
    results: list[dict] = []
    recommended: list[dict] = []
    spent = 0

    for rank, c in enumerate(candidates, start=1):
        meta = _meta(c)
        meta["rank"] = rank
        snippet = None
        if c.content and spent + c.token_est <= token_budget:
            snippet = redact_snippet(c.content)
            spent += c.token_est
        else:
            recommended.append(
                {"path": c.path, "line_start": c.line_start, "line_end": c.line_end}
            )
        meta["snippet"] = snippet
        results.append(meta)

    return results, recommended
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_budget.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/retrieval/budget.py tests/test_budget.py
git commit -m "feat(retrieval): greedy token budgeting with redaction"
```

---

## Task 9: Pipeline orchestrator (confidence + fallback)

**Files:**
- Create: `src/codebase_index/retrieval/pipeline.py`
- Test: `tests/test_pipeline_search.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pipeline_search.py
from codebase_index.retrieval.pipeline import search


def test_search_payload_shape(seeded_index):
    payload = search(seeded_index.conn, "where is refresh_access_token implemented",
                     mode="hybrid", limit=10, token_budget=1500, no_fallback=False)
    assert payload["intent"] == "locate_impl"
    assert payload["confidence"] in {"high", "medium", "low"}
    assert payload["results"][0]["path"] == "src/auth/token.py"
    assert "recommended_reads" in payload


def test_low_confidence_emits_fallback(seeded_index):
    payload = search(seeded_index.conn, "nonexistent_symbol_xyz",
                     mode="hybrid", limit=10, token_budget=1500, no_fallback=False)
    assert payload["confidence"] == "low"
    assert payload["fallback_suggestions"]["ripgrep"]


def test_no_fallback_flag_suppresses_suggestions(seeded_index):
    payload = search(seeded_index.conn, "nonexistent_symbol_xyz",
                     mode="hybrid", limit=10, token_budget=1500, no_fallback=True)
    assert payload["fallback_suggestions"] == {}


def test_single_mode_runs_only_one_retriever(seeded_index):
    payload = search(seeded_index.conn, "token", mode="fts",
                     limit=10, token_budget=1500, no_fallback=False)
    assert payload["mode"] == "fts"
    assert payload["results"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline_search.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'codebase_index.retrieval.pipeline'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/codebase_index/retrieval/pipeline.py
"""Orchestrate the hybrid retrieval pipeline (RETRIEVAL.md §1–§7).

query -> intent -> retrievers -> RRF fuse -> rerank -> budget -> payload.
Graph expansion (§5) and vector retrieval (§2 vector) are deferred to M5/M6.
"""

from __future__ import annotations

import re
import sqlite3

from . import searchers
from .budget import apply_budget
from .fusion import fuse
from .intent import detect_intent
from .rerank import rerank
from .types import Confidence

_TERM_RE = re.compile(r"[A-Za-z0-9_]+")
_RRF_K = 60


def _run_retrievers(conn, query, *, mode, limit, weights):
    lists = {}
    if mode in ("hybrid", "fts"):
        lists["fts"] = searchers.fts_candidates(conn, query, limit=limit)
    if mode in ("hybrid", "symbol"):
        lists["symbol"] = searchers.symbol_candidates(conn, query, limit=limit)
    if mode == "hybrid":
        lists["path"] = searchers.path_candidates(conn, query, limit=limit)
    # single-mode: force that source's weight to 1.0
    if mode != "hybrid":
        weights = {mode: 1.0}
    return lists, weights


def _confidence(ranked) -> Confidence:
    if not ranked:
        return Confidence.LOW
    top = ranked[0]
    gap = top.score - (ranked[1].score if len(ranked) > 1 else 0.0)
    agree = getattr(top, "agreeing_sources", 1)
    if getattr(top, "exact_symbol", False) or (agree >= 2 and gap > 0.01):
        return Confidence.HIGH
    if top.score > 0 and (agree >= 2 or gap > 0.005):
        return Confidence.MEDIUM
    return Confidence.LOW


def _fallback_suggestions(query, ranked) -> dict:
    terms = _TERM_RE.findall(query)
    if not terms:
        return {}
    longest = max(terms, key=len)
    rg = [f'rg -n "{longest}"']
    if len(terms) > 1:
        rg.append(f'rg -n "{".*".join(terms[:3])}"')
    return {"ripgrep": rg}


def search(
    conn: sqlite3.Connection,
    query: str,
    *,
    mode: str,
    limit: int,
    token_budget: int,
    no_fallback: bool,
) -> dict:
    plan = detect_intent(query)
    lists, weights = _run_retrievers(
        conn, query, mode=mode, limit=limit, weights=plan.weights
    )
    fused = fuse(lists, weights=weights, k=_RRF_K)
    ranked = rerank(fused, query=query, intent=plan.intent)[:limit]
    confidence = _confidence(ranked)
    results, recommended = apply_budget(ranked, token_budget=token_budget)

    fallback = {}
    if not no_fallback and confidence == Confidence.LOW:
        fallback = _fallback_suggestions(query, ranked)

    return {
        "query": query,
        "intent": plan.intent.value,
        "mode": mode,
        "confidence": confidence.value,
        "results": results,
        "recommended_reads": recommended,
        "fallback_suggestions": fallback,
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_pipeline_search.py -v`
Expected: PASS (4 passed)

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/retrieval/pipeline.py tests/test_pipeline_search.py
git commit -m "feat(retrieval): pipeline orchestrator with confidence and fallback"
```

---

## Task 10: Output renderers

**Files:**
- Create: `src/codebase_index/output/json.py`
- Create: `src/codebase_index/output/markdown.py`
- Test: `tests/test_output.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_output.py
import json as _json

from codebase_index.output import json as json_out
from codebase_index.output import markdown as md_out

PAYLOAD = {
    "query": "find X",
    "intent": "locate_impl",
    "mode": "hybrid",
    "confidence": "high",
    "results": [
        {"rank": 1, "path": "src/a.py", "line_start": 1, "line_end": 6,
         "symbols": ["X"], "score": 0.91, "reason": "exact symbol match",
         "token_est": 30, "snippet": "def X():\n    ..."},
    ],
    "recommended_reads": [{"path": "src/b.py", "line_start": 4, "line_end": 9}],
    "fallback_suggestions": {},
}


def test_json_round_trips():
    out = json_out.render(PAYLOAD)
    assert _json.loads(out)["results"][0]["path"] == "src/a.py"


def test_markdown_is_compact_and_has_snippet():
    out = md_out.render(PAYLOAD)
    assert "src/a.py" in out and "1-6" in out
    assert "```" in out and "def X()" in out
    assert "exact symbol match" in out
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_output.py -v`
Expected: FAIL with `ImportError: cannot import name 'json' from 'codebase_index.output'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/codebase_index/output/json.py
"""Render the retrieval payload as a JSON string (RETRIEVAL.md §8)."""

from __future__ import annotations

import json


def render(payload: dict) -> str:
    return json.dumps(payload, indent=2, ensure_ascii=False)
```

```python
# src/codebase_index/output/markdown.py
"""Render the retrieval payload as compact Markdown for Claude's context."""

from __future__ import annotations


def render(payload: dict) -> str:
    lines: list[str] = []
    lines.append(f"**Query:** {payload['query']}  ")
    lines.append(
        f"**Intent:** `{payload['intent']}` · **Confidence:** {payload['confidence']}\n"
    )

    if payload["results"]:
        lines.append("| # | Path | Lines | Reason |")
        lines.append("|---|------|-------|--------|")
        for r in payload["results"]:
            lines.append(
                f"| {r['rank']} | `{r['path']}` | {r['line_start']}-{r['line_end']} "
                f"| {r.get('reason', '')} |"
            )
        lines.append("")
        for r in payload["results"]:
            if r.get("snippet"):
                lines.append(f"`{r['path']}:{r['line_start']}-{r['line_end']}`")
                lines.append("```")
                lines.append(r["snippet"])
                lines.append("```")

    if payload["recommended_reads"]:
        lines.append("\n**Recommended reads:**")
        for rr in payload["recommended_reads"]:
            lines.append(f"- `{rr['path']}:{rr['line_start']}-{rr['line_end']}`")

    fb = payload.get("fallback_suggestions", {}).get("ripgrep")
    if fb:
        lines.append("\n**Fallback (low confidence) — try:**")
        for cmd in fb:
            lines.append(f"- `{cmd}`")

    return "\n".join(lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_output.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/output/json.py src/codebase_index/output/markdown.py tests/test_output.py
git commit -m "feat(output): JSON and compact Markdown renderers"
```

---

## Task 11: Wire `search` and `explain` into the CLI

**Files:**
- Modify: `src/codebase_index/cli.py:99-147`
- Test: `tests/test_search_cli.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_search_cli.py
import json as _json

from typer.testing import CliRunner

from codebase_index.cli import app

runner = CliRunner()


def _build(tmp_path, monkeypatch):
    # Build a real index over the bundled fixture into tmp_path.
    from codebase_index.config import Config
    from codebase_index.indexer.pipeline import build_index
    from codebase_index.storage.db import Database

    from tests.conftest import FIXTURE_ROOT  # type: ignore

    cfg = Config(root=str(FIXTURE_ROOT))
    db_path = tmp_path / "index.sqlite"
    with Database(db_path) as db:
        build_index(cfg, db, root=FIXTURE_ROOT)
    return db_path


def test_search_json_runs(tmp_path, monkeypatch):
    db_path = _build(tmp_path, monkeypatch)
    # Point the CLI at our prebuilt DB by faking root resolution to tmp parent.
    monkeypatch.setenv("CBX_DB_PATH", str(db_path))
    result = runner.invoke(app, ["search", "refresh token", "--json"])
    assert result.exit_code == 0
    payload = _json.loads(result.stdout)
    assert payload["mode"] == "hybrid"
    assert "results" in payload


def test_explain_forces_intent_shape(tmp_path, monkeypatch):
    db_path = _build(tmp_path, monkeypatch)
    monkeypatch.setenv("CBX_DB_PATH", str(db_path))
    result = runner.invoke(app, ["explain", "how does token refresh work", "--json"])
    assert result.exit_code == 0
    payload = _json.loads(result.stdout)
    assert payload["intent"] in {"how_it_works", "architecture"}
```

> The test introduces a `CBX_DB_PATH` override so the CLI can target a prebuilt DB without depending on cwd discovery. Implement that override in Step 3 (small, and it makes the search commands testable + scriptable).

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_search_cli.py -v`
Expected: FAIL — `search` still prints "not implemented" so `_json.loads` raises / exit asserts fail.

- [ ] **Step 3: Write minimal implementation**

Add a DB-path resolver near the top of `cli.py` (after imports):

```python
import os


def _resolve_db_path(ctx: "typer.Context") -> Path:
    from .config import load

    override = os.environ.get("CBX_DB_PATH")
    if override:
        return Path(override)
    root_opt = ctx.obj.get("root") if ctx.obj else None
    cfg = load(root_opt)
    return Path(cfg.root) / ".claude" / "cache" / "codebase-index" / "index.sqlite"
```

Replace the `search` body (`cli.py:99-109`):

```python
@app.command()
def search(
    ctx: typer.Context,
    query: str = typer.Argument(..., help="Search query."),
    limit: int = typer.Option(10, "--limit"),
    token_budget: int = typer.Option(1500, "--token-budget"),
    mode: str = typer.Option("hybrid", "--mode", help="hybrid|fts|symbol|vector"),
    no_fallback: bool = typer.Option(False, "--no-fallback"),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Hybrid ranked search; returns compact results + recommended_reads."""
    from .output import json as json_renderer
    from .output import markdown as md_renderer
    from .retrieval.pipeline import search as run_search
    from .storage.db import Database

    if mode == "vector":
        typer.echo("[codebase-index] vector mode requires embeddings (M6); use --mode hybrid.")
        raise typer.Exit(code=2)

    db_path = _resolve_db_path(ctx)
    if not db_path.exists():
        typer.echo("No index found. Run `codebase-index index`.")
        raise typer.Exit(code=1)

    with Database(db_path) as db:
        payload = run_search(
            db.conn, query, mode=mode, limit=limit,
            token_budget=token_budget, no_fallback=no_fallback,
        )

    want_json = json_out or (ctx.obj and ctx.obj.get("json"))
    typer.echo(json_renderer.render(payload) if want_json else md_renderer.render(payload))
```

Replace the `explain` body (`cli.py:141-147`):

```python
@app.command()
def explain(
    ctx: typer.Context,
    query: str = typer.Argument(...),
    token_budget: int = typer.Option(2200, "--token-budget"),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Intent-aware bundle for 'how does X work' / overview questions."""
    from .output import json as json_renderer
    from .output import markdown as md_renderer
    from .retrieval.pipeline import search as run_search
    from .storage.db import Database

    db_path = _resolve_db_path(ctx)
    if not db_path.exists():
        typer.echo("No index found. Run `codebase-index index`.")
        raise typer.Exit(code=1)

    # Bias toward explanatory queries: prepend "how does" if the user didn't.
    q = query if any(w in query.lower() for w in ("how", "architecture", "overview")) else f"how does {query} work"
    with Database(db_path) as db:
        payload = run_search(db.conn, q, mode="hybrid", limit=10,
                             token_budget=token_budget, no_fallback=False)

    want_json = json_out or (ctx.obj and ctx.obj.get("json"))
    typer.echo(json_renderer.render(payload) if want_json else md_renderer.render(payload))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_search_cli.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/cli.py tests/test_search_cli.py
git commit -m "feat(cli): wire hybrid search and explain commands"
```

---

## Task 12: Acceptance — hybrid outranks single retrievers

**Files:**
- Test: `tests/test_hybrid_ranking.py`

This is the milestone exit gate. No new production code unless this test exposes a regression.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_hybrid_ranking.py
import pytest

from codebase_index.retrieval.pipeline import search


def _rank_of(payload, path) -> int:
    for r in payload["results"]:
        if r["path"] == path:
            return r["rank"]
    return 10**6  # not found -> worst possible rank


# (query, expected target path)
CASES = [
    ("where is refresh_access_token implemented", "src/auth/token.py"),
    ("find the User class", "src/models/user.py"),
]


@pytest.mark.parametrize("query,target", CASES)
def test_hybrid_outranks_single_retrievers(seeded_index, query, target):
    conn = seeded_index.conn
    common = dict(limit=10, token_budget=1500, no_fallback=True)
    hybrid = search(conn, query, mode="hybrid", **common)
    fts = search(conn, query, mode="fts", **common)
    sym = search(conn, query, mode="symbol", **common)

    h = _rank_of(hybrid, target)
    assert h <= _rank_of(fts, target)
    assert h <= _rank_of(sym, target)
    assert hybrid["results"][0]["path"] == target  # hybrid puts target #1


def test_budget_is_enforced(seeded_index):
    payload = search(seeded_index.conn, "token", mode="hybrid",
                     limit=10, token_budget=120, no_fallback=True)
    spent = sum(r["token_est"] for r in payload["results"] if r["snippet"])
    assert spent <= 120


def test_at_least_one_strict_improvement(seeded_index):
    # On the decoy-heavy "token" query, hybrid should beat fts-only for the
    # symbol-bearing file (fts alone over-weights docs/notes.md).
    conn = seeded_index.conn
    common = dict(limit=10, token_budget=1500, no_fallback=True)
    hybrid = search(conn, "refresh token access", mode="hybrid", **common)
    fts = search(conn, "refresh token access", mode="fts", **common)
    target = "src/auth/token.py"
    assert _rank_of(hybrid, target) < _rank_of(fts, target)
```

- [ ] **Step 2: Run test to verify it fails (or passes — diagnose)**

Run: `pytest tests/test_hybrid_ranking.py -v`
Expected: Initially may FAIL on `test_at_least_one_strict_improvement` if intent weights don't yet let the symbol signal overcome FTS for the decoy query.

- [ ] **Step 3: Adjust weights/rerank ONLY if the acceptance test fails**

If `test_at_least_one_strict_improvement` fails, the symbol/path signal is too weak for the `keyword`/`how_it_works` intent. Bump the symbol weight for the relevant intent in `intent.py` (e.g. `Intent.KEYWORD` symbol weight `0.6 -> 0.8`) OR raise the exact/centrality bonus in `rerank.py`. Re-run after each single change. Do not weaken the FTS path — the goal is fusion winning, not FTS losing.

- [ ] **Step 4: Run the full suite**

Run: `pytest -v`
Expected: PASS (all M4 tests + existing M0–M3 tests green)

- [ ] **Step 5: Commit**

```bash
git add tests/test_hybrid_ranking.py src/codebase_index/retrieval/intent.py src/codebase_index/retrieval/rerank.py
git commit -m "test(retrieval): acceptance — hybrid outranks single retrievers + budget enforced"
```

---

## Final verification

- [ ] Run the whole suite: `pytest -q` → all green.
- [ ] Manual smoke (after a real `codebase-index index` in a repo):
  - `codebase-index search "where is X implemented"` → ranked table + snippets.
  - `codebase-index search "zzz_nonexistent" ` → low confidence + ripgrep fallback shown.
  - `codebase-index search "X" --mode fts` and `--mode symbol` run single retrievers.
  - `codebase-index explain "token refresh"` → explanatory bundle.
  - `codebase-index search "X" --json` → valid JSON matching RETRIEVAL.md §8 shape.
- [ ] Confirm no network calls were introduced (vector remains gated/absent).

---

## Self-Review notes (author)

- **Spec coverage:** intent (`§1`, Task 2), retrievers path/symbol/fts (`§2`, Tasks 4–5), RRF (`§3`, Task 6), rerank + reason (`§4`, Task 7), budget + redaction (`§6`, Task 8), confidence + fallback (`§7`, Task 9), payload + Markdown (`§8`, Task 10), CLI `search`/`explain` (ROADMAP M4, Task 11), exit criterion (Task 12). Graph expansion (`§5`) and vector retrieval explicitly deferred to M5/M6 — noted in Assumptions.
- **Type consistency:** `Candidate` fields (`key()`, `exact_symbol`, `in_degree`, `reason`, `agreeing_sources`) are used consistently across fusion/rerank/budget/pipeline; the two dynamic attributes (`reason`, `agreeing_sources`) are flagged with the option to declare them in Task 1.
- **No placeholders:** every code step contains runnable code; every test step has assertions; ranking thresholds in Task 12 include a concrete tuning instruction rather than "adjust as needed".
