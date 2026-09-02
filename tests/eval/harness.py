"""Retrieval evaluation harness: query set x tuning -> IR metrics + latency.

Design constraints:
  * Reproducible. The index is built once per corpus into a temp dir and reused
    across every tuning variant in a sweep, so ablation deltas measure ranking,
    not indexing noise.
  * Honest. Ground truth is validated against the source tree before any query
    runs (`validate_queries`); a stale expectation fails the run loudly instead
    of silently deflating scores.
  * In-process. `search()` is called directly, so latency excludes interpreter
    start-up and measures the thing we can actually optimise.
"""

from __future__ import annotations

import statistics
import time
from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from codebase_index.config import Config
from codebase_index.indexer.pipeline import build_index
from codebase_index.retrieval.pipeline import search
from codebase_index.retrieval.tuning import RetrievalTuning
from codebase_index.storage.db import Database

from . import metrics

QUERY_DIR = Path(__file__).parent / "queries"
DEFAULT_BUDGET = 1500
DEFAULT_LIMIT = 10


@dataclass(frozen=True)
class EvalQuery:
    query: str
    category: str
    expected_files: tuple[str, ...]
    expected_symbols: tuple[str, ...] = ()


@dataclass
class QueryOutcome:
    query: EvalQuery
    ranked_files: list[str]
    returned: list[tuple[str, int]]
    latency_ms: float


@dataclass
class EvalReport:
    """Aggregate metrics for one (query set, tuning) pair."""

    label: str
    n_queries: int
    recall_at_5: float
    recall_at_10: float
    mrr: float
    ndcg_at_10: float
    hit_rate_at_3: float
    precision_at_5: float
    map_score: float
    useful_context: float
    p50_ms: float
    p95_ms: float
    p99_ms: float
    mean_ms: float
    per_category: dict[str, float] = field(default_factory=dict)

    def as_row(self) -> dict[str, float | str | int]:
        return {
            "label": self.label,
            "n": self.n_queries,
            "recall@5": self.recall_at_5,
            "recall@10": self.recall_at_10,
            "MRR": self.mrr,
            "nDCG@10": self.ndcg_at_10,
            "hit@3": self.hit_rate_at_3,
            "P@5": self.precision_at_5,
            "MAP": self.map_score,
            "useful@budget": self.useful_context,
            "p50_ms": self.p50_ms,
            "p95_ms": self.p95_ms,
            "p99_ms": self.p99_ms,
        }


def load_queries(name_or_path: str | Path) -> list[EvalQuery]:
    """Load a query set by bare name (`self_repo`) or explicit path."""
    path = Path(name_or_path)
    if not path.is_file():
        path = QUERY_DIR / f"{name_or_path}.yml"
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or []
    out: list[EvalQuery] = []
    for entry in raw:
        out.append(
            EvalQuery(
                query=entry["query"],
                category=entry.get("category", "uncategorized"),
                expected_files=tuple(entry.get("expected_files", ())),
                expected_symbols=tuple(entry.get("expected_symbols", ())),
            )
        )
    return out


def validate_queries(queries: Iterable[EvalQuery], root: Path) -> list[str]:
    """Return a list of ground-truth problems (missing files). Empty == valid."""
    problems: list[str] = []
    for q in queries:
        if not q.expected_files:
            problems.append(f"{q.query!r}: no expected_files (unscoreable)")
        for rel in q.expected_files:
            if not (root / rel).is_file():
                problems.append(f"{q.query!r}: expected file missing from tree: {rel}")
    return problems


# The ground-truth YAML quotes every benchmark query verbatim, so leaving it in
# the corpus makes it the top lexical hit for almost every query — a measurement
# artifact that depresses scores and hides real ranking behaviour. Benchmark
# scaffolding is excluded from the corpus it grades.
CORPUS_EXCLUDES = ("tests/eval/**", "tests/benchmark_*", "tests/fixtures/expected_answers.yml")


def build_corpus_index(root: Path, db_path: Path) -> Database:
    """Build a fresh index for `root` at `db_path` and return the open handle."""
    cfg = Config()
    cfg.root = str(root)
    cfg.embeddings.enabled = False
    cfg.extra_ignore = [*cfg.extra_ignore, *CORPUS_EXCLUDES]
    db = Database(db_path).open()
    build_index(cfg, db, root=root)
    return db


def _normalise(path: str) -> str:
    return path.replace("\\", "/")


def run_query(
    conn,
    q: EvalQuery,
    *,
    tuning: RetrievalTuning,
    limit: int,
    token_budget: int,
    mode: str = "hybrid",
) -> QueryOutcome:
    start = time.perf_counter()
    payload = search(
        conn,
        q.query,
        mode=mode,
        limit=limit,
        token_budget=token_budget,
        no_fallback=True,
        tuning=tuning,
    )
    latency_ms = (time.perf_counter() - start) * 1000.0

    ranked_files: list[str] = []
    returned: list[tuple[str, int]] = []
    for r in payload.get("results", []):
        p = _normalise(r["path"])
        # File-level ranking: the agent's unit of decision is "which file do I
        # open", so multiple hits inside one file collapse to its best rank.
        if p not in ranked_files:
            ranked_files.append(p)
        returned.append((p, int(r.get("token_est") or 0)))
    return QueryOutcome(query=q, ranked_files=ranked_files, returned=returned,
                        latency_ms=latency_ms)


def evaluate(
    conn,
    queries: Sequence[EvalQuery],
    *,
    tuning: RetrievalTuning,
    label: str,
    limit: int = DEFAULT_LIMIT,
    token_budget: int = DEFAULT_BUDGET,
    repeats: int = 1,
) -> EvalReport:
    """Run every query and aggregate metrics. `repeats` only affects latency."""
    outcomes: list[QueryOutcome] = []
    latencies: list[float] = []
    for q in queries:
        outcome = run_query(conn, q, tuning=tuning, limit=limit, token_budget=token_budget)
        outcomes.append(outcome)
        latencies.append(outcome.latency_ms)
        for _ in range(max(0, repeats - 1)):
            latencies.append(
                run_query(conn, q, tuning=tuning, limit=limit,
                          token_budget=token_budget).latency_ms
            )

    def mean(fn) -> float:
        vals = [fn(o) for o in outcomes]
        return statistics.fmean(vals) if vals else 0.0

    per_category: dict[str, list[float]] = {}
    for o in outcomes:
        per_category.setdefault(o.query.category, []).append(
            metrics.reciprocal_rank(o.ranked_files, o.query.expected_files)
        )

    return EvalReport(
        label=label,
        n_queries=len(outcomes),
        recall_at_5=mean(lambda o: metrics.recall_at_k(o.ranked_files, o.query.expected_files, 5)),
        recall_at_10=mean(lambda o: metrics.recall_at_k(o.ranked_files, o.query.expected_files, 10)),
        mrr=mean(lambda o: metrics.reciprocal_rank(o.ranked_files, o.query.expected_files)),
        ndcg_at_10=mean(lambda o: metrics.ndcg_at_k(o.ranked_files, o.query.expected_files, 10)),
        hit_rate_at_3=mean(lambda o: metrics.hit_rate_at_k(o.ranked_files, o.query.expected_files, 3)),
        precision_at_5=mean(lambda o: metrics.precision_at_k(o.ranked_files, o.query.expected_files, 5)),
        map_score=mean(lambda o: metrics.average_precision(o.ranked_files, o.query.expected_files)),
        useful_context=mean(
            lambda o: metrics.useful_context_at_budget(
                o.returned, o.query.expected_files, token_budget
            )
        ),
        p50_ms=metrics.percentile(latencies, 50),
        p95_ms=metrics.percentile(latencies, 95),
        p99_ms=metrics.percentile(latencies, 99),
        mean_ms=statistics.fmean(latencies) if latencies else 0.0,
        per_category={
            cat: statistics.fmean(vals) for cat, vals in sorted(per_category.items())
        },
    )


def format_table(reports: Sequence[EvalReport], *, baseline: EvalReport | None = None) -> str:
    """Render reports as a Markdown table, with deltas against `baseline`."""
    cols = ["label", "recall@5", "recall@10", "MRR", "nDCG@10", "hit@3", "P@5",
            "MAP", "useful@budget", "p50_ms", "p95_ms"]
    lines = ["| " + " | ".join(cols) + " |",
             "|" + "|".join("---" for _ in cols) + "|"]
    for rep in reports:
        row = rep.as_row()
        cells = []
        for c in cols:
            v = row[c]
            if isinstance(v, float):
                cell = f"{v:.3f}" if c.endswith("_ms") is False else f"{v:.1f}"
                if baseline is not None and rep is not baseline:
                    delta = v - float(baseline.as_row()[c])
                    if abs(delta) >= 0.0005:
                        cell += f" ({delta:+.3f})" if not c.endswith("_ms") else f" ({delta:+.1f})"
                cells.append(cell)
            else:
                cells.append(str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)
