#!/usr/bin/env python3
"""M12.5 — Real-repo benchmark expansion.

Extends the public benchmark with:
- Scale fixtures at 10k and 100k LOC with ~200 files
- Framework graph tasks: route → handler → service → repository chain
- Repo-map baseline (Aider-style: enumerate files + symbols)
- Vanilla-grep baseline (already used in benchmark_public)
- Token economy comparison across all three baselines
- Per-language breakdown at scale

Run:
    python tests/benchmark_real_repo.py --scale 10k
    python tests/benchmark_real_repo.py --scale 10k,100k
    python tests/benchmark_real_repo.py --scale 10k --human-eval
"""

from __future__ import annotations

import argparse
import json
import math
import re
import shutil
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from codebase_index.config import Config
from codebase_index.graph.expand import impact_lookup
from codebase_index.indexer.pipeline import build_index
from codebase_index.retrieval.pipeline import search
from codebase_index.storage import repo as repo_store
from codebase_index.storage.db import Database

TOKEN_CHARS = 4
GREP_WINDOW = 80

# LOC targets for each scale tier.
SCALE_TARGETS = {"10k": 10_000, "100k": 100_000}


# ── fixture files ─────────────────────────────────────────────────────────────

def _python_module(i: int) -> str:
    return f'''\
"""Service module {i}."""
from __future__ import annotations
from typing import Optional


class DataService{i}:
    """Handles processing for domain area {i}."""

    def __init__(self) -> None:
        self._store: list[str] = []

    def process_{i}(self, value: str) -> Optional[str]:
        """Process a single value in domain {i}."""
        if not value:
            return None
        self._store.append(value)
        return value.strip().lower()

    def batch_process_{i}(self, values: list[str]) -> list[str]:
        return [v for v in (self.process_{i}(x) for x in values) if v is not None]

    def count_{i}(self) -> int:
        return len(self._store)

    def clear_{i}(self) -> None:
        self._store.clear()


def compute_score_{i}(inputs: list[str], weight: float = 1.0) -> dict[str, float]:
    """Aggregate scoring for domain {i}."""
    svc = DataService{i}()
    for inp in inputs:
        svc.process_{i}(inp)
    total = float(svc.count_{i}())
    return {{"score": total * weight, "index": float({i}), "count": total}}


def validate_{i}(value: str) -> bool:
    """Validate input for domain {i}."""
    return bool(value) and len(value) >= 2 and value.isascii()
'''


def _typescript_module(i: int) -> str:
    return f'''\
/**
 * TypeScript service module {i}.
 */

export interface Item{i} {{
  id: number;
  name: string;
  value: number;
}}

export class ItemService{i} {{
  private items: Item{i}[] = [];

  add_{i}(item: Item{i}): void {{
    this.items.push(item);
  }}

  find_{i}(id: number): Item{i} | undefined {{
    return this.items.find(it => it.id === id);
  }}

  remove_{i}(id: number): boolean {{
    const idx = this.items.findIndex(it => it.id === id);
    if (idx < 0) return false;
    this.items.splice(idx, 1);
    return true;
  }}

  count_{i}(): number {{
    return this.items.length;
  }}

  totalValue_{i}(): number {{
    return this.items.reduce((sum, it) => sum + it.value, 0);
  }}
}}

export function createItem{i}(name: string, value: number): Item{i} {{
  return {{ id: Date.now() + {i}, name, value }};
}}
'''


def _java_class(i: int) -> str:
    return f'''\
package com.example.service{i};

import java.util.ArrayList;
import java.util.List;
import java.util.Optional;

/**
 * Service class for domain area {i}.
 */
public class Service{i} {{

    private final List<String> records = new ArrayList<>();

    public void add{i}(String record) {{
        if (record != null && !record.isEmpty()) {{
            records.add(record);
        }}
    }}

    public Optional<String> find{i}(String query) {{
        return records.stream()
            .filter(r -> r.contains(query))
            .findFirst();
    }}

    public int count{i}() {{
        return records.size();
    }}

    public boolean remove{i}(String record) {{
        return records.remove(record);
    }}

    public List<String> getAll{i}() {{
        return new ArrayList<>(records);
    }}

    public double score{i}(String input) {{
        long matches = records.stream().filter(r -> r.startsWith(input)).count();
        return (double) matches / Math.max(records.size(), 1);
    }}
}}
'''


def _go_file(i: int) -> str:
    return f'''\
// Package service{i} implements domain operations for area {i}.
package service{i}

import (
    "fmt"
    "strings"
)

// Record{i} holds a single domain record.
type Record{i} struct {{
    ID    int
    Value string
}}

// Store{i} manages records in memory.
type Store{i} struct {{
    records []Record{i}
}}

// Add{i} inserts a new record.
func (s *Store{i}) Add{i}(value string) {{
    s.records = append(s.records, Record{i}{{
        ID:    len(s.records) + {i}*1000,
        Value: value,
    }})
}}

// Find{i} searches by value prefix.
func (s *Store{i}) Find{i}(prefix string) *Record{i} {{
    for _, r := range s.records {{
        if strings.HasPrefix(r.Value, prefix) {{
            return &r
        }}
    }}
    return nil
}}

// Count{i} returns the number of stored records.
func (s *Store{i}) Count{i}() int {{
    return len(s.records)
}}

// Summary{i} returns a human-readable summary.
func (s *Store{i}) Summary{i}() string {{
    return fmt.Sprintf("store-%d: %d records", {i}, len(s.records))
}}
'''


# ── framework chain fixture ───────────────────────────────────────────────────

FRAMEWORK_CHAIN = {
    "web/routes/user_routes.py": '''\
"""HTTP route definitions for user endpoints."""
from handlers.user_handler import handle_create_user, handle_get_user


def create_user_route(request):
    """POST /users — create a new user."""
    return handle_create_user(request)


def get_user_route(request, user_id: int):
    """GET /users/{id} — retrieve an existing user."""
    return handle_get_user(request, user_id)
''',
    "handlers/user_handler.py": '''\
"""User request handlers — bridge between routes and business logic."""
from services.user_service import create_user_record, fetch_user_record


def handle_create_user(request):
    """Validate request and delegate to user service."""
    body = getattr(request, "body", {})
    return create_user_record(body)


def handle_get_user(request, user_id: int):
    """Fetch user data via service layer."""
    return fetch_user_record(user_id)
''',
    "services/user_service.py": '''\
"""User domain service — business logic and validation."""
from repositories.user_repo import save_user, load_user


def create_user_record(data: dict) -> dict:
    """Validate data and persist a new user record."""
    if not data.get("name"):
        raise ValueError("name is required")
    return save_user(data)


def fetch_user_record(user_id: int) -> dict:
    """Load and return a user record by ID."""
    record = load_user(user_id)
    if record is None:
        raise KeyError(f"user {user_id} not found")
    return record
''',
    "repositories/user_repo.py": '''\
"""User repository — storage layer."""
from __future__ import annotations
from typing import Optional

_STORE: dict[int, dict] = {}
_NEXT_ID = 1


def save_user(data: dict) -> dict:
    """Persist a user and return the saved record with assigned ID."""
    global _NEXT_ID
    record = {"id": _NEXT_ID, **data}
    _STORE[_NEXT_ID] = record
    _NEXT_ID += 1
    return record


def load_user(user_id: int) -> Optional[dict]:
    """Return the user record for user_id, or None if missing."""
    return _STORE.get(user_id)


def delete_user(user_id: int) -> bool:
    """Remove a user record. Returns True if deleted."""
    return _STORE.pop(user_id, None) is not None
''',
    "db/migrations/001_create_users.sql": '''\
-- Migration 001: create users table
CREATE TABLE IF NOT EXISTS users (
    id      INTEGER PRIMARY KEY AUTOINCREMENT,
    name    TEXT    NOT NULL,
    email   TEXT    UNIQUE,
    created_at DATETIME DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_users_email ON users(email);
''',
    "config/app_config.py": '''\
"""Application-level configuration consumed by multiple services."""
import os

DATABASE_URL: str = os.getenv("DATABASE_URL", "sqlite:///app.db")
DEBUG: bool = os.getenv("DEBUG", "false").lower() == "true"
MAX_USERS: int = int(os.getenv("MAX_USERS", "10000"))
''',
    ".github/workflows/ci.yml": '''\
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -e .[dev]
      - run: pytest tests/
''',
}

# Queries targeting the framework chain
FRAMEWORK_CASES = [
    {
        "query": "where is user creation route defined",
        "expected_files": ("web/routes/user_routes.py",),
        "task": "route",
    },
    {
        "query": "handle create user request handler",
        "expected_files": ("handlers/user_handler.py",),
        "task": "handler",
    },
    {
        "query": "create user record business logic service",
        "expected_files": ("services/user_service.py",),
        "task": "service",
    },
    {
        "query": "save user database repository persistence",
        "expected_files": ("repositories/user_repo.py",),
        "task": "repository",
    },
    {
        "query": "database migration create users table schema",
        "expected_files": ("db/migrations/001_create_users.sql",),
        "task": "migration",
    },
    {
        "query": "application configuration database URL settings",
        "expected_files": ("config/app_config.py",),
        "task": "config",
    },
    {
        "query": "CI workflow github actions test pipeline",
        "expected_files": (".github/workflows/ci.yml",),
        "task": "ci_infra",
    },
]

FRAMEWORK_GRAPH_TASKS = [
    # (symbol_or_file, direction, expected_file_suffix, depth, description)
    ("create_user_route", "down", "handlers/user_handler.py", 2,
     "route calls handler (depth 1)"),
    ("create_user_route", "down", "services/user_service.py", 3,
     "route reaches service (depth 2)"),
    ("create_user_route", "down", "repositories/user_repo.py", 4,
     "route reaches repository (depth 3)"),
    ("save_user", "up", "services/user_service.py", 2,
     "repo is called by service"),
    ("create_user_record", "up", "handlers/user_handler.py", 2,
     "service is called by handler"),
]


# ── fixture builder ───────────────────────────────────────────────────────────

def build_scale_fixture(root: Path, *, target_loc: int) -> Path:
    """Build a synthetic repo of approximately target_loc lines.

    Generates a realistic multi-language codebase with the framework chain
    fixture embedded so graph and retrieval tasks can be validated.
    """
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)

    _write(root / ".gitignore", ".claude/cache/codebase-index/\nnode_modules/\n__pycache__/\n")

    # Write the framework chain files first (fixed, known targets).
    for rel_path, content in FRAMEWORK_CHAIN.items():
        _write(root / rel_path, content)

    # Count LOC from framework chain.
    framework_loc = sum(content.count("\n") for content in FRAMEWORK_CHAIN.values())
    remaining = target_loc - framework_loc

    # Generate filler files across languages until we hit the LOC target.
    generators = [
        ("src/services/python", ".py", _python_module),
        ("src/services/ts", ".ts", _typescript_module),
        ("src/services/java", ".java", _java_class),
        ("src/services/go", ".go", _go_file),
    ]
    # Approximate LOC per generated file.
    loc_per_file = {".py": 35, ".ts": 35, ".java": 38, ".go": 36}

    idx = 0
    while remaining > 0:
        subdir, ext, gen_fn = generators[idx % len(generators)]
        content = gen_fn(idx)
        _write(root / subdir / f"module_{idx:04d}{ext}", content)
        remaining -= loc_per_file[ext]
        idx += 1

    return root


# ── benchmark helpers ─────────────────────────────────────────────────────────

@dataclass(frozen=True)
class ScaleCase:
    query: str
    expected_files: tuple[str, ...]
    task: str


@dataclass
class ScaleCaseResult:
    case: ScaleCase
    ranked_files: list[str]
    index_tokens: int
    repomap_tokens: int
    grep_tokens: int
    hit_at_1: bool
    hit_at_3: bool
    hit_at_5: bool
    mrr: float
    ndcg_at_5: float


@dataclass
class ScaleBenchmarkReport:
    scale_label: str
    retrieval_quality: dict[str, float]
    token_economy: dict[str, float]
    graph_tasks: dict[str, Any]
    framework_retrieval: dict[str, float]
    scale: dict[str, Any]
    cases: list[dict[str, Any]] = field(default_factory=list)
    human_eval_rows: list[dict[str, Any]] = field(default_factory=list)

    def to_json(self) -> str:
        d = {
            "scale": self.scale_label,
            "retrieval_quality": self.retrieval_quality,
            "token_economy": self.token_economy,
            "graph_tasks": self.graph_tasks,
            "framework_retrieval": self.framework_retrieval,
            "index_scale": self.scale,
            "cases": self.cases,
        }
        return json.dumps(d, indent=2, ensure_ascii=False)


def run_scale_benchmark(root: Path, scale_label: str) -> ScaleBenchmarkReport:
    cfg = Config()
    cfg.root = str(root)
    cfg.embeddings.enabled = False
    db_path = root / ".claude" / "cache" / "codebase-index" / "index.sqlite"

    with Database(db_path) as db:
        t0 = time.perf_counter()
        build_stats = build_index(cfg, db, root=root)
        build_ms = (time.perf_counter() - t0) * 1000

        cases = [_make_case(c) for c in FRAMEWORK_CASES]
        results = [_run_scale_case(db, root, c, cfg) for c in cases]

        graph = _run_graph_tasks(db)

        scale = {
            "label": scale_label,
            "files_indexed": repo_store.count_files(db.conn),
            "symbols_indexed": repo_store.count_symbols(db.conn),
            "edges_indexed": repo_store.count_edges(db.conn),
            "bytes_indexed": build_stats.total_bytes,
            "build_ms": round(build_ms, 1),
        }

    repomap_baseline = _repomap_tokens(root)

    return ScaleBenchmarkReport(
        scale_label=scale_label,
        retrieval_quality=_quality_metrics(results),
        token_economy=_token_economy(results, repomap_baseline),
        graph_tasks=graph,
        framework_retrieval=_framework_quality(results),
        scale=scale,
        cases=[_case_row(r) for r in results],
    )


def _make_case(d: dict) -> ScaleCase:
    return ScaleCase(
        query=d["query"],
        expected_files=tuple(d["expected_files"]),
        task=d["task"],
    )


def _run_scale_case(
    db: Database, root: Path, case: ScaleCase, cfg: Config
) -> ScaleCaseResult:
    payload = search(
        db.conn,
        case.query,
        mode="hybrid",
        limit=10,
        token_budget=5000,
        no_fallback=False,
        root=root,
        config=cfg,
    )
    ranked_files = [r["path"] for r in payload.get("results", [])]
    index_toks = _index_tokens(root, payload)
    grep_toks = _grep_tokens(root, case.query)
    return ScaleCaseResult(
        case=case,
        ranked_files=ranked_files,
        index_tokens=index_toks,
        repomap_tokens=0,  # filled after by _token_economy
        grep_tokens=grep_toks,
        hit_at_1=_hit(ranked_files, case.expected_files, 1),
        hit_at_3=_hit(ranked_files, case.expected_files, 3),
        hit_at_5=_hit(ranked_files, case.expected_files, 5),
        mrr=_rr(ranked_files, case.expected_files),
        ndcg_at_5=_ndcg(ranked_files, case.expected_files, 5),
    )


def _run_graph_tasks(db: Database) -> dict[str, Any]:
    results = []
    for target, direction, expected_suffix, depth, desc in FRAMEWORK_GRAPH_TASKS:
        resp = impact_lookup(db.conn, target, depth=depth, direction=direction)
        found_files = set(resp.files) | {n.path for n in resp.nodes}
        hit = any(f.endswith(expected_suffix) or f == expected_suffix for f in found_files)
        results.append({
            "description": desc,
            "target": target,
            "direction": direction,
            "depth": depth,
            "expected": expected_suffix,
            "passed": hit,
            "found_files": sorted(found_files),
        })
    passed = sum(1 for r in results if r["passed"])
    return {
        "tasks": len(results),
        "passed": passed,
        "pass_rate": passed / len(results) if results else 0.0,
        "details": results,
    }


# ── baselines ─────────────────────────────────────────────────────────────────

def _repomap_tokens(root: Path) -> int:
    """Estimate tokens for an Aider-style repo-map (file path + top symbols)."""
    lines: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or _ignored(path.relative_to(root)):
            continue
        try:
            text = path.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        # Extract top-level symbol names with a simple pattern.
        symbols = re.findall(
            r"^(?:def |class |func |function |public (?:class|void|int|String)|export (?:class|function|interface))\s*(\w+)",
            text,
            re.MULTILINE,
        )[:5]
        rel = path.relative_to(root)
        line = str(rel)
        if symbols:
            line += ": " + ", ".join(symbols)
        lines.append(line)
    return _est_tokens("\n".join(lines))


def _index_tokens(root: Path, payload: dict, top_k: int = 3) -> int:
    total = 0
    for result in payload.get("results", [])[:top_k]:
        snippet = result.get("snippet")
        if snippet:
            total += _est_tokens(snippet)
            continue
        path = root / result["path"]
        total += _est_tokens(_read_lines(path, result.get("line_start", 1), result.get("line_end", 80)))
    return total


def _grep_tokens(root: Path, query: str, top_k: int = 3) -> int:
    terms = _salient_terms(query)
    scored: list[tuple[int, Path, int]] = []
    for path in root.rglob("*"):
        if not path.is_file() or _ignored(path.relative_to(root)):
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        hits = [i for i, ln in enumerate(lines, 1) if any(t.lower() in ln.lower() for t in terms)]
        if hits:
            scored.append((len(hits), path, hits[len(hits) // 2]))
    scored.sort(key=lambda r: r[0], reverse=True)
    total = 0
    for _, path, center in scored[:top_k]:
        total += _est_tokens(_read_lines(path, center - GREP_WINDOW // 2, center + GREP_WINDOW // 2))
    return total


# ── metrics ───────────────────────────────────────────────────────────────────

def _quality_metrics(results: list[ScaleCaseResult]) -> dict[str, float]:
    return {
        "recall_at_1": _mean(r.hit_at_1 for r in results),
        "recall_at_3": _mean(r.hit_at_3 for r in results),
        "recall_at_5": _mean(r.hit_at_5 for r in results),
        "mrr": _mean(r.mrr for r in results),
        "ndcg_at_5": _mean(r.ndcg_at_5 for r in results),
    }


def _token_economy(
    results: list[ScaleCaseResult], repomap_tokens: int
) -> dict[str, float]:
    index_avg = _mean(r.index_tokens for r in results)
    grep_avg = _mean(r.grep_tokens for r in results)
    return {
        "index_tokens_avg": round(index_avg, 1),
        "grep_window_tokens_avg": round(grep_avg, 1),
        "repomap_tokens_total": repomap_tokens,
        "compression_vs_grep": round(grep_avg / max(index_avg, 1.0), 2),
        "compression_vs_repomap": round(repomap_tokens / max(index_avg * len(results), 1.0), 2),
    }


def _framework_quality(results: list[ScaleCaseResult]) -> dict[str, float]:
    by_task = {}
    for r in results:
        by_task[r.case.task] = {
            "hit_at_1": r.hit_at_1,
            "hit_at_3": r.hit_at_3,
            "query": r.case.query,
            "top_file": r.ranked_files[0] if r.ranked_files else None,
            "expected": r.case.expected_files[0] if r.case.expected_files else None,
        }
    return by_task


# ── math helpers ──────────────────────────────────────────────────────────────

def _hit(ranked: list[str], expected: tuple[str, ...], k: int) -> bool:
    return any(
        any(path.endswith(exp) or path == exp for path in ranked[:k])
        for exp in expected
    )


def _rr(ranked: list[str], expected: tuple[str, ...]) -> float:
    for i, path in enumerate(ranked, 1):
        if any(path.endswith(exp) or path == exp for exp in expected):
            return 1.0 / i
    return 0.0


def _ndcg(ranked: list[str], expected: tuple[str, ...], k: int) -> float:
    dcg = 0.0
    matched: set[str] = set()
    for i, path in enumerate(ranked[:k], 1):
        hit = next((exp for exp in expected if path.endswith(exp) or path == exp), None)
        if hit and hit not in matched:
            matched.add(hit)
            dcg += 1.0 / math.log2(i + 1)
    ideal = min(len(expected), k)
    idcg = sum(1.0 / math.log2(i + 1) for i in range(1, ideal + 1))
    return dcg / idcg if idcg else 0.0


def _mean(values) -> float:
    rows = list(values)
    return float(sum(float(v) for v in rows) / len(rows)) if rows else 0.0


def _est_tokens(text: str) -> int:
    return max(1, len(text) // TOKEN_CHARS) if text else 0


def _read_lines(path: Path, start: int, end: int) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return ""
    start = max(1, int(start or 1))
    end = max(start, int(end or start))
    return "\n".join(lines[start - 1:end])


def _salient_terms(query: str) -> list[str]:
    stopwords = {
        "the", "a", "an", "is", "are", "how", "does", "do", "where", "who", "in",
        "to", "of", "for", "and", "or", "with", "find",
    }
    return [t for t in re.findall(r"[A-Za-z_][A-Za-z0-9_]+", query)
            if len(t) >= 3 and t.lower() not in stopwords]


def _ignored(rel: Path) -> bool:
    return any(part in {".git", ".claude", "node_modules", "__pycache__"} for part in rel.parts)


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _case_row(r: ScaleCaseResult) -> dict[str, Any]:
    return {
        "task": r.case.task,
        "query": r.case.query,
        "expected": list(r.case.expected_files),
        "top_5_files": r.ranked_files[:5],
        "hit_at_1": r.hit_at_1,
        "hit_at_3": r.hit_at_3,
        "hit_at_5": r.hit_at_5,
        "mrr": round(r.mrr, 4),
        "index_tokens": r.index_tokens,
        "grep_tokens": r.grep_tokens,
    }


# ── entry point ───────────────────────────────────────────────────────────────

def main() -> int:
    parser = argparse.ArgumentParser(description="M12.5 real-repo benchmark expansion")
    parser.add_argument(
        "--scale",
        default="10k",
        help="Comma-separated scale tiers to run: 10k,100k (default: 10k)",
    )
    parser.add_argument(
        "--workdir",
        type=Path,
        default=Path(".tmp-real-repo-benchmark"),
        help="Working directory for fixture repos and indexes.",
    )
    parser.add_argument(
        "--human-eval",
        action="store_true",
        help="Print per-query results for human review alongside JSON output.",
    )
    args = parser.parse_args()

    tiers = [t.strip() for t in args.scale.split(",") if t.strip()]
    reports: list[ScaleBenchmarkReport] = []

    for tier in tiers:
        if tier not in SCALE_TARGETS:
            print(f"[warn] unknown scale tier '{tier}', skipping (valid: {list(SCALE_TARGETS)})")
            continue
        target_loc = SCALE_TARGETS[tier]
        repo_root = args.workdir / f"repo_{tier}"
        print(f"[{tier}] building {target_loc:,} LOC fixture …", flush=True)
        t0 = time.perf_counter()
        build_scale_fixture(repo_root, target_loc=target_loc)
        build_ms = (time.perf_counter() - t0) * 1000
        print(f"[{tier}] fixture ready in {build_ms:.0f} ms, indexing …", flush=True)
        report = run_scale_benchmark(repo_root, tier)
        reports.append(report)
        print(f"[{tier}] index: {report.scale['files_indexed']} files, "
              f"{report.scale['symbols_indexed']} symbols, "
              f"build {report.scale['build_ms']:.0f} ms", flush=True)

        if args.human_eval:
            print(f"\n{'─'*60}")
            print(f"HUMAN EVAL — {tier}")
            print(f"{'─'*60}")
            for row in report.cases:
                mark = "✓" if row["hit_at_3"] else "✗"
                print(f"[{mark}] [{row['task']}] {row['query']}")
                print(f"     expected : {row['expected'][0] if row['expected'] else '?'}")
                print(f"     got      : {row['top_5_files'][:3]}")
            graph = report.graph_tasks
            print(f"\nGraph tasks: {graph['passed']}/{graph['tasks']} passed")
            for d in graph["details"]:
                mark = "✓" if d["passed"] else "✗"
                print(f"  [{mark}] {d['description']}")
            print()

    combined = {"reports": [json.loads(r.to_json()) for r in reports]}
    print(json.dumps(combined, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
