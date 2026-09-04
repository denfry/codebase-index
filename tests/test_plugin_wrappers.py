from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
BASH = shutil.which("bash")


def _bash_works() -> bool:
    """Check if bash is a real shell, not the WSL relay on Windows."""
    if BASH is None:
        return False
    try:
        res = subprocess.run([BASH, "-c", "echo ok"], capture_output=True, text=True)
    except OSError:
        return False
    return res.returncode == 0 and res.stdout.strip() == "ok"


BASH_OK = _bash_works()


def _stage_plugin(tmp_path: Path) -> Path:
    """Copy bin/cbx into a throwaway plugin tree so tests never touch the repo."""
    dst = tmp_path / "plugin"
    (dst / "bin").mkdir(parents=True)
    shutil.copy(ROOT / "bin" / "cbx", dst / "bin" / "cbx")
    (dst / "bin" / "cbx").chmod(0o755)
    return dst


@pytest.mark.skipif(not BASH_OK, reason="bash not available or non-functional")
def test_cbx_refuses_destructive_subcommand(tmp_path):
    plugin = _stage_plugin(tmp_path)
    res = subprocess.run(
        [BASH, str(plugin / "bin" / "cbx"), "clean"],
        capture_output=True, text=True,
    )
    assert res.returncode == 2
    assert "refusing" in res.stderr


@pytest.mark.skipif(not BASH_OK, reason="bash not available or non-functional")
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


def _whitelist_sh(path: Path) -> set[str]:
    m = re.search(r'^ALLOWED="([^"]+)"', path.read_text(encoding="utf-8"), re.M)
    assert m, f"no ALLOWED= line in {path}"
    return set(m.group(1).split())


def _whitelist_ps1(path: Path) -> set[str]:
    m = re.search(r"\$allowed = @\(([^)]+)\)", path.read_text(encoding="utf-8"), re.S)
    assert m, f"no $allowed line in {path}"
    return {tok.strip().strip('"') for tok in m.group(1).split(",")}


def test_plugin_wrapper_whitelist_matches_skill_template():
    """The plugin `bin/` wrappers must allow exactly what the skill template's
    `cbx` allows, or plugin users silently lose commands the SKILL.md advertises
    (this drifted once: architecture/diff-impact/path/describe were missing)."""
    template = ROOT / "src/codebase_index/skill_template/scripts"
    expected = _whitelist_sh(template / "cbx")
    assert _whitelist_ps1(template / "cbx.ps1") == expected
    assert _whitelist_sh(ROOT / "bin/cbx") == expected
    assert _whitelist_ps1(ROOT / "bin/cbx.ps1") == expected
