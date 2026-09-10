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
from codebase_index.retrieval.diversity import (
    normalize_code_tokens,
    simhash_distance,
    token_fingerprint,
)
from codebase_index.retrieval.pipeline import search
from codebase_index.retrieval.tuning import RetrievalTuning
from codebase_index.storage.db import Database

from . import gen_queries, metrics

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
    total_tokens: int = 0
    """Snippet tokens actually handed to the agent for this query."""
    duplicates: int = 0
    """Results whose snippet near-duplicates an earlier result in the same page."""
    n_results: int = 0
    pool_files: list[str] = field(default_factory=list)
    """Distinct files in the pre-rerank candidate pool, in fused order.

    The oracle metrics are computed against this, so they measure exactly what the
    ranker was handed — not what the retrievers could have found with other
    settings."""


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
    mean_tokens: float = 0.0
    """Mean tokens of snippet context returned per query — the agent's actual bill."""
    duplicate_rate: float = 0.0
    """Fraction of returned results that near-duplicate an earlier result."""
    mean_candidates: float = 0.0
    """Mean results returned per query, before the agent reads anything."""
    oracle_mrr: float = 0.0
    """Ceiling MRR a perfect reranker could reach over the pool actually generated.

    `1 - oracle_mrr` is the share of the query set no reranking can ever fix."""
    candidate_recall: float = 0.0
    """Mean fraction of expected files present anywhere in the candidate pool."""
    mean_pool: float = 0.0
    """Mean distinct files in the candidate pool, i.e. what the ranker chose from."""
    per_category: dict[str, float] = field(default_factory=dict)
    per_query: dict[str, list[float]] = field(default_factory=dict)
    """Per-query metric vectors, in query order. Required for paired significance
    testing: aggregate deltas alone cannot separate a real gain from resampling
    noise on a set this size."""

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
            "tokens": self.mean_tokens,
            "dup%": self.duplicate_rate * 100.0,
            "p50_ms": self.p50_ms,
            "p95_ms": self.p95_ms,
            "p99_ms": self.p99_ms,
            "oracle": self.oracle_mrr,
            "eff": metrics.rerank_efficiency(self.mrr, self.oracle_mrr),
            "cand_recall": self.candidate_recall,
            "pool": self.mean_pool,
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
#
# Changelog-like files are excluded for the mirror-image reason: a git-derived
# query *is* a commit subject, and a changelog entry paraphrases that subject
# verbatim while never being an accepted answer (`gen_queries._ANSWER_DENY_RE`).
# Indexing them plants an unbeatable distractor at rank 1 for a large share of
# queries, which compresses every variant's score toward the same floor and hides
# ranking differences. `gen_queries.CHANGELOG_EXCLUDES` documented this exclusion;
# it was never applied to the corpus.
CORPUS_EXCLUDES = (
    "tests/eval/**",
    "tests/benchmark_*",
    "tests/fixtures/expected_answers.yml",
    *gen_queries.CHANGELOG_EXCLUDES,
)


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
        # The pre-rerank pool is what the oracle metrics are measured against.
        # Building it costs ~30 dict literals per query, which is inside the noise
        # of a 38ms query (measured: -0.8ms p50, i.e. unmeasurable), so it stays on
        # for the timed call rather than forcing a second untimed pass.
        explain=True,
    )
    latency_ms = (time.perf_counter() - start) * 1000.0
    pool_files: list[str] = []
    for entry in payload.get("diagnostics", {}).get("pool", ()):
        p = _normalise(entry["path"])
        if p not in pool_files:
            pool_files.append(p)

    ranked_files: list[str] = []
    returned: list[tuple[str, int]] = []
    total_tokens = 0
    duplicates = 0
    fingerprints: list[int] = []
    results = payload.get("results", [])
    for r in results:
        p = _normalise(r["path"])
        # File-level ranking: the agent's unit of decision is "which file do I
        # open", so multiple hits inside one file collapse to its best rank.
        if p not in ranked_files:
            ranked_files.append(p)
        tokens = int(r.get("token_est") or 0)
        returned.append((p, tokens))
        snippet = r.get("snippet")
        # Only snippets are actually placed in the agent's context. Results past
        # the budget still carry a `token_est` for their (unread) chunk, so summing
        # it would report a bill the agent never pays.
        if snippet:
            total_tokens += tokens
        # Duplicate rate is measured on what the agent actually receives, using the
        # same fingerprint the pipeline suppresses with — so the number reports the
        # residual noise after selection, not the raw candidate overlap.
        chunk_tokens = normalize_code_tokens(snippet or "")
        if chunk_tokens:
            fingerprint = token_fingerprint(chunk_tokens)
            if any(simhash_distance(fingerprint, seen) <= 3 for seen in fingerprints):
                duplicates += 1
            fingerprints.append(fingerprint)
    return QueryOutcome(
        query=q,
        ranked_files=ranked_files,
        returned=returned,
        latency_ms=latency_ms,
        total_tokens=total_tokens,
        duplicates=duplicates,
        n_results=len(results),
        pool_files=pool_files,
    )


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

    # Named metric extractors, so aggregate values and the per-query vectors used
    # for significance testing can never be computed two different ways.
    scorers = {
        "recall@5": lambda o: metrics.recall_at_k(o.ranked_files, o.query.expected_files, 5),
        "recall@10": lambda o: metrics.recall_at_k(o.ranked_files, o.query.expected_files, 10),
        "MRR": lambda o: metrics.reciprocal_rank(o.ranked_files, o.query.expected_files),
        "nDCG@10": lambda o: metrics.ndcg_at_k(o.ranked_files, o.query.expected_files, 10),
        "hit@3": lambda o: metrics.hit_rate_at_k(o.ranked_files, o.query.expected_files, 3),
        "P@5": lambda o: metrics.precision_at_k(o.ranked_files, o.query.expected_files, 5),
        "MAP": lambda o: metrics.average_precision(o.ranked_files, o.query.expected_files),
        "useful@budget": lambda o: metrics.useful_context_at_budget(
            o.returned, o.query.expected_files, token_budget
        ),
        # Scored per query so the oracle ceiling gets the same paired significance
        # treatment as everything else: a ranking change that only moved the
        # ceiling has not improved ranking.
        "oracle": lambda o: metrics.oracle_reciprocal_rank(
            o.pool_files, o.query.expected_files
        ),
        "cand_recall": lambda o: metrics.recall_at_k(
            o.pool_files, o.query.expected_files, len(o.pool_files)
        ),
    }
    per_query = {name: [fn(o) for o in outcomes] for name, fn in scorers.items()}

    def mean(name: str) -> float:
        vals = per_query[name]
        return statistics.fmean(vals) if vals else 0.0

    per_category: dict[str, list[float]] = {}
    for o, rr in zip(outcomes, per_query["MRR"]):
        per_category.setdefault(o.query.category, []).append(rr)

    returned_total = sum(o.n_results for o in outcomes)
    duplicate_total = sum(o.duplicates for o in outcomes)

    return EvalReport(
        label=label,
        n_queries=len(outcomes),
        recall_at_5=mean("recall@5"),
        recall_at_10=mean("recall@10"),
        mrr=mean("MRR"),
        ndcg_at_10=mean("nDCG@10"),
        hit_rate_at_3=mean("hit@3"),
        precision_at_5=mean("P@5"),
        map_score=mean("MAP"),
        useful_context=mean("useful@budget"),
        p50_ms=metrics.percentile(latencies, 50),
        p95_ms=metrics.percentile(latencies, 95),
        p99_ms=metrics.percentile(latencies, 99),
        mean_ms=statistics.fmean(latencies) if latencies else 0.0,
        mean_tokens=(
            statistics.fmean([o.total_tokens for o in outcomes]) if outcomes else 0.0
        ),
        duplicate_rate=(duplicate_total / returned_total) if returned_total else 0.0,
        mean_candidates=(returned_total / len(outcomes)) if outcomes else 0.0,
        oracle_mrr=mean("oracle"),
        candidate_recall=mean("cand_recall"),
        mean_pool=(
            statistics.fmean([len(o.pool_files) for o in outcomes]) if outcomes else 0.0
        ),
        per_category={
            cat: statistics.fmean(vals) for cat, vals in sorted(per_category.items())
        },
        per_query=per_query,
    )


_WIDE_COLS = ("tokens", "dup%")


def format_table(
    reports: Sequence[EvalReport],
    *,
    baseline: EvalReport | None = None,
    columns: Sequence[str] | None = None,
) -> str:
    """Render reports as a Markdown table, with deltas against `baseline`."""
    cols = list(columns) if columns else [
        "label", "recall@5", "recall@10", "MRR", "oracle", "eff", "nDCG@10",
        "hit@3", "P@5", "MAP", "useful@budget", "tokens", "dup%", "p50_ms", "p95_ms",
    ]
    lines = ["| " + " | ".join(cols) + " |",
             "|" + "|".join("---" for _ in cols) + "|"]
    for rep in reports:
        row = rep.as_row()
        cells = []
        for c in cols:
            v = row[c]
            if isinstance(v, float):
                coarse = c.endswith("_ms") or c in _WIDE_COLS
                cell = f"{v:.1f}" if coarse else f"{v:.3f}"
                if baseline is not None and rep is not baseline:
                    delta = v - float(baseline.as_row()[c])
                    if abs(delta) >= (0.05 if coarse else 0.0005):
                        cell += f" ({delta:+.1f})" if coarse else f" ({delta:+.3f})"
                cells.append(cell)
            else:
                cells.append(str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def pool(reports: Sequence[EvalReport], *, label: str) -> EvalReport:
    """Concatenate per-corpus reports into one, weighting every query equally.

    Averaging the per-corpus averages would let a 36-query corpus outvote a
    118-query one; pooling the raw per-query vectors keeps one query = one vote and
    is what makes the significance tests valid across a mixed-language benchmark.
    """
    reports = list(reports)
    if not reports:
        raise ValueError("cannot pool an empty report list")

    per_query: dict[str, list[float]] = {}
    for rep in reports:
        for name, values in rep.per_query.items():
            per_query.setdefault(name, []).extend(values)

    def mean(name: str) -> float:
        vals = per_query.get(name, [])
        return statistics.fmean(vals) if vals else 0.0

    total = sum(rep.n_queries for rep in reports) or 1

    def weighted(attr: str) -> float:
        return sum(getattr(rep, attr) * rep.n_queries for rep in reports) / total

    per_category: dict[str, list[float]] = {}
    for rep in reports:
        for cat, value in rep.per_category.items():
            per_category.setdefault(cat, []).append(value)

    return EvalReport(
        label=label,
        n_queries=total,
        recall_at_5=mean("recall@5"),
        recall_at_10=mean("recall@10"),
        mrr=mean("MRR"),
        ndcg_at_10=mean("nDCG@10"),
        hit_rate_at_3=mean("hit@3"),
        precision_at_5=mean("P@5"),
        map_score=mean("MAP"),
        useful_context=mean("useful@budget"),
        # Latency percentiles cannot be pooled from percentiles; report the
        # query-weighted mean of each, which is honest about being an approximation
        # only when corpora differ wildly in size.
        p50_ms=weighted("p50_ms"),
        p95_ms=weighted("p95_ms"),
        p99_ms=weighted("p99_ms"),
        mean_ms=weighted("mean_ms"),
        mean_tokens=weighted("mean_tokens"),
        duplicate_rate=weighted("duplicate_rate"),
        mean_candidates=weighted("mean_candidates"),
        oracle_mrr=mean("oracle"),
        candidate_recall=mean("cand_recall"),
        mean_pool=weighted("mean_pool"),
        per_category={c: statistics.fmean(v) for c, v in sorted(per_category.items())},
        per_query=per_query,
    )


def format_significance(
    baseline: EvalReport,
    candidate: EvalReport,
    *,
    resamples: int = 5000,
) -> str:
    """Paired bootstrap CI + permutation p-value per metric, candidate vs baseline."""
    lines = [
        f"paired comparison: {candidate.label} vs {baseline.label} "
        f"(n={min(baseline.n_queries, candidate.n_queries)})",
        f"| {'metric':13} | {'delta':>8} | {'95% CI':>19} | {'p':>6} | sig |",
        "|" + "|".join("---" for _ in range(5)) + "|",
    ]
    for name, base_values in baseline.per_query.items():
        cand_values = candidate.per_query.get(name, [])
        if len(cand_values) != len(base_values):
            continue
        deltas = [c - b for b, c in zip(base_values, cand_values)]
        delta, lo, hi = metrics.paired_bootstrap_ci(deltas, resamples=resamples)
        p = metrics.paired_permutation_p(deltas, resamples=resamples)
        lines.append(
            f"| {name:13} | {delta:+8.4f} | [{lo:+.4f},{hi:+.4f}] | {p:6.3f} | "
            f"{'yes' if p < 0.05 else 'no':3} |"
        )
    return "\n".join(lines)
