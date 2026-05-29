# M2 — FTS5 Lexical Indexing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `codebase-index search "<q>" --mode fts` returns ranked lexical matches with file/line ranges and secret-redacted snippets, backed by chunked content synced into FTS5.

**Architecture:** The indexer gains a chunking stage: each eligible file is split into overlapping line windows (`parsers/line_chunker.py`) and stored in `chunks`; the existing `schema.sql` triggers keep `fts_chunks` in sync automatically. Code-aware tokenization is split across two layers: the FTS tokenizer is changed to plain `unicode61` (dropping `tokenchars '_'`) so **snake_case identifiers split into subtokens at index time** (`refresh_access_token` → `refresh`/`access`/`token`); and the searcher adds **query-time camelCase expansion** (`refreshAccessToken` → also `refresh`/`access`/`token`) since stdlib `sqlite3` cannot register a custom FTS5 tokenizer to split camelCase at index time. A minimal output-time secret redactor (`output/redact.py`) scrubs snippets. Two renderers (`output/json.py`, `output/markdown.py`) emit the shared `SearchResponse`.

> **Why edit `schema.sql`:** the project is pre-release (no shipped index DBs), so changing the FTS tokenizer is a free edit — `SCHEMA_VERSION` stays `1`, no migration. The original `tokenchars '_'` setting would index snake_case as a single token, defeating subtoken search; dropping it is the pragmatic stand-in for the deferred custom (APSW) tokenizer.

**Tech Stack:** Python 3.10+, stdlib `sqlite3` FTS5, pydantic v2 (`SearchResponse` in `models.py`), Typer, pytest. Builds directly on the M1 storage + discovery + pipeline layer.

**Depends on:** M1 (Database, repo.files/meta accessors, config.load, discovery.walk, indexer.pipeline.build_index, sample_repo fixture). This plan extends those modules; it does not re-create them.

---

## File Structure

| File | Create/Modify | Responsibility |
|---|---|---|
| `src/codebase_index/parsers/base.py` | Create | `Chunk` + `Symbol` dataclasses and the `Parser` protocol shared by all parsers. |
| `src/codebase_index/parsers/line_chunker.py` | Create | Split file text into overlapping line windows with a token estimate. M2's only parser. |
| `src/codebase_index/storage/repo.py` | Modify | Add `replace_chunks`, `chunks_for_file`, `count_chunks`, `fts_search` (raw row query). |
| `src/codebase_index/indexer/pipeline.py` | Modify | After upserting each file, chunk it and `replace_chunks`. Track chunk count in `BuildStats`. |
| `src/codebase_index/output/redact.py` | Create | Minimal, conservative secret redactor applied to snippet text before emission. |
| `src/codebase_index/retrieval/searchers.py` | Create | `Candidate` dataclass, `build_match_query` (identifier expansion), `fts_search`, `fts_response` assembly (freshness + confidence + budget + fallback). |
| `src/codebase_index/output/json.py` | Create | `render(resp) -> str`: `SearchResponse` as pretty JSON. |
| `src/codebase_index/output/markdown.py` | Create | `render(resp) -> str`: compact Markdown table + fenced snippets + recommended reads + fallbacks. |
| `src/codebase_index/cli.py` | Modify | Wire the `search` command to `fts_response` + renderers (`--mode fts`, `hybrid` aliases fts until M4). |
| `tests/test_chunker.py` | Create | Windowing, overlap, token estimate, edge cases (empty/short files). |
| `tests/test_storage.py` | Modify | `replace_chunks` idempotency + FTS sync + `count_chunks`. |
| `tests/test_pipeline.py` | Modify | `build_index` populates `chunks` and FTS is queryable. |
| `tests/test_redact.py` | Create | Secret patterns masked; benign code untouched; line count preserved. |
| `tests/test_searchers.py` | Create | `build_match_query` expansion + `fts_search`/`fts_response` over the fixture. |
| `tests/test_output.py` | Create | JSON round-trips; Markdown contains paths/ranges/snippets. |
| `tests/test_search_cli.py` | Create | `search --mode fts --json` end-to-end on the fixture. |

**Conventions:** `from __future__ import annotations`; pydantic v2; `--json` output stays plain text only; all SQL lives in `storage/repo.py`.

---

## Task 1: Parsers — `base.py` types + `line_chunker.py`

**Files:**
- Create: `src/codebase_index/parsers/base.py`
- Create: `src/codebase_index/parsers/line_chunker.py`
- Test: `tests/test_chunker.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_chunker.py
from __future__ import annotations

from codebase_index.parsers.line_chunker import chunk_text


def _lines(n: int) -> str:
    return "\n".join(f"line{i}" for i in range(1, n + 1))


def test_short_file_is_one_chunk():
    chunks = chunk_text(_lines(10), window_lines=80, overlap_lines=10)
    assert len(chunks) == 1
    c = chunks[0]
    assert c.line_start == 1 and c.line_end == 10
    assert c.kind == "window"
    assert c.token_est >= 1


def test_windows_and_overlap():
    chunks = chunk_text(_lines(200), window_lines=80, overlap_lines=10)
    # stride = 80 - 10 = 70 -> starts at 1, 71, 141 -> 3 windows
    assert [c.line_start for c in chunks] == [1, 71, 141]
    assert chunks[0].line_end == 80
    assert chunks[1].line_start == 71  # overlaps previous (71..80 shared)
    assert chunks[-1].line_end == 200  # last window clamps to EOF


def test_empty_file_yields_no_chunks():
    assert chunk_text("", window_lines=80, overlap_lines=10) == []
    assert chunk_text("   \n  \n", window_lines=80, overlap_lines=10) == []


def test_token_estimate_scales_with_size():
    small = chunk_text(_lines(5), window_lines=80, overlap_lines=10)[0]
    big = chunk_text(_lines(60), window_lines=80, overlap_lines=10)[0]
    assert big.token_est > small.token_est
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_chunker.py -v`
Expected: FAIL — `ModuleNotFoundError: codebase_index.parsers.line_chunker`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/codebase_index/parsers/base.py
"""Shared parser types. A Parser turns file text into chunks (+ symbols later)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol


@dataclass
class Chunk:
    line_start: int
    line_end: int
    content: str
    token_est: int
    kind: str = "window"            # 'window' | 'symbol_body' | 'doc'
    symbol_index: Optional[int] = None  # index into the same parse's symbol list (M3)


@dataclass
class Symbol:
    name: str
    kind: str
    line_start: int
    line_end: int
    qualified: Optional[str] = None
    signature: Optional[str] = None
    parent_index: Optional[int] = None
    docstring: Optional[str] = None


@dataclass
class ParseResult:
    chunks: list[Chunk] = field(default_factory=list)
    symbols: list[Symbol] = field(default_factory=list)


class Parser(Protocol):
    def parse(self, text: str) -> ParseResult: ...
```

```python
# src/codebase_index/parsers/line_chunker.py
"""Fallback chunker: overlapping fixed-size line windows + a token estimate.

Used for every file in M2 (tree-sitter symbol-aligned chunks arrive in M3).
"""

from __future__ import annotations

from .base import Chunk

_CHARS_PER_TOKEN = 4  # crude but stable estimate; good enough for budgeting


def estimate_tokens(text: str) -> int:
    return max(1, round(len(text) / _CHARS_PER_TOKEN))


def chunk_text(text: str, *, window_lines: int, overlap_lines: int) -> list[Chunk]:
    if not text or not text.strip():
        return []
    if overlap_lines >= window_lines:
        overlap_lines = window_lines - 1  # guarantee forward progress
    stride = window_lines - overlap_lines

    lines = text.splitlines()
    n = len(lines)
    chunks: list[Chunk] = []
    start = 0  # 0-based index into `lines`
    while start < n:
        end = min(start + window_lines, n)
        body = "\n".join(lines[start:end])
        chunks.append(
            Chunk(
                line_start=start + 1,     # 1-based, inclusive
                line_end=end,             # 1-based, inclusive
                content=body,
                token_est=estimate_tokens(body),
                kind="window",
            )
        )
        if end >= n:
            break
        start += stride
    return chunks
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_chunker.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/parsers/base.py src/codebase_index/parsers/line_chunker.py tests/test_chunker.py
git commit -m "feat(parsers): line-window chunker with token estimate"
```

---

## Task 2: Storage — FTS tokenizer fix + chunk accessors + FTS query

**Files:**
- Modify: `src/codebase_index/storage/schema.sql` (FTS tokenizer)
- Modify: `docs/SCHEMA.md` (keep DDL doc in sync)
- Modify: `src/codebase_index/storage/repo.py`
- Test: `tests/test_storage.py` (append)

- [ ] **Step 1: Change the FTS tokenizer in `schema.sql`**

Edit `src/codebase_index/storage/schema.sql` — in the `CREATE VIRTUAL TABLE ... fts_chunks` block, change the tokenize line from:

```sql
    tokenize = "unicode61 remove_diacritics 2 tokenchars '_'"
```

to (drop `tokenchars '_'` so underscores are token separators → snake_case splits into subtokens):

```sql
    tokenize = "unicode61 remove_diacritics 2"
```

Mirror the same change in `docs/SCHEMA.md` (the `CREATE VIRTUAL TABLE fts_chunks` block and the note paragraph below it — update the note to: *"Underscores are token separators, so `snake_case` identifiers are searchable by their parts. camelCase splitting is handled at query time; a true custom tokenizer (APSW) is deferred."*).

- [ ] **Step 2: Write the failing test**

```python
# tests/test_storage.py  (append)
from codebase_index.parsers.base import Chunk


def test_replace_chunks_syncs_fts(tmp_path):
    db = _open(tmp_path)
    fid = repo.upsert_file(
        db.conn, path="src/a.py", lang="python", size_bytes=10, sha256="h",
        mtime_ns=1, git_status=None, parser="line", indexed_at="t", is_generated=False,
    )
    repo.replace_chunks(db.conn, fid, [
        Chunk(line_start=1, line_end=3, content="def refresh_token():\n    pass", token_est=8),
    ])
    assert repo.count_chunks(db.conn) == 1
    # FTS is in sync via triggers — querying the virtual table finds the chunk
    hit = db.conn.execute(
        "SELECT rowid FROM fts_chunks WHERE fts_chunks MATCH 'refresh_token'"
    ).fetchall()
    assert len(hit) == 1

    # replacing chunks for the file removes the old ones (and their FTS rows)
    repo.replace_chunks(db.conn, fid, [
        Chunk(line_start=1, line_end=1, content="x = 1", token_est=2),
    ])
    assert repo.count_chunks(db.conn) == 1
    none = db.conn.execute(
        "SELECT rowid FROM fts_chunks WHERE fts_chunks MATCH 'refresh_token'"
    ).fetchall()
    assert none == []
    db.close()
    # (Step 1's schema change is what makes `refresh_token` searchable by parts)


def test_fts_search_returns_path_and_lines(tmp_path):
    db = _open(tmp_path)
    fid = repo.upsert_file(
        db.conn, path="src/auth/token.py", lang="python", size_bytes=10, sha256="h",
        mtime_ns=1, git_status=None, parser="line", indexed_at="t", is_generated=False,
    )
    repo.replace_chunks(db.conn, fid, [
        Chunk(line_start=5, line_end=9, content="def bootstrap():\n    return 1", token_est=6),
    ])
    rows = repo.fts_search(db.conn, "bootstrap", limit=10)
    assert len(rows) == 1
    r = rows[0]
    assert r["path"] == "src/auth/token.py"
    assert r["line_start"] == 5 and r["line_end"] == 9
    assert "bootstrap" in r["content"]
    db.close()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_storage.py -v`
Expected: FAIL — `AttributeError: module 'repo' has no attribute 'replace_chunks'`.

- [ ] **Step 4: Write minimal implementation**

Append to `src/codebase_index/storage/repo.py` (add `from ..parsers.base import Chunk` to imports and `from typing import ... Sequence`):

```python
# src/codebase_index/storage/repo.py  (append)

def replace_chunks(conn: sqlite3.Connection, file_id: int, chunks: "Sequence[Chunk]") -> int:
    """Delete a file's existing chunks then insert the new set. FTS5 triggers
    in schema.sql keep `fts_chunks` in sync automatically."""
    conn.execute("DELETE FROM chunks WHERE file_id = ?", (file_id,))
    conn.executemany(
        """
        INSERT INTO chunks (file_id, line_start, line_end, kind, symbol_id, content, token_est)
        VALUES (?, ?, ?, ?, NULL, ?, ?)
        """,
        [
            (file_id, c.line_start, c.line_end, c.kind, c.content, c.token_est)
            for c in chunks
        ],
    )
    return len(chunks)


def chunks_for_file(conn: sqlite3.Connection, file_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM chunks WHERE file_id = ? ORDER BY line_start", (file_id,)
    ).fetchall()


def count_chunks(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0])


def fts_search(conn: sqlite3.Connection, match_query: str, *, limit: int) -> list[sqlite3.Row]:
    """Raw bm25-ranked lexical search. `match_query` is a valid FTS5 MATCH expr.
    Lower bm25() is a better match, so we order ascending."""
    if not match_query.strip():
        return []
    return conn.execute(
        """
        SELECT c.id          AS chunk_id,
               f.path         AS path,
               c.line_start   AS line_start,
               c.line_end     AS line_end,
               c.content      AS content,
               c.token_est    AS token_est,
               bm25(fts_chunks) AS bm25
        FROM fts_chunks
        JOIN chunks c ON c.id = fts_chunks.rowid
        JOIN files  f ON f.id = c.file_id
        WHERE fts_chunks MATCH ?
        ORDER BY bm25(fts_chunks)
        LIMIT ?
        """,
        (match_query, limit),
    ).fetchall()
```

Add the imports at the top of the file:

```python
from typing import Iterable, Optional, Sequence
from ..parsers.base import Chunk
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_storage.py -v`
Expected: PASS (all storage tests incl. the two new ones).

- [ ] **Step 6: Commit**

```bash
git add src/codebase_index/storage/schema.sql docs/SCHEMA.md src/codebase_index/storage/repo.py tests/test_storage.py
git commit -m "feat(storage): split snake_case in FTS + chunk accessors + bm25 fts_search"
```

---

## Task 3: Indexer — chunk files during `build_index`

**Files:**
- Modify: `src/codebase_index/indexer/pipeline.py`
- Test: `tests/test_pipeline.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pipeline.py  (append)
from codebase_index.storage import repo as _repo


def test_build_populates_chunks_and_fts(sample_repo, tmp_path):
    cfg = Config()
    cfg.root = str(sample_repo)
    db = Database(tmp_path / "index.sqlite").open()
    stats = build_index(cfg, db, root=sample_repo)

    assert stats.chunks > 0
    assert _repo.count_chunks(db.conn) == stats.chunks

    # the fixture's refresh_access_token is searchable via FTS
    rows = _repo.fts_search(db.conn, "refresh_access_token", limit=10)
    assert any(r["path"] == "src/auth/token.py" for r in rows)
    db.close()


def test_reindex_replaces_chunks_not_duplicates(sample_repo, tmp_path):
    cfg = Config()
    cfg.root = str(sample_repo)
    db = Database(tmp_path / "index.sqlite").open()
    s1 = build_index(cfg, db, root=sample_repo)
    s2 = build_index(cfg, db, root=sample_repo)
    assert s1.chunks == s2.chunks  # idempotent, no accumulation
    db.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline.py -v`
Expected: FAIL — `AttributeError: 'BuildStats' object has no attribute 'chunks'`.

- [ ] **Step 3: Write minimal implementation**

In `src/codebase_index/indexer/pipeline.py`: add a `chunks` field to `BuildStats`, import the chunker + repo chunk API, and chunk each candidate after upserting it.

```python
# src/codebase_index/indexer/pipeline.py  — modify

from ..config import Config
from ..discovery.walker import walk
from ..parsers.line_chunker import chunk_text
from ..storage import repo
from ..storage.db import Database


@dataclass
class BuildStats:
    indexed: int = 0
    deleted: int = 0
    total_bytes: int = 0
    chunks: int = 0
```

Inside the `for cand in walk(...)` loop, after the existing `repo.upsert_file(...)` call (which returns the file id — capture it) add the chunking step:

```python
        file_id = repo.upsert_file(
            conn,
            path=cand.rel_path,
            lang=cand.lang,
            size_bytes=cand.size_bytes,
            sha256=sha,
            mtime_ns=mtime_ns,
            git_status=None,
            parser=cand.parser,
            indexed_at=now,
            is_generated=cand.is_generated,
        )
        text = _read_text(cand.path)
        file_chunks = chunk_text(
            text,
            window_lines=config.chunk.window_lines,
            overlap_lines=config.chunk.overlap_lines,
        )
        repo.replace_chunks(conn, file_id, file_chunks)
        stats.chunks += len(file_chunks)

        seen.add(cand.rel_path)
        stats.indexed += 1
        stats.total_bytes += cand.size_bytes
```

Add the text reader helper near `_sha256_file`:

```python
def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""
```

> Note: pruning deleted files via `repo.delete_files` cascade-deletes their chunks (FK `ON DELETE CASCADE`), and the chunk DELETE triggers remove the FTS rows — so no orphaned FTS entries.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_pipeline.py -v`
Expected: PASS (M1 pipeline tests + 2 new).

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/indexer/pipeline.py tests/test_pipeline.py
git commit -m "feat(indexer): chunk files into FTS during build_index"
```

---

## Task 4: Output — minimal secret redactor

**Files:**
- Create: `src/codebase_index/output/redact.py`
- Test: `tests/test_redact.py`

> M2 is the first milestone that emits file content to Claude, so a conservative redactor ships
> now. It only masks within a line and never changes line count (per SECURITY.md §3). The fuller
> entropy-based redaction is M4.

- [ ] **Step 1: Write the failing test**

```python
# tests/test_redact.py
from __future__ import annotations

from codebase_index.output.redact import redact_snippet


def test_masks_assigned_secrets():
    out = redact_snippet('API_KEY = "sk-livesecret1234567890abcd"')
    assert "sk-livesecret" not in out
    assert "«redacted" in out


def test_masks_known_formats():
    assert "AKIA" not in redact_snippet("aws = AKIAIOSFODNN7EXAMPLE")
    assert "BEGIN" in redact_snippet("-----BEGIN PRIVATE KEY-----")  # header text kept...
    assert "«redacted:private_key»" in redact_snippet(
        "-----BEGIN PRIVATE KEY-----\nMIIBVgIBADANBg\n-----END PRIVATE KEY-----"
    )


def test_benign_code_untouched():
    src = "def add(a, b):\n    return a + b"
    assert redact_snippet(src) == src


def test_line_count_preserved():
    src = 'token = "abcd1234efgh5678ijkl"\nx = 1\ny = 2'
    out = redact_snippet(src)
    assert out.count("\n") == src.count("\n")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_redact.py -v`
Expected: FAIL — `ModuleNotFoundError: codebase_index.output.redact`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/codebase_index/output/redact.py
"""Conservative, output-time secret redaction. Masks within a line; never
widens the snippet or changes the line count. See docs/SECURITY.md §3."""

from __future__ import annotations

import re

# (pattern, replacement-type-label)
_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # PEM private key blocks (multiline)
    (re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----.*?-----END [A-Z ]*PRIVATE KEY-----",
                re.DOTALL), "private_key"),
    # AWS access key id
    (re.compile(r"\bAKIA[0-9A-Z]{16}\b"), "aws_key"),
    # JWT (three base64url segments)
    (re.compile(r"\beyJ[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\.[A-Za-z0-9_-]+\b"), "jwt"),
    # Slack tokens
    (re.compile(r"\bxox[baprs]-[A-Za-z0-9-]+\b"), "slack_token"),
    # value assigned to a secret-ish key:  name = "...."  /  name: '....'
    (re.compile(
        r"((?:[A-Za-z0-9_]*?(?:secret|token|password|passwd|api[_-]?key|apikey|key)"
        r"[A-Za-z0-9_]*)\s*[:=]\s*)(['\"])([^'\"]{6,})\2",
        re.IGNORECASE,
    ), "secret_value"),
]


def redact_snippet(text: str) -> str:
    out = text
    for pattern, label in _PATTERNS:
        if label == "secret_value":
            out = pattern.sub(lambda m: f'{m.group(1)}{m.group(2)}«redacted:{label}»{m.group(2)}', out)
        elif label == "private_key":
            # collapse the block to a single marker but keep the surrounding lines
            out = pattern.sub(lambda m: _mask_block(m.group(0), label), out)
        else:
            out = pattern.sub(f"«redacted:{label}»", out)
    return out


def _mask_block(block: str, label: str) -> str:
    """Replace a multiline secret block with a single marker, preserving the
    number of newlines so line numbers downstream stay correct."""
    newlines = "\n" * block.count("\n")
    return f"«redacted:{label}»{newlines}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_redact.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/output/redact.py tests/test_redact.py
git commit -m "feat(output): minimal conservative secret redactor for snippets"
```

---

## Task 5: Retrieval — FTS searcher + query expansion + response assembly

**Files:**
- Create: `src/codebase_index/retrieval/searchers.py`
- Test: `tests/test_searchers.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_searchers.py
from __future__ import annotations

from codebase_index.config import Config
from codebase_index.indexer.pipeline import build_index
from codebase_index.retrieval.searchers import build_match_query, fts_response
from codebase_index.storage.db import Database


def test_build_match_query_expands_identifiers():
    q = build_match_query("refreshAccessToken")
    # original kept AND subtokens OR-ed
    assert "refreshAccessToken" in q
    assert "refresh" in q and "access" in q.lower() and "token" in q.lower()
    assert "OR" in q


def test_build_match_query_handles_snake_case():
    q = build_match_query("refresh_access_token")
    assert "refresh" in q and "access" in q and "token" in q


def test_build_match_query_empty_is_empty():
    assert build_match_query("   ") == ""
    assert build_match_query("!!!") == ""


def _indexed(sample_repo, tmp_path):
    cfg = Config()
    cfg.root = str(sample_repo)
    db = Database(tmp_path / "index.sqlite").open()
    build_index(cfg, db, root=sample_repo)
    return cfg, db


def test_fts_response_finds_symbol_with_snippet(sample_repo, tmp_path):
    cfg, db = _indexed(sample_repo, tmp_path)
    resp = fts_response(db.conn, "refresh access token", limit=10, token_budget=1500, root=sample_repo)
    assert resp.intent == "keyword"
    assert resp.results, "expected at least one lexical hit"
    top = resp.results[0]
    assert top.path == "src/auth/token.py"
    assert top.rank == 1
    assert top.snippet is not None  # budget allows a snippet for the top hit
    assert resp.recommended_reads[0].path == "src/auth/token.py"
    assert resp.confidence in ("high", "medium", "low")
    db.close()


def test_fts_response_empty_query_low_confidence_with_fallback(sample_repo, tmp_path):
    cfg, db = _indexed(sample_repo, tmp_path)
    resp = fts_response(db.conn, "zzznotpresentzzz", limit=10, token_budget=1500, root=sample_repo)
    assert resp.results == []
    assert resp.confidence == "low"
    assert resp.fallback_suggestions.get("ripgrep")
    db.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_searchers.py -v`
Expected: FAIL — `ModuleNotFoundError: codebase_index.retrieval.searchers`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/codebase_index/retrieval/searchers.py
"""FTS lexical searcher + response assembly (M2).

Stdlib sqlite3 cannot register a custom FTS5 tokenizer, so identifier-aware
matching is done at QUERY time: each query term is split into camelCase /
snake_case subtokens and OR-ed with the original term. Fusion/rerank/graph
expansion arrive in M4 — here `intent` is fixed to 'keyword'.
"""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..models import IndexFreshness, ReadRange, Result, SearchResponse
from ..output.redact import redact_snippet
from ..storage import repo

_WORD_RE = re.compile(r"[A-Za-z0-9_]+")
_CAMEL_RE = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z0-9]+")
_SNIPPET_MAX_LINES = 18


@dataclass
class Candidate:
    chunk_id: int
    path: str
    line_start: int
    line_end: int
    content: str
    token_est: int
    bm25: float


# -- query construction --------------------------------------------------
def _subtokens(term: str) -> list[str]:
    parts: list[str] = []
    for piece in term.split("_"):
        parts.extend(m.group(0) for m in _CAMEL_RE.finditer(piece))
    return [p for p in parts if len(p) >= 2]


def build_match_query(query: str) -> str:
    """Turn a free-text query into an FTS5 MATCH expression with identifier
    expansion. Groups (orig OR sub OR sub) are AND-ed across query terms."""
    groups: list[str] = []
    for term in _WORD_RE.findall(query):
        variants = {term, *(_subtokens(term))}
        variants = {v for v in variants if len(v) >= 2}
        if not variants:
            continue
        # quote each variant so FTS treats it as a bare term
        ored = " OR ".join(f'"{v}"' for v in sorted(variants, key=str.lower))
        groups.append(f"({ored})" if len(variants) > 1 else ored)
    return " ".join(groups)


# -- search --------------------------------------------------------------
def fts_search(conn: sqlite3.Connection, query: str, *, limit: int) -> list[Candidate]:
    match = build_match_query(query)
    rows = repo.fts_search(conn, match, limit=limit)
    return [
        Candidate(
            chunk_id=r["chunk_id"], path=r["path"],
            line_start=r["line_start"], line_end=r["line_end"],
            content=r["content"], token_est=r["token_est"], bm25=r["bm25"],
        )
        for r in rows
    ]


def fts_response(
    conn: sqlite3.Connection,
    query: str,
    *,
    limit: int,
    token_budget: int,
    root: Path,
) -> SearchResponse:
    cands = fts_search(conn, query, limit=limit)
    freshness = _freshness(conn)
    confidence = _confidence(cands)

    results: list[Result] = []
    recommended: list[ReadRange] = []
    spent = 0
    for i, c in enumerate(cands):
        recommended.append(ReadRange(path=c.path, line_start=c.line_start, line_end=c.line_end))
        snippet: Optional[str] = None
        # greedily attach a redacted snippet to the highest-ranked results
        if spent + c.token_est <= token_budget:
            snippet = redact_snippet(_trim(c.content))
            spent += c.token_est
        results.append(Result(
            rank=i + 1,
            path=c.path,
            line_start=c.line_start,
            line_end=c.line_end,
            symbols=[],
            score=round(1.0 / (i + 1), 4),
            reason="lexical match (bm25)",
            snippet=snippet,
        ))

    return SearchResponse(
        query=query,
        intent="keyword",
        index=freshness,
        confidence=confidence,
        results=results,
        recommended_reads=recommended,
        fallback_suggestions=_fallbacks(query) if confidence != "high" else {},
    )


# -- helpers -------------------------------------------------------------
def _trim(content: str) -> str:
    lines = content.splitlines()
    if len(lines) <= _SNIPPET_MAX_LINES:
        return content
    return "\n".join(lines[:_SNIPPET_MAX_LINES]) + "\n…"


def _confidence(cands: list[Candidate]) -> str:
    if not cands:
        return "low"
    if len(cands) == 1:
        return "medium"
    # bm25 is negative; a clear gap between #1 and #2 => high confidence
    gap = abs(cands[1].bm25 - cands[0].bm25)
    return "high" if gap >= 1.0 else "medium"


def _fallbacks(query: str) -> dict[str, list[str]]:
    terms = _WORD_RE.findall(query)
    primary = terms[0] if terms else query
    return {"ripgrep": [f'rg -n "{primary}"', f'rg -ni "{primary}"']}


def _freshness(conn: sqlite3.Connection) -> IndexFreshness:
    built_at = repo.get_meta(conn, "built_at")
    head = repo.get_meta(conn, "head_commit")
    # M2 reports existence + build metadata. Full staleness detection
    # (files_changed_since_build) is part of the M8 incremental/watch work.
    return IndexFreshness(
        exists=built_at is not None,
        stale=False,
        files_changed_since_build=0,
        built_at=built_at,
        head_commit=head,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_searchers.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/retrieval/searchers.py tests/test_searchers.py
git commit -m "feat(retrieval): FTS searcher with identifier expansion + response assembly"
```

---

## Task 6: Output — JSON + Markdown renderers

**Files:**
- Create: `src/codebase_index/output/json.py`
- Create: `src/codebase_index/output/markdown.py`
- Test: `tests/test_output.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_output.py
from __future__ import annotations

import json as _json

from codebase_index.models import IndexFreshness, ReadRange, Result, SearchResponse
from codebase_index.output import json as json_out
from codebase_index.output import markdown as md_out


def _resp() -> SearchResponse:
    return SearchResponse(
        query="bootstrap",
        intent="keyword",
        index=IndexFreshness(exists=True, stale=False, built_at="2026-05-29T00:00:00Z"),
        confidence="high",
        results=[Result(
            rank=1, path="web/app.ts", line_start=1, line_end=3,
            symbols=[], score=1.0, reason="lexical match (bm25)",
            snippet="export function bootstrap(): void {}",
        )],
        recommended_reads=[ReadRange(path="web/app.ts", line_start=1, line_end=3)],
        fallback_suggestions={},
    )


def test_json_renderer_round_trips():
    text = json_out.render(_resp())
    data = _json.loads(text)
    assert data["query"] == "bootstrap"
    assert data["results"][0]["path"] == "web/app.ts"
    assert data["index"]["exists"] is True


def test_markdown_renderer_contains_key_fields():
    text = md_out.render(_resp())
    assert "web/app.ts" in text
    assert "1-3" in text or "1–3" in text
    assert "bootstrap" in text
    assert "high" in text.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_output.py -v`
Expected: FAIL — `ModuleNotFoundError: codebase_index.output.json`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/codebase_index/output/json.py
"""Machine-readable JSON renderer for SearchResponse (what the skill parses)."""

from __future__ import annotations

from ..models import SearchResponse


def render(resp: SearchResponse) -> str:
    return resp.model_dump_json(indent=2)
```

```python
# src/codebase_index/output/markdown.py
"""Compact Markdown renderer for SearchResponse — optimized for low token count."""

from __future__ import annotations

from ..models import SearchResponse


def render(resp: SearchResponse) -> str:
    lines: list[str] = []
    fresh = "fresh" if not resp.index.stale else "STALE"
    if not resp.index.exists:
        fresh = "NO INDEX"
    lines.append(f"**query:** {resp.query}  ·  **intent:** {resp.intent}  "
                 f"·  **confidence:** {resp.confidence}  ·  **index:** {fresh}")
    lines.append("")

    if resp.results:
        lines.append("| # | path | lines | reason |")
        lines.append("|---|------|-------|--------|")
        for r in resp.results:
            syms = (" `" + ",".join(r.symbols) + "`") if r.symbols else ""
            lines.append(f"| {r.rank} | `{r.path}`{syms} | {r.line_start}-{r.line_end} | {r.reason} |")
        lines.append("")
        for r in resp.results:
            if r.snippet:
                lines.append(f"`{r.path}:{r.line_start}-{r.line_end}`")
                lines.append("```")
                lines.append(r.snippet)
                lines.append("```")
        lines.append("")
    else:
        lines.append("_No index matches._")
        lines.append("")

    if resp.recommended_reads:
        lines.append("**recommended reads:**")
        for rr in resp.recommended_reads:
            lines.append(f"- `{rr.path}:{rr.line_start}-{rr.line_end}`")
        lines.append("")

    if resp.fallback_suggestions:
        lines.append("**fallback:**")
        for tool, cmds in resp.fallback_suggestions.items():
            for cmd in cmds:
                lines.append(f"- `{cmd}`")
    return "\n".join(lines).rstrip() + "\n"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_output.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/output/json.py src/codebase_index/output/markdown.py tests/test_output.py
git commit -m "feat(output): JSON + compact Markdown renderers for SearchResponse"
```

---

## Task 7: CLI — wire the `search` command

**Files:**
- Modify: `src/codebase_index/cli.py` (the `search` command + add `ctx`)
- Test: `tests/test_search_cli.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_search_cli.py
from __future__ import annotations

import json

from typer.testing import CliRunner

from codebase_index.cli import app

runner = CliRunner()


def test_search_fts_json_after_index(sample_repo):
    idx = runner.invoke(app, ["--root", str(sample_repo), "--json", "index"])
    assert idx.exit_code == 0, idx.output

    res = runner.invoke(
        app,
        ["--root", str(sample_repo), "--json", "search", "refresh access token", "--mode", "fts"],
    )
    assert res.exit_code == 0, res.output
    data = json.loads(res.output)
    assert data["intent"] == "keyword"
    assert any(r["path"] == "src/auth/token.py" for r in data["results"])


def test_search_without_index_reports_missing(sample_repo, tmp_path, monkeypatch):
    # point root at an empty dir with no built index
    empty = tmp_path / "empty"
    (empty / ".git").mkdir(parents=True)
    res = runner.invoke(app, ["--root", str(empty), "--json", "search", "anything"])
    assert res.exit_code == 0
    data = json.loads(res.output)
    assert data["index"]["exists"] is False
    assert data["results"] == []


def test_search_markdown_default(sample_repo):
    runner.invoke(app, ["--root", str(sample_repo), "index"])
    res = runner.invoke(app, ["--root", str(sample_repo), "search", "bootstrap", "--mode", "fts"])
    assert res.exit_code == 0
    assert "web/app.ts" in res.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_search_cli.py -v`
Expected: FAIL — current `search` prints `not implemented`; `json.loads` raises.

- [ ] **Step 3: Write minimal implementation**

Replace the `search` command in `src/codebase_index/cli.py`:

```python
# src/codebase_index/cli.py  — replace the `search` function

@app.command()
def search(
    ctx: typer.Context,
    query: str = typer.Argument(..., help="Search query."),
    limit: int = typer.Option(10, "--limit"),
    token_budget: int = typer.Option(1500, "--token-budget"),
    mode: str = typer.Option("hybrid", "--mode", help="hybrid|fts|symbol|vector"),
    no_fallback: bool = typer.Option(False, "--no-fallback"),
) -> None:
    """Lexical (FTS) ranked search; returns compact results + recommended_reads.

    M2 implements the FTS path. `hybrid` aliases `fts` until fusion lands in M4;
    `symbol`/`vector` are not available yet.
    """
    from .config import load
    from .models import IndexFreshness, SearchResponse
    from .output import json as json_out
    from .output import markdown as md_out
    from .retrieval.searchers import fts_response
    from .storage.db import Database

    is_json = bool(ctx.obj and ctx.obj.get("json"))

    if mode in ("symbol", "vector"):
        typer.echo(f"[codebase-index] --mode {mode} is not available until a later milestone "
                   "(M3/M6). Use --mode fts.")
        raise typer.Exit(code=0)

    cfg = load(ctx.obj.get("root") if ctx.obj else None)
    db_path = Path(cfg.root) / ".claude" / "cache" / "codebase-index" / "index.sqlite"

    if not db_path.exists():
        empty = SearchResponse(
            query=query, intent="keyword",
            index=IndexFreshness(exists=False, stale=False),
            confidence="low", results=[], recommended_reads=[],
            fallback_suggestions={} if no_fallback else {"ripgrep": [f'rg -n "{query}"']},
        )
        typer.echo(json_out.render(empty) if is_json else md_out.render(empty))
        raise typer.Exit(code=0)

    with Database(db_path) as db:
        resp = fts_response(
            db.conn, query, limit=limit, token_budget=token_budget, root=Path(cfg.root)
        )
    if no_fallback:
        resp.fallback_suggestions = {}

    typer.echo(json_out.render(resp) if is_json else md_out.render(resp))
```

> `search` now takes `ctx: typer.Context` as its first parameter (Typer injects it).
>
> **Check the existing M0 smoke test** `tests/test_cli.py::test_search_accepts_query_and_flags`:
> it invokes `["search", "auth token", "--json", "--limit", "5"]`. `--json` is a **callback
> (parent) option**, and Click routes options appearing *after* the subcommand name to the
> subcommand — `search` has no `--json`, so this invocation now errors with "no such option".
> Fix the smoke test by moving global options before the subcommand:
> `runner.invoke(app, ["--json", "search", "auth token", "--limit", "5"])`. With no built index in
> the cwd, `search` returns an empty `SearchResponse` and exit code 0, so the assertion holds.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_search_cli.py tests/test_cli.py -v`
Expected: PASS (3 new + the 2 M0 smoke tests).

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/cli.py tests/test_search_cli.py tests/test_cli.py
git commit -m "feat(cli): wire search to FTS retrieval + renderers"
```

---

## Task 8: Full suite, lint, manual smoke, roadmap update

**Files:**
- Modify: `docs/ROADMAP.md` (mark M2 done; note the tokenizer decision)

- [ ] **Step 1: Run the whole suite**

Run: `pytest -v`
Expected: all M0/M1/M2 tests PASS (test_cli, test_storage, test_config, test_classify, test_ignore, test_discovery, test_pipeline, test_chunker, test_redact, test_searchers, test_output, test_search_cli).

- [ ] **Step 2: Lint + type-check**

Run: `ruff check src tests` and `mypy src/codebase_index`
Expected: clean. Fix unused imports / typing nits inline.

- [ ] **Step 3: Manual end-to-end smoke on this repo**

Run:

```bash
pip install -e .
codebase-index --root . index
codebase-index --root . search "build index" --mode fts
codebase-index --root . --json search "config_hash" --mode fts
```

Expected: ranked results with `src/...` paths, line ranges, and a snippet on the top hit; JSON parses; no secret values appear in any snippet.

- [ ] **Step 4: Update the roadmap**

Edit `docs/ROADMAP.md`:
- Change the M2 heading to `## M2 — FTS5 lexical indexing ✅`.
- Append a one-line note under M2: *"snake_case is split at index time (plain unicode61 tokenizer); camelCase is expanded at query time. A true custom FTS5 tokenizer via APSW is deferred."*

- [ ] **Step 5: Commit**

```bash
git add docs/ROADMAP.md
git commit -m "docs: mark M2 (FTS5 lexical indexing) complete"
```

---

## Acceptance Criteria (M2 exit)

- `codebase-index index` populates `chunks` (overlapping line windows + token estimate) and keeps
  `fts_chunks` in sync; re-indexing replaces chunks without duplication or orphaned FTS rows.
- `codebase-index search "<q>" --mode fts` returns ranked lexical results with `path`,
  `line_start/line_end`, a `reason`, and a budget-limited, **secret-redacted** snippet on top hits;
  lower-ranked hits appear in `recommended_reads`.
- camelCase / snake_case queries match the same identifiers via query-time expansion
  (`refreshAccessToken` finds `refresh_access_token`).
- Empty/no-match queries return `confidence: "low"` with `ripgrep` fallback suggestions; a missing
  index returns `index.exists = false` (and the skill knows to run `index`).
- `--json` emits parseable `SearchResponse`; default output is compact Markdown.
- Full `pytest` green; `ruff` + `mypy` clean; base install remains network-free.

## Deferred to later milestones (explicitly NOT in M2)

- Symbol extraction, symbol-aligned chunks, `symbol`/`refs` commands (M3).
- Intent detection, path/symbol/vector retrievers, RRF fusion, reranking, `explain` (M4).
- Graph edges + `impact` (M5); embeddings/vector search (M6).
- True custom FTS5 tokenizer via APSW (bidirectional camelCase splitting at index time) — M2 splits
  snake_case via the index tokenizer and camelCase via query-time expansion. Known gap: querying a
  camelCase identifier in code by separate words requires naming that identifier.
- Full staleness detection (`files_changed_since_build`) + incremental `update` (M8); M2 reports
  existence + build metadata only.
- Entropy-based redaction expansion (M4) — M2 ships the conservative pattern-based redactor.
