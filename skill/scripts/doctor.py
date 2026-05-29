#!/usr/bin/env python3
"""Doctor check for codebase-index.

Verifies the environment is correctly set up for indexing
and reports any issues that could affect functionality.
"""

import importlib
import json
import sys
from pathlib import Path


def check_python_version() -> bool:
    major, minor = sys.version_info[:2]
    ok = major == 3 and minor >= 10
    status = "OK" if ok else "FAIL"
    print(f"[{status}] Python {major}.{minor} (requires 3.10+)")
    return ok


def check_package_installed() -> bool:
    try:
        mod = importlib.import_module("codebase_index")
        version = getattr(mod, "__version__", "unknown")
        print(f"[OK] codebase-index package installed (v{version})")
        return True
    except ImportError:
        print("[FAIL] codebase-index package not installed")
        print("  Install with: pip install -e .")
        return False


def check_tree_sitter() -> bool:
    try:
        import tree_sitter  # noqa: F401
        print("[OK] tree-sitter is available")
        return True
    except ImportError:
        print("[WARN] tree-sitter not installed (symbol extraction disabled)")
        print("  Install with: pip install tree-sitter tree-sitter-language-pack")
        return False


def check_cache_location(project_root: Path) -> bool:
    cache_dir = project_root / ".claude" / "cache" / "codebase-index"
    if cache_dir.exists():
        print(f"[OK] Cache directory exists: {cache_dir}")
        # Check if it's in .gitignore
        gitignore = project_root / ".gitignore"
        if gitignore.exists():
            content = gitignore.read_text()
            if "codebase-index" in content or ".claude/cache" in content:
                print("[OK] Cache directory is in .gitignore")
                return True
            else:
                print("[WARN] Cache directory may not be in .gitignore")
                return False
        return True
    else:
        print(f"[INFO] Cache directory not yet created: {cache_dir}")
        print("  It will be created on first `codebase-index index` run")
        return True


def check_skill_installed(project_root: Path) -> bool:
    skill_dir = project_root / ".claude" / "skills" / "codebase-index"
    if skill_dir.exists():
        print(f"[OK] Skill installed at: {skill_dir}")
        return True
    else:
        print(f"[INFO] Skill not installed in .claude/skills/")
        print("  Run: python skill/scripts/install.py")
        return True  # Not a hard failure


def check_config(project_root: Path) -> bool:
    config_path = project_root / ".codeindex.json"
    if config_path.exists():
        try:
            config = json.loads(config_path.read_text())
            print(f"[OK] Configuration file found: {config_path}")
            if config.get("embeddings", {}).get("allow_external"):
                print("[WARN] External embeddings are enabled — code will be sent to a remote API")
        except json.JSONDecodeError:
            print(f"[FAIL] Invalid JSON in {config_path}")
            return False
    else:
        print(f"[INFO] No config file (using defaults)")
    return True


def main() -> int:
    print("=== codebase-index Doctor ===\n")

    project_root = Path(__file__).resolve().parent.parent.parent

    checks = [
        check_python_version(),
        check_package_installed(),
        check_tree_sitter(),
        check_cache_location(project_root),
        check_skill_installed(project_root),
        check_config(project_root),
    ]

    print()
    if all(checks):
        print("All checks passed.")
        return 0
    else:
        failed = checks.count(False)
        print(f"{failed} check(s) failed. Review the output above.")
        return 1


if __name__ == "__main__":
    sys.exit(main())
