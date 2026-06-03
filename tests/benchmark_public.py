#!/usr/bin/env python3
"""Public benchmark suite for codebase-index.

The suite is intentionally reproducible: it creates a deterministic multi-language
fixture repo, builds an index, runs quality/token/freshness/graph checks, and
prints JSON. Larger real-repo benchmarks can plug into the same metric helpers.

Run:
    python tests/benchmark_public.py --workdir .tmp-public-benchmark
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
from codebase_index.indexer.freshness import compute_freshness
from codebase_index.indexer.pipeline import build_index, update_index
from codebase_index.retrieval.pipeline import search
from codebase_index.storage import repo as repo_store
from codebase_index.storage.db import Database

TOKEN_CHARS = 4
GREP_WINDOW = 80


@dataclass(frozen=True)
class BenchmarkCase:
    query: str
    expected_files: tuple[str, ...]
    expected_symbols: tuple[str, ...] = ()
    language: str = "unknown"
    task: str = "retrieval"


@dataclass
class CaseResult:
    case: BenchmarkCase
    ranked_files: list[str]
    ranked_symbols: list[str]
    index_tokens: int
    grep_tokens: int
    answer_correct: bool


@dataclass
class BenchmarkReport:
    retrieval_quality: dict[str, float]
    answer_correctness: dict[str, float]
    token_economy: dict[str, float]
    language_breakdown: dict[str, dict[str, float]]
    freshness: dict[str, float | bool]
    graph_tasks: dict[str, float | int]
    scale: dict[str, int]
    cases: list[dict[str, Any]] = field(default_factory=list)

    def to_json(self) -> str:
        return json.dumps(
            {
                "retrieval_quality": self.retrieval_quality,
                "answer_correctness": self.answer_correctness,
                "token_economy": self.token_economy,
                "language_breakdown": self.language_breakdown,
                "freshness": self.freshness,
                "graph_tasks": self.graph_tasks,
                "scale": self.scale,
                "cases": self.cases,
            },
            indent=2,
            ensure_ascii=False,
        )


CASES = [
    BenchmarkCase(
        query="where is refresh access token implemented",
        expected_files=("src/auth/token.py",),
        expected_symbols=("refresh_access_token",),
        language="python",
        task="implementation",
    ),
    BenchmarkCase(
        query="who handles auth login route in TypeScript",
        expected_files=("web/routes/auth.ts",),
        expected_symbols=("loginRoute",),
        language="typescript",
        task="route",
    ),
    BenchmarkCase(
        query="how does war capture resolution work in Java",
        expected_files=("server/java/WarManager.java",),
        expected_symbols=("resolveCapture",),
        language="java",
        task="implementation",
    ),
    BenchmarkCase(
        query="find go payment authorization service",
        expected_files=("services/go/payment.go",),
        expected_symbols=("AuthorizePayment",),
        language="go",
        task="implementation",
    ),
    BenchmarkCase(
        query="rust settlement score calculation",
        expected_files=("services/rust/src/lib.rs",),
        expected_symbols=("settlement_score",),
        language="rust",
        task="implementation",
    ),
    BenchmarkCase(
        query="csharp user repository save operation",
        expected_files=("services/csharp/UserRepository.cs",),
        expected_symbols=("SaveUser",),
        language="csharp",
        task="implementation",
    ),
    BenchmarkCase(
        query="php order controller submits order",
        expected_files=("services/php/OrderController.php",),
        expected_symbols=("submitOrder",),
        language="php",
        task="controller",
    ),
    BenchmarkCase(
        query="database migration creates users table",
        expected_files=("db/migrations/001_create_users.sql",),
        language="sql",
        task="config",
    ),
]


def build_public_fixture(root: Path, *, filler_files: int = 24) -> Path:
    if root.exists():
        shutil.rmtree(root)
    root.mkdir(parents=True)
    _write(root / ".gitignore", ".claude/cache/codebase-index/\nnode_modules/\n")
    _write(
        root / "src/auth/token.py",
        """\
def refresh_access_token(refresh_token: str) -> str:
    \"\"\"Exchange a refresh token for a new access token.\"\"\"
    return "access-" + refresh_token


def login(refresh_token: str) -> str:
    return refresh_access_token(refresh_token)
""",
    )
    _write(
        root / "src/models/user.py",
        """\
class User:
    def __init__(self, name: str) -> None:
        self.name = name
""",
    )
    _write(
        root / "src/api/service.py",
        """\
from auth.token import refresh_access_token
from models.user import User


class AdminUser(User):
    def renew(self, refresh_token: str) -> str:
        return refresh_access_token(refresh_token)
""",
    )
    _write(
        root / "web/routes/auth.ts",
        """\
export class AuthController {
  loginRoute(request: Request): Response {
    return new Response("login ok")
  }
}

export function loginRoute(request: Request): Response {
  return new AuthController().loginRoute(request)
}
""",
    )
    _write(
        root / "server/java/WarManager.java",
        """\
package server.java;

public class WarManager {
    public int resolveCapture(int attackers, int defenders) {
        return attackers - defenders;
    }
}
""",
    )
    _write(
        root / "services/go/payment.go",
        """\
package payment

func AuthorizePayment(userId string, cents int) bool {
    return userId != "" && cents > 0
}
""",
    )
    _write(
        root / "services/rust/src/lib.rs",
        """\
pub fn settlement_score(population: i32, buildings: i32) -> i32 {
    population * 2 + buildings * 5
}
""",
    )
    _write(
        root / "services/csharp/UserRepository.cs",
        """\
namespace Services {
  public class UserRepository {
    public void SaveUser(string name) {
      System.Console.WriteLine(name);
    }
  }
}
""",
    )
    _write(
        root / "services/php/OrderController.php",
        """\
<?php
class OrderController {
    public function submitOrder($request) {
        return ["status" => "submitted"];
    }
}
""",
    )
    _write(
        root / "db/migrations/001_create_users.sql",
        """\
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL
);
""",
    )
    for i in range(filler_files):
        _write(
            root / "docs" / f"filler_{i:03d}.md",
            f"Documentation filler {i}\n\nThis file mentions generic project notes and search noise.\n",
        )
    return root


def run_public_benchmark(root: Path) -> BenchmarkReport:
    cfg = Config()
    cfg.root = str(root)
    cfg.embeddings.enabled = False
    db_path = root / ".claude" / "cache" / "codebase-index" / "index.sqlite"

    with Database(db_path) as db:
        build_stats = build_index(cfg, db, root=root)
        case_results = [_run_case(db, root, case) for case in CASES]
        freshness = _freshness_metrics(db, root, cfg)
        graph = _graph_metrics(db)
        scale = {
            "files_indexed": repo_store.count_files(db.conn),
            "symbols_indexed": repo_store.count_symbols(db.conn),
            "edges_indexed": repo_store.count_edges(db.conn),
            "bytes_indexed": build_stats.total_bytes,
        }

    return BenchmarkReport(
        retrieval_quality=_retrieval_metrics(case_results),
        answer_correctness=_answer_metrics(case_results),
        token_economy=_token_metrics(case_results),
        language_breakdown=_language_metrics(case_results),
        freshness=freshness,
        graph_tasks=graph,
        scale=scale,
        cases=[_case_row(r) for r in case_results],
    )


def _run_case(db: Database, root: Path, case: BenchmarkCase) -> CaseResult:
    payload = search(
        db.conn,
        case.query,
        mode="hybrid",
        limit=10,
        token_budget=5000,
        no_fallback=False,
        root=root,
        config=_config_for(root),
    )
    ranked_files = [r["path"] for r in payload.get("results", [])]
    ranked_symbols: list[str] = []
    for result in payload.get("results", []):
        ranked_symbols.extend(result.get("symbols", []))
    index_tokens = _tokens_for_index_payload(root, payload)
    grep_tokens = _tokens_for_grep_window(root, case.query)
    answer_correct = _hit_at(ranked_files, case.expected_files, 3)
    if case.expected_symbols:
        answer_correct = answer_correct and bool(set(case.expected_symbols) & set(ranked_symbols[:5]))
    return CaseResult(case, ranked_files, ranked_symbols, index_tokens, grep_tokens, answer_correct)


def _config_for(root: Path) -> Config:
    cfg = Config()
    cfg.root = str(root)
    cfg.embeddings.enabled = False
    return cfg


def _retrieval_metrics(results: list[CaseResult]) -> dict[str, float]:
    return {
        "recall_at_1": _mean(_hit_at(r.ranked_files, r.case.expected_files, 1) for r in results),
        "recall_at_3": _mean(_hit_at(r.ranked_files, r.case.expected_files, 3) for r in results),
        "recall_at_5": _mean(_hit_at(r.ranked_files, r.case.expected_files, 5) for r in results),
        "mrr": _mean(_reciprocal_rank(r.ranked_files, r.case.expected_files) for r in results),
        "ndcg_at_5": _mean(_ndcg_at_k(r.ranked_files, r.case.expected_files, 5) for r in results),
    }


def _answer_metrics(results: list[CaseResult]) -> dict[str, float]:
    return {"answer_correctness_at_3": _mean(r.answer_correct for r in results)}


def _token_metrics(results: list[CaseResult]) -> dict[str, float]:
    index_avg = _mean(r.index_tokens for r in results)
    grep_avg = _mean(r.grep_tokens for r in results)
    return {
        "index_tokens_avg": index_avg,
        "grep_window_tokens_avg": grep_avg,
        "tokens_saved_avg": grep_avg - index_avg,
        "compression_vs_grep": grep_avg / max(index_avg, 1.0),
    }


def _language_metrics(results: list[CaseResult]) -> dict[str, dict[str, float]]:
    out: dict[str, dict[str, float]] = {}
    for lang in sorted({r.case.language for r in results}):
        rows = [r for r in results if r.case.language == lang]
        out[lang] = {
            "cases": float(len(rows)),
            "recall_at_3": _mean(_hit_at(r.ranked_files, r.case.expected_files, 3) for r in rows),
            "answer_correctness_at_3": _mean(r.answer_correct for r in rows),
        }
    return out


def _freshness_metrics(db: Database, root: Path, cfg: Config) -> dict[str, float | bool]:
    target = root / "src" / "auth" / "token.py"
    before = compute_freshness(db.conn, root, cfg)
    time.sleep(0.01)  # ensure mtime changes on coarse filesystems
    target.write_text(target.read_text(encoding="utf-8") + "\n# benchmark freshness edit\n", encoding="utf-8")
    stale = compute_freshness(db.conn, root, cfg)
    start = time.perf_counter()
    stats = update_index(cfg, db, root=root)
    update_ms = (time.perf_counter() - start) * 1000
    after = compute_freshness(db.conn, root, cfg)
    return {
        "was_fresh_before_edit": not before.stale,
        "stale_after_edit": stale.stale,
        "files_changed_after_edit": float(stale.files_changed_since_build),
        "update_latency_ms": update_ms,
        "files_reindexed": float(stats.indexed),
        "fresh_after_update": not after.stale,
    }


def _graph_metrics(db: Database) -> dict[str, float | int]:
    tasks = [
        ("refresh_access_token", "up", "src/api/service.py"),
        ("renew", "down", "src/auth/token.py"),
        ("src/models/user.py", "up", "src/api/service.py"),
    ]
    passed = 0
    for target, direction, expected_file in tasks:
        resp = impact_lookup(db.conn, target, depth=2, direction=direction)
        if expected_file in resp.files or any(n.path == expected_file for n in resp.nodes):
            passed += 1
    return {"tasks": len(tasks), "passed": passed, "pass_rate": passed / len(tasks)}


def _tokens_for_index_payload(root: Path, payload: dict[str, Any], top_k: int = 3) -> int:
    total = 0
    for result in payload.get("results", [])[:top_k]:
        snippet = result.get("snippet")
        if snippet:
            total += _estimate_tokens(snippet)
            continue
        path = root / result["path"]
        total += _estimate_tokens(_read_lines(path, result.get("line_start", 1), result.get("line_end", 80)))
    return total


def _tokens_for_grep_window(root: Path, query: str, top_k: int = 3) -> int:
    terms = _salient_terms(query)
    scored: list[tuple[int, Path, int]] = []
    for path in root.rglob("*"):
        if not path.is_file() or _ignored(path.relative_to(root)):
            continue
        try:
            lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
        except OSError:
            continue
        hits = [
            idx for idx, line in enumerate(lines, start=1)
            if any(term.lower() in line.lower() for term in terms)
        ]
        if hits:
            scored.append((len(hits), path, hits[len(hits) // 2]))
    scored.sort(key=lambda row: row[0], reverse=True)
    total = 0
    for _score, path, center in scored[:top_k]:
        total += _estimate_tokens(_read_lines(path, center - GREP_WINDOW // 2, center + GREP_WINDOW // 2))
    return total


def _read_lines(path: Path, start: int, end: int) -> str:
    try:
        lines = path.read_text(encoding="utf-8", errors="ignore").splitlines()
    except OSError:
        return ""
    start = max(1, int(start or 1))
    end = max(start, int(end or start))
    return "\n".join(lines[start - 1:end])


def _estimate_tokens(text: str) -> int:
    return max(1, len(text) // TOKEN_CHARS) if text else 0


def _salient_terms(query: str) -> list[str]:
    stopwords = {
        "the", "a", "an", "is", "are", "how", "does", "do", "where", "who", "in",
        "to", "of", "for", "and", "or", "with", "find",
    }
    return [
        token for token in re.findall(r"[A-Za-z_][A-Za-z0-9_]+", query)
        if len(token) >= 3 and token.lower() not in stopwords
    ]


def _ignored(rel: Path) -> bool:
    return any(part in {".git", ".claude", "node_modules", "__pycache__"} for part in rel.parts)


def _hit_at(ranked_files: list[str], expected_files: tuple[str, ...], k: int) -> bool:
    top = ranked_files[:k]
    return any(any(path.endswith(expected) for path in top) for expected in expected_files)


def _reciprocal_rank(ranked_files: list[str], expected_files: tuple[str, ...]) -> float:
    for idx, path in enumerate(ranked_files, start=1):
        if any(path.endswith(expected) for expected in expected_files):
            return 1.0 / idx
    return 0.0


def _ndcg_at_k(ranked_files: list[str], expected_files: tuple[str, ...], k: int) -> float:
    dcg = 0.0
    matched: set[str] = set()
    for idx, path in enumerate(ranked_files[:k], start=1):
        hit = next((expected for expected in expected_files if path.endswith(expected)), None)
        if hit is not None and hit not in matched:
            matched.add(hit)
            dcg += 1.0 / math.log2(idx + 1)
    ideal_hits = min(len(expected_files), k)
    idcg = sum(1.0 / math.log2(idx + 1) for idx in range(1, ideal_hits + 1))
    return dcg / idcg if idcg else 0.0


def _mean(values) -> float:
    rows = list(values)
    if not rows:
        return 0.0
    return float(sum(float(v) for v in rows) / len(rows))


def _case_row(result: CaseResult) -> dict[str, Any]:
    return {
        "query": result.case.query,
        "language": result.case.language,
        "task": result.case.task,
        "expected_files": list(result.case.expected_files),
        "top_files": result.ranked_files[:5],
        "index_tokens": result.index_tokens,
        "grep_tokens": result.grep_tokens,
        "answer_correct": result.answer_correct,
    }


def _write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workdir", type=Path, default=Path(".tmp-public-benchmark"))
    parser.add_argument("--filler-files", type=int, default=24)
    args = parser.parse_args()

    root = build_public_fixture(args.workdir / "repo", filler_files=args.filler_files)
    report = run_public_benchmark(root)
    print(report.to_json())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
