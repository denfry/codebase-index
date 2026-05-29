# M7.5 — One-Command Plugin Install Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn this repo into a Claude Code plugin so a user installs the `codebase-index` skill with one action (`/plugin install codebase-index@<marketplace>` or a chat request), with the Python CLI auto-provisioned on first session start — no manual `pip`/`init`/`index`.

**Architecture:** A `SessionStart` hook runs `scripts/bootstrap.sh`/`.ps1`, which provisions a Python venv into the persistent `${CLAUDE_PLUGIN_DATA}` (reinstalling only when the bundled `requirements.lock` changes — the official diff-pattern) and writes a `.venv-path` pointer file. The plugin's `bin/` wrappers (`cbx`, `codebase-index`) are auto-added to the Bash tool's PATH; they read that pointer to exec the venv CLI while keeping the existing subcommand whitelist. The skill itself (`skills/codebase-index/SKILL.md`) already triggers the first `index` via the freshness contract.

**Tech Stack:** Claude Code plugin spec (`.claude-plugin/plugin.json` + `marketplace.json`, `hooks/hooks.json`, `bin/`), POSIX bash + PowerShell 7 bootstrap, Python 3.10+ venv (uv-preferred, `python -m venv`+pip fallback), pytest for manifest/wrapper/bootstrap tests.

**Why a pointer file:** Per the plugins reference, `${CLAUDE_PLUGIN_ROOT}` / `${CLAUDE_PLUGIN_DATA}` are exported only to **hook, MCP, and LSP subprocesses** — *not* to `bin/` executables invoked via the Bash tool. The hook (which does get `${CLAUDE_PLUGIN_DATA}`) writes the resolved venv path into `${CLAUDE_PLUGIN_ROOT}/.venv-path`; the wrappers resolve their own directory and read `../.venv-path`. The pointer is rewritten every session (ROOT is per-version/ephemeral; never durable state).

**Prerequisite (documented, not solved here):** the package must be installable as `codebase-index==0.1.0` from PyPI (M9). Until then, set `CBX_INSTALL_SPEC` to a local path or git ref. The bootstrap honors `CBX_INSTALL_SPEC` (install source) and `CBX_NO_UV=1` (force the pip fallback) — both used by tests.

---

## File Structure

| File | Create/Modify | Responsibility |
|---|---|---|
| `.claude-plugin/plugin.json` | Create | Plugin manifest (name, version, description, author, repository). |
| `.claude-plugin/marketplace.json` | Create | In-repo marketplace catalog; lists this plugin with `source: "./"`. |
| `requirements.lock` | Create | Single pinned spec line; the bootstrap diff sentinel. |
| `hooks/hooks.json` | Create | `SessionStart` → run `scripts/bootstrap.sh`. |
| `scripts/bootstrap.sh` | Create | POSIX: provision venv in `${CLAUDE_PLUGIN_DATA}`, write `.venv-path`, diff-reinstall. |
| `scripts/bootstrap.ps1` | Create | Windows equivalent of the bootstrap. |
| `bin/cbx` | Create | POSIX whitelist wrapper; execs the venv CLI via the `.venv-path` pointer. |
| `bin/cbx.ps1` | Create | Windows whitelist wrapper. |
| `bin/codebase-index` | Create | POSIX shim → execs `cbx` (lets the byte-identical SKILL.md call `codebase-index`). |
| `bin/codebase-index.ps1` | Create | Windows shim → execs `cbx.ps1`. |
| `skills/codebase-index/SKILL.md` | Create | Plugin skill; byte-identical copy of `skill/SKILL.md` (parity-tested). |
| `tests/test_plugin_manifest.py` | Create | Manifest + marketplace + lock-pin consistency. |
| `tests/test_plugin_wrappers.py` | Create | `cbx` refuses destructive subcommands; resolves venv via pointer. |
| `tests/test_bootstrap.py` | Create | Bootstrap: cold install, warm no-op, lock-change reinstall, missing-Python message. |
| `tests/test_plugin_skill_parity.py` | Create | `skills/codebase-index/SKILL.md` == `skill/SKILL.md`. |
| `README.md` | Modify | Transparency section: what bootstrap downloads + where; one-command install. |
| `docs/ROADMAP.md` | Modify | Add the M7.5 milestone entry. |

**Conventions:** `from __future__ import annotations` at the top of every test module; tests are pure-stdlib + pytest; no network in tests (bootstrap is driven with fake `python`/`uv` shims).

---

## Task 1: Plugin manifest + marketplace catalog

**Files:**
- Create: `.claude-plugin/plugin.json`
- Create: `.claude-plugin/marketplace.json`
- Create: `tests/test_plugin_manifest.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_plugin_manifest.py
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _load(rel: str) -> dict:
    return json.loads((ROOT / rel).read_text(encoding="utf-8"))


def test_plugin_manifest_has_required_fields():
    m = _load(".claude-plugin/plugin.json")
    assert m["name"] == "codebase-index"
    assert m["version"]
    assert m["description"]


def test_marketplace_lists_plugin_from_repo_root():
    mk = _load(".claude-plugin/marketplace.json")
    assert mk["name"]
    assert "owner" in mk
    entries = {p["name"]: p for p in mk["plugins"]}
    assert "codebase-index" in entries
    assert entries["codebase-index"]["source"] == "./"


def test_plugin_version_matches_pyproject():
    pyproject = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    ver = re.search(r'^version = "([^"]+)"', pyproject, re.MULTILINE).group(1)
    assert _load(".claude-plugin/plugin.json")["version"] == ver
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_plugin_manifest.py -v`
Expected: FAIL — `.claude-plugin/plugin.json` does not exist (FileNotFoundError).

- [ ] **Step 3: Create the manifest**

```json
// .claude-plugin/plugin.json
{
  "$schema": "https://json.schemastore.org/claude-code-plugin-manifest.json",
  "name": "codebase-index",
  "displayName": "Codebase Index",
  "description": "Local-first hybrid codebase index. Auto-provisions its Python CLI on first session start; the skill searches the index so Claude reads only the most relevant files.",
  "version": "0.1.0",
  "author": { "name": "codebase-index contributors" },
  "repository": "https://github.com/your-org/codebase-index",
  "license": "MIT",
  "keywords": ["code-search", "tree-sitter", "rag", "sqlite", "fts5"]
}
```

- [ ] **Step 4: Create the marketplace catalog**

```json
// .claude-plugin/marketplace.json
{
  "name": "codebase-index",
  "owner": { "name": "codebase-index contributors" },
  "plugins": [
    {
      "name": "codebase-index",
      "source": "./",
      "description": "Local-first hybrid codebase index skill with auto-provisioned CLI."
    }
  ]
}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest tests/test_plugin_manifest.py -v`
Expected: PASS (3 tests). If `test_plugin_version_matches_pyproject` fails, the `version` in `plugin.json` must equal the `version` in `pyproject.toml` (currently `0.1.0`).

- [ ] **Step 6: Commit**

```bash
git add .claude-plugin/plugin.json .claude-plugin/marketplace.json tests/test_plugin_manifest.py
git commit -m "feat(plugin): add plugin.json manifest + in-repo marketplace catalog"
```

---

## Task 2: Pinned `requirements.lock` (bootstrap diff sentinel)

**Files:**
- Create: `requirements.lock`
- Modify: `tests/test_plugin_manifest.py`

- [ ] **Step 1: Add the failing test**

Append to `tests/test_plugin_manifest.py`:

```python
# tests/test_plugin_manifest.py  (append)
def test_requirements_lock_pins_package_version():
    version = _load(".claude-plugin/plugin.json")["version"]
    lock = (ROOT / "requirements.lock").read_text(encoding="utf-8").strip()
    assert lock == f"codebase-index=={version}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_plugin_manifest.py::test_requirements_lock_pins_package_version -v`
Expected: FAIL — `requirements.lock` does not exist.

- [ ] **Step 3: Create the lock file**

```text
// requirements.lock
codebase-index==0.1.0
```

(Single line, trailing newline. The pin must equal the `plugin.json` version so the diff sentinel and the install spec stay in lockstep.)

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_plugin_manifest.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add requirements.lock tests/test_plugin_manifest.py
git commit -m "feat(plugin): pin install spec in requirements.lock"
```

---

## Task 3: `bin/` wrappers — whitelist + venv resolution

**Files:**
- Create: `bin/cbx`
- Create: `bin/codebase-index`
- Create: `bin/cbx.ps1`
- Create: `bin/codebase-index.ps1`
- Create: `tests/test_plugin_wrappers.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_plugin_wrappers.py
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BASH = shutil.which("bash")


def _stage_plugin(tmp_path: Path) -> Path:
    """Copy bin/cbx into a throwaway plugin tree so tests never touch the repo."""
    dst = tmp_path / "plugin"
    (dst / "bin").mkdir(parents=True)
    shutil.copy(ROOT / "bin" / "cbx", dst / "bin" / "cbx")
    (dst / "bin" / "cbx").chmod(0o755)
    return dst


@pytest.mark.skipif(BASH is None, reason="bash not available")
def test_cbx_refuses_destructive_subcommand(tmp_path):
    plugin = _stage_plugin(tmp_path)
    res = subprocess.run(
        [BASH, str(plugin / "bin" / "cbx"), "clean"],
        capture_output=True, text=True,
    )
    assert res.returncode == 2
    assert "refusing" in res.stderr


@pytest.mark.skipif(BASH is None, reason="bash not available")
def test_cbx_execs_venv_cli_via_pointer(tmp_path):
    plugin = _stage_plugin(tmp_path)

    # Fake venv whose codebase-index echoes its args.
    venv = tmp_path / "data" / "venv"
    (venv / "bin").mkdir(parents=True)
    stub = venv / "bin" / "codebase-index"
    stub.write_text('#!/usr/bin/env bash\necho "CBXSTUB $*"\n', encoding="utf-8")
    stub.chmod(0o755)

    # Pointer file the wrapper reads (bin/../.venv-path).
    (plugin / ".venv-path").write_text(str(venv) + "\n", encoding="utf-8")

    res = subprocess.run(
        [BASH, str(plugin / "bin" / "cbx"), "search", "foo"],
        capture_output=True, text=True,
    )
    assert res.returncode == 0, res.stderr
    assert "CBXSTUB search foo" in res.stdout
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_plugin_wrappers.py -v`
Expected: FAIL — `bin/cbx` does not exist (shutil.copy raises FileNotFoundError).

- [ ] **Step 3: Create `bin/cbx`**

```bash
#!/usr/bin/env bash
# Plugin wrapper: whitelist-guards subcommands, then execs the codebase-index CLI
# from the venv provisioned by scripts/bootstrap.sh (located via the .venv-path pointer).
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

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
venv=""
if [ -f "$here/../.venv-path" ]; then
  venv="$(cat "$here/../.venv-path")"
fi

if [ -n "$venv" ] && [ -x "$venv/bin/codebase-index" ]; then
  exec "$venv/bin/codebase-index" "$@"
elif [ -n "$venv" ] && [ -x "$venv/Scripts/codebase-index.exe" ]; then
  exec "$venv/Scripts/codebase-index.exe" "$@"
elif command -v codebase-index >/dev/null 2>&1; then
  exec codebase-index "$@"
else
  exec python -m codebase_index "$@"
fi
```

- [ ] **Step 4: Create `bin/codebase-index` (shim)**

```bash
#!/usr/bin/env bash
# Alias for cbx so a byte-identical SKILL.md (which calls `codebase-index`) works
# inside the plugin while keeping the same subcommand whitelist and venv resolution.
exec "$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/cbx" "$@"
```

- [ ] **Step 5: Create `bin/cbx.ps1`**

```powershell
# Windows plugin wrapper around the venv-provisioned codebase-index CLI.
# Mirrors bin/cbx: whitelists subcommands, resolves the venv via the .venv-path pointer.
param(
    [Parameter(Mandatory = $true, Position = 0)] [string]$Subcommand,
    [Parameter(ValueFromRemainingArguments = $true)] [string[]]$Rest
)
$ErrorActionPreference = "Stop"
$allowed = @("search", "explain", "symbol", "refs", "impact", "stats", "update", "index")
if ($allowed -notcontains $Subcommand) {
    Write-Error "cbx: refusing subcommand '$Subcommand'. Allowed: $($allowed -join ', ')"
    exit 2
}

$here = Split-Path -Parent $MyInvocation.MyCommand.Path
$pointer = Join-Path $here "..\.venv-path"
$venv = if (Test-Path $pointer) { (Get-Content $pointer -Raw).Trim() } else { "" }

if ($venv) {
    $winCli = Join-Path $venv "Scripts\codebase-index.exe"
    $nixCli = Join-Path $venv "bin\codebase-index"
    if (Test-Path $winCli) { & $winCli $Subcommand @Rest; exit $LASTEXITCODE }
    if (Test-Path $nixCli) { & $nixCli $Subcommand @Rest; exit $LASTEXITCODE }
}
$bin = Get-Command codebase-index -ErrorAction SilentlyContinue
if ($bin) { & $bin.Source $Subcommand @Rest; exit $LASTEXITCODE }
& python -m codebase_index $Subcommand @Rest
exit $LASTEXITCODE
```

- [ ] **Step 6: Create `bin/codebase-index.ps1` (shim)**

```powershell
# Windows alias for cbx.ps1 (see bin/codebase-index).
param(
    [Parameter(Mandatory = $true, Position = 0)] [string]$Subcommand,
    [Parameter(ValueFromRemainingArguments = $true)] [string[]]$Rest
)
$here = Split-Path -Parent $MyInvocation.MyCommand.Path
& (Join-Path $here "cbx.ps1") $Subcommand @Rest
exit $LASTEXITCODE
```

- [ ] **Step 7: Run test to verify it passes**

Run: `pytest tests/test_plugin_wrappers.py -v`
Expected: PASS (2 tests). If `bash` is unavailable the tests skip — that is acceptable; rely on the Windows QA in Task 8.

- [ ] **Step 8: Commit**

```bash
git add bin/cbx bin/codebase-index bin/cbx.ps1 bin/codebase-index.ps1 tests/test_plugin_wrappers.py
git commit -m "feat(plugin): bin wrappers resolve venv via .venv-path pointer"
```

---

## Task 4: `scripts/bootstrap.sh` — provision venv on SessionStart

**Files:**
- Create: `scripts/bootstrap.sh`
- Create: `tests/test_bootstrap.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_bootstrap.py
from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BASH = shutil.which("bash")

# A fake `python` that satisfies `-m venv DIR` and `-m pip install ...` without network.
FAKE_PYTHON = """#!/usr/bin/env bash
if [ "$1" = "-m" ] && [ "$2" = "venv" ]; then
  mkdir -p "$3/bin"
  cp "$0" "$3/bin/python"
  chmod +x "$3/bin/python"
  exit 0
fi
if [ "$1" = "-m" ] && [ "$2" = "pip" ]; then
  if [ "$3" = "install" ]; then
    d="$(cd "$(dirname "$0")" && pwd)"
    # Only create the CLI for a real package install, not the pip upgrade.
    case " $* " in
      *" --upgrade pip "*) : ;;
      *) printf '#!/usr/bin/env bash\\necho INSTALLED\\n' > "$d/codebase-index"; chmod +x "$d/codebase-index" ;;
    esac
  fi
  exit 0
fi
exit 0
"""


def _stage(tmp_path: Path) -> tuple[Path, Path, dict]:
    root = tmp_path / "root"
    root.mkdir()
    shutil.copy(ROOT / "scripts" / "bootstrap.sh", root / "bootstrap.sh")
    (root / "bootstrap.sh").chmod(0o755)
    (root / "requirements.lock").write_text("codebase-index==0.1.0\n", encoding="utf-8")

    data = tmp_path / "data"
    data.mkdir()

    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    for name in ("python", "python3"):
        p = fakebin / name
        p.write_text(FAKE_PYTHON, encoding="utf-8")
        p.chmod(0o755)

    env = dict(os.environ)
    env["PATH"] = f"{fakebin}{os.pathsep}{env['PATH']}"
    env["CLAUDE_PLUGIN_ROOT"] = str(root)
    env["CLAUDE_PLUGIN_DATA"] = str(data)
    env["CBX_NO_UV"] = "1"  # force the python -m venv + pip fallback
    return root, data, env


def _run(root: Path, env: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [BASH, str(root / "bootstrap.sh")],
        capture_output=True, text=True, env=env,
    )


@pytest.mark.skipif(BASH is None, reason="bash not available")
def test_cold_run_provisions_venv_and_pointer(tmp_path):
    root, data, env = _stage(tmp_path)
    res = _run(root, env)
    assert res.returncode == 0, res.stderr
    assert (data / "venv" / "bin" / "codebase-index").is_file()
    assert (data / "requirements.lock").read_text(encoding="utf-8").strip() == "codebase-index==0.1.0"
    assert (root / ".venv-path").read_text(encoding="utf-8").strip() == str(data / "venv")


@pytest.mark.skipif(BASH is None, reason="bash not available")
def test_warm_run_is_noop(tmp_path):
    root, data, env = _stage(tmp_path)
    assert _run(root, env).returncode == 0
    cli = data / "venv" / "bin" / "codebase-index"
    first_mtime = cli.stat().st_mtime_ns
    assert _run(root, env).returncode == 0
    assert cli.stat().st_mtime_ns == first_mtime  # not reinstalled


@pytest.mark.skipif(BASH is None, reason="bash not available")
def test_lock_change_triggers_reinstall(tmp_path):
    root, data, env = _stage(tmp_path)
    assert _run(root, env).returncode == 0
    (data / "venv" / "bin" / "codebase-index").unlink()  # simulate a stale/removed CLI
    (root / "requirements.lock").write_text("codebase-index==0.2.0\n", encoding="utf-8")
    assert _run(root, env).returncode == 0
    assert (data / "venv" / "bin" / "codebase-index").is_file()
    assert (data / "requirements.lock").read_text(encoding="utf-8").strip() == "codebase-index==0.2.0"


@pytest.mark.skipif(BASH is None, reason="bash not available")
def test_missing_python_reports_clearly(tmp_path):
    root, data, env = _stage(tmp_path)
    env["PATH"] = str(tmp_path / "empty")  # no python anywhere
    (tmp_path / "empty").mkdir()
    res = _run(root, env)
    assert res.returncode == 0  # SessionStart must not hard-fail the session
    assert "Python 3.10+" in res.stderr
    assert not (data / "venv" / "bin" / "codebase-index").exists()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_bootstrap.py -v`
Expected: FAIL — `scripts/bootstrap.sh` does not exist.

- [ ] **Step 3: Write `scripts/bootstrap.sh`**

```bash
#!/usr/bin/env bash
# SessionStart bootstrap for the codebase-index plugin.
# Provisions a Python venv with the codebase-index CLI into ${CLAUDE_PLUGIN_DATA},
# reinstalling only when the bundled requirements.lock changes (official diff-pattern).
# Writes ${CLAUDE_PLUGIN_ROOT}/.venv-path so the bin/ wrappers can locate the venv.
set -euo pipefail

ROOT="${CLAUDE_PLUGIN_ROOT:?CLAUDE_PLUGIN_ROOT not set}"
DATA="${CLAUDE_PLUGIN_DATA:?CLAUDE_PLUGIN_DATA not set}"

VENV="$DATA/venv"
LOCK_SRC="$ROOT/requirements.lock"
LOCK_DST="$DATA/requirements.lock"
SPEC="${CBX_INSTALL_SPEC:-codebase-index==0.1.0}"

mkdir -p "$DATA"
# Pointer the wrappers read. ROOT is per-version/ephemeral, so rewrite it every session.
printf '%s\n' "$VENV" > "$ROOT/.venv-path"

# Warm path: venv present and the lock unchanged -> nothing to do.
if [ -x "$VENV/bin/codebase-index" ] && diff -q "$LOCK_SRC" "$LOCK_DST" >/dev/null 2>&1; then
  exit 0
fi

PY="$(command -v python3 || command -v python || true)"
if [ -z "$PY" ]; then
  echo "codebase-index: Python 3.10+ was not found on PATH. Install Python, then restart Claude Code." >&2
  exit 0
fi

install() {
  if [ "${CBX_NO_UV:-0}" != "1" ] && command -v uv >/dev/null 2>&1; then
    uv venv "$VENV" >&2
    uv pip install --python "$VENV/bin/python" "$SPEC" >&2
  else
    "$PY" -m venv "$VENV" >&2
    "$VENV/bin/python" -m pip install --upgrade pip >&2
    "$VENV/bin/python" -m pip install "$SPEC" >&2
  fi
}

# `install` is called in an `if`, which disables set -e inside it, so a failed
# step returns non-zero here instead of aborting the script.
if install; then
  cp "$LOCK_SRC" "$LOCK_DST"
else
  rm -f "$LOCK_DST"
  echo "codebase-index: bootstrap install failed; will retry next session." >&2
  exit 0
fi
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_bootstrap.py -v`
Expected: PASS (4 tests). If `test_warm_run_is_noop` flakes on identical mtimes, it asserts equality (no reinstall) — the warm path must `exit 0` before touching the CLI.

- [ ] **Step 5: Commit**

```bash
git add scripts/bootstrap.sh tests/test_bootstrap.py
git commit -m "feat(plugin): SessionStart bootstrap provisions venv (diff-pattern)"
```

---

## Task 5: `scripts/bootstrap.ps1` — Windows bootstrap

**Files:**
- Create: `scripts/bootstrap.ps1`
- Modify: `tests/test_bootstrap.py`

- [ ] **Step 1: Add the failing test**

Append to `tests/test_bootstrap.py`:

```python
# tests/test_bootstrap.py  (append)
PWSH = shutil.which("pwsh")


@pytest.mark.skipif(PWSH is None, reason="pwsh not available")
def test_powershell_cold_run_provisions_venv(tmp_path):
    root = tmp_path / "root"
    root.mkdir()
    shutil.copy(ROOT / "scripts" / "bootstrap.ps1", root / "bootstrap.ps1")
    (root / "requirements.lock").write_text("codebase-index==0.1.0\n", encoding="utf-8")
    data = tmp_path / "data"
    data.mkdir()

    # Fake python.bat that satisfies `-m venv DIR` and `-m pip install ...`.
    fakebin = tmp_path / "fakebin"
    fakebin.mkdir()
    (fakebin / "python.bat").write_text(
        "@echo off\r\n"
        'if "%1"=="-m" if "%2"=="venv" (mkdir "%3\\Scripts" & copy "%~f0" "%3\\Scripts\\python.bat" >NUL & exit /b 0)\r\n'
        'if "%1"=="-m" if "%2"=="pip" (\r\n'
        '  echo %* | findstr /C:"--upgrade pip" >NUL && exit /b 0\r\n'
        '  if "%3"=="install" (echo @echo INSTALLED> "%~dp0codebase-index.exe.bat" & exit /b 0)\r\n'
        '  exit /b 0\r\n'
        ")\r\n"
        "exit /b 0\r\n",
        encoding="utf-8",
    )

    env = dict(os.environ)
    env["PATH"] = f"{fakebin}{os.pathsep}{env['PATH']}"
    env["CLAUDE_PLUGIN_ROOT"] = str(root)
    env["CLAUDE_PLUGIN_DATA"] = str(data)
    env["CBX_NO_UV"] = "1"

    res = subprocess.run(
        [PWSH, "-NoProfile", "-File", str(root / "bootstrap.ps1")],
        capture_output=True, text=True, env=env,
    )
    assert res.returncode == 0, res.stderr
    assert (root / ".venv-path").read_text(encoding="utf-8").strip() == str(data / "venv")
```

> The Windows fake-python uses `.bat` because the bootstrap calls the interpreter by name. If `python.bat`/`Scripts\python.bat` resolution proves brittle in CI, gate this test behind an explicit `CBX_RUN_PWSH_BOOTSTRAP=1` env check and rely on the Task 8 manual QA for Windows confirmation. Do not weaken the bootstrap to satisfy the fake.

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_bootstrap.py -k powershell -v`
Expected: FAIL — `scripts/bootstrap.ps1` does not exist (or SKIP if `pwsh` is absent).

- [ ] **Step 3: Write `scripts/bootstrap.ps1`**

```powershell
# SessionStart bootstrap (Windows) for the codebase-index plugin. Mirrors bootstrap.sh.
$ErrorActionPreference = "Stop"
$root = $env:CLAUDE_PLUGIN_ROOT
$data = $env:CLAUDE_PLUGIN_DATA
if (-not $root -or -not $data) { Write-Error "CLAUDE_PLUGIN_ROOT/DATA not set"; exit 0 }

$venv = Join-Path $data "venv"
$lockSrc = Join-Path $root "requirements.lock"
$lockDst = Join-Path $data "requirements.lock"
$spec = if ($env:CBX_INSTALL_SPEC) { $env:CBX_INSTALL_SPEC } else { "codebase-index==0.1.0" }

New-Item -ItemType Directory -Force -Path $data | Out-Null
Set-Content -Path (Join-Path $root ".venv-path") -Value $venv

$cli = Join-Path $venv "Scripts\codebase-index.exe"
if ((Test-Path $cli) -and (Test-Path $lockDst) -and
    ((Get-Content $lockSrc -Raw) -eq (Get-Content $lockDst -Raw))) {
    exit 0
}

$py = Get-Command python -ErrorAction SilentlyContinue
if (-not $py) { $py = Get-Command python3 -ErrorAction SilentlyContinue }
if (-not $py) {
    Write-Error "codebase-index: Python 3.10+ was not found on PATH. Install Python, then restart Claude Code."
    exit 0
}

try {
    $useUv = ($env:CBX_NO_UV -ne "1") -and (Get-Command uv -ErrorAction SilentlyContinue)
    if ($useUv) {
        & uv venv $venv
        & uv pip install --python (Join-Path $venv "Scripts\python.exe") $spec
    } else {
        & $py.Source -m venv $venv
        & (Join-Path $venv "Scripts\python.exe") -m pip install --upgrade pip
        & (Join-Path $venv "Scripts\python.exe") -m pip install $spec
    }
    Copy-Item $lockSrc $lockDst -Force
} catch {
    Remove-Item $lockDst -ErrorAction SilentlyContinue
    Write-Error "codebase-index: bootstrap install failed; will retry next session."
    exit 0
}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_bootstrap.py -k powershell -v`
Expected: PASS (or SKIP without `pwsh`). The pointer file is written before the warm-check, so it always reflects the current `${CLAUDE_PLUGIN_DATA}/venv`.

- [ ] **Step 5: Commit**

```bash
git add scripts/bootstrap.ps1 tests/test_bootstrap.py
git commit -m "feat(plugin): Windows SessionStart bootstrap (bootstrap.ps1)"
```

---

## Task 6: Wire the `SessionStart` hook

**Files:**
- Create: `hooks/hooks.json`
- Modify: `tests/test_plugin_manifest.py`

- [ ] **Step 1: Add the failing test**

Append to `tests/test_plugin_manifest.py`:

```python
# tests/test_plugin_manifest.py  (append)
def test_session_start_hook_runs_bootstrap():
    hooks = _load("hooks/hooks.json")["hooks"]
    assert "SessionStart" in hooks
    cmds = [
        h["command"]
        for entry in hooks["SessionStart"]
        for h in entry["hooks"]
        if h["type"] == "command"
    ]
    assert any("bootstrap.sh" in c and "${CLAUDE_PLUGIN_ROOT}" in c for c in cmds)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_plugin_manifest.py::test_session_start_hook_runs_bootstrap -v`
Expected: FAIL — `hooks/hooks.json` does not exist.

- [ ] **Step 3: Create `hooks/hooks.json`**

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "\"${CLAUDE_PLUGIN_ROOT}/scripts/bootstrap.sh\""
          }
        ]
      }
    ]
  }
}
```

> Direct invocation (shebang + executable bit) follows the documented hook pattern. Windows support is confirmed in Task 8; if Claude Code on Windows cannot run the `.sh`, add a second `SessionStart` entry invoking `bootstrap.ps1` (both warm-exit via the same lock check, so running both is safe).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_plugin_manifest.py -v`
Expected: PASS (5 tests total in this file).

- [ ] **Step 5: Commit**

```bash
git add hooks/hooks.json tests/test_plugin_manifest.py
git commit -m "feat(plugin): run bootstrap on SessionStart"
```

---

## Task 7: Plugin skill (byte-identical to the authored skill)

**Files:**
- Create: `skills/codebase-index/SKILL.md`
- Create: `tests/test_plugin_skill_parity.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_plugin_skill_parity.py
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def test_plugin_skill_matches_authored_skill():
    plugin = (ROOT / "skills" / "codebase-index" / "SKILL.md").read_text(encoding="utf-8")
    authored = (ROOT / "skill" / "SKILL.md").read_text(encoding="utf-8")
    assert plugin == authored
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_plugin_skill_parity.py -v`
Expected: FAIL — `skills/codebase-index/SKILL.md` does not exist.

- [ ] **Step 3: Create the plugin skill as a verbatim copy**

Copy the authored skill into the plugin's skills directory:

```bash
mkdir -p skills/codebase-index
cp skill/SKILL.md skills/codebase-index/SKILL.md
```

> Keep the two byte-identical. The plugin ships `bin/codebase-index` and `bin/cbx` (both on PATH, both whitelisted, both venv-resolving), so every command the authored SKILL.md issues — whether `codebase-index search …` or `cbx search …` — works unchanged inside the plugin. When you edit one SKILL.md, copy it to the other; the parity test enforces it.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_plugin_skill_parity.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add skills/codebase-index/SKILL.md tests/test_plugin_skill_parity.py
git commit -m "feat(plugin): ship the skill at skills/codebase-index/SKILL.md"
```

---

## Task 8: Validate, document, manual QA

**Files:**
- Modify: `README.md`
- Modify: `docs/ROADMAP.md`

- [ ] **Step 1: Run the full suite + validator**

Run: `pytest -v`
Expected: all tests pass (bash/pwsh-gated tests may SKIP per platform).

Run: `claude plugin validate .`
Expected: no errors. (This checks the manifest, marketplace, and hook config against the plugin schema.)

- [ ] **Step 2: Manual QA via `--plugin-dir` (uses a local install spec, no PyPI dependency)**

```bash
# Point the bootstrap at the local source so it works before the M9 PyPI release.
export CBX_INSTALL_SPEC="$(pwd)"        # installs the working tree into the venv
claude --plugin-dir .
# In the session:
#   1. Confirm no SessionStart errors in /plugin (the venv builds under ~/.claude/plugins/data/...).
#   2. Ask a codebase question (e.g. "where is auth token refresh implemented?").
#      The skill runs `codebase-index search ... --json`; index.exists:false triggers a first `index`,
#      then returns compact recommended_reads.
#   3. In a Bash tool call, run `cbx clean` and confirm it exits 2 (whitelist).
```

Expected: the question is answered from the index with `file:line` citations; `cbx clean` is refused. Record the outcome. On Windows, repeat and confirm the `SessionStart` hook ran (`.venv-path` exists under the cached plugin dir and `Scripts\codebase-index.exe` exists under the data dir); if the `.sh` hook did not fire, add the `bootstrap.ps1` hook entry described in Task 6 and re-test.

- [ ] **Step 3: Add the README transparency + install section**

Add to `README.md` (near the top, under a new `## Install as a Claude Code plugin` heading):

```markdown
## Install as a Claude Code plugin

One command in Claude Code:

```
/plugin marketplace add your-org/codebase-index
/plugin install codebase-index@codebase-index
```

Or just ask: "install the codebase-index plugin".

**What happens on first run:** when a session starts, a `SessionStart` hook
(`scripts/bootstrap.sh` / `.ps1`) creates a private Python virtual environment under
`~/.claude/plugins/data/codebase-index-*/venv` and installs the pinned
`codebase-index` package (from `requirements.lock`) into it — using `uv` if present,
otherwise `python -m venv` + `pip`. It reinstalls only when the pinned version changes.
Nothing is installed globally; uninstalling the plugin removes the data directory.

**Prerequisite:** Python 3.10+ on your PATH. The first install needs network access to
fetch the package; later sessions are offline. The skill builds its index on your first
codebase question — no manual `index` step.
```

- [ ] **Step 4: Add the roadmap entry**

In `docs/ROADMAP.md`, add after the M7 section:

```markdown
## M7.5 — One-command plugin install
- Repo doubles as a Claude Code plugin (`.claude-plugin/plugin.json` + `marketplace.json`).
- `SessionStart` hook (`scripts/bootstrap.sh`/`.ps1`) provisions a venv in `${CLAUDE_PLUGIN_DATA}`
  with the pinned CLI (uv-preferred, pip fallback), reinstalling only when `requirements.lock` changes.
- `bin/cbx` + `bin/codebase-index` wrappers resolve the venv via a `.venv-path` pointer and keep the
  subcommand whitelist.
- **Exit:** `/plugin install codebase-index@<marketplace>` → ask a codebase question → compact reads,
  no manual `pip`/`init`/`index`. Depends on the M9 PyPI release for the non-`CBX_INSTALL_SPEC` path.
```

- [ ] **Step 5: Commit**

```bash
git add README.md docs/ROADMAP.md
git commit -m "docs(plugin): one-command install instructions + M7.5 roadmap"
```

---

## Acceptance Criteria (M7.5 exit)

- `.claude-plugin/plugin.json` + `marketplace.json` are valid (`claude plugin validate` clean); the plugin version equals the `pyproject.toml` version and the `requirements.lock` pin.
- Installing via `--plugin-dir`/marketplace and starting a session provisions the venv once into `${CLAUDE_PLUGIN_DATA}`; the warm path is a no-op; a changed `requirements.lock` reinstalls; missing Python prints a clear message and never hard-fails the session.
- `bin/cbx` and `bin/codebase-index` resolve the venv through `.venv-path`, exec the CLI, and refuse `clean`/`init`/`watch` with exit 2.
- The authored `skill/SKILL.md` and `skills/codebase-index/SKILL.md` are byte-identical; a codebase question in a plugin session returns compact `recommended_reads` (first question builds the index automatically).
- Full `pytest` green (platform-gated shell tests may skip); README documents the prerequisite (Python 3.10+) and the first-run network install transparently.

## Deferred (NOT in M7.5)

- PyPI publication of `codebase-index==0.1.0` — **M9** (until then, the bootstrap uses `CBX_INSTALL_SPEC`).
- Community-marketplace submission/acceptance (`@claude-community`) — external review timeline.
- Trimming `src/`, `tests/`, `docs/` from the cached plugin copy (a dedicated plugin subtree or build step) — optimization, not correctness.
- Hooks/watch auto-update of the index — **M8**.
