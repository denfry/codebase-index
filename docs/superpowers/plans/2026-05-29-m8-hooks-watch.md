# M8 — Hooks + Watch Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the index stay fresh as files change — implement the incremental `update` engine that the M7 freshness contract already tells the skill to run, wire it to a debounced `watch` mode and an opt-in `PostToolUse` hook (`init --with-hooks` auto-merges the hook into `.claude/settings.json`), and have `doctor` report which hooks are enabled and whether the index is fresh — all without ever blocking the edit loop.

**Architecture:** `indexer/pipeline.py` gains `update_index()`: a content-aware incremental re-index that walks the current indexable set, skips files whose `(size_bytes, mtime_ns)` are unchanged (hashing only on a fast-path miss), re-chunks the rest, prunes deletions, and refreshes `head_commit` so the M7 freshness fast-path reports clean again. `update --since <ref>` narrows the candidate set to git-changed paths. The hook and `watch` are thin callers of `update`: `watch/watcher.py` adds a pure, unit-testable `DebouncedIndexer` (coalesces a burst of edits into one `update` after a quiet window) wrapped by a lazily-imported watchdog observer so the base install never needs `watchdog`. `init --with-hooks` is upgraded from M7's "write a reviewable example" to idempotently deep-merging the `PostToolUse` block into `.claude/settings.json` via a new `scaffold.merge_hook_settings()`. `doctor` (previously a stub) reports enabled `codebase-index` hooks, cache-gitignore coverage, and live freshness, exiting non-zero under `--strict` on high-severity findings.

**Tech Stack:** Python 3.10+, stdlib (`subprocess`, `time`, `json`, `threading`), pydantic v2, Typer, pytest. `watchdog>=4.0` is an **optional** extra (`pip install "codebase-index[watch]"`); everything except live `watch` works without it. Builds on M1 (config/storage/discovery/pipeline), M2 (FTS searchers + output), and M7 (`scaffold.py`, `indexer/freshness.py`, `init`).

**Scope decision — shipped behavior:** M8 delivers (1) incremental `update` (mtime fast-path + sha verify + prune) including `--since <ref>` and `--all`; (2) `watch` mode (debounced watchdog → `update`), degrading to a clear error when `watchdog` is not installed; (3) `init --with-hooks` upgraded to **auto-merge** the `PostToolUse` hook into `.claude/settings.json` idempotently; (4) `doctor` reporting enabled hooks + cache-gitignore + freshness with `--strict`. **Deferred:** the full SECURITY.md §6 `doctor` checklist (indexed-secret leak scan, oversized/binary slip-through audit, world-writable perms, `allowed-tools` diffing) lands in **M9**; symbol/graph/chunk incremental invalidation beyond file-level re-chunk (M3–M5 own those tables and are re-chunked wholesale per changed file here); per-file content-hash freshness caching stays the M7 full-walk approach.

**Depends on:** **M7** (`src/codebase_index/scaffold.py` with `SKILL_REL`/`CACHE_REL`/`_CACHE_IGNORE_LINE`/`_template_root()`/`write_hooks_example()`, `src/codebase_index/indexer/freshness.py` with `compute_freshness`, and the implemented `init` command), plus M1 (`config.py`, `storage/repo.py`, `indexer/pipeline.py`, `discovery/walker.py`) and M2 (`output/`). **If M7 is not yet merged, implement it first** — this plan extends those files and does not recreate them.

---

## File Structure

| File | Create/Modify | Responsibility |
|---|---|---|
| `src/codebase_index/storage/repo.py` | Modify | Add `fingerprints(conn)` → `{path: (mtime_ns, size_bytes, sha256)}` for incremental diffing. |
| `src/codebase_index/indexer/pipeline.py` | Modify | Add `update_index()` (incremental) + `_git_changed_since()`; add `skipped` to `BuildStats`. |
| `src/codebase_index/cli.py` | Modify | Implement `update` (delegates to `update_index`); implement `watch`; implement `doctor`. |
| `src/codebase_index/scaffold.py` | Modify | Add `merge_hook_settings()` (idempotent deep-merge into `.claude/settings.json`) + `enabled_hooks()` reader. |
| `src/codebase_index/watch/watcher.py` | Create | `DebouncedIndexer` (pure, testable) + `run_watch()` (lazy watchdog observer). |
| `src/codebase_index/doctor.py` | Create | `run_doctor(root, config)` → list of `Finding`; severity model used by the CLI. |
| `tests/test_update.py` | Create | `update_index`: skip-unchanged, re-chunk on edit, prune deletion, `--all`, `--since`. |
| `tests/test_update_cli.py` | Create | `update` CLI: edits flip stale→fresh; `--quiet`/`--json`; no index → clear message. |
| `tests/test_hooks_merge.py` | Create | `merge_hook_settings`: writes block, idempotent, preserves existing settings; `enabled_hooks`. |
| `tests/test_init_cli.py` | Modify | `init --with-hooks` now writes/merges `.claude/settings.json`. |
| `tests/test_watcher.py` | Create | `DebouncedIndexer` coalescing via injected clock; `run_watch` clean error without watchdog. |
| `tests/test_doctor.py` | Create | `run_doctor` + `doctor` CLI: hook detection, gitignore finding, freshness, `--strict` exit. |

**Conventions (unchanged):** `from __future__ import annotations` at the top of every module; **all SQL lives in `storage/repo.py`**; `--json` output stays plain (no Rich markup); the base install stays network-free and `watchdog`-free.

---

## Task 1: `repo.fingerprints` — per-file change-detection accessor

**Files:**
- Modify: `src/codebase_index/storage/repo.py`
- Modify: `tests/test_storage.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_storage.py` (reuses the `_open` helper + `repo` import already present from M1):

```python
# tests/test_storage.py  (append)
def test_fingerprints_returns_mtime_size_and_sha(tmp_path):
    db = _open(tmp_path)
    repo.upsert_file(
        db.conn, path="src/a.py", lang="python", size_bytes=10, sha256="aaa",
        mtime_ns=111, git_status=None, parser="line", indexed_at="t", is_generated=False,
    )
    repo.upsert_file(
        db.conn, path="src/b.py", lang="python", size_bytes=20, sha256="bbb",
        mtime_ns=222, git_status=None, parser="line", indexed_at="t", is_generated=False,
    )
    fps = repo.fingerprints(db.conn)
    assert fps == {
        "src/a.py": (111, 10, "aaa"),
        "src/b.py": (222, 20, "bbb"),
    }
    db.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_storage.py::test_fingerprints_returns_mtime_size_and_sha -v`
Expected: FAIL — `AttributeError: module 'codebase_index.storage.repo' has no attribute 'fingerprints'`.

- [ ] **Step 3: Write minimal implementation**

Append to `src/codebase_index/storage/repo.py`:

```python
# src/codebase_index/storage/repo.py  (append)

def fingerprints(conn: sqlite3.Connection) -> dict[str, tuple[int, int, str]]:
    """Map every indexed path to its (mtime_ns, size_bytes, sha256) for incremental update."""
    return {
        row["path"]: (int(row["mtime_ns"]), int(row["size_bytes"]), row["sha256"])
        for row in conn.execute(
            "SELECT path, mtime_ns, size_bytes, sha256 FROM files"
        ).fetchall()
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_storage.py::test_fingerprints_returns_mtime_size_and_sha -v`
Expected: PASS. (`db.conn.row_factory` is `sqlite3.Row` from M1; if a test opens a raw connection without it, access by index instead — but `_open` already sets it.)

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/storage/repo.py tests/test_storage.py
git commit -m "feat(storage): add fingerprints accessor for incremental update"
```

---

## Task 2: `update_index` — incremental re-index engine

**Files:**
- Modify: `src/codebase_index/indexer/pipeline.py`
- Create: `tests/test_update.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_update.py
from __future__ import annotations

from pathlib import Path

from codebase_index.config import Config
from codebase_index.indexer.pipeline import build_index, update_index
from codebase_index.storage import repo
from codebase_index.storage.db import Database


def _cfg(root: Path) -> Config:
    cfg = Config()
    cfg.root = str(root)
    return cfg


def _repo(tmp_path: Path) -> Path:
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")
    (root / "src" / "b.py").write_text("def beta():\n    return 2\n", encoding="utf-8")
    return root


def test_update_skips_unchanged_files(tmp_path):
    root = _repo(tmp_path)
    cfg = _cfg(root)
    db = Database(tmp_path / "index.sqlite").open()
    build_index(cfg, db, root=root)

    stats = update_index(cfg, db, root=root)
    assert stats.indexed == 0          # nothing changed
    assert stats.skipped == 2
    assert stats.deleted == 0
    db.close()


def test_update_reindexes_edited_file(tmp_path):
    root = _repo(tmp_path)
    cfg = _cfg(root)
    db = Database(tmp_path / "index.sqlite").open()
    build_index(cfg, db, root=root)
    before = repo.fingerprints(db.conn)["src/a.py"][2]  # sha256

    (root / "src" / "a.py").write_text("def alpha():\n    return 999\n", encoding="utf-8")
    stats = update_index(cfg, db, root=root)

    assert stats.indexed == 1
    assert stats.skipped == 1
    after = repo.fingerprints(db.conn)["src/a.py"][2]
    assert after != before              # sha refreshed
    db.close()


def test_update_prunes_deleted_file(tmp_path):
    root = _repo(tmp_path)
    cfg = _cfg(root)
    db = Database(tmp_path / "index.sqlite").open()
    build_index(cfg, db, root=root)

    (root / "src" / "b.py").unlink()
    stats = update_index(cfg, db, root=root)

    assert stats.deleted == 1
    assert "src/b.py" not in repo.all_paths(db.conn)
    db.close()


def test_update_all_rehashes_even_when_mtime_matches(tmp_path):
    """--all ignores the mtime fast-path: a same-mtime content change is still caught."""
    root = _repo(tmp_path)
    cfg = _cfg(root)
    db = Database(tmp_path / "index.sqlite").open()
    build_index(cfg, db, root=root)

    p = root / "src" / "a.py"
    stat = p.stat()
    p.write_text("def alpha():\n    return 7\n", encoding="utf-8")
    import os
    os.utime(p, ns=(stat.st_atime_ns, stat.st_mtime_ns))  # restore old mtime

    skipped = update_index(cfg, db, root=root)            # fast-path: misses the edit
    assert skipped.indexed == 0
    forced = update_index(cfg, db, root=root, all_files=True)
    assert forced.indexed == 1                            # --all hashes and catches it
    db.close()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_update.py -v`
Expected: FAIL — `ImportError: cannot import name 'update_index'`.

- [ ] **Step 3: Write minimal implementation**

In `src/codebase_index/indexer/pipeline.py`, add `skipped` to `BuildStats` and add `update_index` plus a git helper. Reuse the existing `_sha256_file`, `_read_text`, `_utc_now_iso`, `_git_head`, and `walk`.

```python
# src/codebase_index/indexer/pipeline.py  — extend BuildStats
@dataclass
class BuildStats:
    indexed: int = 0
    deleted: int = 0
    total_bytes: int = 0
    chunks: int = 0
    skipped: int = 0
```

```python
# src/codebase_index/indexer/pipeline.py  (append)

def update_index(
    config: Config,
    db: Database,
    root: Optional[Path] = None,
    *,
    since: Optional[str] = None,
    all_files: bool = False,
) -> BuildStats:
    """Incrementally re-index changed files.

    Fast path: a candidate whose (size_bytes, mtime_ns) match the stored row is skipped
    without reading it. On a mismatch (or with all_files=True) we hash the file and only
    re-chunk when the sha256 actually changed; an mtime-only change just refreshes mtime.
    Deletions are pruned. `since` narrows the candidate set to git-changed paths.
    """
    root = Path(root or config.root).resolve()
    conn = db.conn
    now = _utc_now_iso()
    stats = BuildStats()

    indexed_fp = repo.fingerprints(conn)
    scope = _git_changed_since(root, since) if since else None

    seen: set[str] = set()
    for cand in walk(root, config):
        seen.add(cand.rel_path)
        if scope is not None and cand.rel_path not in scope:
            stats.skipped += 1
            continue

        st = cand.path.stat()
        prior = indexed_fp.get(cand.rel_path)
        fast_ok = (
            not all_files
            and prior is not None
            and prior[0] == st.st_mtime_ns
            and prior[1] == cand.size_bytes
        )
        if fast_ok:
            stats.skipped += 1
            continue

        sha = _sha256_file(cand.path)
        if prior is not None and prior[2] == sha:
            # content identical; only mtime/size metadata drifted — refresh it cheaply.
            conn.execute(
                "UPDATE files SET mtime_ns = ?, size_bytes = ?, indexed_at = ? WHERE path = ?",
                (st.st_mtime_ns, cand.size_bytes, now, cand.rel_path),
            )
            stats.skipped += 1
            continue

        file_id = repo.upsert_file(
            conn,
            path=cand.rel_path,
            lang=cand.lang,
            size_bytes=cand.size_bytes,
            sha256=sha,
            mtime_ns=st.st_mtime_ns,
            git_status=None,
            parser=cand.parser,
            indexed_at=now,
            is_generated=cand.is_generated,
        )
        file_chunks = chunk_text(
            _read_text(cand.path),
            window_lines=config.chunk.window_lines,
            overlap_lines=config.chunk.overlap_lines,
        )
        repo.replace_chunks(conn, file_id, file_chunks)
        stats.chunks += len(file_chunks)
        stats.indexed += 1
        stats.total_bytes += cand.size_bytes

    # Prune deletions. With a git scope, only prune paths git reported as gone.
    if scope is None:
        gone = repo.all_paths(conn) - seen
    else:
        gone = {p for p in scope if p not in seen and p in indexed_fp}
    stats.deleted = repo.delete_files(conn, gone)

    repo.set_meta(conn, "built_at", repo.get_meta(conn, "built_at") or now)
    repo.set_meta(conn, "updated_at", now)
    repo.set_meta(conn, "config_hash", config.config_hash())
    if head := _git_head(root):
        repo.set_meta(conn, "head_commit", head)
    conn.commit()
    return stats


def _git_changed_since(root: Path, ref: str) -> set[str]:
    """Repo-relative paths changed (working tree vs `ref`) plus untracked files."""
    changed: set[str] = set()
    try:
        diff = subprocess.run(
            ["git", "-C", str(root), "diff", "--name-only", ref],
            capture_output=True, text=True, timeout=15, check=False,
        )
        if diff.returncode == 0:
            changed.update(line for line in diff.stdout.splitlines() if line)
        untracked = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--others", "--exclude-standard"],
            capture_output=True, text=True, timeout=15, check=False,
        )
        if untracked.returncode == 0:
            changed.update(line for line in untracked.stdout.splitlines() if line)
    except (OSError, subprocess.SubprocessError):
        return set()
    return changed
```

> The `since` path uses git's posix-style relative paths, which already match `cand.rel_path` (discovery stores repo-relative posix paths). No path normalization needed.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_update.py -v`
Expected: PASS (4 tests). The `_repo` fixture has no `.git`, so `since` is unused here; the `--since` path is covered in Task 3.

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/indexer/pipeline.py tests/test_update.py
git commit -m "feat(indexer): incremental update_index (mtime fast-path + sha verify + prune)"
```

---

## Task 3: Wire the `update` CLI command

**Files:**
- Modify: `src/codebase_index/cli.py` (replace the `update` stub)
- Create: `tests/test_update_cli.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_update_cli.py
from __future__ import annotations

import json
import subprocess

from typer.testing import CliRunner

from codebase_index.cli import app

runner = CliRunner()


def _git_repo(tmp_path):
    root = tmp_path / "proj"
    (root / "src").mkdir(parents=True)
    (root / "src" / "a.py").write_text("def alpha():\n    return 1\n", encoding="utf-8")
    subprocess.run(["git", "-C", str(root), "init", "-q"], check=True)
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(root), "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-q", "-m", "init"],
        check=True,
    )
    return root


def test_update_no_index_reports_clearly(tmp_path):
    res = runner.invoke(app, ["--root", str(tmp_path), "update"])
    assert res.exit_code == 0
    assert "index" in res.output.lower()


def test_update_json_reports_counts(tmp_path):
    root = _git_repo(tmp_path)
    assert runner.invoke(app, ["--root", str(root), "index"]).exit_code == 0

    (root / "src" / "a.py").write_text("def alpha():\n    return 42\n", encoding="utf-8")
    res = runner.invoke(app, ["--root", str(root), "--json", "update"])
    assert res.exit_code == 0, res.output
    data = json.loads(res.output)
    assert data["indexed"] == 1
    assert data["deleted"] == 0


def test_update_refreshes_freshness(tmp_path):
    root = _git_repo(tmp_path)
    assert runner.invoke(app, ["--root", str(root), "index"]).exit_code == 0
    (root / "src" / "a.py").write_text("def alpha():\n    return 5\n", encoding="utf-8")

    # stale before update
    stale = json.loads(
        runner.invoke(app, ["--root", str(root), "--json", "search", "alpha"]).output
    )
    assert stale["index"]["stale"] is True

    assert runner.invoke(app, ["--root", str(root), "update"]).exit_code == 0
    subprocess.run(["git", "-C", str(root), "add", "."], check=True)
    subprocess.run(
        ["git", "-C", str(root), "-c", "user.email=t@t", "-c", "user.name=t",
         "commit", "-q", "-m", "edit"],
        check=True,
    )
    fresh = json.loads(
        runner.invoke(app, ["--root", str(root), "--json", "search", "alpha"]).output
    )
    assert fresh["index"]["stale"] is False
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_update_cli.py -v`
Expected: FAIL — `update` prints `not implemented`, so JSON parse / assertions fail.

- [ ] **Step 3: Write minimal implementation**

Replace the `update` command in `src/codebase_index/cli.py` (it currently calls `_todo("update")`). Add `ctx` so global options resolve:

```python
# src/codebase_index/cli.py  — replace `update`

@app.command()
def update(
    ctx: typer.Context,
    since: Optional[str] = typer.Option(None, "--since", help="Re-index files changed since a git ref."),
    all_files: bool = typer.Option(False, "--all", help="Force re-check (hash) of every file."),
) -> None:
    """Incremental re-index (mtime/sha/git aware). Safe to call from a hook or watcher."""
    import json as _json

    from .config import load
    from .indexer.pipeline import update_index
    from .storage.db import Database

    is_json = bool(ctx.obj and ctx.obj.get("json"))
    quiet = bool(ctx.obj and ctx.obj.get("quiet"))

    cfg = load(ctx.obj.get("root") if ctx.obj else None)
    db_path = Path(cfg.root) / ".claude" / "cache" / "codebase-index" / "index.sqlite"
    if not db_path.exists():
        if is_json:
            typer.echo(_json.dumps({"indexed": 0, "deleted": 0, "skipped": 0, "exists": False}))
        elif not quiet:
            typer.echo("No index found. Run `codebase-index index` first.")
        raise typer.Exit(code=0)

    with Database(db_path) as db:
        stats = update_index(cfg, db, root=Path(cfg.root), since=since, all_files=all_files)

    if is_json:
        typer.echo(
            _json.dumps(
                {"indexed": stats.indexed, "deleted": stats.deleted, "skipped": stats.skipped}
            )
        )
    elif not quiet:
        typer.echo(
            f"Updated {stats.indexed} file(s); {stats.deleted} pruned; {stats.skipped} unchanged."
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_update_cli.py -v`
Expected: PASS (3 tests). The freshness test relies on M7's `compute_freshness` git fast-path: after `update` refreshes `head_commit` and the commit makes the tree clean, `stale` is `False`.

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/cli.py tests/test_update_cli.py
git commit -m "feat(cli): implement incremental update (--since/--all, --json, --quiet)"
```

---

## Task 4: `scaffold.merge_hook_settings` — idempotent hook merge

**Files:**
- Modify: `src/codebase_index/scaffold.py`
- Create: `tests/test_hooks_merge.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_hooks_merge.py
from __future__ import annotations

import json

from codebase_index import scaffold


def test_merge_hook_settings_creates_settings(tmp_path):
    changed = scaffold.merge_hook_settings(tmp_path)
    assert changed is True
    data = json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    matchers = [h["matcher"] for h in data["hooks"]["PostToolUse"]]
    assert any("Edit" in m for m in matchers)
    cmds = [
        hk["command"]
        for entry in data["hooks"]["PostToolUse"]
        for hk in entry["hooks"]
    ]
    assert any("codebase-index update" in c for c in cmds)


def test_merge_hook_settings_is_idempotent(tmp_path):
    assert scaffold.merge_hook_settings(tmp_path) is True
    assert scaffold.merge_hook_settings(tmp_path) is False  # already present
    data = json.loads((tmp_path / ".claude" / "settings.json").read_text(encoding="utf-8"))
    cmds = [
        hk["command"]
        for entry in data["hooks"]["PostToolUse"]
        for hk in entry["hooks"]
    ]
    assert sum("codebase-index update" in c for c in cmds) == 1  # not duplicated


def test_merge_hook_settings_preserves_existing(tmp_path):
    settings = tmp_path / ".claude" / "settings.json"
    settings.parent.mkdir(parents=True)
    settings.write_text(json.dumps({"model": "opus", "hooks": {"Stop": []}}), encoding="utf-8")

    scaffold.merge_hook_settings(tmp_path)
    data = json.loads(settings.read_text(encoding="utf-8"))
    assert data["model"] == "opus"          # unrelated keys preserved
    assert "Stop" in data["hooks"]          # unrelated hook groups preserved
    assert "PostToolUse" in data["hooks"]


def test_enabled_hooks_detects_our_hook(tmp_path):
    assert scaffold.enabled_hooks(tmp_path) == []
    scaffold.merge_hook_settings(tmp_path)
    found = scaffold.enabled_hooks(tmp_path)
    assert any("codebase-index update" in c for c in found)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_hooks_merge.py -v`
Expected: FAIL — `AttributeError: module 'codebase_index.scaffold' has no attribute 'merge_hook_settings'`.

- [ ] **Step 3: Write minimal implementation**

First ensure `import json` is in the **top** import block of `src/codebase_index/scaffold.py` (M7's module uses `cfg.model_dump_json`, not the `json` module, so it is likely absent — add it next to the other stdlib imports, not mid-file, to keep `ruff` E402 happy). Then append the rest below M7's helpers. This reads the canonical hook from the packaged template (`_template_root()` from M7) so the merged command never drifts from the shipped example.

```python
# src/codebase_index/scaffold.py  — add to the top imports if absent
import json
```

```python
# src/codebase_index/scaffold.py  (append)

SETTINGS_REL = Path(".claude") / "settings.json"
_HOOK_MARKER = "codebase-index update"  # identifies our PostToolUse command


def _template_hook_entries() -> "list[dict]":
    """The PostToolUse entries from the packaged hooks example (single source of truth)."""
    src = _template_root() / "examples" / "hooks" / "settings.json"
    data = json.loads(src.read_text(encoding="utf-8"))
    return data["hooks"]["PostToolUse"]


def _has_our_hook(settings: dict) -> bool:
    for entry in settings.get("hooks", {}).get("PostToolUse", []):
        for hk in entry.get("hooks", []):
            if _HOOK_MARKER in hk.get("command", ""):
                return True
    return False


def merge_hook_settings(root: Path) -> bool:
    """Idempotently merge the PostToolUse update hook into `<root>/.claude/settings.json`.

    Preserves every existing key/hook-group. Returns True if the file changed.
    """
    path = root / SETTINGS_REL
    settings: dict = {}
    if path.exists():
        settings = json.loads(path.read_text(encoding="utf-8"))
    if _has_our_hook(settings):
        return False

    hooks = settings.setdefault("hooks", {})
    post = hooks.setdefault("PostToolUse", [])
    post.extend(_template_hook_entries())

    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(settings, indent=2) + "\n", encoding="utf-8")
    return True


def enabled_hooks(root: Path) -> list[str]:
    """Return the commands of any `codebase-index` PostToolUse hooks in settings.json."""
    path = root / SETTINGS_REL
    if not path.exists():
        return []
    try:
        settings = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return [
        hk.get("command", "")
        for entry in settings.get("hooks", {}).get("PostToolUse", [])
        for hk in entry.get("hooks", [])
        if _HOOK_MARKER in hk.get("command", "")
    ]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_hooks_merge.py -v`
Expected: PASS (4 tests). Relies on M7's packaged `skill_template/examples/hooks/settings.json` containing a `PostToolUse` → `codebase-index update` command.

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/scaffold.py tests/test_hooks_merge.py
git commit -m "feat(scaffold): idempotent PostToolUse hook merge + enabled_hooks reader"
```

---

## Task 5: Upgrade `init --with-hooks` to auto-merge the hook

**Files:**
- Modify: `src/codebase_index/cli.py` (the `init` command from M7)
- Modify: `tests/test_init_cli.py`

- [ ] **Step 1: Write the failing test**

Replace the M7 `test_init_with_hooks_writes_example` test in `tests/test_init_cli.py` with the stronger M8 behavior (auto-merge), and keep the example-write assertion:

```python
# tests/test_init_cli.py  — replace test_init_with_hooks_writes_example
def test_init_with_hooks_merges_settings(tmp_path):
    root = _project(tmp_path)  # existing helper that mkdirs .git
    res = runner.invoke(app, ["--root", str(root), "init", "--with-hooks"])
    assert res.exit_code == 0, res.output

    # the reviewable example is still written next to the skill
    hook_example = root / ".claude" / "skills" / "codebase-index" / "examples" / "hooks" / "settings.json"
    assert hook_example.is_file()

    # and the hook is now actually merged into the project's settings.json
    import json
    settings = json.loads((root / ".claude" / "settings.json").read_text(encoding="utf-8"))
    cmds = [
        hk["command"]
        for entry in settings["hooks"]["PostToolUse"]
        for hk in entry["hooks"]
    ]
    assert any("codebase-index update" in c for c in cmds)
    assert "hook" in res.output.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_init_cli.py::test_init_with_hooks_merges_settings -v`
Expected: FAIL — M7's `init` only writes the example (no `.claude/settings.json` merge).

- [ ] **Step 3: Write minimal implementation**

In `src/codebase_index/cli.py`, extend the `with_hooks` branch of `init` (added in M7). After `scaffold.write_hooks_example(root)`, also merge into settings and adjust the summary line:

```python
# src/codebase_index/cli.py  — inside `init`, replace the `if with_hooks:` block

    if with_hooks:
        hook_path = scaffold.write_hooks_example(root)
        merged = scaffold.merge_hook_settings(root)
        state = "enabled in .claude/settings.json" if merged else "already enabled"
        lines.append(f"Auto-update hook  → {state}")
        lines.append(f"Hook example      → {hook_path} (reference copy)")
```

> The hook command is `codebase-index update --quiet` (backgrounded). On Windows, Claude Code runs the same `command` string; users on cmd.exe who need non-blocking behavior can switch `&` to `start /b` per docs/INSTALLATION.md §6. M8 ships the POSIX-style command from the template unchanged (it is the documented default).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_init_cli.py -v`
Expected: PASS (M7's init tests + the upgraded hook test).

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/cli.py tests/test_init_cli.py
git commit -m "feat(cli): init --with-hooks auto-merges the update hook into settings.json"
```

---

## Task 6: `watch/watcher.py` — debounced live indexing

**Files:**
- Create: `src/codebase_index/watch/watcher.py`
- Create: `tests/test_watcher.py`

- [ ] **Step 1: Write the failing test**

The coalescing logic is pure and clock-injected so it's deterministic; the watchdog wiring is a thin lazy import we only smoke-test for a clean missing-dependency error.

```python
# tests/test_watcher.py
from __future__ import annotations

from codebase_index.watch.watcher import DebouncedIndexer


class _Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t

    def advance(self, dt: float) -> None:
        self.t += dt


def test_debouncer_coalesces_burst_into_one_run():
    clock = _Clock()
    runs: list[int] = []
    d = DebouncedIndexer(lambda: runs.append(1), window_s=0.5, clock=clock)

    d.notify(); clock.advance(0.1)
    d.notify(); clock.advance(0.1)
    d.notify()
    assert d.maybe_run() is False        # still inside the quiet window
    assert runs == []

    clock.advance(0.5)                   # window elapsed since last notify
    assert d.maybe_run() is True
    assert runs == [1]                   # the whole burst → exactly one run


def test_debouncer_does_not_run_without_events():
    clock = _Clock()
    runs: list[int] = []
    d = DebouncedIndexer(lambda: runs.append(1), window_s=0.5, clock=clock)
    clock.advance(10)
    assert d.maybe_run() is False
    assert runs == []


def test_debouncer_rearms_after_running():
    clock = _Clock()
    runs: list[int] = []
    d = DebouncedIndexer(lambda: runs.append(1), window_s=0.5, clock=clock)
    d.notify(); clock.advance(0.5); d.maybe_run()
    assert runs == [1]
    d.notify(); clock.advance(0.5); d.maybe_run()
    assert runs == [1, 1]                # second burst runs again


def test_run_watch_without_watchdog_raises_clear_error(monkeypatch):
    import builtins

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "watchdog" or name.startswith("watchdog."):
            raise ImportError("No module named 'watchdog'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    from codebase_index.watch import watcher
    try:
        watcher.run_watch(config=None, db_path=None, debounce_ms=500)
        assert False, "expected RuntimeError"
    except RuntimeError as exc:
        assert "watchdog" in str(exc).lower()
        assert "pip install" in str(exc).lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_watcher.py -v`
Expected: FAIL — `ModuleNotFoundError: codebase_index.watch.watcher`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/codebase_index/watch/watcher.py
"""Optional live indexing (extra: watch).

A burst of filesystem events is coalesced by `DebouncedIndexer` into a single incremental
`update` once edits go quiet for `window_s`, so we never block or thrash the edit loop.
`run_watch` wires that to a watchdog observer; watchdog is imported lazily so the base
install never depends on it.
"""

from __future__ import annotations

import time
from pathlib import Path
from typing import Callable, Optional


class DebouncedIndexer:
    """Coalesce edit notifications; run the callback once the quiet window elapses.

    Pure and clock-injected for deterministic tests. `notify()` records an edit;
    `maybe_run()` runs the callback exactly once if there is pending work and at least
    `window_s` has passed since the last notification, then re-arms.
    """

    def __init__(
        self,
        callback: Callable[[], None],
        *,
        window_s: float,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._callback = callback
        self._window_s = window_s
        self._clock = clock
        self._last_event: Optional[float] = None

    def notify(self) -> None:
        self._last_event = self._clock()

    def maybe_run(self) -> bool:
        if self._last_event is None:
            return False
        if self._clock() - self._last_event < self._window_s:
            return False
        self._last_event = None
        self._callback()
        return True


def run_watch(config, db_path, debounce_ms: int) -> None:  # pragma: no cover - exercised via CLI/manual QA
    """Watch the repo and run incremental `update` on debounced changes.

    Raises RuntimeError (not ImportError) with install guidance if watchdog is absent.
    """
    try:
        from watchdog.events import FileSystemEventHandler
        from watchdog.observers import Observer
    except ImportError as exc:
        raise RuntimeError(
            "watch mode requires the optional 'watchdog' dependency. "
            'Install it with: pip install "codebase-index[watch]"'
        ) from exc

    from ..indexer.pipeline import update_index
    from ..storage.db import Database

    root = Path(config.root).resolve()

    def _run_update() -> None:
        with Database(db_path) as db:
            stats = update_index(config, db, root=root)
        if stats.indexed or stats.deleted:
            print(f"[watch] updated {stats.indexed}, pruned {stats.deleted}", flush=True)

    debouncer = DebouncedIndexer(_run_update, window_s=debounce_ms / 1000.0)

    class _Handler(FileSystemEventHandler):
        def on_any_event(self, event) -> None:
            if not event.is_directory:
                debouncer.notify()

    observer = Observer()
    observer.schedule(_Handler(), str(root), recursive=True)
    observer.start()
    print(f"[watch] watching {root} (debounce {debounce_ms}ms). Ctrl-C to stop.", flush=True)
    try:
        while True:
            time.sleep(min(0.25, debounce_ms / 1000.0))
            debouncer.maybe_run()
    except KeyboardInterrupt:
        pass
    finally:
        observer.stop()
        observer.join()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_watcher.py -v`
Expected: PASS (4 tests). `run_watch` is excluded from coverage (`pragma: no cover`) except the import-guard path the test forces.

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/watch/watcher.py tests/test_watcher.py
git commit -m "feat(watch): debounced live indexer + lazy watchdog observer"
```

---

## Task 7: Wire the `watch` CLI command

**Files:**
- Modify: `src/codebase_index/cli.py` (replace the `watch` stub)
- Modify: `tests/test_watcher.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_watcher.py`:

```python
# tests/test_watcher.py  (append)
def test_watch_cli_errors_clearly_without_watchdog(tmp_path, monkeypatch):
    import builtins

    from typer.testing import CliRunner

    from codebase_index.cli import app

    real_import = builtins.__import__

    def fake_import(name, *args, **kwargs):
        if name == "watchdog" or name.startswith("watchdog."):
            raise ImportError("No module named 'watchdog'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", fake_import)

    # an index must exist so we reach the watch wiring (not the early "no index" exit)
    runner = CliRunner()
    (tmp_path / ".git").mkdir()
    assert runner.invoke(app, ["--root", str(tmp_path), "index"]).exit_code == 0

    res = runner.invoke(app, ["--root", str(tmp_path), "watch"])
    assert res.exit_code != 0
    assert "watchdog" in res.output.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_watcher.py::test_watch_cli_errors_clearly_without_watchdog -v`
Expected: FAIL — `watch` prints `not implemented` and exits 0.

- [ ] **Step 3: Write minimal implementation**

Replace the `watch` command in `src/codebase_index/cli.py`:

```python
# src/codebase_index/cli.py  — replace `watch`

@app.command()
def watch(
    ctx: typer.Context,
    debounce: int = typer.Option(500, "--debounce", help="Debounce window in ms."),
) -> None:
    """Live incremental indexing via filesystem events (requires the 'watch' extra)."""
    from .config import load
    from .watch.watcher import run_watch

    cfg = load(ctx.obj.get("root") if ctx.obj else None)
    db_path = Path(cfg.root) / ".claude" / "cache" / "codebase-index" / "index.sqlite"
    if not db_path.exists():
        typer.echo("No index found. Run `codebase-index index` before `watch`.")
        raise typer.Exit(code=1)

    try:
        run_watch(config=cfg, db_path=db_path, debounce_ms=debounce)
    except RuntimeError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_watcher.py -v`
Expected: PASS. If `watchdog` happens to be installed in the dev env, the monkeypatched import still forces the `RuntimeError` path, so the test holds either way.

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/cli.py tests/test_watcher.py
git commit -m "feat(cli): implement watch command (graceful without the watch extra)"
```

---

## Task 8: `doctor.py` + `doctor` CLI — report hooks & freshness

**Files:**
- Create: `src/codebase_index/doctor.py`
- Modify: `src/codebase_index/cli.py` (replace the `doctor` stub)
- Create: `tests/test_doctor.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_doctor.py
from __future__ import annotations

import json

from typer.testing import CliRunner

from codebase_index import scaffold
from codebase_index.cli import app
from codebase_index.config import Config
from codebase_index.doctor import run_doctor

runner = CliRunner()


def test_doctor_flags_uncovered_cache(tmp_path):
    cfg = Config()
    cfg.root = str(tmp_path)
    findings = run_doctor(tmp_path, cfg)
    ids = {f.id for f in findings}
    assert "cache_gitignored" in ids
    cache = next(f for f in findings if f.id == "cache_gitignored")
    assert cache.ok is False and cache.severity == "high"  # not gitignored yet


def test_doctor_reports_hook_state(tmp_path):
    cfg = Config()
    cfg.root = str(tmp_path)

    off = {f.id: f for f in run_doctor(tmp_path, cfg)}
    assert off["hooks_enabled"].ok is False  # no hook yet (informational)

    scaffold.merge_hook_settings(tmp_path)
    on = {f.id: f for f in run_doctor(tmp_path, cfg)}
    assert on["hooks_enabled"].ok is True
    assert "codebase-index update" in on["hooks_enabled"].detail


def test_doctor_cli_json(tmp_path):
    res = runner.invoke(app, ["--root", str(tmp_path), "--json", "doctor"])
    assert res.exit_code == 0, res.output
    data = json.loads(res.output)
    assert "findings" in data
    assert any(f["id"] == "cache_gitignored" for f in data["findings"])


def test_doctor_strict_exits_nonzero_on_high_severity(tmp_path):
    # uncovered cache is a high-severity finding → --strict must fail
    res = runner.invoke(app, ["--root", str(tmp_path), "doctor", "--strict"])
    assert res.exit_code != 0

    # once the cache is gitignored, --strict passes
    scaffold.merge_gitignore(tmp_path)
    res2 = runner.invoke(app, ["--root", str(tmp_path), "doctor", "--strict"])
    assert res2.exit_code == 0, res2.output
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_doctor.py -v`
Expected: FAIL — `ModuleNotFoundError: codebase_index.doctor`.

- [ ] **Step 3: Write minimal implementation (doctor module)**

```python
# src/codebase_index/doctor.py
"""Safety / health self-check (docs/SECURITY.md §6).

M8 scope: report enabled `codebase-index` hooks, whether the cache is gitignored, and
index freshness. The fuller checklist (indexed-secret leak scan, oversized/binary audit,
permissions, allowed-tools diff) is M9.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from . import scaffold
from .config import Config

Severity = Literal["high", "medium", "info"]


@dataclass
class Finding:
    id: str
    ok: bool
    severity: Severity
    detail: str


def run_doctor(root: Path, config: Config) -> list[Finding]:
    root = Path(root)
    findings: list[Finding] = []

    # 1. Is the cache gitignored? (committing the index can leak code/secrets.)
    gitignore = root / ".gitignore"
    covered = (
        gitignore.exists()
        and scaffold._CACHE_IGNORE_LINE in gitignore.read_text(encoding="utf-8")
    )
    findings.append(
        Finding(
            id="cache_gitignored",
            ok=covered,
            severity="high",
            detail=(
                "cache is gitignored"
                if covered
                else f"add '{scaffold._CACHE_IGNORE_LINE}' to .gitignore (run `init`)"
            ),
        )
    )

    # 2. Which auto-update hooks are enabled? (informational; hooks run on every edit.)
    hooks = scaffold.enabled_hooks(root)
    findings.append(
        Finding(
            id="hooks_enabled",
            ok=bool(hooks),
            severity="info",
            detail="; ".join(hooks) if hooks else "no auto-update hook (run `init --with-hooks`)",
        )
    )

    # 3. Index freshness.
    db_path = root / scaffold.CACHE_REL / "index.sqlite"
    if not db_path.exists():
        findings.append(
            Finding("index_fresh", ok=False, severity="medium", detail="no index (run `index`)")
        )
    else:
        from .indexer.freshness import compute_freshness
        from .storage.db import Database

        with Database(db_path) as db:
            fr = compute_freshness(db.conn, root, config)
        findings.append(
            Finding(
                id="index_fresh",
                ok=not fr.stale,
                severity="medium",
                detail=(
                    "index is fresh"
                    if not fr.stale
                    else f"{fr.files_changed_since_build} file(s) changed — run `update`"
                ),
            )
        )

    return findings


def has_high_severity_failure(findings: list[Finding]) -> bool:
    return any(f.severity == "high" and not f.ok for f in findings)
```

- [ ] **Step 4: Write minimal implementation (CLI)**

Replace the `doctor` command in `src/codebase_index/cli.py`:

```python
# src/codebase_index/cli.py  — replace `doctor`

@app.command()
def doctor(
    ctx: typer.Context,
    strict: bool = typer.Option(False, "--strict", help="Exit non-zero on high-severity findings."),
) -> None:
    """Diagnose configuration and security issues (see docs/SECURITY.md)."""
    import json as _json

    from .config import load
    from .doctor import has_high_severity_failure, run_doctor

    cfg = load(ctx.obj.get("root") if ctx.obj else None)
    findings = run_doctor(Path(cfg.root), cfg)

    if ctx.obj and ctx.obj.get("json"):
        typer.echo(
            _json.dumps(
                {
                    "findings": [
                        {"id": f.id, "ok": f.ok, "severity": f.severity, "detail": f.detail}
                        for f in findings
                    ]
                }
            )
        )
    else:
        for f in findings:
            mark = "OK " if f.ok else ("!! " if f.severity == "high" else "-- ")
            typer.echo(f"{mark}[{f.severity}] {f.id}: {f.detail}")

    if strict and has_high_severity_failure(findings):
        raise typer.Exit(code=1)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest tests/test_doctor.py -v`
Expected: PASS (4 tests). `run_doctor` reaches into `scaffold._CACHE_IGNORE_LINE`/`CACHE_REL`/`enabled_hooks` (M7 + Task 4) and M7's `compute_freshness`.

- [ ] **Step 6: Commit**

```bash
git add src/codebase_index/doctor.py src/codebase_index/cli.py tests/test_doctor.py
git commit -m "feat(doctor): report hooks, cache-gitignore, and freshness (--strict)"
```

---

## Task 9: Full suite, lint, manual QA, docs

**Files:**
- Modify: `docs/ROADMAP.md` (mark M8 done)
- Modify: `docs/INSTALLATION.md` (`--with-hooks` now auto-merges; `update` is incremental; `watch`)

- [ ] **Step 1: Run the whole suite**

Run: `pytest -v`
Expected: all M0–M8 tests PASS.

- [ ] **Step 2: Lint + type-check**

Run: `ruff check src tests` and `mypy src/codebase_index`
Expected: clean.

- [ ] **Step 3: Manual QA on a scratch git repo**

```bash
# in a throwaway clone / worktree so we don't dirty the working tree:
pip install -e .

codebase-index --root . init --with-hooks
grep -q "codebase-index update" .claude/settings.json && echo "hook merged OK"
codebase-index --root . doctor                      # cache_gitignored OK, hooks_enabled OK

codebase-index --root . index
codebase-index --root . --json search "update" | python -c "import sys,json; print('stale', json.load(sys.stdin)['index']['stale'])"   # False

# edit a file → incremental update keeps it fresh
echo "# touch" >> src/codebase_index/cli.py
codebase-index --root . --json update | python -c "import sys,json; d=json.load(sys.stdin); print('indexed', d['indexed'], 'skipped', d['skipped'])"
git add -A && git commit -q -m "scratch edit"
codebase-index --root . --json search "update" | python -c "import sys,json; print('stale-after-update', json.load(sys.stdin)['index']['stale'])"   # False

# --since: only re-checks git-changed files
codebase-index --root . --json update --since HEAD~1

# watch mode (install the extra first); Ctrl-C to stop
pip install "codebase-index[watch]"
codebase-index --root . watch --debounce 400 &
WATCH_PID=$!
sleep 1; echo "# live" >> src/codebase_index/config.py; sleep 2
kill $WATCH_PID
codebase-index --root . --json search "config" | python -c "import sys,json; print('watch-kept-fresh', not json.load(sys.stdin)['index']['stale'])"

# doctor --strict gates CI
codebase-index --root . doctor --strict; echo "exit=$?"   # expect exit=0 (cache gitignored, fresh)
```

Expected: `init --with-hooks` merges the hook into `.claude/settings.json`; `doctor` reports the hook + gitignored cache + fresh index; editing a file and running `update` re-indexes exactly the changed file (`skipped` covers the rest) and `search` reports `stale false`; `--since` runs without error; `watch` keeps the index fresh on a live edit; `doctor --strict` exits `0`. Revert the scratch edits.

- [ ] **Step 4: Update docs**

Edit `docs/ROADMAP.md`:
- Change the M8 heading to `## M8 — Hooks + watch mode ✅`.
- Append under it: *"Shipped: incremental `update` (mtime fast-path + sha verify + prune; `--since <ref>`, `--all`) is the engine the freshness contract calls; `init --with-hooks` auto-merges the `PostToolUse` update hook into `.claude/settings.json` idempotently; `watch` mode (optional `[watch]` extra) coalesces edit bursts into one debounced `update` and degrades to a clear error when watchdog is absent; `doctor` reports enabled hooks, cache-gitignore coverage, and freshness, exiting non-zero under `--strict` on high-severity findings. The full SECURITY.md §6 doctor checklist (secret-leak scan, perms, allowed-tools diff) is M9."*

Edit `docs/INSTALLATION.md`:
- §2/§3: `--with-hooks` now **auto-merges** the hook into `.claude/settings.json` (not just a reviewable example — the example is also written as a reference copy).
- §5 (`update`): note it is incremental (mtime/sha/git aware) and safe to run from a hook or watcher.
- §6 (Hooks detail): cross-reference `doctor` for "report enabled hooks" and `watch` mode for heavy editing.

- [ ] **Step 5: Commit**

```bash
git add docs/ROADMAP.md docs/INSTALLATION.md
git commit -m "docs: mark M8 complete (update/watch/hooks/doctor) + installation updates"
```

---

## Acceptance Criteria (M8 exit)

- `codebase-index update` performs a content-aware incremental re-index: unchanged files are skipped via the `(size_bytes, mtime_ns)` fast-path, edited files are re-hashed and re-chunked, deletions are pruned, and `head_commit` is refreshed so the M7 freshness fast-path reports clean again. `--all` forces a hash of every file; `--since <ref>` narrows the candidate set to git-changed + untracked paths; `--json`/`--quiet` are honored; no index → a clear message and exit 0.
- Editing an indexed file flips `search`'s `index.stale` to `true`, and a subsequent `update` flips it back to `false` with the right file being re-indexed — proving the freshness loop closes.
- `init --with-hooks` idempotently merges the `PostToolUse` → `codebase-index update` hook into `.claude/settings.json`, preserving any existing keys/hook groups, and still writes the reviewable example copy; a second run does not duplicate the hook.
- `watch` mode keeps the index fresh on live edits via a debounced incremental `update`, never blocking the edit loop, and exits non-zero with `pip install "codebase-index[watch]"` guidance when `watchdog` is not installed; the base install needs no `watchdog`.
- `doctor` reports enabled `codebase-index` hooks, whether the cache is gitignored, and index freshness; `--json` emits a `findings` array; `--strict` exits non-zero when a high-severity finding (uncovered cache) is present.
- Full `pytest` green; `ruff` clean; `mypy` clean; base install network-free and watchdog-free.

## Deferred to later milestones (explicitly NOT in M8)

- Full SECURITY.md §6 `doctor` checklist — indexed-secret leak scan, oversized/binary slip-through audit, world-writable cache permissions, resolved `allowed-tools` vs. recommended minimal set — **M9**.
- Symbol/graph/vector incremental invalidation finer than per-file re-chunk: M8 re-chunks a changed file wholesale; M3 (symbols), M5 (graph edges), and M6 (vectors) own re-deriving their rows from those chunks and should hook into `update_index`'s per-file path when they land.
- Caching/persisting the freshness computation between calls (M7 uses a full walk on the accurate path; M8 leaves that unchanged).
- A `FileChanged`-style Claude Code hook (vs. `PostToolUse`) and Windows-specific `start /b` hook command variants — documented in INSTALLATION.md but not auto-selected by `init`.
- PyPI release + `pipx install "codebase-index[watch]"` clean-machine verification — **M9**.
```