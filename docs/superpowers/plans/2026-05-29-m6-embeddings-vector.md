# M6 — Optional Embeddings / Vector Backend Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an **opt-in, local-first** semantic retrieval layer: embed chunks with a pluggable backend, store the vectors in a `sqlite-vec` `vec_chunks` table, and wire a vector retriever into the existing RRF fusion — so that with the `embeddings` extras installed and `embeddings.enabled = true`, paraphrased queries improve recall, while the **default disabled path is byte-for-byte unchanged**.

**Architecture:** A small `embeddings/` package defines an `EmbeddingBackend` protocol and three implementations: `noop` (disabled, the default), `local` (on-device sentence-transformers), and `external` (a network API, refused unless SECURITY.md's three gates all pass). A single factory `resolve_backend(cfg, warn=...)` applies the gating and is the only place backends are constructed. The vector store lives in the same SQLite DB via the `sqlite-vec` extension, loaded at runtime only when embeddings are enabled (`Database.enable_vectors()`); all vector SQL lives in `storage/repo.py`. The indexer embeds chunk text after the FTS/symbol pass and upserts vectors; the retrieval pipeline gains a `vector` retriever that embeds the query and KNN-searches `vec_chunks`, fused by the existing `fusion.fuse` with per-intent vector weights. Everything vector is gated behind `embeddings.enabled`; when off, no extra dependency is imported, no table is created, and no code path changes.

**Tech Stack:** Python 3.10+, stdlib `sqlite3`, Typer, Pydantic v2, pytest. **Optional extras** (never in the base install): `sqlite-vec` + `numpy` (`pip install codebase-index[embeddings]`) for the vector store; `sentence-transformers` (`[embeddings-local]`) for the local model. Builds on M1 (storage/db/discovery/pipeline), M2 (chunks/FTS/output), and **M4** (`retrieval/{types,intent,searchers,fusion,rerank,budget,pipeline}.py`, `output/{json,markdown}.py`, the wired `search`/`explain` CLI, and the `seeded_index` conftest fixture).

---

## Assumptions & Grounding (read before starting)

Verified facts about the tree this plan builds on:

- `config.Config` already has `EmbeddingsConfig` (`config.py:31-37`): `backend: Literal["noop","local","external"] = "noop"`, `enabled: bool = False`, `model: str = "all-MiniLM-L6-v2"`, `allow_external: bool = False`, `endpoint: Optional[str] = None`. `Config.config_hash()` (`config.py:56-68`) currently does **not** include embeddings — Task 1 fixes that (SCHEMA.md says toggling embeddings forces a rebuild).
- `pyproject.toml:25-33` already declares the `embeddings` extra (`numpy`, `sqlite-vec`) and `embeddings-local` extra (`sentence-transformers`). **No change to pyproject is needed.**
- `storage/db.py` exposes `Database(path)` as a context manager (`.conn`, `.open()`, `.close()`); `_apply_schema()` runs `schema.sql`. `schema.sql:107` notes `vec_chunks` is created at runtime only when enabled — i.e. **not** in the static DDL.
- `storage/repo.py` (M1/M4) holds **all** SQL: `upsert_file`, `replace_*`, `fts_search`, `path_search`, `symbol_search`, `get_meta`/`set_meta`. M6 appends the vector accessors here.
- M4's `retrieval/types.py` defines `Candidate` (with `source`, `score`, `key()`, `content`, `token_est`) and `IntentPlan.weight(source)` which returns `0.0` for any source not in `weights` — so a `vector` retriever contributes nothing unless its weight is added to the intent plans (Task 7).
- M4's `retrieval/fusion.fuse(lists, *, weights, k)` is source-agnostic and skips any source whose weight `<= 0`. `_SOURCE_RICHNESS` ranks representative richness (`symbol:3, fts:2, path:1`); Task 7 adds `vector:2`.
- M4's `retrieval/pipeline.search(conn, query, *, mode, limit, token_budget, no_fallback)` orchestrates retrievers→fuse→rerank→budget. M6 adds an optional `backend=None` parameter and a `vector` branch in `_run_retrievers`.
- M4's CLI `search` already rejects `--mode vector` with *"vector mode requires embeddings (M6); use --mode hybrid"* and exit 2 (`cli.py`). Task 10 replaces that stub with the real enabled/disabled behavior.
- M4's `seeded_index` conftest fixture inserts `files` + `chunks` (+ FTS via triggers) + `symbols`. M6 adds a `FakeEmbeddingBackend` and a vector-seeding helper to conftest (Task 11).

**Exit criteria (from ROADMAP M6):** with extras installed + enabled, semantic queries improve recall; the disabled path is unchanged. External backend gated by SECURITY.md §4 rules.

**Offline-test discipline:** the base test run must stay network-free and must not require the optional extras. Therefore:
- Backend **embedding** is tested with an injected `FakeEmbeddingBackend` (deterministic, pure-Python) — never the real model.
- The real `LocalBackend`/`ExternalBackend` embedding paths are tested behind `pytest.importorskip` / fakes, never a live model or network.
- The `sqlite-vec` **store** tests are guarded by `pytest.importorskip("sqlite_vec")`, so a machine without the extra still passes the whole "disabled path unchanged" suite.

---

## File Structure

| File | Create/Modify | Responsibility |
|---|---|---|
| `src/codebase_index/config.py` | Modify | Fold embeddings (`enabled`, `backend`, `model`) into `config_hash()` so toggling forces a rebuild. |
| `src/codebase_index/embeddings/__init__.py` | Create | Package marker. |
| `src/codebase_index/embeddings/backend.py` | Create | `EmbeddingBackend` protocol, `EmbeddingError`, `resolve_backend(cfg, warn=...)` gating factory. |
| `src/codebase_index/embeddings/noop.py` | Create | `NoopBackend` — the disabled default; `embed` raises. |
| `src/codebase_index/embeddings/local.py` | Create | `LocalBackend` — lazy sentence-transformers; clear error if the extra is missing. |
| `src/codebase_index/embeddings/external.py` | Create | `ExternalBackend` — gated network API with an injectable transport (testable, no live calls). |
| `src/codebase_index/storage/db.py` | Modify | `enable_vectors()` — load the `sqlite-vec` extension on demand. |
| `src/codebase_index/storage/repo.py` | Modify | Vector SQL: `ensure_vec_tables`, `upsert_chunk_vector`, `clear_vectors`, `vector_search`, `get_vec_meta`/`set_vec_meta`, `chunks_for_embedding`, `count_vectors`. |
| `src/codebase_index/indexer/pipeline.py` | Modify | After the build, if enabled: embed chunks + upsert vectors; add `vectors` to `BuildStats`. |
| `src/codebase_index/retrieval/intent.py` | Modify | Add `vector` weights to the per-intent plans. |
| `src/codebase_index/retrieval/fusion.py` | Modify | Add `vector` to `_SOURCE_RICHNESS`. |
| `src/codebase_index/retrieval/searchers.py` | Modify | `vector_candidates(conn, query, backend, *, limit)`. |
| `src/codebase_index/retrieval/pipeline.py` | Modify | `backend` param + `vector` retriever branch + `--mode vector`. |
| `src/codebase_index/cli.py` | Modify | Build backend for `search`/`index`; real `--mode vector`; external warning on `index`. |
| `tests/conftest.py` | Modify | `FakeEmbeddingBackend` + `seed_vectors` helper. |
| `tests/test_embeddings_backend.py` | Create | Protocol + factory gating (noop default, external refused/allowed, warning). |
| `tests/test_embeddings_local.py` | Create | Local backend missing-extra error; real embed behind `importorskip`. |
| `tests/test_embeddings_external.py` | Create | External backend with a fake transport (no network). |
| `tests/test_vectors_storage.py` | Create | `vec_chunks` round-trip + KNN (guarded by `importorskip("sqlite_vec")`). |
| `tests/test_pipeline_vectors.py` | Create | Indexer embeds + stores vectors when enabled; no-op when disabled. |
| `tests/test_vector_search.py` | Create | `vector_candidates` + pipeline vector mode + **recall improvement** acceptance. |
| `tests/test_search_cli.py` | Modify | `--mode vector` disabled message + enabled (monkeypatched backend). |

**Conventions (unchanged):** `from __future__ import annotations` at the top of every module; **all SQL lives in `storage/repo.py`**; `--json` output stays plain; the base install imports no optional dependency.

---

## Task 1: Config — embeddings participate in `config_hash`

**Files:**
- Modify: `src/codebase_index/config.py:56-68`
- Test: `tests/test_config.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_config.py` (create the file if M1 did not — the import path is stable):

```python
# tests/test_config.py  (append)
from codebase_index.config import Config


def test_config_hash_changes_when_embeddings_toggled():
    off = Config()
    on = Config()
    on.embeddings.enabled = True
    assert off.config_hash() != on.config_hash()


def test_config_hash_changes_when_embedding_model_changes():
    a = Config()
    b = Config()
    b.embeddings.model = "some-other-model"
    assert a.config_hash() != b.config_hash()


def test_config_hash_ignores_external_endpoint():
    # endpoint/allow_external do not change indexed vectors -> must not force a rebuild
    a = Config()
    b = Config()
    b.embeddings.endpoint = "https://example.test/embed"
    b.embeddings.allow_external = True
    assert a.config_hash() == b.config_hash()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_config.py -k embeddings -v`
Expected: FAIL — `test_config_hash_changes_when_embeddings_toggled` fails because `config_hash` ignores embeddings.

- [ ] **Step 3: Write minimal implementation**

In `src/codebase_index/config.py`, extend the `relevant` dict inside `config_hash()` (keep every existing key):

```python
    def config_hash(self) -> str:
        """Stable hash over indexing-relevant fields; drives rebuild decisions."""
        relevant = {
            "root": self.root,
            "languages": self.languages,
            "max_file_bytes": self.max_file_bytes,
            "ignore_files": self.ignore_files,
            "extra_ignore": self.extra_ignore,
            "chunk": self.chunk.model_dump(),
            "redaction": self.redaction,
            # M6: only the fields that change the stored vectors force a rebuild.
            # endpoint / allow_external are policy, not content -> deliberately excluded.
            "embeddings": {
                "enabled": self.embeddings.enabled,
                "backend": self.embeddings.backend,
                "model": self.embeddings.model,
            },
        }
        blob = json.dumps(relevant, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_config.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/config.py tests/test_config.py
git commit -m "feat(config): embeddings toggle/model participate in config_hash"
```

---

## Task 2: Backend protocol, errors, noop, and the gating factory

**Files:**
- Create: `src/codebase_index/embeddings/__init__.py`
- Create: `src/codebase_index/embeddings/backend.py`
- Create: `src/codebase_index/embeddings/noop.py`
- Test: `tests/test_embeddings_backend.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_embeddings_backend.py
from __future__ import annotations

import pytest

from codebase_index.config import Config
from codebase_index.embeddings.backend import (
    EmbeddingBackend,
    EmbeddingError,
    resolve_backend,
)
from codebase_index.embeddings.noop import NoopBackend


def test_default_config_resolves_to_noop():
    backend = resolve_backend(Config())
    assert isinstance(backend, NoopBackend)
    assert backend.enabled is False


def test_noop_embed_raises():
    with pytest.raises(EmbeddingError):
        NoopBackend().embed(["anything"])


def test_external_refused_without_allow_external(monkeypatch):
    monkeypatch.setenv("CBX_EMBEDDINGS_API_KEY", "sk-test")
    cfg = Config()
    cfg.embeddings.enabled = True
    cfg.embeddings.backend = "external"
    cfg.embeddings.endpoint = "https://example.test/embed"
    cfg.embeddings.allow_external = False
    with pytest.raises(EmbeddingError, match="allow_external"):
        resolve_backend(cfg)


def test_external_refused_without_api_key(monkeypatch):
    monkeypatch.delenv("CBX_EMBEDDINGS_API_KEY", raising=False)
    cfg = Config()
    cfg.embeddings.enabled = True
    cfg.embeddings.backend = "external"
    cfg.embeddings.endpoint = "https://example.test/embed"
    cfg.embeddings.allow_external = True
    with pytest.raises(EmbeddingError, match="API key"):
        resolve_backend(cfg)


def test_external_allowed_emits_warning_naming_endpoint(monkeypatch):
    monkeypatch.setenv("CBX_EMBEDDINGS_API_KEY", "sk-test")
    cfg = Config()
    cfg.embeddings.enabled = True
    cfg.embeddings.backend = "external"
    cfg.embeddings.endpoint = "https://example.test/embed"
    cfg.embeddings.allow_external = True
    warnings: list[str] = []
    backend = resolve_backend(cfg, warn=warnings.append)
    assert isinstance(backend, EmbeddingBackend)  # runtime_checkable protocol
    assert any("example.test" in w for w in warnings)


def test_disabled_config_with_local_backend_is_still_noop():
    # enabled=False overrides backend choice -> never constructs a real backend
    cfg = Config()
    cfg.embeddings.backend = "local"
    cfg.embeddings.enabled = False
    assert isinstance(resolve_backend(cfg), NoopBackend)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_embeddings_backend.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'codebase_index.embeddings'`.

- [ ] **Step 3: Write minimal implementation**

Create `src/codebase_index/embeddings/__init__.py`:

```python
"""Opt-in, local-first embedding backends. Nothing here is imported by the base
install unless embeddings are explicitly enabled (see SECURITY.md §4)."""
```

Create `src/codebase_index/embeddings/backend.py`:

```python
# src/codebase_index/embeddings/backend.py
"""Embedding backend protocol + the single gating factory.

`resolve_backend` is the ONLY place a backend is constructed. It enforces
SECURITY.md §4: external backends are refused unless `allow_external = true`,
an API key is present in the environment, AND a warning naming the endpoint is
emitted. When embeddings are disabled the factory returns a NoopBackend and
imports no optional dependency.
"""

from __future__ import annotations

import os
from typing import Callable, Protocol, runtime_checkable

API_KEY_ENV = "CBX_EMBEDDINGS_API_KEY"


class EmbeddingError(RuntimeError):
    """Raised when embeddings are misconfigured, refused, or a backend is unusable."""


@runtime_checkable
class EmbeddingBackend(Protocol):
    enabled: bool
    name: str
    dim: int

    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one vector (length == `dim`) per input text."""
        ...


def resolve_backend(cfg, warn: Callable[[str], None] = lambda _m: None) -> "EmbeddingBackend":
    """Construct the configured backend, applying all security gates."""
    emb = cfg.embeddings
    if not emb.enabled or emb.backend == "noop":
        from .noop import NoopBackend

        return NoopBackend()

    if emb.backend == "local":
        from .local import LocalBackend

        return LocalBackend(model_name=emb.model)

    if emb.backend == "external":
        if not emb.allow_external:
            raise EmbeddingError(
                "External embeddings require embeddings.allow_external = true (SECURITY.md §4)."
            )
        api_key = os.environ.get(API_KEY_ENV)
        if not api_key:
            raise EmbeddingError(
                f"External embeddings require an API key in ${API_KEY_ENV} (SECURITY.md §4)."
            )
        if not emb.endpoint:
            raise EmbeddingError("External embeddings require embeddings.endpoint to be set.")
        warn(
            f"[codebase-index] EXTERNAL EMBEDDINGS ENABLED — chunk text will be sent to "
            f"{emb.endpoint}. Disable with embeddings.backend=local|noop."
        )
        from .external import ExternalBackend

        return ExternalBackend(endpoint=emb.endpoint, api_key=api_key, model_name=emb.model)

    raise EmbeddingError(f"Unknown embeddings.backend: {emb.backend!r}")
```

Create `src/codebase_index/embeddings/noop.py`:

```python
# src/codebase_index/embeddings/noop.py
"""The disabled default backend. Present so callers never branch on None."""

from __future__ import annotations

from .backend import EmbeddingError


class NoopBackend:
    enabled = False
    name = "noop"
    dim = 0

    def embed(self, texts: list[str]) -> list[list[float]]:
        raise EmbeddingError("Embeddings are disabled (embeddings.enabled = false).")
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_embeddings_backend.py -v`
Expected: PASS (6 tests). The `external` cases reach the `from .external import ExternalBackend` line only in `test_external_allowed_emits_warning_naming_endpoint`, which is implemented in Task 4 — **run this task's tests again after Task 4** (or implement Task 4 first if you prefer). To unblock now, the refusal tests pass immediately; the "allowed" test passes once `external.py` exists.

> Sequencing note: if you run strictly task-by-task, the single "allowed" test will error on the missing `external` module until Task 4. That is expected; the four gating-refusal/noop tests are green here.

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/embeddings/__init__.py src/codebase_index/embeddings/backend.py src/codebase_index/embeddings/noop.py tests/test_embeddings_backend.py
git commit -m "feat(embeddings): backend protocol, noop default, gating factory"
```

---

## Task 3: Local backend (lazy sentence-transformers)

**Files:**
- Create: `src/codebase_index/embeddings/local.py`
- Test: `tests/test_embeddings_local.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_embeddings_local.py
from __future__ import annotations

import builtins

import pytest

from codebase_index.embeddings.backend import EmbeddingError
from codebase_index.embeddings.local import LocalBackend


def test_missing_extra_gives_actionable_error(monkeypatch):
    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "sentence_transformers" or name.startswith("sentence_transformers."):
            raise ImportError("no module")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    backend = LocalBackend(model_name="all-MiniLM-L6-v2")
    with pytest.raises(EmbeddingError, match="embeddings-local"):
        backend.embed(["hello"])


def test_real_local_embed_shape():
    st = pytest.importorskip("sentence_transformers")  # noqa: F841
    backend = LocalBackend(model_name="all-MiniLM-L6-v2")
    vecs = backend.embed(["hello world", "goodbye"])
    assert len(vecs) == 2
    assert backend.dim > 0 and all(len(v) == backend.dim for v in vecs)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_embeddings_local.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'codebase_index.embeddings.local'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/codebase_index/embeddings/local.py
"""On-device embedding via sentence-transformers. No network at query time.

The model is an OPTIONAL dependency (`pip install codebase-index[embeddings-local]`);
it is imported lazily so the base install never pulls it in. The model loads once
on first embed and is cached on the instance.
"""

from __future__ import annotations

from typing import Optional

from .backend import EmbeddingError


class LocalBackend:
    enabled = True

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        self.name = f"local:{model_name}"
        self.model_name = model_name
        self._model = None
        self._dim: Optional[int] = None

    def _load(self):
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer
            except ImportError as exc:  # optional extra not installed
                raise EmbeddingError(
                    "Local embeddings need the optional extra: "
                    "pip install codebase-index[embeddings-local]"
                ) from exc
            self._model = SentenceTransformer(self.model_name)
            self._dim = int(self._model.get_sentence_embedding_dimension())
        return self._model

    @property
    def dim(self) -> int:
        if self._dim is None:
            self._load()
        return int(self._dim or 0)

    def embed(self, texts: list[str]) -> list[list[float]]:
        model = self._load()
        vecs = model.encode(
            list(texts), convert_to_numpy=True, normalize_embeddings=True, show_progress_bar=False
        )
        return [[float(x) for x in row] for row in vecs]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_embeddings_local.py -v`
Expected: PASS — `test_missing_extra_gives_actionable_error` always runs; `test_real_local_embed_shape` runs only if `sentence_transformers` is installed, else `SKIPPED`.

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/embeddings/local.py tests/test_embeddings_local.py
git commit -m "feat(embeddings): lazy on-device sentence-transformers backend"
```

---

## Task 4: External backend (gated, injectable transport)

**Files:**
- Create: `src/codebase_index/embeddings/external.py`
- Test: `tests/test_embeddings_external.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_embeddings_external.py
from __future__ import annotations

from codebase_index.embeddings.external import ExternalBackend


def test_external_uses_injected_transport_no_network():
    calls: list[dict] = []

    def fake_transport(endpoint: str, api_key: str, model: str, texts: list[str]):
        calls.append({"endpoint": endpoint, "api_key": api_key, "model": model, "texts": texts})
        # pretend the API returns a 3-dim vector per text
        return [[0.1, 0.2, 0.3] for _ in texts]

    backend = ExternalBackend(
        endpoint="https://example.test/embed",
        api_key="sk-test",
        model_name="text-embedding-3-small",
        transport=fake_transport,
    )
    vecs = backend.embed(["a", "b"])
    assert vecs == [[0.1, 0.2, 0.3], [0.1, 0.2, 0.3]]
    assert backend.dim == 3
    assert calls and calls[0]["endpoint"] == "https://example.test/embed"
    assert calls[0]["api_key"] == "sk-test"  # forwarded, never logged
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_embeddings_external.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'codebase_index.embeddings.external'`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/codebase_index/embeddings/external.py
"""External embedding API backend. Constructed ONLY via resolve_backend after the
SECURITY.md §4 gates pass. The network call is isolated in a transport callable so
it can be tested without hitting the network and swapped per provider.
"""

from __future__ import annotations

import json
from typing import Callable, Optional
from urllib.request import Request, urlopen

from .backend import EmbeddingError

# (endpoint, api_key, model, texts) -> list[vector]
Transport = Callable[[str, str, str, list[str]], list[list[float]]]


def _http_transport(endpoint: str, api_key: str, model: str, texts: list[str]) -> list[list[float]]:
    body = json.dumps({"model": model, "input": texts}).encode("utf-8")
    req = Request(
        endpoint,
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=30) as resp:  # noqa: S310 - endpoint is user-configured + gated
        payload = json.loads(resp.read().decode("utf-8"))
    # OpenAI-compatible shape: {"data": [{"embedding": [...]}, ...]}
    return [item["embedding"] for item in payload["data"]]


class ExternalBackend:
    enabled = True

    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str,
        model_name: str,
        transport: Optional[Transport] = None,
    ) -> None:
        self.name = f"external:{model_name}"
        self.model_name = model_name
        self._endpoint = endpoint
        self._api_key = api_key
        self._transport = transport or _http_transport
        self._dim: Optional[int] = None

    @property
    def dim(self) -> int:
        if self._dim is None:
            raise EmbeddingError("External backend dim is unknown until the first embed() call.")
        return self._dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vecs = self._transport(self._endpoint, self._api_key, self.model_name, list(texts))
        if not vecs or not vecs[0]:
            raise EmbeddingError("External embedding endpoint returned no vectors.")
        self._dim = len(vecs[0])
        return [[float(x) for x in v] for v in vecs]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_embeddings_external.py tests/test_embeddings_backend.py -v`
Expected: PASS — both the external transport test and the previously-pending `test_external_allowed_emits_warning_naming_endpoint` from Task 2 now pass.

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/embeddings/external.py tests/test_embeddings_external.py
git commit -m "feat(embeddings): gated external backend with injectable transport"
```

---

## Task 5: Vector store — extension loading + `vec_chunks` accessors

**Files:**
- Modify: `src/codebase_index/storage/db.py`
- Modify: `src/codebase_index/storage/repo.py`
- Test: `tests/test_vectors_storage.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_vectors_storage.py
from __future__ import annotations

import pytest

from codebase_index.storage import repo
from codebase_index.storage.db import Database

pytest.importorskip("sqlite_vec")  # skip the whole module without the optional extra


def _file_and_chunk(conn, path: str, content: str) -> int:
    fid = repo.upsert_file(
        conn, path=path, lang="python", size_bytes=1, sha256=path, mtime_ns=1,
        git_status=None, parser="treesitter", indexed_at="t", is_generated=False,
    )
    conn.execute(
        "INSERT INTO chunks (file_id, line_start, line_end, kind, symbol_id, content, token_est) "
        "VALUES (?,?,?,?,NULL,?,?)",
        (fid, 1, 3, "window", content, 5),
    )
    return int(conn.execute("SELECT last_insert_rowid()").fetchone()[0])


def test_vector_roundtrip_and_knn(tmp_path):
    db = Database(tmp_path / "index.sqlite").open()
    db.enable_vectors()
    repo.ensure_vec_tables(db.conn, dim=3)
    repo.set_vec_meta(db.conn, model="fake", dim=3, built_at="t")

    c_auth = _file_and_chunk(db.conn, "src/auth/token.py", "refresh access token")
    c_user = _file_and_chunk(db.conn, "src/models/user.py", "user profile name")
    repo.upsert_chunk_vector(db.conn, c_auth, [1.0, 0.0, 0.0])
    repo.upsert_chunk_vector(db.conn, c_user, [0.0, 1.0, 0.0])
    db.conn.commit()

    assert repo.count_vectors(db.conn) == 2
    meta = repo.get_vec_meta(db.conn)
    assert meta["model"] == "fake" and meta["dim"] == 3

    # query near the auth vector -> auth chunk is nearest
    rows = repo.vector_search(db.conn, [0.9, 0.1, 0.0], limit=2)
    assert rows[0]["path"] == "src/auth/token.py"
    assert rows[0]["chunk_id"] == c_auth
    assert "content" in rows[0].keys() and rows[0]["line_start"] == 1

    # clear removes vectors but leaves chunks intact
    repo.clear_vectors(db.conn)
    assert repo.count_vectors(db.conn) == 0
    assert db.conn.execute("SELECT COUNT(*) FROM chunks").fetchone()[0] == 2
    db.close()


def test_chunks_for_embedding_lists_content(tmp_path):
    db = Database(tmp_path / "index.sqlite").open()
    cid = _file_and_chunk(db.conn, "a.py", "hello body")
    rows = repo.chunks_for_embedding(db.conn)
    assert any(r["id"] == cid and r["content"] == "hello body" for r in rows)
    db.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_vectors_storage.py -v`
Expected: FAIL — `AttributeError: 'Database' object has no attribute 'enable_vectors'` (or module-skipped if the extra is absent — install it with `pip install -e .[embeddings]` to exercise this task).

- [ ] **Step 3: Write minimal implementation**

In `src/codebase_index/storage/db.py`, add the method and import guard:

```python
# src/codebase_index/storage/db.py  — add to the Database class
    def enable_vectors(self) -> None:
        """Load the sqlite-vec extension into this connection (optional extra)."""
        try:
            import sqlite_vec
        except ImportError as exc:
            raise RuntimeError(
                "Vector search needs the optional extra: pip install codebase-index[embeddings]"
            ) from exc
        self.conn.enable_load_extension(True)
        sqlite_vec.load(self.conn)
        self.conn.enable_load_extension(False)
```

Append to `src/codebase_index/storage/repo.py` (vector accessors; `sqlite_vec` is only imported here, lazily):

```python
# src/codebase_index/storage/repo.py  (append — vector store; requires enable_vectors())

def ensure_vec_tables(conn: sqlite3.Connection, *, dim: int) -> None:
    """Create vec_chunks (sqlite-vec) + vec_meta if absent. dim is fixed per build."""
    dim = int(dim)
    conn.execute(
        f"CREATE VIRTUAL TABLE IF NOT EXISTS vec_chunks USING vec0("
        f"chunk_id INTEGER PRIMARY KEY, embedding FLOAT[{dim}])"
    )
    conn.execute("CREATE TABLE IF NOT EXISTS vec_meta (model TEXT, dim INTEGER, built_at TEXT)")


def set_vec_meta(conn: sqlite3.Connection, *, model: str, dim: int, built_at: str) -> None:
    conn.execute("DELETE FROM vec_meta")
    conn.execute(
        "INSERT INTO vec_meta (model, dim, built_at) VALUES (?,?,?)", (model, int(dim), built_at)
    )


def get_vec_meta(conn: sqlite3.Connection) -> "Optional[sqlite3.Row]":
    return conn.execute("SELECT model, dim, built_at FROM vec_meta LIMIT 1").fetchone()


def chunks_for_embedding(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT id, content FROM chunks ORDER BY id").fetchall()


def upsert_chunk_vector(
    conn: sqlite3.Connection, chunk_id: int, embedding: list[float]
) -> None:
    import sqlite_vec

    conn.execute(
        "INSERT INTO vec_chunks (chunk_id, embedding) VALUES (?, ?) "
        "ON CONFLICT(chunk_id) DO UPDATE SET embedding = excluded.embedding",
        (int(chunk_id), sqlite_vec.serialize_float32(embedding)),
    )


def clear_vectors(conn: sqlite3.Connection) -> None:
    conn.execute("DELETE FROM vec_chunks")


def count_vectors(conn: sqlite3.Connection) -> int:
    return int(conn.execute("SELECT COUNT(*) FROM vec_chunks").fetchone()[0])


def vector_search(
    conn: sqlite3.Connection, query_embedding: list[float], *, limit: int
) -> list[sqlite3.Row]:
    """KNN over vec_chunks; joins back to chunks/files for a uniform result row."""
    import sqlite_vec

    return conn.execute(
        "SELECT v.chunk_id AS chunk_id, v.distance AS distance, f.path AS path, "
        "       c.line_start AS line_start, c.line_end AS line_end, "
        "       c.content AS content, c.token_est AS token_est "
        "FROM vec_chunks v "
        "JOIN chunks c ON c.id = v.chunk_id "
        "JOIN files f ON f.id = c.file_id "
        "WHERE v.embedding MATCH ? AND k = ? "
        "ORDER BY v.distance",
        (sqlite_vec.serialize_float32(query_embedding), int(limit)),
    ).fetchall()
```

> `Optional` is already imported in `repo.py` (M4 added `from typing import Optional`); if not, add it.
> **sqlite-vec KNN syntax:** modern `vec0` requires the `k = ?` constraint shown above. If the installed `sqlite-vec` rejects `AND k = ?`, switch to `... WHERE v.embedding MATCH ? ORDER BY v.distance LIMIT ?` — verify against the installed version with `SELECT vec_version();`.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_vectors_storage.py -v` (after `pip install -e .[embeddings]`)
Expected: PASS (2 tests). Without the extra installed: the module is SKIPPED — that is acceptable for the base suite.

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/storage/db.py src/codebase_index/storage/repo.py tests/test_vectors_storage.py
git commit -m "feat(storage): sqlite-vec vector store (load, upsert, KNN, meta)"
```

---

## Task 6: Indexer — embed chunks + store vectors when enabled

**Files:**
- Modify: `src/codebase_index/indexer/pipeline.py`
- Modify: `tests/conftest.py` (add `FakeEmbeddingBackend`)
- Test: `tests/test_pipeline_vectors.py`

- [ ] **Step 1: Add the `FakeEmbeddingBackend` to conftest**

Append to `tests/conftest.py`:

```python
# tests/conftest.py  (append) — deterministic, pure-Python embeddings for tests.
# Concept dims let us simulate semantics offline: synonyms map to the same dim so
# a paraphrased query lands near the right chunk WITHOUT lexical overlap.
_CONCEPTS = ["auth", "user", "db", "http"]
_KEYWORDS = {
    "auth": ["auth", "token", "refresh", "access", "credential", "credentials", "renew", "login"],
    "user": ["user", "profile", "account", "person", "member"],
    "db": ["db", "database", "query", "sql", "store", "persist"],
    "http": ["http", "request", "endpoint", "route", "api", "url"],
}


class FakeEmbeddingBackend:
    enabled = True
    name = "fake"
    dim = len(_CONCEPTS)

    def embed(self, texts: list[str]) -> list[list[float]]:
        out: list[list[float]] = []
        for text in texts:
            low = text.lower()
            vec = [0.0] * len(_CONCEPTS)
            for i, concept in enumerate(_CONCEPTS):
                if any(kw in low for kw in _KEYWORDS[concept]):
                    vec[i] = 1.0
            if not any(vec):
                vec[0] = 0.01  # avoid an all-zero vector
            out.append(vec)
        return out


@pytest.fixture
def fake_backend() -> FakeEmbeddingBackend:
    return FakeEmbeddingBackend()
```

- [ ] **Step 2: Write the failing test**

```python
# tests/test_pipeline_vectors.py
from __future__ import annotations

import pytest

from codebase_index.config import Config
from codebase_index.indexer.pipeline import build_index
from codebase_index.storage import repo
from codebase_index.storage.db import Database

pytest.importorskip("sqlite_vec")


def test_index_disabled_creates_no_vectors(sample_repo, tmp_path):
    cfg = Config()
    cfg.root = str(sample_repo)
    # embeddings off (default) -> no vec table, no vectors, vectors stat == 0
    db = Database(tmp_path / "index.sqlite").open()
    stats = build_index(cfg, db, root=sample_repo)
    assert stats.vectors == 0
    tbl = db.conn.execute(
        "SELECT name FROM sqlite_master WHERE name = 'vec_chunks'"
    ).fetchone()
    assert tbl is None  # disabled path must not create the table
    db.close()


def test_index_enabled_embeds_and_stores(sample_repo, tmp_path, fake_backend, monkeypatch):
    import codebase_index.indexer.pipeline as pipe

    monkeypatch.setattr(pipe, "resolve_backend", lambda cfg, warn=None: fake_backend)
    cfg = Config()
    cfg.root = str(sample_repo)
    cfg.embeddings.enabled = True
    cfg.embeddings.backend = "local"
    db = Database(tmp_path / "index.sqlite").open()
    stats = build_index(cfg, db, root=sample_repo)

    assert stats.vectors > 0
    assert repo.count_vectors(db.conn) == stats.vectors
    meta = repo.get_vec_meta(db.conn)
    assert meta["dim"] == fake_backend.dim
    db.close()


def test_reindex_vectors_idempotent(sample_repo, tmp_path, fake_backend, monkeypatch):
    import codebase_index.indexer.pipeline as pipe

    monkeypatch.setattr(pipe, "resolve_backend", lambda cfg, warn=None: fake_backend)
    cfg = Config()
    cfg.root = str(sample_repo)
    cfg.embeddings.enabled = True
    db = Database(tmp_path / "index.sqlite").open()
    s1 = build_index(cfg, db, root=sample_repo)
    s2 = build_index(cfg, db, root=sample_repo)
    assert s1.vectors == s2.vectors
    db.close()
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest tests/test_pipeline_vectors.py -v`
Expected: FAIL — `AttributeError: 'BuildStats' object has no attribute 'vectors'`.

- [ ] **Step 4: Write minimal implementation**

In `src/codebase_index/indexer/pipeline.py`, add the import and the field, then run the embedding pass after the build (and after the M5 graph pass if present), before the final commit:

```python
# src/codebase_index/indexer/pipeline.py  — add import
from ..embeddings.backend import resolve_backend
from ..storage import repo as _repo
```

Add `vectors` to `BuildStats` (keep existing fields):

```python
@dataclass
class BuildStats:
    indexed: int = 0
    deleted: int = 0
    total_bytes: int = 0
    chunks: int = 0
    symbols: int = 0
    edges: int = 0
    edges_resolved: int = 0   # present if M5 landed; keep if so
    vectors: int = 0
```

Add the embedding pass as a helper and call it once after the walk loop:

```python
# src/codebase_index/indexer/pipeline.py  — add helper

def _embed_chunks(cfg, db, conn) -> int:
    """Embed every chunk and (re)store its vector. Returns the vector count.

    Fully gated: with embeddings disabled this is never called, so no optional
    dependency is imported and vec_chunks is never created.
    """
    backend = resolve_backend(cfg, warn=lambda m: print(m))
    if not getattr(backend, "enabled", False):
        return 0
    rows = _repo.chunks_for_embedding(conn)
    if not rows:
        return 0
    db.enable_vectors()
    texts = [r["content"] for r in rows]
    vectors = backend.embed(texts)
    _repo.ensure_vec_tables(conn, dim=backend.dim)
    _repo.clear_vectors(conn)  # full rebuild keeps reindex deterministic
    for row, vec in zip(rows, vectors):
        _repo.upsert_chunk_vector(conn, int(row["id"]), vec)
    from datetime import datetime, timezone

    built_at = datetime.now(timezone.utc).isoformat()
    _repo.set_vec_meta(conn, model=backend.name, dim=backend.dim, built_at=built_at)
    return len(rows)
```

Then, where `build_index` finishes (after chunks/symbols/edges are written, before the final `conn.commit()`):

```python
    # M6: optional semantic layer. No-op + zero new deps when embeddings are off.
    if cfg.embeddings.enabled:
        stats.vectors = _embed_chunks(cfg, db, conn)
```

> The test monkeypatches `resolve_backend` in the `pipeline` module namespace, so import it as a module-level name (`from ..embeddings.backend import resolve_backend`) rather than calling it via the package path.

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_pipeline_vectors.py -v`
Expected: PASS (3 tests). Run `pytest tests/test_pipeline.py -v` too — the disabled-by-default pipeline tests must remain green and unchanged.

- [ ] **Step 6: Commit**

```bash
git add src/codebase_index/indexer/pipeline.py tests/conftest.py tests/test_pipeline_vectors.py
git commit -m "feat(indexer): embed + store chunk vectors when embeddings enabled"
```

---

## Task 7: Intent vector weights + fusion richness

**Files:**
- Modify: `src/codebase_index/retrieval/intent.py`
- Modify: `src/codebase_index/retrieval/fusion.py`
- Test: `tests/test_intent.py` (append), `tests/test_fusion.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_intent.py`:

```python
# tests/test_intent.py  (append)
from codebase_index.retrieval.intent import detect_intent


def test_semantic_intents_have_vector_weight():
    # how_it_works / keyword / data_flow benefit from semantic recall (RETRIEVAL.md §1)
    for q in ["how does token refresh work", "leftpad", "trace data flow of refresh_token"]:
        assert detect_intent(q).weight("vector") > 0.0


def test_locate_impl_still_favors_symbol_over_vector():
    plan = detect_intent("where is refresh_access_token implemented")
    assert plan.weight("symbol") > plan.weight("vector")
```

Append to `tests/test_fusion.py`:

```python
# tests/test_fusion.py  (append)
def test_vector_source_participates_in_fusion():
    from codebase_index.retrieval.fusion import fuse
    from codebase_index.retrieval.types import Candidate

    vec = [Candidate(path="v.py", line_start=1, line_end=2, source="vector", score=0.9)]
    fused = fuse({"vector": vec}, weights={"vector": 1.0}, k=60)
    assert fused and fused[0].path == "v.py"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_intent.py -k vector tests/test_fusion.py -k vector -v`
Expected: FAIL — `test_semantic_intents_have_vector_weight` fails (`weight("vector")` is 0.0 everywhere).

- [ ] **Step 3: Write minimal implementation**

In `src/codebase_index/retrieval/intent.py`, add a `vector` weight to the relevant plans (leave the other weights and budgets exactly as M4 set them — only add the `"vector": ...` entries shown):

```python
# src/codebase_index/retrieval/intent.py  — add vector weights to _PLANS
_PLANS: dict[Intent, IntentPlan] = {
    Intent.LOCATE_IMPL: IntentPlan(Intent.LOCATE_IMPL, {"symbol": 1.0, "path": 0.7, "fts": 0.4, "vector": 0.2}, 1500),
    Intent.HOW_IT_WORKS: IntentPlan(Intent.HOW_IT_WORKS, {"fts": 1.0, "symbol": 0.7, "path": 0.3, "vector": 0.8}, 2200, graph_strategy="down"),
    Intent.IMPACT: IntentPlan(Intent.IMPACT, {"symbol": 1.0, "path": 0.6, "fts": 0.3, "vector": 0.3}, 1800, graph_strategy="up"),
    Intent.FIND_REFS: IntentPlan(Intent.FIND_REFS, {"symbol": 1.0, "fts": 0.3, "path": 0.2, "vector": 0.2}, 1500, graph_strategy="refs"),
    Intent.DATA_FLOW: IntentPlan(Intent.DATA_FLOW, {"symbol": 0.9, "fts": 0.8, "path": 0.3, "vector": 0.6}, 2000, graph_strategy="both"),
    Intent.DEBUG_ERROR: IntentPlan(Intent.DEBUG_ERROR, {"fts": 1.0, "symbol": 0.6, "path": 0.3, "vector": 0.4}, 1800),
    Intent.ARCHITECTURE: IntentPlan(Intent.ARCHITECTURE, {"fts": 0.6, "symbol": 0.4, "path": 0.5, "vector": 0.5}, 2500, summaries_first=True),
    Intent.KEYWORD: IntentPlan(Intent.KEYWORD, {"fts": 1.0, "symbol": 0.6, "path": 0.5, "vector": 0.7}, 1500),
}
```

In `src/codebase_index/retrieval/fusion.py`, add `vector` to the richness map:

```python
# src/codebase_index/retrieval/fusion.py  — extend richness
_SOURCE_RICHNESS = {"symbol": 3, "fts": 2, "vector": 2, "path": 1}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_intent.py tests/test_fusion.py -v`
Expected: PASS (all M4 cases + the new ones).

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/retrieval/intent.py src/codebase_index/retrieval/fusion.py tests/test_intent.py tests/test_fusion.py
git commit -m "feat(retrieval): per-intent vector weights + fusion richness"
```

---

## Task 8: Vector retriever — `vector_candidates`

**Files:**
- Modify: `src/codebase_index/retrieval/searchers.py`
- Test: `tests/test_vector_search.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_vector_search.py
from __future__ import annotations

import pytest

from codebase_index.storage import repo
from codebase_index.storage.db import Database

pytest.importorskip("sqlite_vec")


def _seed_vectors(conn, backend):
    """Embed each chunk's content with the fake backend and store it."""
    rows = repo.chunks_for_embedding(conn)
    vecs = backend.embed([r["content"] for r in rows])
    repo.ensure_vec_tables(conn, dim=backend.dim)
    for r, v in zip(rows, vecs):
        repo.upsert_chunk_vector(conn, int(r["id"]), v)
    conn.commit()


def test_vector_candidates_uniform_shape(seeded_index, fake_backend):
    db = seeded_index
    db.enable_vectors()
    _seed_vectors(db.conn, fake_backend)

    from codebase_index.retrieval.searchers import vector_candidates

    cands = vector_candidates(db.conn, "refresh access token", fake_backend, limit=5)
    assert cands and all(c.source == "vector" for c in cands)
    assert cands[0].path == "src/auth/token.py"
    assert all(c.content is not None and c.token_est > 0 for c in cands)


def test_vector_candidates_paraphrase_recall(seeded_index, fake_backend):
    # "renew login credentials" shares NO lexical token with "refresh access token"
    # but the fake backend maps both to the `auth` concept -> vector recalls it.
    db = seeded_index
    db.enable_vectors()
    _seed_vectors(db.conn, fake_backend)

    from codebase_index.retrieval.searchers import vector_candidates

    cands = vector_candidates(db.conn, "renew login credentials", fake_backend, limit=5)
    assert any(c.path == "src/auth/token.py" for c in cands)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_vector_search.py -v`
Expected: FAIL — `ImportError: cannot import name 'vector_candidates' from ...searchers`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/codebase_index/retrieval/searchers.py`:

```python
# src/codebase_index/retrieval/searchers.py  (append)

def vector_candidates(
    conn: sqlite3.Connection, query: str, backend, *, limit: int
) -> list[Candidate]:
    """Semantic retriever: embed the query, KNN over vec_chunks.

    `backend` must be an enabled EmbeddingBackend; callers pass None/Noop when
    embeddings are disabled and simply skip this retriever. sqlite-vec `distance`
    is smaller-is-better, so the candidate score negates it for "higher is better".
    """
    if backend is None or not getattr(backend, "enabled", False):
        return []
    query = query.strip()
    if not query:
        return []
    vec = backend.embed([query])[0]
    out: list[Candidate] = []
    for row in repo.vector_search(conn, vec, limit=limit):
        out.append(
            Candidate(
                path=row["path"],
                line_start=row["line_start"],
                line_end=row["line_end"],
                source="vector",
                score=-float(row["distance"]),
                content=row["content"],
                token_est=int(row["token_est"]),
            )
        )
    return out
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_vector_search.py -k vector_candidates -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/retrieval/searchers.py tests/test_vector_search.py
git commit -m "feat(retrieval): vector retriever over sqlite-vec KNN"
```

---

## Task 9: Pipeline — wire the vector retriever + `--mode vector`

**Files:**
- Modify: `src/codebase_index/retrieval/pipeline.py`
- Test: `tests/test_vector_search.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `tests/test_vector_search.py`:

```python
# tests/test_vector_search.py  (append)
def test_pipeline_vector_mode_uses_backend(seeded_index, fake_backend):
    from codebase_index.retrieval.pipeline import search

    db = seeded_index
    db.enable_vectors()
    _seed_vectors(db.conn, fake_backend)

    payload = search(
        db.conn, "renew login credentials", mode="vector", limit=10,
        token_budget=1500, no_fallback=True, backend=fake_backend,
    )
    assert payload["mode"] == "vector"
    assert any(r["path"] == "src/auth/token.py" for r in payload["results"])


def test_pipeline_hybrid_includes_vector_when_backend_present(seeded_index, fake_backend):
    from codebase_index.retrieval.pipeline import search

    db = seeded_index
    db.enable_vectors()
    _seed_vectors(db.conn, fake_backend)

    payload = search(
        db.conn, "how does token refresh work", mode="hybrid", limit=10,
        token_budget=1500, no_fallback=True, backend=fake_backend,
    )
    assert payload["results"]


def test_pipeline_hybrid_without_backend_unchanged(seeded_index):
    # backend=None must behave exactly like M4 (no vector retriever)
    from codebase_index.retrieval.pipeline import search

    payload = search(
        seeded_index.conn, "token", mode="hybrid", limit=10,
        token_budget=1500, no_fallback=True,
    )
    assert payload["mode"] == "hybrid" and payload["results"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_vector_search.py -k pipeline -v`
Expected: FAIL — `TypeError: search() got an unexpected keyword argument 'backend'`.

- [ ] **Step 3: Write minimal implementation**

In `src/codebase_index/retrieval/pipeline.py`, thread an optional `backend` through. Update `_run_retrievers` and `search`:

```python
# src/codebase_index/retrieval/pipeline.py  — update _run_retrievers signature + body
def _run_retrievers(conn, query, *, mode, limit, weights, backend=None):
    lists = {}
    if mode in ("hybrid", "fts"):
        lists["fts"] = searchers.fts_candidates(conn, query, limit=limit)
    if mode in ("hybrid", "symbol"):
        lists["symbol"] = searchers.symbol_candidates(conn, query, limit=limit)
    if mode == "hybrid":
        lists["path"] = searchers.path_candidates(conn, query, limit=limit)
    if mode in ("hybrid", "vector") and backend is not None and getattr(backend, "enabled", False):
        lists["vector"] = searchers.vector_candidates(conn, query, backend, limit=limit)
    # single-mode: force that source's weight to 1.0
    if mode != "hybrid":
        weights = {mode: 1.0}
    return lists, weights
```

```python
# src/codebase_index/retrieval/pipeline.py  — add backend param to search()
def search(
    conn: sqlite3.Connection,
    query: str,
    *,
    mode: str,
    limit: int,
    token_budget: int,
    no_fallback: bool,
    backend=None,
) -> dict:
    plan = detect_intent(query)
    lists, weights = _run_retrievers(
        conn, query, mode=mode, limit=limit, weights=plan.weights, backend=backend
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

Run: `pytest tests/test_vector_search.py -v` and `pytest tests/test_pipeline_search.py -v`
Expected: PASS — new vector-mode tests pass; M4 pipeline tests (called without `backend`) still pass because the parameter defaults to `None`.

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/retrieval/pipeline.py tests/test_vector_search.py
git commit -m "feat(retrieval): wire optional vector retriever + vector mode"
```

---

## Task 10: CLI — real `--mode vector`, build backend, external warning

**Files:**
- Modify: `src/codebase_index/cli.py`
- Modify: `tests/test_search_cli.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_search_cli.py`:

```python
# tests/test_search_cli.py  (append)
def test_vector_mode_disabled_is_clear(tmp_path, monkeypatch):
    db_path = _build(tmp_path, monkeypatch)  # builds with embeddings off (default)
    monkeypatch.setenv("CBX_DB_PATH", str(db_path))
    result = runner.invoke(app, ["search", "token", "--mode", "vector"])
    assert result.exit_code == 2
    assert "embeddings" in result.output.lower()


def test_vector_mode_enabled_runs(tmp_path, monkeypatch):
    pytest.importorskip("sqlite_vec")
    import codebase_index.cli as cli_mod
    from tests.conftest import FakeEmbeddingBackend

    # Build an index WITH vectors using the fake backend.
    from codebase_index.config import Config
    from codebase_index.indexer.pipeline import build_index
    from codebase_index.storage.db import Database
    from tests.conftest import FIXTURE_ROOT  # type: ignore
    import codebase_index.indexer.pipeline as pipe

    fake = FakeEmbeddingBackend()
    monkeypatch.setattr(pipe, "resolve_backend", lambda cfg, warn=None: fake)
    cfg = Config(root=str(FIXTURE_ROOT))
    cfg.embeddings.enabled = True
    db_path = tmp_path / "index.sqlite"
    with Database(db_path) as db:
        build_index(cfg, db, root=FIXTURE_ROOT)

    # CLI search should resolve a (fake) backend and run vector mode.
    monkeypatch.setenv("CBX_DB_PATH", str(db_path))
    monkeypatch.setattr(cli_mod, "_resolve_backend_for_search", lambda ctx: fake)
    result = runner.invoke(app, ["search", "renew credentials", "--mode", "vector", "--json"])
    assert result.exit_code == 0, result.output
    import json as _json
    payload = _json.loads(result.stdout)
    assert payload["mode"] == "vector"
```

> The test patches a small helper `_resolve_backend_for_search(ctx)` so the CLI can be driven without installing a real model. Implement that helper in Step 3.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_search_cli.py -k vector -v`
Expected: FAIL — `test_vector_mode_enabled_runs` fails: `--mode vector` still exits 2 unconditionally (M4 stub).

- [ ] **Step 3: Write minimal implementation**

In `src/codebase_index/cli.py`, add a backend resolver near `_resolve_db_path`:

```python
# src/codebase_index/cli.py  — add helper
def _resolve_backend_for_search(ctx: "typer.Context"):
    """Resolve an embedding backend from config for query-time vector search.

    Returns a NoopBackend (enabled=False) when embeddings are off, so callers can
    branch on `backend.enabled`. Network/external gating is enforced by
    resolve_backend (SECURITY.md §4).
    """
    from .config import load
    from .embeddings.backend import resolve_backend

    cfg = load(ctx.obj.get("root") if ctx.obj else None)
    return resolve_backend(cfg, warn=lambda m: typer.echo(m, err=True))
```

Replace the `search` body's vector handling. Where M4 had:

```python
    if mode == "vector":
        typer.echo("[codebase-index] vector mode requires embeddings (M6); use --mode hybrid.")
        raise typer.Exit(code=2)
```

substitute backend resolution + pass-through:

```python
    backend = None
    if mode in ("vector", "hybrid"):
        backend = _resolve_backend_for_search(ctx)
        if mode == "vector" and not getattr(backend, "enabled", False):
            typer.echo(
                "[codebase-index] vector mode needs embeddings.enabled = true and the "
                "[embeddings] extra. Use --mode hybrid or enable embeddings."
            )
            raise typer.Exit(code=2)
        if backend is not None and getattr(backend, "enabled", False):
            # the query-time connection must have the extension loaded
            pass  # extension loaded on the Database below
```

Then, in the `with Database(db_path) as db:` block, enable vectors when a backend is active and forward it:

```python
    with Database(db_path) as db:
        if backend is not None and getattr(backend, "enabled", False):
            db.enable_vectors()
        payload = run_search(
            db.conn, query, mode=mode, limit=limit,
            token_budget=token_budget, no_fallback=no_fallback, backend=backend,
        )
```

Finally, make `index` surface the external-embeddings warning by resolving the backend through the warning sink (the indexer already calls `resolve_backend` with a `print` warn; ensure the `index` command does not swallow stdout). No code change is required in `index` beyond what Task 6 added — confirm the warning prints by the manual smoke in Task 12.

> If the M4 `search` body does not already accept `backend` on `run_search`, that was added in Task 9. Keep the `want_json`/renderer tail exactly as M4 wrote it.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_search_cli.py -v`
Expected: PASS — disabled message (exit 2) and enabled vector run (exit 0, `mode == "vector"`); the enabled test SKIPS without the `sqlite_vec` extra.

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/cli.py tests/test_search_cli.py
git commit -m "feat(cli): real vector mode + backend resolution + external warning"
```

---

## Task 11: Acceptance — semantic recall improves; disabled path unchanged

**Files:**
- Test: `tests/test_vector_search.py` (append the acceptance gate)

This is the milestone exit gate. No new production code unless it exposes a regression.

- [ ] **Step 1: Write the failing/diagnostic test**

Append to `tests/test_vector_search.py`:

```python
# tests/test_vector_search.py  (append) — milestone exit gate

def _has(payload, path) -> bool:
    return any(r["path"] == path for r in payload["results"])


def test_vector_improves_recall_over_lexical_only(seeded_index, fake_backend):
    """A paraphrase with no shared tokens: hybrid+vector recalls the auth chunk
    where lexical-only (FTS) does not."""
    from codebase_index.retrieval.pipeline import search

    db = seeded_index
    db.enable_vectors()
    _seed_vectors(db.conn, fake_backend)

    query = "renew login credentials"  # shares no token with "refresh access token"
    common = dict(limit=10, token_budget=1500, no_fallback=True)

    lexical = search(db.conn, query, mode="fts", **common)
    semantic = search(db.conn, query, mode="hybrid", backend=fake_backend, **common)

    target = "src/auth/token.py"
    assert not _has(lexical, target)   # FTS alone misses the paraphrase
    assert _has(semantic, target)      # vector recall surfaces it


def test_disabled_pipeline_identical_to_m4(seeded_index):
    """With no backend, hybrid output is exactly M4's (vector never contributes)."""
    from codebase_index.retrieval.pipeline import search

    common = dict(mode="hybrid", limit=10, token_budget=1500, no_fallback=True)
    a = search(seeded_index.conn, "where is refresh_access_token implemented", **common)
    b = search(
        seeded_index.conn, "where is refresh_access_token implemented",
        backend=None, **common,
    )
    assert a == b
```

- [ ] **Step 2: Run the gate**

Run: `pytest tests/test_vector_search.py -k "recall or disabled" -v`
Expected: PASS. If `test_vector_improves_recall_over_lexical_only` fails because the auth chunk still surfaces under FTS, the decoy/seed content shares a token — adjust the **fixture query** to a stricter paraphrase (e.g. "renew login credentials"), not the production weights. If it fails because hybrid misses the target, raise the `KEYWORD`/`HOW_IT_WORKS` vector weight in `intent.py` by 0.1 and re-run (do not lower FTS).

- [ ] **Step 3: Run the full suite (extras installed)**

Run: `pip install -e .[embeddings] && pytest -v`
Expected: all M0–M6 tests PASS, including the `sqlite_vec`-guarded ones.

- [ ] **Step 4: Run the full suite (NO extras — disabled-path guarantee)**

Run (in a venv without the extras): `pytest -v`
Expected: all tests PASS; the vector-store / vector-search modules report SKIPPED, never FAIL. This proves the base install is unaffected.

- [ ] **Step 5: Commit**

```bash
git add tests/test_vector_search.py
git commit -m "test(retrieval): acceptance — vector recall up, disabled path unchanged"
```

---

## Task 12: Lint, manual smoke, docs

**Files:**
- Modify: `docs/ROADMAP.md` (mark M6 done)
- Modify: `docs/SCHEMA.md` (note `vec_chunks` runtime creation already documented — confirm `vec_meta` columns match)

- [ ] **Step 1: Lint + type-check**

Run: `ruff check src tests` and `mypy src/codebase_index`
Expected: clean. (`urllib`/`sqlite_vec`/`sentence_transformers` are lazily imported; mypy should not require the optional stubs — add `# type: ignore[import-not-found]` on the lazy imports if mypy complains about the optional extras.)

- [ ] **Step 2: Manual smoke — disabled (default) path**

```bash
pip install -e .
codebase-index --root . index            # no embeddings, no extra deps
codebase-index --root . search "where is build_index implemented"
codebase-index --root . search "token" --mode vector   # -> clear "needs embeddings" message, exit 2
```

Expected: index/search behave exactly as M4; vector mode is politely refused.

- [ ] **Step 3: Manual smoke — enabled (local) path**

```bash
pip install -e .[embeddings,embeddings-local]
# enable in config:
#   .claude/cache/codebase-index/config.json  ->  {"embeddings": {"enabled": true, "backend": "local"}}
codebase-index --root . index             # embeds chunks; prints vector count in stats
codebase-index --root . search "renew authentication credentials" --mode vector
codebase-index --root . search "how does token refresh work"      # hybrid now includes vector
codebase-index --root . stats             # shows vectors built
```

Expected: vector mode returns semantically-relevant results; hybrid recall on paraphrases improves vs. the disabled run. (First `index` downloads the model once — user-initiated, per SECURITY.md §4.)

- [ ] **Step 4: Update docs**

Edit `docs/ROADMAP.md`:
- Change the M6 heading to `## M6 — Optional embeddings / vector backend ✅`.
- Append under it: *"Shipped: `embeddings/` package (protocol + noop default + lazy local + gated external), `sqlite-vec` `vec_chunks` store loaded on demand, indexer embedding pass behind `embeddings.enabled`, and a vector retriever fused into hybrid with per-intent weights. External backend refused unless `allow_external` + `$CBX_EMBEDDINGS_API_KEY` + an endpoint warning (SECURITY.md §4). Disabled path imports no optional dep and is byte-for-byte unchanged."*

Confirm `docs/SCHEMA.md` §"Optional vector table" matches the implemented `vec_chunks(chunk_id, embedding FLOAT[dim])` + `vec_meta(model, dim, built_at)` (it already does; fix the dim note if your model's dim differs from 384).

- [ ] **Step 5: Commit**

```bash
git add docs/ROADMAP.md docs/SCHEMA.md
git commit -m "docs: mark M6 complete + confirm vector schema"
```

---

## Acceptance Criteria (M6 exit)

- With the `[embeddings]` extra installed and `embeddings.enabled = true`, `codebase-index index` embeds chunks and stores vectors in `vec_chunks`; `stats.vectors` and `repo.count_vectors` agree; reindex is idempotent.
- `codebase-index search "<paraphrase>" --mode vector` returns semantically-relevant results; hybrid mode fuses the vector retriever and improves recall on paraphrased queries vs. lexical-only (proven by `test_vector_improves_recall_over_lexical_only`).
- **Disabled path unchanged:** with embeddings off (the default), no optional dependency is imported, `vec_chunks` is never created, `BuildStats.vectors == 0`, and `pipeline.search(..., backend=None)` is byte-for-byte identical to M4 (`test_disabled_pipeline_identical_to_m4`). The full suite passes in a venv **without** the extras (vector tests SKIP, never FAIL).
- External backend is refused unless `allow_external = true` **and** `$CBX_EMBEDDINGS_API_KEY` is set **and** a warning naming the endpoint is emitted (SECURITY.md §4) — enforced solely in `resolve_backend`.
- Toggling embeddings (or changing the model) changes `config_hash`, forcing a rebuild; changing only `endpoint`/`allow_external` does not.
- `ruff` + `mypy` clean; base install network-free.

## Deferred to later milestones (explicitly NOT in M6)

- Incremental vector maintenance on `update` (only changed chunks re-embedded) — M6 rebuilds all vectors on full `index`; incremental `update` is M8.
- `doctor` reporting of external-embedding status / leaked-secret vectors (SECURITY.md §6) — wired into `doctor` in a later milestone; M6 emits the warning at `index`/factory time.
- Batching/throughput tuning, multiple models, per-language embedding, and ANN index parameters — single-pass, single-model, exact-KNN is sufficient for the exit gate.
- Vector-aware graph expansion or semantic edges (overlaps M5's graph) — out of scope.
- Reranking on vector distance beyond its RRF contribution — the existing feature reranker is unchanged for vector candidates.
