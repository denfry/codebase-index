#!/usr/bin/env python3
"""Smoke test for codebase-index.

Runs a minimal end-to-end test:
1. Creates a temporary project with a few source files.
2. Initializes and indexes it.
3. Runs a search query.
4. Verifies results are returned.
5. Cleans up.
"""

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def run(cmd: list[str], cwd: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(cwd),
    )


def main() -> int:
    print("=== codebase-index Smoke Test ===\n")

    with tempfile.TemporaryDirectory() as tmpdir:
        project = Path(tmpdir) / "test-project"
        project.mkdir()

        # Create test files
        (project / "src").mkdir()
        (project / "src" / "auth.py").write_text(
            "class AuthService:\n"
            "    def login(self, username: str, password: str) -> bool:\n"
            "        return True\n"
            "\n"
            "    def validate_password(self, password: str) -> bool:\n"
            "        return len(password) >= 8\n"
        )
        (project / "src" / "models.py").write_text(
            "class User:\n"
            "    def __init__(self, id: int, name: str):\n"
            "        self.id = id\n"
            "        self.name = name\n"
        )

        # Initialize
        print("[1/4] Initializing...")
        result = run([sys.executable, "-m", "codebase_index", "init"], project)
        if result.returncode != 0:
            print(f"[FAIL] init failed: {result.stderr}")
            return 1
        print("  OK")

        # Index
        print("[2/4] Indexing...")
        result = run([sys.executable, "-m", "codebase_index", "index"], project)
        if result.returncode != 0:
            print(f"[FAIL] index failed: {result.stderr}")
            return 1
        print("  OK")

        # Search
        print("[3/4] Searching for 'AuthService login'...")
        result = run(
            [sys.executable, "-m", "codebase_index", "search", "AuthService login", "--json"],
            project,
        )
        if result.returncode != 0:
            print(f"[FAIL] search failed: {result.stderr}")
            return 1

        try:
            data = json.loads(result.stdout)
            results = data.get("results", [])
            if not results:
                print("[FAIL] No results returned")
                return 1
            print(f"  OK — {len(results)} result(s) returned")
            print(f"  Top match: {results[0].get('path', 'unknown')}")
        except json.JSONDecodeError:
            print(f"[FAIL] Invalid JSON output: {result.stdout[:200]}")
            return 1

        # Stats
        print("[4/4] Checking stats...")
        result = run([sys.executable, "-m", "codebase_index", "stats", "--json"], project)
        if result.returncode != 0:
            print(f"[FAIL] stats failed: {result.stderr}")
            return 1

        try:
            data = json.loads(result.stdout)
            files = data.get("files", 0)
            print(f"  OK — {files} file(s) indexed")
        except json.JSONDecodeError:
            print(f"[FAIL] Invalid JSON output: {result.stdout[:200]}")
            return 1

    print("\n=== All smoke tests passed ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
