#!/usr/bin/env python3
"""Install script for codebase-index Claude Code Skill.

Copies the skill directory into .claude/skills/codebase-index
and verifies the Python package is available.
"""

import shutil
import subprocess
import sys
from pathlib import Path


def main() -> int:
    skill_dir = Path(__file__).resolve().parent.parent
    project_root = skill_dir.parent

    print("=== codebase-index Skill Installer ===\n")

    # 1. Check Python package
    try:
        result = subprocess.run(
            [sys.executable, "-m", "codebase_index", "--version"],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            print(f"[OK] codebase-index is installed: {result.stdout.strip()}")
        else:
            print("[WARN] codebase-index CLI returned non-zero exit code")
            print(f"  stderr: {result.stderr.strip()}")
    except FileNotFoundError:
        print("[WARN] codebase-index Python package not found.")
        print("  Install it with: pip install -e .")
        print("  Or: pipx install codebase-index")
    except subprocess.TimeoutExpired:
        print("[ERROR] codebase-index CLI timed out")
        return 1

    # 2. Install skill into .claude/skills/
    target = project_root / ".claude" / "skills" / "codebase-index"
    if target.exists():
        print(f"[SKIP] Skill already installed at: {target}")
    else:
        target.parent.mkdir(parents=True, exist_ok=True)
        print(f"[COPY] Installing skill to: {target}")
        shutil.copytree(skill_dir, target, dirs_exist_ok=True)
        print("[OK] Skill installed successfully")

    # 3. Run doctor
    print("\nRunning doctor check...")
    try:
        result = subprocess.run(
            [sys.executable, "-m", "codebase_index", "doctor"],
            capture_output=True,
            text=True,
            timeout=30,
            cwd=str(project_root),
        )
        print(result.stdout)
        if result.returncode != 0:
            print(result.stderr)
            print("[WARN] Doctor found issues. Review the output above.")
    except Exception as e:
        print(f"[WARN] Doctor check failed: {e}")

    print("\n=== Installation complete ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
