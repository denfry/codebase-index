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

    return findings


def has_high_severity_failure(findings: list[Finding]) -> bool:
    return any(f.severity == "high" and not f.ok for f in findings)
