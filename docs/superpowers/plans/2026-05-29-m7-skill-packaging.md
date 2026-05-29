# M7 — Claude Code Skill Packaging Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `codebase-index init` materialize a working, committable skill (`SKILL.md` + `scripts/cbx`/`cbx.ps1`) into a project from a template shipped inside the wheel, write a resolved `config.json`, gitignore the cache, and honor the **freshness contract end-to-end** so the skill's `index` block tells Claude when to run `update`/`index` — fresh `init` → ask a question in Claude Code → compact reads.

**Architecture:** The shipped truth for the skill is `src/codebase_index/skill_template/` (SKILL.md + scripts + a hooks example), force-included into the wheel and read via `importlib.resources` so it works in both editable and zip-wheel installs. A new pure-Python `scaffold.py` materializes that template to `.claude/skills/codebase-index/`, writes `.claude/cache/codebase-index/config.json` from `Config()` defaults, and merges an idempotent `.gitignore` block; the `init` CLI command wires those three steps plus `--force`/`--with-hooks`. Separately, a new `indexer/freshness.py` computes real staleness (git fast-path: clean tree at the indexed commit ⇒ not stale; otherwise an accurate mtime diff of the current indexable set vs. the `files` table) and `fts_response` returns it in `index`, so the skill triggers `update`/`index` per `SKILL.md` step 2.

**Tech Stack:** Python 3.10+, stdlib (`importlib.resources`, `subprocess`, `shutil`, `stat`), pydantic v2, Typer, pytest. Builds on M1 (config/storage/discovery/pipeline), M2 (FTS searchers + output). Hatchling for the wheel.

**Scope decision — shipped behavior:** M7 delivers `init` (template materialization + config + gitignore + `--force`), the freshness contract wired into `search`, and the packaged template. `--with-hooks` lands in a **minimal** form (writes a reviewable `examples/hooks/settings.json` into the skill dir + prints the enable command); auto-merging into `.claude/settings.json` and `watch` mode are **M8** and explicitly deferred. The freshness check uses a git clean-tree fast-path and an accurate mtime fallback; smarter incremental freshness (per-file hashing, partial walks) is deferred to M8.

**Depends on:** M1 (`config.py`, `storage/repo.py`, `storage/db.py`, `indexer/pipeline.py`, `discovery/walker.py`), M2 (`retrieval/searchers.py`, `output/`, `search` CLI). It extends those files; it does not recreate them.

---

## File Structure

| File | Create/Modify | Responsibility |
|---|---|---|
| `src/codebase_index/skill_template/scripts/cbx` | Create | POSIX wrapper shipped in the wheel (copy of `skill/scripts/cbx`). |
| `src/codebase_index/skill_template/scripts/cbx.ps1` | Create | Windows wrapper shipped in the wheel (copy of `skill/scripts/cbx.ps1`). |
| `src/codebase_index/skill_template/examples/hooks/settings.json` | Create | Reviewable PostToolUse hook example (for `--with-hooks`). |
| `pyproject.toml` | Modify | `force-include` the `skill_template/` dir so non-`.py` files ship in the wheel. |
| `src/codebase_index/scaffold.py` | Create | Pure helpers: read packaged template, materialize skill dir, write config.json, merge .gitignore. |
| `src/codebase_index/indexer/freshness.py` | Create | `compute_freshness(conn, root, config)` → `IndexFreshness` (git fast-path + mtime diff). |
| `src/codebase_index/storage/repo.py` | Modify | Add `path_mtimes(conn)` accessor. |
| `src/codebase_index/retrieval/searchers.py` | Modify | `fts_response` accepts `config`; `_freshness` delegates to `compute_freshness`. |
| `src/codebase_index/cli.py` | Modify | Implement `init`; pass `config` into `fts_response` from `search`. |
| `tests/test_packaging.py` | Create | Packaged template resources are discoverable + parity with `skill/SKILL.md`. |
| `tests/test_scaffold.py` | Create | `materialize_skill`, `write_config`, `merge_gitignore` over `tmp_path`. |
| `tests/test_init_cli.py` | Create | `init` end-to-end: files written, `--force`, idempotent gitignore, `--with-hooks`. |
| `tests/test_freshness.py` | Create | `compute_freshness`: missing index, fresh, stale-after-edit, deleted file. |
| `tests/test_search_cli.py` | Modify | `search` reports `stale: true` after editing an indexed file. |

**Conventions (unchanged):** `from __future__ import annotations` at the top of every module; **all SQL lives in `storage/repo.py`**; `--json` output stays plain.

---

## Task 1: Ship the skill template (scripts + hooks example) in the wheel

**Files:**
- Create: `src/codebase_index/skill_template/scripts/cbx`
- Create: `src/codebase_index/skill_template/scripts/cbx.ps1`
- Create: `src/codebase_index/skill_template/examples/hooks/settings.json`
- Modify: `pyproject.toml`
- Create: `tests/test_packaging.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_packaging.py
from __future__ import annotations

from importlib import resources
from pathlib import Path


def _template():
    return resources.files("codebase_index") / "skill_template"


def test_packaged_template_has_skill_and_scripts():
    root = _template()
    assert (root / "SKILL.md").is_file()
    assert (root / "scripts" / "cbx").is_file()
    assert (root / "scripts" / "cbx.ps1").is_file()
    assert (root / "examples" / "hooks" / "settings.json").is_file()


def test_packaged_skill_matches_dev_copy():
    """The wheel-shipped SKILL.md must not drift from the authored skill/SKILL.md."""
    packaged = (_template() / "SKILL.md").read_text(encoding="utf-8")
    dev = Path("skill/SKILL.md").read_text(encoding="utf-8")
    assert packaged == dev


def test_packaged_cbx_whitelists_safe_subcommands_only():
    cbx = (_template() / "scripts" / "cbx").read_text(encoding="utf-8")
    assert 'ALLOWED="search explain symbol refs impact stats update index"' in cbx
    # destructive/scaffolding subcommands must never be reachable via the wrapper
    for forbidden in ("clean", "init", "watch"):
        assert f" {forbidden} " not in f' {cbx.split("ALLOWED=")[1].splitlines()[0]} '
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_packaging.py -v`
Expected: FAIL — `scripts/cbx` does not exist under `skill_template` yet.

- [ ] **Step 3: Create the template files**

Copy the authored POSIX wrapper verbatim to `src/codebase_index/skill_template/scripts/cbx`:

```bash
#!/usr/bin/env bash
# Thin, safe wrapper around the installed `codebase-index` CLI.
# - Resolves the binary (prefers one on PATH; falls back to `python -m codebase_index`).
# - Whitelists subcommands so the skill can never invoke destructive ones (clean/init/watch).
set -euo pipefail

ALLOWED="search explain symbol refs impact stats update index"

sub="${1:-}"
case " $ALLOWED " in
  *" ${sub} "*) : ;;
  *)
    echo "cbx: refusing subcommand '${sub}'. Allowed: ${ALLOWED}" >&2
    exit 2
    ;;
esac

if command -v codebase-index >/dev/null 2>&1; then
  exec codebase-index "$@"
else
  exec python -m codebase_index "$@"
fi
```

Copy the authored Windows wrapper verbatim to `src/codebase_index/skill_template/scripts/cbx.ps1`:

```powershell
# Windows PowerShell wrapper around the installed `codebase-index` CLI.
# Mirrors scripts/cbx: whitelists safe subcommands, falls back to `python -m codebase_index`.
param(
    [Parameter(Mandatory = $true, Position = 0)]
    [string]$Subcommand,
    [Parameter(ValueFromRemainingArguments = $true)]
    [string[]]$Rest
)

$ErrorActionPreference = "Stop"
$allowed = @("search", "explain", "symbol", "refs", "impact", "stats", "update", "index")

if ($allowed -notcontains $Subcommand) {
    Write-Error "cbx: refusing subcommand '$Subcommand'. Allowed: $($allowed -join ', ')"
    exit 2
}

$bin = Get-Command codebase-index -ErrorAction SilentlyContinue
if ($bin) {
    & $bin.Source $Subcommand @Rest
} else {
    & python -m codebase_index $Subcommand @Rest
}
exit $LASTEXITCODE
```

Create the hooks example `src/codebase_index/skill_template/examples/hooks/settings.json`:

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write|MultiEdit",
        "hooks": [
          {
            "type": "command",
            "command": "codebase-index update --quiet >/dev/null 2>&1 &",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

> Keep `skill/SKILL.md` and `src/codebase_index/skill_template/SKILL.md` byte-identical (the parity test enforces it). When you edit one, copy it to the other.

- [ ] **Step 4: Force-include the template in the wheel**

In `pyproject.toml`, replace the existing `artifacts` line under `[tool.hatch.build.targets.wheel]` with an explicit force-include so every non-`.py` template file ships:

```toml
[tool.hatch.build.targets.wheel]
packages = ["src/codebase_index"]

# Ship the skill template (SKILL.md + scripts + hooks example) inside the wheel so
# `init` can materialize it via importlib.resources in both editable and zip installs.
[tool.hatch.build.targets.wheel.force-include]
"src/codebase_index/skill_template" = "codebase_index/skill_template"
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_packaging.py -v`
Expected: PASS. (Editable install reads the template from the source tree.) If `resources.files(...)` can't see the dir, ensure you ran `pip install -e .` after M0 and that the files are tracked.

- [ ] **Step 6: Commit**

```bash
git add src/codebase_index/skill_template pyproject.toml tests/test_packaging.py
git commit -m "feat(packaging): ship skill template (scripts + hooks) in the wheel"
```

---

## Task 2: `scaffold.py` — materialize helpers

**Files:**
- Create: `src/codebase_index/scaffold.py`
- Create: `tests/test_scaffold.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_scaffold.py
from __future__ import annotations

import json

from codebase_index import scaffold


def test_materialize_skill_writes_all_template_files(tmp_path):
    written = scaffold.materialize_skill(tmp_path, force=False)
    dest = tmp_path / ".claude" / "skills" / "codebase-index"
    assert (dest / "SKILL.md").is_file()
    assert (dest / "scripts" / "cbx").is_file()
    assert (dest / "scripts" / "cbx.ps1").is_file()
    # returns the list of written files
    assert (dest / "SKILL.md") in written


def test_materialize_skill_refuses_existing_without_force(tmp_path):
    scaffold.materialize_skill(tmp_path, force=False)
    try:
        scaffold.materialize_skill(tmp_path, force=False)
        assert False, "expected FileExistsError"
    except FileExistsError:
        pass
    # force overwrites cleanly
    scaffold.materialize_skill(tmp_path, force=True)


def test_write_config_emits_resolved_defaults(tmp_path):
    path = scaffold.write_config(tmp_path, force=False)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["root"] == "."
    assert data["retrieval"]["default_mode"] == "hybrid"
    assert data["embeddings"]["enabled"] is False
    # idempotent: not overwritten without force
    path.write_text('{"root": "custom"}', encoding="utf-8")
    scaffold.write_config(tmp_path, force=False)
    assert json.loads(path.read_text(encoding="utf-8"))["root"] == "custom"


def test_merge_gitignore_is_idempotent(tmp_path):
    changed_first = scaffold.merge_gitignore(tmp_path)
    text = (tmp_path / ".gitignore").read_text(encoding="utf-8")
    assert ".claude/cache/codebase-index/" in text
    assert changed_first is True
    # running again does not duplicate the block
    changed_second = scaffold.merge_gitignore(tmp_path)
    assert changed_second is False
    assert text.count(".claude/cache/codebase-index/") == 1


def test_write_hooks_example(tmp_path):
    path = scaffold.write_hooks_example(tmp_path)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert "PostToolUse" in data["hooks"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_scaffold.py -v`
Expected: FAIL — `ModuleNotFoundError: codebase_index.scaffold`.

- [ ] **Step 3: Write minimal implementation**

```python
# src/codebase_index/scaffold.py
"""Materialize the bundled skill template into a project's `.claude/` tree.

Pure filesystem helpers used by the `init` CLI command. The template is read from
the wheel via importlib.resources, so it works in editable and zip installs alike.
"""

from __future__ import annotations

import stat
from importlib import resources
from importlib.resources.abc import Traversable
from pathlib import Path

from .config import Config

SKILL_REL = Path(".claude") / "skills" / "codebase-index"
CACHE_REL = Path(".claude") / "cache" / "codebase-index"
_CACHE_IGNORE_LINE = ".claude/cache/codebase-index/"
_GITIGNORE_BLOCK = (
    "\n# codebase-index cache (machine-local; do not commit)\n"
    f"{_CACHE_IGNORE_LINE}\n"
)


def _template_root() -> Traversable:
    return resources.files("codebase_index") / "skill_template"


def _iter_template(node: Traversable, prefix: str = "") -> "list[tuple[str, Traversable]]":
    """Depth-first list of (relative-posix-path, file) under a template dir."""
    out: list[tuple[str, Traversable]] = []
    for child in node.iterdir():
        rel = f"{prefix}{child.name}"
        if child.is_dir():
            out.extend(_iter_template(child, prefix=f"{rel}/"))
        else:
            out.append((rel, child))
    return out


def materialize_skill(root: Path, *, force: bool) -> list[Path]:
    """Copy the whole skill template to `<root>/.claude/skills/codebase-index/`."""
    dest = root / SKILL_REL
    if dest.exists() and not force:
        raise FileExistsError(dest)

    written: list[Path] = []
    for rel, node in _iter_template(_template_root()):
        target = dest / Path(rel)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(node.read_bytes())
        if rel == "scripts/cbx":  # make the POSIX wrapper executable
            target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
        written.append(target)
    return written


def write_config(root: Path, *, force: bool) -> Path:
    """Write resolved defaults to `<root>/.claude/cache/codebase-index/config.json`."""
    path = root / CACHE_REL / "config.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not force:
        return path
    cfg = Config()  # built-in defaults; `root` stays "." (resolved at load time)
    path.write_text(cfg.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path


def merge_gitignore(root: Path) -> bool:
    """Append the cache-ignore block to `<root>/.gitignore` if absent. Returns True if changed."""
    path = root / ".gitignore"
    existing = path.read_text(encoding="utf-8") if path.exists() else ""
    if _CACHE_IGNORE_LINE in existing:
        return False
    sep = "" if existing.endswith("\n") or existing == "" else "\n"
    path.write_text(existing + sep + _GITIGNORE_BLOCK, encoding="utf-8")
    return True


def write_hooks_example(root: Path) -> Path:
    """Copy the hooks example next to the installed skill (for manual `--with-hooks` review)."""
    src = _template_root() / "examples" / "hooks" / "settings.json"
    path = root / SKILL_REL / "examples" / "hooks" / "settings.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(src.read_bytes())
    return path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_scaffold.py -v`
Expected: PASS (5 tests). If `importlib.resources.abc` import fails on Python 3.10, use `from importlib.abc import Traversable` instead (it moved in 3.11).

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/scaffold.py tests/test_scaffold.py
git commit -m "feat(scaffold): skill/config/gitignore materialization helpers"
```

---

## Task 3: Wire the `init` command

**Files:**
- Modify: `src/codebase_index/cli.py` (replace the `init` stub)
- Create: `tests/test_init_cli.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_init_cli.py
from __future__ import annotations

import json

from typer.testing import CliRunner

from codebase_index.cli import app

runner = CliRunner()


def _project(tmp_path):
    (tmp_path / ".git").mkdir()
    return tmp_path


def test_init_scaffolds_skill_config_and_gitignore(tmp_path):
    root = _project(tmp_path)
    res = runner.invoke(app, ["--root", str(root), "init"])
    assert res.exit_code == 0, res.output

    skill = root / ".claude" / "skills" / "codebase-index"
    assert (skill / "SKILL.md").is_file()
    assert (skill / "scripts" / "cbx").is_file()
    assert (skill / "scripts" / "cbx.ps1").is_file()

    cfg = root / ".claude" / "cache" / "codebase-index" / "config.json"
    assert json.loads(cfg.read_text(encoding="utf-8"))["root"] == "."

    gitignore = (root / ".gitignore").read_text(encoding="utf-8")
    assert ".claude/cache/codebase-index/" in gitignore
    # the human-facing summary mentions next steps
    assert "codebase-index index" in res.output


def test_init_refuses_existing_without_force(tmp_path):
    root = _project(tmp_path)
    assert runner.invoke(app, ["--root", str(root), "init"]).exit_code == 0
    res = runner.invoke(app, ["--root", str(root), "init"])
    assert res.exit_code != 0
    assert "--force" in res.output


def test_init_force_overwrites(tmp_path):
    root = _project(tmp_path)
    runner.invoke(app, ["--root", str(root), "init"])
    res = runner.invoke(app, ["--root", str(root), "init", "--force"])
    assert res.exit_code == 0, res.output


def test_init_with_hooks_writes_example(tmp_path):
    root = _project(tmp_path)
    res = runner.invoke(app, ["--root", str(root), "init", "--with-hooks"])
    assert res.exit_code == 0, res.output
    hook = root / ".claude" / "skills" / "codebase-index" / "examples" / "hooks" / "settings.json"
    assert hook.is_file()
    assert "hook" in res.output.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_init_cli.py -v`
Expected: FAIL — `init` prints `not implemented` (exit 0, no files), assertions fail.

- [ ] **Step 3: Write minimal implementation**

Replace the `init` command in `src/codebase_index/cli.py` (it currently calls `_todo("init")`). Note the signature gains `ctx` so `--root` resolves:

```python
# src/codebase_index/cli.py  — replace `init`

@app.command()
def init(
    ctx: typer.Context,
    force: bool = typer.Option(False, "--force", help="Overwrite an existing skill install."),
    with_hooks: bool = typer.Option(False, "--with-hooks", help="Also write a hooks example to review."),
) -> None:
    """Scaffold the skill, config.json, and .gitignore rules into the current project."""
    from . import scaffold
    from .config import find_root

    root_opt = ctx.obj.get("root") if ctx.obj else None
    root = Path(root_opt).resolve() if root_opt else find_root()

    try:
        scaffold.materialize_skill(root, force=force)
    except FileExistsError:
        typer.echo(
            "[codebase-index] skill already installed at "
            f"{root / scaffold.SKILL_REL}. Re-run with --force to overwrite."
        )
        raise typer.Exit(code=1)

    cfg_path = scaffold.write_config(root, force=force)
    gitignore_changed = scaffold.merge_gitignore(root)

    lines = [
        f"Installed skill   → {root / scaffold.SKILL_REL}",
        f"Wrote config      → {cfg_path}",
        f".gitignore        → {'updated' if gitignore_changed else 'already covered'}",
    ]
    if with_hooks:
        hook_path = scaffold.write_hooks_example(root)
        lines.append(f"Hooks example     → {hook_path} (review, then merge into .claude/settings.json)")

    lines += [
        "",
        "Next steps:",
        "  1. codebase-index index      # build the index",
        "  2. codebase-index stats       # verify coverage",
        "  3. Ask a codebase question in Claude Code — the skill auto-invokes.",
    ]
    typer.echo("\n".join(lines))
```

> The `init` command is intentionally **not** exposed through the `cbx` wrapper (scaffolding stays a manual human action — see SECURITY.md §5).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_init_cli.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/cli.py tests/test_init_cli.py
git commit -m "feat(cli): implement init (skill + config + gitignore + hooks example)"
```

---

## Task 4: `indexer/freshness.py` — compute staleness

**Files:**
- Create: `src/codebase_index/indexer/freshness.py`
- Modify: `src/codebase_index/storage/repo.py`
- Create: `tests/test_freshness.py`
- Modify: `tests/test_storage.py`

- [ ] **Step 1: Write the failing test (storage accessor)**

Append to `tests/test_storage.py` (reuses the `_open` helper + `repo` import present from M1):

```python
# tests/test_storage.py  (append)
def test_path_mtimes_returns_indexed_paths(tmp_path):
    db = _open(tmp_path)
    repo.upsert_file(
        db.conn, path="src/a.py", lang="python", size_bytes=1, sha256="a",
        mtime_ns=111, git_status=None, parser="line", indexed_at="t", is_generated=False,
    )
    repo.upsert_file(
        db.conn, path="src/b.py", lang="python", size_bytes=1, sha256="b",
        mtime_ns=222, git_status=None, parser="line", indexed_at="t", is_generated=False,
    )
    mtimes = repo.path_mtimes(db.conn)
    assert mtimes == {"src/a.py": 111, "src/b.py": 222}
    db.close()
```

- [ ] **Step 2: Write the failing test (freshness)**

```python
# tests/test_freshness.py
from __future__ import annotations

from codebase_index.config import Config
from codebase_index.indexer.freshness import compute_freshness
from codebase_index.indexer.pipeline import build_index
from codebase_index.storage.db import Database


def _indexed(sample_repo, tmp_path):
    cfg = Config()
    cfg.root = str(sample_repo)
    db = Database(tmp_path / "index.sqlite").open()
    build_index(cfg, db, root=sample_repo)
    return cfg, db


def test_missing_index_is_not_fresh(tmp_path):
    db = Database(tmp_path / "index.sqlite").open()
    fr = compute_freshness(db.conn, tmp_path, Config())
    assert fr.exists is False and fr.stale is False
    db.close()


def test_freshly_built_index_is_not_stale(sample_repo, tmp_path):
    cfg, db = _indexed(sample_repo, tmp_path)
    fr = compute_freshness(db.conn, sample_repo, cfg)
    assert fr.exists is True
    assert fr.stale is False
    assert fr.files_changed_since_build == 0
    db.close()


def test_edited_file_makes_index_stale(sample_repo, tmp_path, monkeypatch):
    """An indexed file whose mtime advanced past the build is counted as changed."""
    cfg, db = _indexed(sample_repo, tmp_path)

    # Simulate the index having been built in the past so the current tree looks newer.
    from codebase_index.storage import repo
    indexed = repo.path_mtimes(db.conn)
    a_path = next(iter(indexed))
    repo.set_meta(db.conn, "head_commit", "deadbeef")  # force git fast-path miss
    db.conn.execute("UPDATE files SET mtime_ns = 1 WHERE path = ?", (a_path,))
    db.conn.commit()

    fr = compute_freshness(db.conn, sample_repo, cfg)
    assert fr.stale is True
    assert fr.files_changed_since_build >= 1
    db.close()
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_storage.py::test_path_mtimes_returns_indexed_paths tests/test_freshness.py -v`
Expected: FAIL — `repo.path_mtimes` missing; `codebase_index.indexer.freshness` missing.

- [ ] **Step 4: Write minimal implementation (storage accessor)**

Append to `src/codebase_index/storage/repo.py`:

```python
# src/codebase_index/storage/repo.py  (append)

def path_mtimes(conn: sqlite3.Connection) -> dict[str, int]:
    """Map every indexed file's repo-relative path to its stored mtime_ns."""
    return {
        row["path"]: int(row["mtime_ns"])
        for row in conn.execute("SELECT path, mtime_ns FROM files").fetchall()
    }
```

- [ ] **Step 5: Write minimal implementation (freshness)**

```python
# src/codebase_index/indexer/freshness.py
"""Compute index freshness for the `index` block of every response.

Contract (consumed by SKILL.md step 2):
  exists -> a build has happened (meta.built_at present).
  stale  -> the working tree differs from what was indexed.
  files_changed_since_build -> how many indexable files differ.

Strategy:
  * Git fast-path: if the repo is a clean git tree AT the indexed commit, nothing
    changed -> not stale (cheap; no walk).
  * Accurate fallback (dirty tree, different commit, or no git): walk the current
    indexable set and diff (path, mtime_ns) against the `files` table. This reuses
    the discovery gates, so ignored/secret/binary files never count as changes.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

from ..config import Config
from ..discovery.walker import walk
from ..models import IndexFreshness
from ..storage import repo


def compute_freshness(conn, root: Path, config: Config) -> IndexFreshness:
    built_at = repo.get_meta(conn, "built_at")
    if built_at is None:
        return IndexFreshness(exists=False, stale=False)

    head = repo.get_meta(conn, "head_commit")
    root = Path(root)

    if _git_clean_at(root, head):
        changed = 0
    else:
        changed = _changed_count(conn, root, config)

    return IndexFreshness(
        exists=True,
        stale=changed > 0,
        files_changed_since_build=changed,
        built_at=built_at,
        head_commit=head,
    )


def _changed_count(conn, root: Path, config: Config) -> int:
    """Added + removed + mtime-modified indexable files vs. the index."""
    current: dict[str, int] = {}
    for cand in walk(root, config):
        try:
            current[cand.rel_path] = cand.path.stat().st_mtime_ns
        except OSError:
            continue
    indexed = repo.path_mtimes(conn)

    changed = 0
    for path, mtime in current.items():
        if path not in indexed or indexed[path] != mtime:
            changed += 1
    for path in indexed:
        if path not in current:
            changed += 1
    return changed


def _git_clean_at(root: Path, indexed_head: "str | None") -> bool:
    """True iff git is available, HEAD == indexed_head, and the tree has no changes."""
    if indexed_head is None or not (root / ".git").exists():
        return False
    try:
        head = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=5, check=False,
        )
        if head.returncode != 0 or head.stdout.strip() != indexed_head:
            return False
        status = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            capture_output=True, text=True, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return False
    return status.returncode == 0 and status.stdout.strip() == ""
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `pytest tests/test_storage.py tests/test_freshness.py -v`
Expected: PASS. (The `sample_repo` fixture has no `.git`, so the accurate path runs and a freshly built index reports 0 changes; the edited-mtime test reports ≥1.)

- [ ] **Step 7: Commit**

```bash
git add src/codebase_index/indexer/freshness.py src/codebase_index/storage/repo.py tests/test_freshness.py tests/test_storage.py
git commit -m "feat(indexer): compute index freshness (git fast-path + mtime diff)"
```

---

## Task 5: Wire freshness into search responses + CLI

**Files:**
- Modify: `src/codebase_index/retrieval/searchers.py`
- Modify: `src/codebase_index/cli.py` (pass `config` into `fts_response`)
- Modify: `tests/test_search_cli.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_search_cli.py` (reuses the existing `sample_repo` fixture + `CliRunner`; mirror the import style already in that file):

```python
# tests/test_search_cli.py  (append)
import json as _json


def test_search_reports_stale_after_edit(sample_repo, tmp_path, monkeypatch):
    from typer.testing import CliRunner

    from codebase_index.cli import app

    runner = CliRunner()
    # build the index
    assert runner.invoke(app, ["--root", str(sample_repo), "index"]).exit_code == 0

    # fresh: not stale
    res = runner.invoke(app, ["--root", str(sample_repo), "--json", "search", "token"])
    assert res.exit_code == 0, res.output
    fresh = _json.loads(res.output)
    assert fresh["index"]["exists"] is True
    assert fresh["index"]["stale"] is False

    # mark the stored mtimes stale so the current tree looks newer, drop the head pin
    db_path = sample_repo / ".claude" / "cache" / "codebase-index" / "index.sqlite"
    import sqlite3
    conn = sqlite3.connect(db_path)
    conn.execute("UPDATE files SET mtime_ns = 1")
    conn.execute("DELETE FROM meta WHERE key = 'head_commit'")
    conn.commit()
    conn.close()

    res2 = runner.invoke(app, ["--root", str(sample_repo), "--json", "search", "token"])
    stale = _json.loads(res2.output)
    assert stale["index"]["stale"] is True
    assert stale["index"]["files_changed_since_build"] >= 1
```

> Clean up the cache the test wrote: if `test_search_cli.py` lacks an autouse cleanup for `sample_repo / ".claude"`, add one (the M2 CLI tests already build the index under the fixture). Prefer pointing `index` at `tmp_path` if the existing tests do; match the surrounding pattern.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_search_cli.py::test_search_reports_stale_after_edit -v`
Expected: FAIL — `stale` is always `False` (the current `_freshness` hardcodes it).

- [ ] **Step 3: Write minimal implementation**

In `src/codebase_index/retrieval/searchers.py`, thread `config` through and delegate freshness. Add the import and an optional `Config` param:

```python
# src/codebase_index/retrieval/searchers.py  — imports
from ..config import Config
from ..indexer.freshness import compute_freshness
```

Change `fts_response` to accept `config` and use the real freshness when it (and `root`) are present:

```python
def fts_response(
    conn: sqlite3.Connection,
    query: str,
    *,
    limit: int,
    token_budget: int,
    root: Path,
    config: Optional[Config] = None,
) -> SearchResponse:
    candidates = fts_search(conn, query, limit=limit)
    # ... unchanged result/recommended assembly ...

    confidence = _confidence(candidates)
    return SearchResponse(
        query=query,
        intent="keyword",
        index=_freshness(conn, root, config),
        confidence=confidence,
        results=results,
        recommended_reads=recommended,
        fallback_suggestions=_fallbacks(query) if confidence != "high" else {},
    )
```

> Remove the `del root` line — `root` is now used.

Replace the `_freshness` helper:

```python
def _freshness(
    conn: sqlite3.Connection, root: Path, config: Optional[Config]
) -> IndexFreshness:
    if config is not None:
        return compute_freshness(conn, root, config)
    # Back-compat for callers that don't pass config (e.g. unit tests): meta-only view.
    built_at = repo.get_meta(conn, "built_at")
    return IndexFreshness(
        exists=built_at is not None,
        stale=False,
        files_changed_since_build=0,
        built_at=built_at,
        head_commit=repo.get_meta(conn, "head_commit"),
    )
```

In `src/codebase_index/cli.py`, pass the loaded config from the `search` command:

```python
# src/codebase_index/cli.py  — inside `search`, in the fts_response call
        resp = fts_response(
            db.conn,
            query,
            limit=limit,
            token_budget=token_budget,
            root=Path(cfg.root),
            config=cfg,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_search_cli.py -v`
Expected: PASS (existing M2 search-CLI tests + the new staleness test). If an M2 test asserted `index.stale is False` on a built index with no `.git`, it still holds (a freshly built index reports 0 changes).

- [ ] **Step 5: Run the searcher unit tests**

Run: `pytest tests/test_searchers.py -v`
Expected: PASS — they call `fts_response` without `config`, which now takes the meta-only back-compat path.

- [ ] **Step 6: Commit**

```bash
git add src/codebase_index/retrieval/searchers.py src/codebase_index/cli.py tests/test_search_cli.py
git commit -m "feat(retrieval): honor freshness contract in search responses"
```

---

## Task 6: Full suite, lint, manual QA, docs

**Files:**
- Modify: `docs/ROADMAP.md` (mark M7 done)
- Modify: `docs/INSTALLATION.md` (correct the `--with-hooks` description for M7 scope)

- [ ] **Step 1: Run the whole suite**

Run: `pytest -v`
Expected: all M0–M7 tests PASS.

- [ ] **Step 2: Lint + type-check**

Run: `ruff check src tests` and `mypy src/codebase_index`
Expected: clean.

- [ ] **Step 3: Manual QA on a scratch copy of this repo**

```bash
# in a throwaway clone / worktree so we don't dirty the working tree:
pip install -e .
codebase-index --root . init
test -f .claude/skills/codebase-index/SKILL.md && echo "skill OK"
test -f .claude/skills/codebase-index/scripts/cbx && echo "cbx OK"
grep -q ".claude/cache/codebase-index/" .gitignore && echo "gitignore OK"

codebase-index --root . index
codebase-index --root . --json search "freshness" | python -c "import sys,json; d=json.load(sys.stdin); print('exists', d['index']['exists'], 'stale', d['index']['stale'])"

# edit a file, then confirm the index reports stale
echo "# touch" >> src/codebase_index/cli.py
codebase-index --root . --json search "freshness" | python -c "import sys,json; d=json.load(sys.stdin); print('stale', d['index']['stale'], 'changed', d['index']['files_changed_since_build'])"

# wrapper refuses destructive subcommands
.claude/skills/codebase-index/scripts/cbx clean ; echo "exit=$?"   # expect exit=2

codebase-index --root . update
codebase-index --root . --json search "freshness" | python -c "import sys,json; d=json.load(sys.stdin); print('stale-after-update', d['index']['stale'])"
```

Expected: `init` writes the skill/config/gitignore; a fresh index reports `stale false`; editing a file flips `stale true` with `files_changed_since_build >= 1`; the `cbx` wrapper exits `2` for `clean`; after `update` the index reports `stale false` again. Revert the scratch edit.

- [ ] **Step 4: Update docs**

Edit `docs/ROADMAP.md`:
- Change the M7 heading to `## M7 — Claude Code Skill packaging ✅`.
- Append under it: *"Shipped: `init` materializes the wheel-bundled skill template (SKILL.md + cbx/cbx.ps1) to `.claude/skills/codebase-index/`, writes resolved `config.json`, and idempotently gitignores the cache (`--force` to overwrite). The freshness contract is honored end-to-end — `search` returns real `stale`/`files_changed_since_build` (git clean-tree fast-path + mtime diff), so the skill triggers `update`/`index` per SKILL.md. `--with-hooks` writes a reviewable hooks example; auto-merging hooks + `watch` are M8."*

Edit `docs/INSTALLATION.md` §2 and §6 to match the shipped `--with-hooks` behavior: it **writes a reviewable `examples/hooks/settings.json` into the skill dir and prints the enable instructions** (it does not yet auto-merge into `.claude/settings.json` — that is M8).

- [ ] **Step 5: Commit**

```bash
git add docs/ROADMAP.md docs/INSTALLATION.md
git commit -m "docs: mark M7 complete + correct --with-hooks scope"
```

---

## Acceptance Criteria (M7 exit)

- The skill template (SKILL.md + `scripts/cbx` + `scripts/cbx.ps1` + hooks example) ships inside the wheel and is discoverable via `importlib.resources`; `skill_template/SKILL.md` stays byte-identical to `skill/SKILL.md`.
- `codebase-index init` writes `.claude/skills/codebase-index/{SKILL.md,scripts/cbx,scripts/cbx.ps1}`, a resolved `.claude/cache/codebase-index/config.json`, and an idempotent `.gitignore` cache rule; `--force` overwrites, a second run without `--force` refuses with a clear message and non-zero exit; `--with-hooks` writes the reviewable hooks example.
- `codebase-index search` (and any `fts_response` caller passing `config`) returns a real `index` block: `stale=false`/`files_changed_since_build=0` on a freshly built clean tree; `stale=true` with a positive count after an indexed file changes; `exists=false` when no build exists.
- The git clean-tree fast-path avoids a walk when HEAD matches the indexed commit and the tree is clean; the mtime diff is accurate otherwise and never counts ignored/secret/binary files (it reuses `discovery.walk`).
- Fresh `init` → `index` → ask a codebase question in Claude Code returns compact `recommended_reads`; the `cbx` wrapper exits `2` on `clean`/`init`/`watch`.
- Full `pytest` green; `ruff` clean; `mypy` clean; base install network-free.

## Deferred to later milestones (explicitly NOT in M7)

- Auto-merging the hooks example into `.claude/settings.json` and `watch` mode — **M8** (`init --with-hooks` here only writes a reviewable example).
- `doctor` reporting enabled hooks / cache-gitignore status — **M8/M9** (the SECURITY.md doctor checklist).
- Smarter incremental freshness (per-file content hashing, partial walks, debounced caching of the freshness result) — M8 alongside `watch`/hooks; M7 uses a full walk on the accurate path.
- Wiring freshness into `explain`/`symbol`/`refs`/`impact` responses — those commands land/extend in M3–M5; once present, they should call `compute_freshness` the same way `search` now does (one-line change each).
- PyPI release + `pipx install` clean-machine verification — **M9**.
```