from __future__ import annotations

import os
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BASH = shutil.which("bash")


def _bash_works() -> bool:
    if BASH is None:
        return False
    res = subprocess.run([BASH, "-c", "echo ok"], capture_output=True, text=True)
    return res.returncode == 0 and res.stdout.strip() == "ok"


BASH_OK = _bash_works()

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


@pytest.mark.skipif(not BASH_OK, reason="bash not available or non-functional")
def test_cold_run_provisions_venv_and_pointer(tmp_path):
    root, data, env = _stage(tmp_path)
    res = _run(root, env)
    assert res.returncode == 0, res.stderr
    assert (data / "venv" / "bin" / "codebase-index").is_file()
    assert (data / "requirements.lock").read_text(encoding="utf-8").strip() == "codebase-index==0.1.0"
    assert (root / ".venv-path").read_text(encoding="utf-8").strip() == str(data / "venv")


@pytest.mark.skipif(not BASH_OK, reason="bash not available or non-functional")
def test_warm_run_is_noop(tmp_path):
    root, data, env = _stage(tmp_path)
    assert _run(root, env).returncode == 0
    cli = data / "venv" / "bin" / "codebase-index"
    first_mtime = cli.stat().st_mtime_ns
    assert _run(root, env).returncode == 0
    assert cli.stat().st_mtime_ns == first_mtime  # not reinstalled


@pytest.mark.skipif(not BASH_OK, reason="bash not available or non-functional")
def test_lock_change_triggers_reinstall(tmp_path):
    root, data, env = _stage(tmp_path)
    assert _run(root, env).returncode == 0
    (data / "venv" / "bin" / "codebase-index").unlink()  # simulate a stale/removed CLI
    (root / "requirements.lock").write_text("codebase-index==0.2.0\n", encoding="utf-8")
    assert _run(root, env).returncode == 0
    assert (data / "venv" / "bin" / "codebase-index").is_file()
    assert (data / "requirements.lock").read_text(encoding="utf-8").strip() == "codebase-index==0.2.0"


@pytest.mark.skipif(not BASH_OK, reason="bash not available or non-functional")
def test_missing_python_reports_clearly(tmp_path):
    root, data, env = _stage(tmp_path)
    env["PATH"] = str(tmp_path / "empty")  # no python anywhere
    (tmp_path / "empty").mkdir()
    res = _run(root, env)
    assert res.returncode == 0  # SessionStart must not hard-fail the session
    assert "Python 3.10+" in res.stderr
    assert not (data / "venv" / "bin" / "codebase-index").exists()


PWSH = shutil.which("pwsh")
PWSH_BOOTSTRAP_ENABLED = os.environ.get("CBX_RUN_PWSH_BOOTSTRAP", "0") == "1"


@pytest.mark.skipif(not (PWSH and PWSH_BOOTSTRAP_ENABLED), reason="pwsh not available or CBX_RUN_PWSH_BOOTSTRAP != 1")
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
