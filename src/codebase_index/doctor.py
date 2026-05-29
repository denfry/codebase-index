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

        # 4. Symbol-extraction coverage (Guardrail 2): a tree-sitter language with many files
        #    but ~0 symbols means extraction silently failed (the original Java bug).
        from .storage import repo
        from .storage.db import Database

        with Database(db_path) as db:
            coverage = repo.treesitter_coverage(db.conn)
        dead = [r["lang"] for r in coverage if r["files"] >= _ZERO_SYMBOL_FILE_THRESHOLD
                and (r["symbols"] or 0) == 0]
        findings.append(
            Finding(
                id="symbol_extraction",
                ok=not dead,
                severity="medium",
                detail=(
                    "tree-sitter languages extract symbols"
                    if not dead
                    else f"no symbols extracted for tree-sitter language(s): {', '.join(dead)} "
                    "— extraction path likely broken"
                ),
            )
        )

    return findings


# Threshold above which a tree-sitter language with zero symbols is treated as broken rather
# than just a tiny/empty repo.
_ZERO_SYMBOL_FILE_THRESHOLD = 3


def has_high_severity_failure(findings: list[Finding]) -> bool:
    return any(f.severity == "high" and not f.ok for f in findings)
