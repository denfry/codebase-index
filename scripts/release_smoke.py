# scripts/release_smoke.py
"""Build the wheel, install it into a throwaway virtualenv, and exercise the
public install path end-to-end (init -> index -> search). Approximates what a
user gets from `pipx install codebase-index` on a clean machine.

Usage:  python scripts/release_smoke.py
Exit 0 = the released artifact works from a clean environment.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
import venv
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]


def run(cmd: list[str], cwd: Path | None = None) -> subprocess.CompletedProcess[str]:
    print("+", " ".join(cmd))
    return subprocess.run(cmd, cwd=cwd, text=True, capture_output=True, check=True)


def main() -> int:
    run([sys.executable, "-m", "build"], cwd=REPO)
    wheels = sorted((REPO / "dist").glob("codebase_index-*.whl"))
    if not wheels:
        print("no wheel built", file=sys.stderr)
        return 1
    wheel = wheels[-1]

    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        env_dir = tmp_path / "venv"
        venv.create(env_dir, with_pip=True)
        bin_dir = env_dir / ("Scripts" if sys.platform == "win32" else "bin")
        py = bin_dir / ("python.exe" if sys.platform == "win32" else "python")
        cbx = bin_dir / ("codebase-index.exe" if sys.platform == "win32" else "codebase-index")

        run([str(py), "-m", "pip", "install", str(wheel)])

        # a tiny throwaway project
        proj = tmp_path / "proj"
        (proj / "src").mkdir(parents=True)
        (proj / "src" / "app.py").write_text(
            "def greet(name):\n    return f'hello {name}'\n", encoding="utf-8"
        )
        run(["git", "init"], cwd=proj)

        run([str(cbx), "--root", str(proj), "init"])
        assert (proj / ".claude" / "skills" / "codebase-index" / "SKILL.md").is_file()

        run([str(cbx), "--root", str(proj), "index"])
        res = run([str(cbx), "--root", str(proj), "--json", "search", "greet"])
        payload = json.loads(res.stdout)
        assert payload["index"]["exists"] is True, payload
        assert payload["results"], "expected at least one result for 'greet'"

    print("\nrelease smoke OK — clean-machine install path works")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except subprocess.CalledProcessError as exc:
        print(f"\nFAILED: {' '.join(exc.cmd)}\n{exc.stdout}\n{exc.stderr}", file=sys.stderr)
        sys.exit(1)
