# M1 — Storage + Discovery + Ignore Rules Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver the first end-to-end runnable slice: `codebase-index index` walks the repo, applies layered ignore + security gates, and populates the `files` table; `codebase-index stats` reports real coverage and freshness.

**Architecture:** A `storage` layer owns the SQLite DB (pragmas, schema, migrations) and all SQL via typed accessors. `config.load()` resolves project root + merged config + a stable `config_hash`. `discovery` walks the tree, prunes ignored directories, and runs each file through classification (language / binary / secret / size / generated) so secrets/binaries/build dirs never become indexable candidates. `indexer/pipeline` hashes survivors, upserts them into `files`, prunes deleted rows, and writes `meta`. No chunks/symbols/edges yet — those are M2/M3.

**Tech Stack:** Python 3.10+, Typer (CLI), pydantic v2 (config), pathspec (gitignore matching), sqlite3 (stdlib), pytest (TDD). No network, no tree-sitter use yet (the dep is installed but unused in M1).

---

## File Structure

| File | Create/Modify | Responsibility |
|---|---|---|
| `src/codebase_index/storage/db.py` | Create | `Database` connection wrapper: pragmas, apply `schema.sql`, `schema_version` guard. |
| `src/codebase_index/storage/repo.py` | Create | Typed accessors. M1 scope: `files` upsert/read/prune + `meta` get/set + counts. All SQL lives here. |
| `src/codebase_index/config.py` | Modify | Implement `find_root()`, `load()`, `Config.config_hash()`. |
| `src/codebase_index/discovery/classify.py` | Create | Pure classification: language, secret-filename, binary, generated detection. No filesystem walking. |
| `src/codebase_index/discovery/ignore.py` | Create | `IgnoreMatcher`: built-in denylist + layered ignore files merged via pathspec. |
| `src/codebase_index/discovery/walker.py` | Create | `walk()`: os.walk + prune ignored dirs + per-file gates → yields `Candidate`. |
| `src/codebase_index/indexer/pipeline.py` | Create | `build_index()`: walk → hash → upsert `files` → prune deleted → write `meta`. Returns `BuildStats`. |
| `src/codebase_index/cli.py` | Modify | Wire `index` and `stats` to the real pipeline/storage; keep other commands as stubs. |
| `tests/fixtures/sample_repo/` | Create | Shared fixture repo with planted secrets/binaries/build dirs (see fixtures README). |
| `tests/test_storage.py` | Create | DB open/close/recreate, pragmas, schema_version, files+meta accessors. |
| `tests/test_config.py` | Create | Root discovery, config merge, stable `config_hash`. |
| `tests/test_classify.py` | Create | Language/secret/binary/generated classification. |
| `tests/test_ignore.py` | Create | Built-in denylist + ignore-file layering. |
| `tests/test_discovery.py` | Create | `walk()` over the fixture: gates enforced. |
| `tests/test_index_cli.py` | Create | `index` populates `files`; `stats` reports counts; security exclusions hold end-to-end. |

**Conventions to follow (already in the repo):** `from __future__ import annotations` at top of modules; pydantic v2 models in `config.py`; module docstrings describing responsibilities; `--json` output stays plain (no rich) so it's machine-parseable.

---

## Task 1: Storage — `Database` connection, pragmas, schema, version guard

**Files:**
- Create: `src/codebase_index/storage/db.py`
- Test: `tests/test_storage.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_storage.py
from __future__ import annotations

import sqlite3

from codebase_index.storage.db import Database, SCHEMA_VERSION


def test_open_creates_schema_and_sets_pragmas(tmp_path):
    db_path = tmp_path / "index.sqlite"
    with Database(db_path) as db:
        # pragmas
        assert db.conn.execute("PRAGMA journal_mode").fetchone()[0].lower() == "wal"
        assert db.conn.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        # core tables exist
        tables = {
            r[0] for r in db.conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert {"files", "chunks", "symbols", "edges", "modules", "meta"} <= tables
        # version recorded
        assert db.get_schema_version() == SCHEMA_VERSION
    assert db_path.exists()


def test_reopen_is_idempotent_and_keeps_version(tmp_path):
    db_path = tmp_path / "index.sqlite"
    with Database(db_path) as db:
        db.conn.execute("INSERT INTO meta(key, value) VALUES ('probe', '1')")
    with Database(db_path) as db:
        assert db.get_schema_version() == SCHEMA_VERSION
        assert db.conn.execute("SELECT value FROM meta WHERE key='probe'").fetchone()[0] == "1"


def test_future_schema_version_raises(tmp_path):
    db_path = tmp_path / "index.sqlite"
    with Database(db_path) as db:
        db.conn.execute(
            "UPDATE meta SET value = ? WHERE key = 'schema_version'",
            (str(SCHEMA_VERSION + 1),),
        )
    import pytest
    with pytest.raises(RuntimeError, match="rebuild"):
        with Database(db_path):
            pass
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_storage.py -v`
Expected: FAIL — `ModuleNotFoundError: codebase_index.storage.db` / `ImportError: SCHEMA_VERSION`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/codebase_index/storage/db.py
"""SQLite connection management: pragmas, schema application, version guard."""

from __future__ import annotations

import sqlite3
from importlib import resources
from pathlib import Path
from typing import Optional

SCHEMA_VERSION = 1


class Database:
    """Owns a single SQLite connection for one CLI invocation.

    Applies pragmas, creates the schema on first open, and guards the
    `meta.schema_version`. Use as a context manager.
    """

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._conn: Optional[sqlite3.Connection] = None

    # -- lifecycle -------------------------------------------------------
    def open(self) -> "Database":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._apply_pragmas()
        self._apply_schema()
        self._guard_version()
        return self

    def close(self) -> None:
        if self._conn is not None:
            self._conn.commit()
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "Database":
        return self.open()

    def __exit__(self, *exc) -> None:
        self.close()

    # -- accessors -------------------------------------------------------
    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Database is not open")
        return self._conn

    def get_schema_version(self) -> int:
        row = self.conn.execute("SELECT value FROM meta WHERE key='schema_version'").fetchone()
        return int(row[0]) if row else 0

    # -- internals -------------------------------------------------------
    def _apply_pragmas(self) -> None:
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA synchronous = NORMAL")
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA temp_store = MEMORY")

    def _apply_schema(self) -> None:
        ddl = resources.files("codebase_index.storage").joinpath("schema.sql").read_text(
            encoding="utf-8"
        )
        self.conn.executescript(ddl)

    def _guard_version(self) -> None:
        current = self.get_schema_version()
        if current == 0:
            self.conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            self.conn.commit()
        elif current > SCHEMA_VERSION:
            raise RuntimeError(
                f"Index schema_version {current} is newer than supported {SCHEMA_VERSION}; "
                "run `codebase-index index --rebuild` with an updated CLI."
            )
        # current < SCHEMA_VERSION: additive migrations land here in later milestones.
```

> Note: `schema.sql` already begins with the four `PRAGMA` lines, but those only take effect for the running connection when executed by `_apply_pragmas`; `executescript` re-running them is harmless. Keep both — `_apply_pragmas` is the source of truth, `schema.sql` documents intent.

> Packaging: `schema.sql` is inside the `codebase_index.storage` package, so `importlib.resources` finds it both from source and from the built wheel. No change to `pyproject.toml` needed.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_storage.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/storage/db.py tests/test_storage.py
git commit -m "feat(storage): Database wrapper with pragmas, schema apply, version guard"
```

---

## Task 2: Storage — `files` + `meta` typed accessors

**Files:**
- Create: `src/codebase_index/storage/repo.py`
- Test: `tests/test_storage.py` (append)

- [ ] **Step 1: Write the failing test**

```python
# tests/test_storage.py  (append)
from codebase_index.storage import repo


def _open(tmp_path):
    return Database(tmp_path / "index.sqlite").open()


def test_upsert_and_get_file(tmp_path):
    db = _open(tmp_path)
    fid = repo.upsert_file(
        db.conn,
        path="src/a.py",
        lang="python",
        size_bytes=10,
        sha256="aaa",
        mtime_ns=123,
        git_status=None,
        parser="treesitter",
        indexed_at="2026-05-29T00:00:00Z",
        is_generated=False,
    )
    assert fid > 0
    row = repo.get_file(db.conn, "src/a.py")
    assert row is not None and row["sha256"] == "aaa" and row["lang"] == "python"

    # upsert on same path updates in place (same id, new hash)
    fid2 = repo.upsert_file(
        db.conn, path="src/a.py", lang="python", size_bytes=11, sha256="bbb",
        mtime_ns=456, git_status=None, parser="treesitter",
        indexed_at="2026-05-29T00:01:00Z", is_generated=False,
    )
    assert fid2 == fid
    assert repo.get_file(db.conn, "src/a.py")["sha256"] == "bbb"
    assert repo.count_files(db.conn) == 1
    db.close()


def test_all_paths_and_prune(tmp_path):
    db = _open(tmp_path)
    for p in ("a.py", "b.py", "c.py"):
        repo.upsert_file(
            db.conn, path=p, lang="python", size_bytes=1, sha256="x",
            mtime_ns=1, git_status=None, parser="line",
            indexed_at="t", is_generated=False,
        )
    assert repo.all_paths(db.conn) == {"a.py", "b.py", "c.py"}
    deleted = repo.delete_files(db.conn, ["b.py", "c.py"])
    assert deleted == 2
    assert repo.all_paths(db.conn) == {"a.py"}
    db.close()


def test_meta_get_set(tmp_path):
    db = _open(tmp_path)
    assert repo.get_meta(db.conn, "missing") is None
    repo.set_meta(db.conn, "head_commit", "abc123")
    repo.set_meta(db.conn, "head_commit", "def456")  # overwrite
    assert repo.get_meta(db.conn, "head_commit") == "def456"
    db.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_storage.py -v`
Expected: FAIL — `ImportError: cannot import name 'repo'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/codebase_index/storage/repo.py
"""Typed read/write accessors. ALL SQL lives here — never raw SQL elsewhere.

M1 scope: the `files` table + `meta` key/value. chunks/symbols/edges accessors
arrive in later milestones.
"""

from __future__ import annotations

import sqlite3
from typing import Iterable, Optional


def upsert_file(
    conn: sqlite3.Connection,
    *,
    path: str,
    lang: Optional[str],
    size_bytes: int,
    sha256: str,
    mtime_ns: int,
    git_status: Optional[str],
    parser: str,
    indexed_at: str,
    is_generated: bool,
) -> int:
    """Insert or update a file row keyed by unique `path`. Returns its id."""
    conn.execute(
        """
        INSERT INTO files
            (path, lang, size_bytes, sha256, mtime_ns, git_status, parser, indexed_at, is_generated)
        VALUES (:path, :lang, :size_bytes, :sha256, :mtime_ns, :git_status, :parser, :indexed_at, :is_generated)
        ON CONFLICT(path) DO UPDATE SET
            lang=excluded.lang,
            size_bytes=excluded.size_bytes,
            sha256=excluded.sha256,
            mtime_ns=excluded.mtime_ns,
            git_status=excluded.git_status,
            parser=excluded.parser,
            indexed_at=excluded.indexed_at,
            is_generated=excluded.is_generated
        """,
        {
            "path": path,
            "lang": lang,
            "size_bytes": size_bytes,
            "sha256": sha256,
            "mtime_ns": mtime_ns,
            "git_status": git_status,
            "parser": parser,
            "indexed_at": indexed_at,
            "is_generated": 1 if is_generated else 0,
        },
    )
    row = conn.execute("SELECT id FROM files WHERE path = ?", (path,)).fetchone()
    return int(row[0])


def get_file(conn: sqlite3.Connection, path: str) -> Optional[sqlite3.Row]:
    return conn.execute("SELECT * FROM files WHERE path = ?", (path,)).fetchone()


def all_paths(conn: sqlite3.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT path FROM files")}


def delete_files(conn: sqlite3.Connection, paths: Iterable[str]) -> int:
    paths = list(paths)
    if not paths:
        return 0
    conn.executemany("DELETE FROM files WHERE path = ?", [(p,) for p in paths])
    return len(paths)


def count_files(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM files").fetchone()[0])


def get_meta(conn: sqlite3.Connection, key: str) -> Optional[str]:
    row = conn.execute("SELECT value FROM meta WHERE key = ?", (key,)).fetchone()
    return row[0] if row else None


def set_meta(conn: sqlite3.Connection, key: str, value: str) -> None:
    conn.execute(
        "INSERT INTO meta(key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
        (key, value),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_storage.py -v`
Expected: PASS (all storage tests).

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/storage/repo.py tests/test_storage.py
git commit -m "feat(storage): files + meta typed accessors"
```

---

## Task 3: Config — root discovery, `load()`, stable `config_hash()`

**Files:**
- Modify: `src/codebase_index/config.py`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_config.py
from __future__ import annotations

import json

from codebase_index.config import Config, find_root, load


def test_find_root_walks_up_to_git(tmp_path):
    (tmp_path / ".git").mkdir()
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    assert find_root(nested) == tmp_path


def test_find_root_falls_back_to_start(tmp_path):
    nested = tmp_path / "x"
    nested.mkdir()
    assert find_root(nested) == nested  # no .git/.claude -> use the start dir


def test_load_defaults_when_no_config_file(tmp_path):
    (tmp_path / ".git").mkdir()
    cfg = load(tmp_path)
    assert isinstance(cfg, Config)
    assert cfg.max_file_bytes == 1_048_576
    assert cfg.embeddings.backend == "noop"


def test_load_merges_config_json(tmp_path):
    (tmp_path / ".git").mkdir()
    cache = tmp_path / ".claude" / "cache" / "codebase-index"
    cache.mkdir(parents=True)
    (cache / "config.json").write_text(json.dumps({"max_file_bytes": 2048}))
    cfg = load(tmp_path)
    assert cfg.max_file_bytes == 2048
    assert cfg.retrieval.rrf_k == 60  # untouched default preserved


def test_config_hash_stable_and_sensitive():
    a = Config()
    b = Config()
    assert a.config_hash() == b.config_hash()  # deterministic
    c = Config(max_file_bytes=42)
    assert c.config_hash() != a.config_hash()  # indexing-relevant change shifts hash
    # retrieval-only change must NOT shift the indexing hash
    d = Config()
    d.retrieval.token_budget = 9999
    assert d.config_hash() == a.config_hash()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -v`
Expected: FAIL — `ImportError: cannot import name 'find_root'` / `NotImplementedError`.

- [ ] **Step 3: Write minimal implementation**

Replace the bottom of `src/codebase_index/config.py` (the `config_hash` body and the `load` stub) and add `find_root`. Keep all existing model classes unchanged.

```python
# src/codebase_index/config.py  — replace `config_hash` and `load`, add `find_root` + imports

import hashlib
import json
import os

# ... (existing model classes unchanged) ...

class Config(BaseModel):
    # ... existing fields unchanged ...

    def config_hash(self) -> str:
        """Stable hash over INDEXING-relevant fields only.

        Retrieval/graph/embeddings-query knobs are excluded so tweaking
        ranking does not force a full re-index. Changing what gets indexed
        (root, languages, size cap, ignore rules, chunking) does.
        """
        relevant = {
            "root": self.root,
            "languages": self.languages,
            "max_file_bytes": self.max_file_bytes,
            "ignore_files": self.ignore_files,
            "extra_ignore": self.extra_ignore,
            "chunk": self.chunk.model_dump(),
            "redaction": self.redaction,
        }
        blob = json.dumps(relevant, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()


_ROOT_MARKERS = (".git", ".claude")


def find_root(start: Optional[Path] = None) -> Path:
    """Walk upward from `start` (default cwd) to the nearest dir containing a
    `.git` or `.claude` marker. Fall back to `start` if none is found.
    """
    start = (start or Path.cwd()).resolve()
    for candidate in (start, *start.parents):
        if any((candidate / marker).exists() for marker in _ROOT_MARKERS):
            return candidate
    return start


def _config_path(root: Path) -> Path:
    return root / ".claude" / "cache" / "codebase-index" / "config.json"


def load(root: Optional[Path] = None) -> Config:
    """Resolve project root and return a validated, merged Config.

    Order (later wins): built-in defaults -> config.json -> CBX_* env overrides.
    """
    resolved_root = find_root(root)
    data: dict = {}
    cfg_file = _config_path(resolved_root)
    if cfg_file.is_file():
        data = json.loads(cfg_file.read_text(encoding="utf-8"))

    # Minimal env overrides for the indexing knobs most likely tuned in CI.
    if "CBX_MAX_FILE_BYTES" in os.environ:
        data["max_file_bytes"] = int(os.environ["CBX_MAX_FILE_BYTES"])

    cfg = Config(**data)
    cfg.root = str(resolved_root)
    return cfg
```

> The existing `from typing import ... Optional` import already covers `Optional`; add `import hashlib, json, os` to the top alongside the existing imports.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/config.py tests/test_config.py
git commit -m "feat(config): root discovery, config.json merge, stable indexing config_hash"
```

---

## Task 4: Discovery — `classify.py` (language / secret / binary / generated)

**Files:**
- Create: `src/codebase_index/discovery/classify.py`
- Test: `tests/test_classify.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_classify.py
from __future__ import annotations

from codebase_index.discovery.classify import (
    detect_language,
    is_secret_filename,
    is_generated,
    looks_binary,
    parser_for,
)


def test_detect_language_by_extension():
    assert detect_language("src/auth/token.py") == "python"
    assert detect_language("web/app.ts") == "typescript"
    assert detect_language("main.go") == "go"
    assert detect_language("README") is None


def test_secret_filenames():
    for p in (".env", ".env.local", "secrets.pem", "id_rsa", "server.key", "creds/credentials.json"):
        assert is_secret_filename(p), p
    assert not is_secret_filename("src/auth/token.py")


def test_generated_patterns():
    for p in ("dist/bundle.min.js", "poetry.lock", "api_pb2.py", "schema.generated.ts"):
        assert is_generated(p), p
    assert not is_generated("src/app.py")


def test_looks_binary_detects_nul_bytes():
    assert looks_binary(b"\x89PNG\r\n\x1a\n\x00\x00") is True
    assert looks_binary(b"def main():\n    pass\n") is False


def test_parser_for_supported_vs_unsupported():
    assert parser_for("python") == "treesitter"
    assert parser_for(None) == "line"
    assert parser_for("makefile") == "line"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_classify.py -v`
Expected: FAIL — `ModuleNotFoundError: codebase_index.discovery.classify`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/codebase_index/discovery/classify.py
"""Pure file classification — no filesystem walking, no I/O beyond the bytes
handed in. Decides language, and whether a path is a secret/binary/generated
file. See docs/SECURITY.md §2.
"""

from __future__ import annotations

import fnmatch
from pathlib import PurePosixPath
from typing import Optional

# Extension -> language. Languages with tree-sitter coverage (M3) get the
# 'treesitter' parser; everything else falls back to the line chunker.
LANG_BY_EXT: dict[str, str] = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".go": "go",
    ".java": "java",
    ".rs": "rust",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".rb": "ruby",
    ".php": "php",
}

TREESITTER_LANGS = set(LANG_BY_EXT.values())

# Filenames/paths that must never be indexed (secret stores).
SECRET_GLOBS = (
    ".env", ".env.*", "*.pem", "*.key", "*.p12", "*.pfx",
    "id_rsa", "id_rsa.*", "id_dsa", "id_ed25519", "*.crt", "*.keystore",
    "credentials*", "secrets*", "*.pkcs12",
)

# Generated / vendored artifacts: summary-only at most, never symbol-parsed.
GENERATED_GLOBS = (
    "*.min.js", "*.min.css", "*.map", "*.lock", "*.pb.go",
    "*_pb2.py", "*_pb2.pyi", "*.generated.*", "*.g.dart",
)


def detect_language(rel_path: str) -> Optional[str]:
    return LANG_BY_EXT.get(PurePosixPath(rel_path).suffix.lower())


def parser_for(lang: Optional[str]) -> str:
    return "treesitter" if lang in TREESITTER_LANGS else "line"


def _matches_any(name_or_path: str, globs: tuple[str, ...]) -> bool:
    base = PurePosixPath(name_or_path).name
    return any(fnmatch.fnmatch(base, g) for g in globs)


def is_secret_filename(rel_path: str) -> bool:
    return _matches_any(rel_path, SECRET_GLOBS)


def is_generated(rel_path: str) -> bool:
    return _matches_any(rel_path, GENERATED_GLOBS)


def looks_binary(head: bytes) -> bool:
    """A NUL byte in the first chunk is the classic binary signal."""
    return b"\x00" in head
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_classify.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/discovery/classify.py tests/test_classify.py
git commit -m "feat(discovery): file classification (language/secret/binary/generated)"
```

---

## Task 5: Discovery — `ignore.py` (built-in denylist + layered ignore files)

**Files:**
- Create: `src/codebase_index/discovery/ignore.py`
- Test: `tests/test_ignore.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_ignore.py
from __future__ import annotations

from codebase_index.discovery.ignore import IgnoreMatcher


def test_builtin_denylist_dirs(tmp_path):
    m = IgnoreMatcher.from_root(tmp_path, ignore_files=[], extra_ignore=[])
    assert m.is_ignored("node_modules/lodash/index.js")
    assert m.is_ignored(".git/config")
    assert m.is_ignored("dist/bundle.js")
    assert m.is_ignored("__pycache__/x.pyc")
    assert not m.is_ignored("src/app.py")


def test_dir_pruning_signal(tmp_path):
    m = IgnoreMatcher.from_root(tmp_path, ignore_files=[], extra_ignore=[])
    assert m.is_ignored_dir("node_modules")
    assert m.is_ignored_dir(".venv")
    assert not m.is_ignored_dir("src")


def test_layered_ignore_files(tmp_path):
    (tmp_path / ".gitignore").write_text("*.log\nbuild/\n")
    (tmp_path / ".codeindexignore").write_text("docs/private/**\n")
    m = IgnoreMatcher.from_root(
        tmp_path,
        ignore_files=[".gitignore", ".cursorignore", ".claudeignore", ".codeindexignore"],
        extra_ignore=["**/snapshots/**"],
    )
    assert m.is_ignored("app.log")
    assert m.is_ignored("build/out.o")
    assert m.is_ignored("docs/private/secret.md")
    assert m.is_ignored("tests/snapshots/a.snap")
    assert not m.is_ignored("docs/public/readme.md")


def test_missing_ignore_files_are_skipped(tmp_path):
    # none of the ignore files exist -> only builtin denylist applies, no crash
    m = IgnoreMatcher.from_root(
        tmp_path, ignore_files=[".gitignore", ".claudeignore"], extra_ignore=[]
    )
    assert not m.is_ignored("src/app.py")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_ignore.py -v`
Expected: FAIL — `ModuleNotFoundError: codebase_index.discovery.ignore`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/codebase_index/discovery/ignore.py
"""Layered ignore matching.

Combines, in one pathspec matcher:
  1. a built-in denylist of dependency/build/VCS dirs (always excluded),
  2. user ignore files (.gitignore/.cursorignore/.claudeignore/.codeindexignore),
  3. `extra_ignore` globs from config.

M1 reads ignore files at the project ROOT only; nested .gitignore support is a
later refinement (tracked in ROADMAP). Patterns use gitwildmatch semantics.
"""

from __future__ import annotations

from pathlib import Path

from pathspec import PathSpec

# Directory names excluded regardless of ignore files. Trailing `/` makes the
# gitwildmatch pattern match the directory and everything under it.
BUILTIN_DENYLIST = [
    ".git/", ".hg/", ".svn/",
    "node_modules/", "bower_components/",
    ".venv/", "venv/", "env/", "__pycache__/", ".mypy_cache/", ".pytest_cache/",
    ".ruff_cache/", ".tox/",
    "dist/", "build/", "target/", "out/", "bin/", "obj/",
    "vendor/", ".gradle/", ".idea/", ".vscode/",
    ".claude/cache/",
]

# Bare directory names used for fast os.walk pruning (derived from the denylist).
_DENYLIST_DIRNAMES = {p.rstrip("/") for p in BUILTIN_DENYLIST if "/" not in p.rstrip("/")}


class IgnoreMatcher:
    def __init__(self, spec: PathSpec) -> None:
        self._spec = spec

    @classmethod
    def from_root(
        cls,
        root: Path,
        *,
        ignore_files: list[str],
        extra_ignore: list[str],
    ) -> "IgnoreMatcher":
        patterns: list[str] = list(BUILTIN_DENYLIST)
        for fname in ignore_files:
            fpath = root / fname
            if fpath.is_file():
                for line in fpath.read_text(encoding="utf-8", errors="ignore").splitlines():
                    stripped = line.strip()
                    if stripped and not stripped.startswith("#"):
                        patterns.append(stripped)
        patterns.extend(extra_ignore)
        spec = PathSpec.from_lines("gitwildmatch", patterns)
        return cls(spec)

    def is_ignored(self, rel_path: str) -> bool:
        """`rel_path` is POSIX, repo-relative."""
        return self._spec.match_file(rel_path)

    def is_ignored_dir(self, dirname: str) -> bool:
        """Cheap check for os.walk dir pruning by bare directory name."""
        return dirname in _DENYLIST_DIRNAMES
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_ignore.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/discovery/ignore.py tests/test_ignore.py
git commit -m "feat(discovery): layered ignore matcher (builtin denylist + ignore files)"
```

---

## Task 6: Build the shared fixture repo

**Files:**
- Create: `tests/fixtures/sample_repo/` (multiple files; some binary/oversized generated programmatically)
- Create: `tests/conftest.py` (a `sample_repo` fixture that returns the path)

> The fixture mirrors `tests/fixtures/README.md`. Text files are committed directly; the binary
> (`logo.png`) and oversized (`huge.json`) files are generated by a one-time script so they don't
> bloat the diff or rely on a real PNG. A `node_modules` file is committed to prove dir pruning.

- [ ] **Step 1: Create the text files of the sample repo**

```bash
mkdir -p tests/fixtures/sample_repo/src/auth
mkdir -p tests/fixtures/sample_repo/src/models
mkdir -p tests/fixtures/sample_repo/web
mkdir -p tests/fixtures/sample_repo/node_modules/leftpad
mkdir -p tests/fixtures/sample_repo/dist
```

Create `tests/fixtures/sample_repo/src/auth/token.py`:

```python
"""Auth token helpers (fixture)."""


def refresh_access_token(refresh_token: str) -> str:
    """Exchange a refresh token for a new access token."""
    return "access-" + refresh_token
```

Create `tests/fixtures/sample_repo/src/models/user.py`:

```python
"""User model (fixture) — imported widely for impact tests."""


class User:
    def __init__(self, name: str) -> None:
        self.name = name
```

Create `tests/fixtures/sample_repo/web/app.ts`:

```typescript
export function bootstrap(): void {
  console.log("app started");
}
```

Create `tests/fixtures/sample_repo/.env`:

```
API_KEY=sk-should-never-be-indexed
DB_PASSWORD=hunter2
```

Create `tests/fixtures/sample_repo/secrets.pem`:

```
-----BEGIN PRIVATE KEY-----
ZmFrZS1rZXktZm9yLXRlc3Rpbmctb25seQ==
-----END PRIVATE KEY-----
```

Create `tests/fixtures/sample_repo/dist/bundle.min.js` (proves `dist/` dir-pruning):

```javascript
console.log("generated");var a=1;
```

Create `tests/fixtures/sample_repo/src/schema.generated.ts` (a generated file that survives
dir-pruning, so the walker's generated-flag path is exercised):

```typescript
export const GENERATED = true;
```

Create `tests/fixtures/sample_repo/node_modules/leftpad/index.js`:

```javascript
module.exports = function () { return "dep"; };
```

Create `tests/fixtures/sample_repo/.gitignore`:

```
*.log
```

- [ ] **Step 2: Generate the binary and oversized files**

Run (one-time generation; the files are then committed):

```bash
python - <<'PY'
from pathlib import Path
base = Path("tests/fixtures/sample_repo")
# minimal binary file with NUL bytes
(base / "logo.png").write_bytes(b"\x89PNG\r\n\x1a\n" + b"\x00" * 32)
# oversized JSON (> default 1 MiB cap)
(base / "huge.json").write_text("{\"data\": \"" + "x" * (1_100_000) + "\"}")
print("generated logo.png and huge.json")
PY
```

- [ ] **Step 3: Add the conftest fixture**

```python
# tests/conftest.py
from __future__ import annotations

from pathlib import Path

import pytest

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "sample_repo"


@pytest.fixture
def sample_repo() -> Path:
    assert FIXTURE_ROOT.is_dir(), "run the M1 fixture-build steps first"
    return FIXTURE_ROOT
```

- [ ] **Step 4: Verify the fixture is well-formed**

Run:

```bash
python - <<'PY'
from pathlib import Path
b = Path("tests/fixtures/sample_repo")
assert (b/"src/auth/token.py").is_file()
assert b"\x00" in (b/"logo.png").read_bytes()
assert (b/"huge.json").stat().st_size > 1_048_576
print("fixture OK")
PY
```

Expected: prints `fixture OK`.

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/sample_repo tests/conftest.py
git commit -m "test(fixtures): sample_repo with planted secrets/binary/generated/oversized files"
```

---

## Task 7: Discovery — `walker.py` (gates integrated, yields `Candidate`)

**Files:**
- Create: `src/codebase_index/discovery/walker.py`
- Test: `tests/test_discovery.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_discovery.py
from __future__ import annotations

from codebase_index.config import Config
from codebase_index.discovery.walker import walk


def _walk_paths(root):
    cfg = Config()
    return {c.rel_path: c for c in walk(root, cfg)}


def test_walk_includes_source_excludes_unsafe(sample_repo):
    found = _walk_paths(sample_repo)

    # included source
    assert "src/auth/token.py" in found
    assert "src/models/user.py" in found
    assert "web/app.ts" in found

    # excluded by gates
    assert ".env" not in found                       # secret filename
    assert "secrets.pem" not in found                # secret filename
    assert "logo.png" not in found                   # binary
    assert "huge.json" not in found                  # oversized
    assert "node_modules/leftpad/index.js" not in found  # dependency dir
    assert "dist/bundle.min.js" not in found              # dist/ pruned by denylist
    # a generated file outside a pruned dir passes the gates but is flagged
    assert found["src/schema.generated.ts"].is_generated is True


def test_candidate_fields(sample_repo):
    found = _walk_paths(sample_repo)
    c = found["src/auth/token.py"]
    assert c.lang == "python"
    assert c.parser == "treesitter"
    assert c.size_bytes > 0
    assert c.is_generated is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_discovery.py -v`
Expected: FAIL — `ModuleNotFoundError: codebase_index.discovery.walker`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/codebase_index/discovery/walker.py
"""Walk the project root and yield indexable Candidates.

Pipeline per file (all gates must pass; see docs/SECURITY.md §2):
  ignore files/denylist -> secret filename -> size cap -> binary sniff.
Generated files pass but are flagged (`is_generated=True`) for summary-only
treatment downstream.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

from ..config import Config
from . import classify
from .ignore import IgnoreMatcher

_BINARY_SNIFF_BYTES = 4096


@dataclass
class Candidate:
    path: Path           # absolute path on disk
    rel_path: str        # POSIX, repo-relative
    size_bytes: int
    lang: Optional[str]
    parser: str          # 'treesitter' | 'line'
    is_generated: bool


def walk(root: Path, config: Config) -> Iterator[Candidate]:
    root = Path(root).resolve()
    matcher = IgnoreMatcher.from_root(
        root,
        ignore_files=config.ignore_files,
        extra_ignore=config.extra_ignore,
    )

    for dirpath, dirnames, filenames in os.walk(root):
        # prune ignored directories in place so os.walk skips them
        dirnames[:] = [
            d for d in dirnames
            if not matcher.is_ignored_dir(d)
            and not matcher.is_ignored(
                _rel(root, Path(dirpath) / d) + "/"
            )
        ]
        for fname in filenames:
            abs = Path(dirpath) / fname
            rel = _rel(root, abs)

            if matcher.is_ignored(rel):
                continue
            if classify.is_secret_filename(rel):
                continue
            try:
                size = abs.stat().st_size
            except OSError:
                continue
            if size > config.max_file_bytes:
                continue
            try:
                with abs.open("rb") as fh:
                    head = fh.read(_BINARY_SNIFF_BYTES)
            except OSError:
                continue
            if classify.looks_binary(head):
                continue

            lang = classify.detect_language(rel)
            yield Candidate(
                path=abs,
                rel_path=rel,
                size_bytes=size,
                lang=lang,
                parser=classify.parser_for(lang),
                is_generated=classify.is_generated(rel),
            )


def _rel(root: Path, p: Path) -> str:
    return p.resolve().relative_to(root).as_posix()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_discovery.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/discovery/walker.py tests/test_discovery.py
git commit -m "feat(discovery): walker with integrated security gates"
```

---

## Task 8: Indexer — `pipeline.build_index()` populates `files`

**Files:**
- Create: `src/codebase_index/indexer/pipeline.py`
- Test: `tests/test_pipeline.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_pipeline.py
from __future__ import annotations

from codebase_index.config import Config
from codebase_index.indexer.pipeline import build_index
from codebase_index.storage import repo
from codebase_index.storage.db import Database


def _index(sample_repo, tmp_path):
    cfg = Config()
    cfg.root = str(sample_repo)
    db = Database(tmp_path / "index.sqlite").open()
    stats = build_index(cfg, db, root=sample_repo)
    return cfg, db, stats


def test_build_populates_files_and_excludes_unsafe(sample_repo, tmp_path):
    cfg, db, stats = _index(sample_repo, tmp_path)
    paths = repo.all_paths(db.conn)

    assert "src/auth/token.py" in paths
    assert ".env" not in paths and "logo.png" not in paths and "huge.json" not in paths
    assert not any(p.startswith("node_modules/") for p in paths)

    assert stats.indexed == repo.count_files(db.conn)
    assert stats.indexed >= 4
    # meta written
    assert repo.get_meta(db.conn, "built_at") is not None
    assert repo.get_meta(db.conn, "config_hash") == cfg.config_hash()
    db.close()


def test_rebuild_prunes_deleted_files(sample_repo, tmp_path):
    cfg, db, _ = _index(sample_repo, tmp_path)
    # inject a stale row that no longer exists on disk
    repo.upsert_file(
        db.conn, path="ghost/old.py", lang="python", size_bytes=1, sha256="z",
        mtime_ns=1, git_status=None, parser="line", indexed_at="t", is_generated=False,
    )
    assert "ghost/old.py" in repo.all_paths(db.conn)
    stats = build_index(cfg, db, root=sample_repo)
    assert "ghost/old.py" not in repo.all_paths(db.conn)
    assert stats.deleted >= 1
    db.close()


def test_file_row_has_hash_and_parser(sample_repo, tmp_path):
    _, db, _ = _index(sample_repo, tmp_path)
    row = repo.get_file(db.conn, "src/auth/token.py")
    assert row["parser"] == "treesitter"
    assert len(row["sha256"]) == 64  # sha256 hex
    db.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline.py -v`
Expected: FAIL — `ModuleNotFoundError: codebase_index.indexer.pipeline`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/codebase_index/indexer/pipeline.py
"""Drive a build: discovery -> hash -> upsert files -> prune deleted -> meta.

M1 only populates the `files` table. Chunk/symbol/edge/summary stages land in
M2+ and will hang off this same function.
"""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..config import Config
from ..discovery.walker import walk
from ..storage import repo
from ..storage.db import Database


@dataclass
class BuildStats:
    indexed: int = 0
    deleted: int = 0
    total_bytes: int = 0


def build_index(config: Config, db: Database, root: Optional[Path] = None) -> BuildStats:
    root = Path(root or config.root).resolve()
    conn = db.conn
    now = _utc_now_iso()

    stats = BuildStats()
    seen: set[str] = set()

    for cand in walk(root, config):
        sha = _sha256_file(cand.path)
        mtime_ns = cand.path.stat().st_mtime_ns
        repo.upsert_file(
            conn,
            path=cand.rel_path,
            lang=cand.lang,
            size_bytes=cand.size_bytes,
            sha256=sha,
            mtime_ns=mtime_ns,
            git_status=None,  # populated in a later (incremental/git) milestone
            parser=cand.parser,
            indexed_at=now,
            is_generated=cand.is_generated,
        )
        seen.add(cand.rel_path)
        stats.indexed += 1
        stats.total_bytes += cand.size_bytes

    stale = repo.all_paths(conn) - seen
    stats.deleted = repo.delete_files(conn, stale)

    repo.set_meta(conn, "built_at", now)
    repo.set_meta(conn, "config_hash", config.config_hash())
    head = _git_head(root)
    if head:
        repo.set_meta(conn, "head_commit", head)
    conn.commit()
    return stats


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _git_head(root: Path) -> Optional[str]:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        return out.stdout.strip() if out.returncode == 0 else None
    except (OSError, subprocess.SubprocessError):
        return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_pipeline.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/indexer/pipeline.py tests/test_pipeline.py
git commit -m "feat(indexer): build_index populates files, prunes deleted, writes meta"
```

---

## Task 9: CLI — wire `index` and `stats`

**Files:**
- Modify: `src/codebase_index/cli.py:54-57` (the `index` command) and `:121-124` (the `stats` command)
- Test: `tests/test_index_cli.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_index_cli.py
from __future__ import annotations

import json

from typer.testing import CliRunner

from codebase_index.cli import app

runner = CliRunner()


def test_index_then_stats_json(sample_repo):
    # index the fixture repo
    r1 = runner.invoke(app, ["--root", str(sample_repo), "--json", "index"])
    assert r1.exit_code == 0, r1.output
    payload = json.loads(r1.output)
    assert payload["indexed"] >= 4
    assert payload["deleted"] == 0

    # stats reflects it
    r2 = runner.invoke(app, ["--root", str(sample_repo), "--json", "stats"])
    assert r2.exit_code == 0, r2.output
    stats = json.loads(r2.output)
    assert stats["files"] == payload["indexed"]
    assert stats["built_at"] is not None


def test_index_excludes_secrets_end_to_end(sample_repo):
    r = runner.invoke(app, ["--root", str(sample_repo), "--json", "index"])
    assert r.exit_code == 0
    # query the DB the CLI just wrote
    from codebase_index.config import find_root
    from codebase_index.storage.db import Database
    from codebase_index.storage import repo
    db_path = find_root(sample_repo) / ".claude" / "cache" / "codebase-index" / "index.sqlite"
    with Database(db_path) as db:
        paths = repo.all_paths(db.conn)
    assert ".env" not in paths and "secrets.pem" not in paths
```

> Cleanup note: the test writes `.claude/cache/codebase-index/index.sqlite` *inside the fixture
> dir*. Add `tests/fixtures/sample_repo/.claude/` to `.gitignore` so the generated DB is never
> committed (see Step 5).

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_index_cli.py -v`
Expected: FAIL — `index` currently prints `not implemented` and returns no JSON (`json.loads` raises).

- [ ] **Step 3: Write minimal implementation**

Replace the `index` command body:

```python
# src/codebase_index/cli.py  — replace the `index` function

@app.command()
def index(
    ctx: typer.Context,
    rebuild: bool = typer.Option(False, "--rebuild", help="Discard and rebuild from scratch."),
) -> None:
    """Full index build into .claude/cache/codebase-index/index.sqlite."""
    import json as _json

    from .config import load
    from .indexer.pipeline import build_index
    from .storage.db import Database

    root_opt = ctx.obj.get("root") if ctx.obj else None
    cfg = load(root_opt)
    db_path = Path(cfg.root) / ".claude" / "cache" / "codebase-index" / "index.sqlite"
    if rebuild and db_path.exists():
        db_path.unlink()

    with Database(db_path) as db:
        stats = build_index(cfg, db, root=Path(cfg.root))

    if ctx.obj and ctx.obj.get("json"):
        typer.echo(_json.dumps({
            "indexed": stats.indexed,
            "deleted": stats.deleted,
            "total_bytes": stats.total_bytes,
        }))
    elif not (ctx.obj and ctx.obj.get("quiet")):
        typer.echo(f"Indexed {stats.indexed} files ({stats.deleted} pruned).")
```

Replace the `stats` command body:

```python
# src/codebase_index/cli.py  — replace the `stats` function

@app.command()
def stats(ctx: typer.Context) -> None:
    """Index size, coverage %, and freshness."""
    import json as _json

    from .config import load
    from .storage import repo
    from .storage.db import Database

    root_opt = ctx.obj.get("root") if ctx.obj else None
    cfg = load(root_opt)
    db_path = Path(cfg.root) / ".claude" / "cache" / "codebase-index" / "index.sqlite"

    if not db_path.exists():
        if ctx.obj and ctx.obj.get("json"):
            typer.echo(_json.dumps({"files": 0, "built_at": None, "exists": False}))
        else:
            typer.echo("No index found. Run `codebase-index index`.")
        raise typer.Exit(code=0)

    with Database(db_path) as db:
        files = repo.count_files(db.conn)
        built_at = repo.get_meta(db.conn, "built_at")
        head = repo.get_meta(db.conn, "head_commit")

    if ctx.obj and ctx.obj.get("json"):
        typer.echo(_json.dumps({
            "files": files, "built_at": built_at, "head_commit": head, "exists": True,
        }))
    else:
        typer.echo(f"files={files}  built_at={built_at}  head={head}")
```

> `index` and `stats` now take `ctx: typer.Context` as their first parameter — Typer injects it
> automatically. The other stub commands are unchanged in M1.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_index_cli.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Add gitignore rule for the fixture cache, then commit**

Append to `.gitignore`:

```
tests/fixtures/sample_repo/.claude/
```

```bash
git add src/codebase_index/cli.py tests/test_index_cli.py .gitignore
git commit -m "feat(cli): wire index and stats to storage+pipeline"
```

---

## Task 10: Full suite, lint, roadmap update

**Files:**
- Modify: `docs/ROADMAP.md:10-14` (mark M1 done)
- Modify: `tests/fixtures/README.md` (drop the "to be added in M1" note)

- [ ] **Step 1: Run the whole test suite**

Run: `pytest -v`
Expected: all M0 + M1 tests PASS (test_cli, test_storage, test_config, test_classify, test_ignore, test_discovery, test_pipeline, test_index_cli).

- [ ] **Step 2: Lint and type-check**

Run: `ruff check src tests` and `mypy src/codebase_index`
Expected: no errors. Fix any reported issues inline (e.g. unused imports).

- [ ] **Step 3: Manual end-to-end smoke on this very repo**

Run:

```bash
pip install -e .
codebase-index --root . index
codebase-index --root . stats
```

Expected: `index` reports a file count > 0; `stats` shows the same count and a `built_at`.
Verify no secret/`.git`/cache files are counted (`codebase-index --root . --json stats`).

- [ ] **Step 4: Mark M1 complete in the roadmap**

Edit `docs/ROADMAP.md` — change the M1 heading to `## M1 — Storage + discovery + ignore rules ✅`
and the `tests/fixtures/README.md` line from "(to be added in M1...)" to "(added in M1)".

- [ ] **Step 5: Commit**

```bash
git add docs/ROADMAP.md tests/fixtures/README.md
git commit -m "docs: mark M1 (storage + discovery) complete"
```

---

## Acceptance Criteria (M1 exit)

- `codebase-index index` populates `files` with repo-relative POSIX paths, content sha256, parser,
  language, and `is_generated` flag.
- Secrets (`.env`, `*.pem`, …), binaries (NUL-byte sniff), oversized files (> `max_file_bytes`), and
  built-in denylist dirs (`node_modules`, `.git`, build dirs) are **never** present in `files`.
- Layered ignore files (`.gitignore`/`.cursorignore`/`.claudeignore`/`.codeindexignore`) + config
  `extra_ignore` are honored at the project root.
- A second `index` run prunes rows for deleted files and writes fresh `meta` (`built_at`,
  `config_hash`, `head_commit`).
- `codebase-index stats` reports real file count + freshness; `--json` emits parseable output.
- DB opens with WAL + foreign keys, applies `schema.sql`, and refuses a newer `schema_version`.
- Full `pytest` suite green; `ruff` + `mypy` clean. Base install remains network-free.

## Deferred to later milestones (explicitly NOT in M1)

- Chunks, symbols, edges, FTS population (M2/M3) — `files` only here.
- Incremental hash/mtime skip + `update` command + git-status column (M2 incremental work).
- Nested (per-directory) `.gitignore` resolution — M1 reads root-level ignore files only.
- Output-time secret redaction (M4 output layer); M1 enforces index-time exclusion only.
