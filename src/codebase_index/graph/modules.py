"""Build-system modules: which module a file belongs to, and who names it.

"Would a change here break another module?" is a build-graph question the code
graph cannot answer: a Gradle subproject that nothing depends on has no incoming
edges whether or not other projects exist. Agents answered it by grepping every
build file. This reads the build files instead — cheaply, without evaluating
them — and reports the lines of *other* build files that mention the module, so
the answer comes with its evidence.
"""

from __future__ import annotations

import os
import re
from pathlib import Path, PurePosixPath
from typing import Optional

BUILD_FILES = (
    "build.gradle.kts", "build.gradle", "settings.gradle.kts", "settings.gradle",
    "pom.xml", "Cargo.toml", "package.json", "go.mod", "pyproject.toml",
)
_SKIP_DIRS = frozenset({
    ".git", "build", "target", "node_modules", "dist", "out", ".gradle", ".venv",
    "venv", "__pycache__", ".idea", ".claude", "run",
})
_MAX_DEPTH = 5
_COMMENT_PREFIXES = ("//", "#", "<!--", "*", "/*")
_MAX_REFERENCES = 20


def owning_module(root: Path, rel_path: str) -> Optional[str]:
    """Nearest directory above `rel_path` (below the root) that has a build file."""
    parent = PurePosixPath(rel_path).parent
    while str(parent) not in ("", "."):
        if any((root / str(parent) / name).is_file() for name in BUILD_FILES):
            return str(parent)
        parent = parent.parent
    return None


def _build_files(root: Path) -> list[Path]:
    found: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        rel = Path(dirpath).relative_to(root)
        depth = len(rel.parts)
        dirnames[:] = [d for d in dirnames if d not in _SKIP_DIRS and depth < _MAX_DEPTH]
        found.extend(Path(dirpath) / f for f in filenames if f in BUILD_FILES)
    return sorted(found)


def module_references(root: Path, module: str) -> list[dict]:
    """Lines of build files outside `module` that name it (`include`, deps, members)."""
    name = PurePosixPath(module).name
    # `:realism-polity`, "realism-polity", ../realism-polity, realism_polity (Cargo
    # crates use either spelling), bounded so `realism-polity-api` is not a hit.
    spellings = {name, name.replace("-", "_"), name.replace("_", "-")}
    pattern = re.compile(
        r"(?<![\w-])(?:" + "|".join(re.escape(s) for s in sorted(spellings)) + r")(?![\w-])"
    )
    own = (root / module).resolve()
    out: list[dict] = []
    for path in _build_files(root):
        if path.resolve().parent == own:
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        settings = path.name.startswith("settings.gradle")
        in_members = False
        for number, line in enumerate(text.splitlines(), start=1):
            opens = _MEMBERS_OPEN.search(line)
            if line.lstrip().startswith(_COMMENT_PREFIXES):
                continue
            if pattern.search(line):
                membership = settings or in_members or bool(opens) or "include" in line
                out.append({
                    "path": path.relative_to(root).as_posix(),
                    "line": number,
                    "text": line.strip()[:160],
                    "kind": "member" if membership else "dependency",
                })
                if len(out) >= _MAX_REFERENCES:
                    return out
            if opens and "]" not in line[opens.end():]:
                in_members = True
            elif in_members and "]" in line:
                in_members = False
    return out


# A workspace member list (Cargo `members = [`, npm `"workspaces": [`): naming a
# module there includes it in the build; it is not a dependency on it.
_MEMBERS_OPEN = re.compile(r"""^\s*"?(?:(?:default-)?members|workspaces)"?\s*[=:]\s*\[""")


def modules_for_paths(root: Path, paths: list[str]) -> list[dict]:
    """One entry per module the paths live in, with the build lines that name it."""
    seen: dict[str, dict] = {}
    for rel in paths:
        module = owning_module(root, rel)
        if module is None or module in seen:
            continue
        refs = module_references(root, module)
        seen[module] = {
            "module": module,
            # `member`: the build includes the module; `dependency`: another module
            # names it outside a member list, which is how dependencies are declared.
            "referenced_by": refs,
            "dependents": sorted({r["path"] for r in refs if r["kind"] == "dependency"}),
        }
    return list(seen.values())
