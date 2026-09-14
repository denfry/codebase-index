"""Benchmark runner: many systems, one query sweep, paired significance.

Design constraints inherited from `tests/eval/harness.py`, deliberately, so that the
numbers here are comparable with the ones the product publishes:

  * one index per corpus, shared by every variant -- deltas measure retrieval, not
    indexing variance;
  * metrics come from `tests.eval.metrics` verbatim, never reimplemented;
  * every variant sees the identical query in the identical order, so per-query
    vectors stay aligned and the paired bootstrap / permutation tests are valid.

One constraint is new here. The co-change relation must never see the query's own
commit, so queries are swept **oldest-first** and the history model is advanced
monotonically. Running all variants inside one sweep is therefore not just faster --
it is what guarantees every variant sees exactly the same revealed history.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sqlite3
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Optional

import yaml

from codebase_index.retrieval.diversity import (
    normalize_code_tokens, simhash_distance, token_fingerprint,
)
from codebase_index.retrieval.tuning import RetrievalTuning
from tests.eval import metrics
from tests.eval.harness import EvalReport, format_significance, format_table, pool

from . import baselines
from .relations import CoChangeModel, RelationGraph, RelationWeights, load_static_edges
from .search import NucleusParams, ObligationIndex, nucleus_search


@dataclass(frozen=True)
class Query:
    query: str
    category: str
    expected_files: tuple[str, ...]
    commit: str
    position: int          # git log position; larger == older


@dataclass
class Ctx:
    """Everything a variant may need for one corpus."""
    conn: sqlite3.Connection
    graph: RelationGraph
    obligations: ObligationIndex
    lsa: Optional[baselines.LSAIndex] = None


Variant = Callable[[Ctx, str], dict]


@dataclass
class Outcome:
    ranked_files: list[str]
    returned: list[tuple[str, int]]
    latency_ms: float
    total_tokens: int
    duplicates: int
    n_results: int
    pool_files: list[str]


def _norm(p: str) -> str:
    return p.replace("\\", "/")


def load_queries(path: Path, repo: Path) -> list[Query]:
    import subprocess

    raw = subprocess.run(["git", "-C", str(repo), "log", "--format=%H"],
                         capture_output=True, text=True, encoding="utf-8",
                         errors="replace")
    order = {s.strip()[:12]: i for i, s in enumerate(raw.stdout.splitlines()) if s.strip()}
    out: list[Query] = []
    for e in yaml.safe_load(path.read_text(encoding="utf-8")) or []:
        commit = e.get("commit", "")
        pos = order.get(commit)
        if pos is None:
            continue
        out.append(Query(
            query=e["query"], category=e.get("category", "uncategorized"),
            expected_files=tuple(_norm(f) for f in e.get("expected_files", ())),
            commit=commit, position=pos,
        ))
    # Oldest first: the co-change model is append-only and must never see the future.
    out.sort(key=lambda q: -q.position)
    return out


def outcome_from_payload(payload: dict, latency_ms: float) -> Outcome:
    """Mirrors tests/eval/harness.run_query's accounting exactly.

    Only snippets are billed (results past the budget carry a token_est for a chunk
    the agent never receives); file-level ranking collapses several hits in one file
    to its best rank; duplicates are measured with the pipeline's own fingerprint.
    """
    pool_files: list[str] = []
    for entry in payload.get("diagnostics", {}).get("pool", ()):
        p = _norm(entry["path"])
        if p not in pool_files:
            pool_files.append(p)

    ranked_files: list[str] = []
    returned: list[tuple[str, int]] = []
    total_tokens = 0
    duplicates = 0
    fingerprints: list[int] = []
    results = payload.get("results", [])
    for r in results:
        p = _norm(r["path"])
        if p not in ranked_files:
            ranked_files.append(p)
        tokens = int(r.get("token_est") or 0)
        returned.append((p, tokens))
        snippet = r.get("snippet")
        if snippet:
            total_tokens += tokens
        chunk_tokens = normalize_code_tokens(snippet or "")
        if chunk_tokens:
            fp = token_fingerprint(chunk_tokens)
            if any(simhash_distance(fp, seen) <= 3 for seen in fingerprints):
                duplicates += 1
            fingerprints.append(fp)
    return Outcome(ranked_files, returned, latency_ms, total_tokens, duplicates,
                   len(results), pool_files)


def aggregate(label: str, queries: list[Query], outcomes: list[Outcome],
              *, token_budget: int) -> EvalReport:
    scorers = {
        "recall@5": lambda q, o: metrics.recall_at_k(o.ranked_files, q.expected_files, 5),
        "recall@10": lambda q, o: metrics.recall_at_k(o.ranked_files, q.expected_files, 10),
        "recall@15": lambda q, o: metrics.recall_at_k(o.ranked_files, q.expected_files, 15),
        "MRR": lambda q, o: metrics.reciprocal_rank(o.ranked_files, q.expected_files),
        "nDCG@10": lambda q, o: metrics.ndcg_at_k(o.ranked_files, q.expected_files, 10),
        "hit@3": lambda q, o: metrics.hit_rate_at_k(o.ranked_files, q.expected_files, 3),
        "P@5": lambda q, o: metrics.precision_at_k(o.ranked_files, q.expected_files, 5),
        "MAP": lambda q, o: metrics.average_precision(o.ranked_files, q.expected_files),
        "useful@budget": lambda q, o: metrics.useful_context_at_budget(
            o.returned, q.expected_files, token_budget),
        # Token-normalised recall at three budgets. This is the agent-centric view:
        # not "is the answer ranked somewhere" but "is it inside the context the
        # agent can afford", which is the only axis on which a system returning a
        # bigger page can be compared fairly with one returning a smaller page.
        "useful@500": lambda q, o: metrics.useful_context_at_budget(
            o.returned, q.expected_files, 500),
        "useful@1000": lambda q, o: metrics.useful_context_at_budget(
            o.returned, q.expected_files, 1000),
        "oracle": lambda q, o: metrics.oracle_reciprocal_rank(o.pool_files, q.expected_files),
        "cand_recall": lambda q, o: metrics.recall_at_k(
            o.pool_files, q.expected_files, len(o.pool_files)),
    }
    per_query = {n: [fn(q, o) for q, o in zip(queries, outcomes)] for n, fn in scorers.items()}

    def mean(n: str) -> float:
        v = per_query[n]
        return statistics.fmean(v) if v else 0.0

    per_cat: dict[str, list[float]] = {}
    for q, rr in zip(queries, per_query["MRR"]):
        per_cat.setdefault(q.category, []).append(rr)
    lat = [o.latency_ms for o in outcomes]
    returned_total = sum(o.n_results for o in outcomes)
    dup_total = sum(o.duplicates for o in outcomes)
    return EvalReport(
        label=label, n_queries=len(outcomes),
        recall_at_5=mean("recall@5"), recall_at_10=mean("recall@10"), mrr=mean("MRR"),
        ndcg_at_10=mean("nDCG@10"), hit_rate_at_3=mean("hit@3"),
        precision_at_5=mean("P@5"), map_score=mean("MAP"),
        useful_context=mean("useful@budget"),
        p50_ms=metrics.percentile(lat, 50), p95_ms=metrics.percentile(lat, 95),
        p99_ms=metrics.percentile(lat, 99),
        mean_ms=statistics.fmean(lat) if lat else 0.0,
        mean_tokens=statistics.fmean([o.total_tokens for o in outcomes]) if outcomes else 0.0,
        duplicate_rate=(dup_total / returned_total) if returned_total else 0.0,
        mean_candidates=(returned_total / len(outcomes)) if outcomes else 0.0,
        oracle_mrr=mean("oracle"), candidate_recall=mean("cand_recall"),
        mean_pool=statistics.fmean([len(o.pool_files) for o in outcomes]) if outcomes else 0.0,
        per_category={c: statistics.fmean(v) for c, v in sorted(per_cat.items())},
        per_query=per_query,
    )


# --- variants ----------------------------------------------------------------


LIMIT = 10
BUDGET = 1500


def make_variants(names: set[str], nucleus_params: dict[str, NucleusParams]) -> dict[str, Variant]:
    v: dict[str, Variant] = {}
    if "bm25" in names:
        v["bm25"] = lambda ctx, q: baselines.finalize(
            baselines.bm25_candidates(ctx.conn, q, limit=LIMIT),
            query=q, token_budget=BUDGET, limit=LIMIT)
    if "dense" in names:
        v["dense"] = lambda ctx, q: baselines.finalize(
            ctx.lsa.query(q, limit=LIMIT) if ctx.lsa else [],
            query=q, token_budget=BUDGET, limit=LIMIT)
    if "rag" in names:
        v["rag"] = lambda ctx, q: baselines.finalize(
            baselines.rrf_hybrid(
                baselines.bm25_candidates(ctx.conn, q, limit=LIMIT),
                ctx.lsa.query(q, limit=LIMIT) if ctx.lsa else []),
            query=q, token_budget=BUDGET, limit=LIMIT)
    if "hybrid13" in names:
        def _hybrid13(ctx: Ctx, q: str) -> dict:
            # The incumbent, allowed exactly the page growth NUCLEUS takes. Without
            # this row a "bigger page wins" result would be indistinguishable from a
            # "better page wins" result.
            cands, pool_paths = baselines.product_candidates(
                ctx.conn, q, limit=13, tuning=RetrievalTuning())
            return baselines.finalize(cands, query=q, token_budget=BUDGET,
                                      limit=13, pool_paths=pool_paths)
        v["hybrid13"] = _hybrid13
    if "hybrid" in names:
        def _hybrid(ctx: Ctx, q: str) -> dict:
            cands, pool_paths = baselines.product_candidates(
                ctx.conn, q, limit=LIMIT, tuning=RetrievalTuning())
            return baselines.finalize(cands, query=q, token_budget=BUDGET,
                                      limit=LIMIT, pool_paths=pool_paths)
        v["hybrid"] = _hybrid
    if "graph" in names:
        def _graph(ctx: Ctx, q: str) -> dict:
            cands, pool_paths = baselines.product_candidates(
                ctx.conn, q, limit=LIMIT, tuning=baselines.GRAPH_TUNING,
                force_graph=True)
            return baselines.finalize(cands, query=q, token_budget=BUDGET,
                                      limit=LIMIT, pool_paths=pool_paths)
        v["graph"] = _graph
    for label, params in nucleus_params.items():
        def mk(p: NucleusParams, lim: int) -> Variant:
            return lambda ctx, q: nucleus_search(
                ctx.conn, q, limit=lim, token_budget=BUDGET, graph=ctx.graph,
                obligations=ctx.obligations, params=p, explain=True)
        # `nucleus13` asks the sharpest question available: does accretion add
        # anything ON TOP OF simply returning more results, which is the cheap
        # alternative that `hybrid13` shows is already effective?
        v[label] = mk(params, 13 if label.endswith("13") else LIMIT)
    return v


def run_corpus(
    name: str, repo: Path, queries_path: Path, index_path: Path,
    variants_wanted: set[str], nucleus_params: dict[str, NucleusParams],
    *, need_dense: bool,
) -> tuple[list[Query], dict[str, list[Outcome]]]:
    queries = load_queries(queries_path, repo)
    conn = sqlite3.connect(index_path)
    conn.row_factory = sqlite3.Row
    files = [r[0].replace("\\", "/") for r in conn.execute("SELECT path FROM files")]
    cochange = CoChangeModel.from_repo(repo)
    graph = RelationGraph(files, static=load_static_edges(index_path), cochange=cochange)
    obligations = ObligationIndex(conn)
    lsa = baselines.LSAIndex.build(conn) if need_dense else None
    ctx = Ctx(conn=conn, graph=graph, obligations=obligations, lsa=lsa)

    variants = make_variants(variants_wanted, nucleus_params)
    out: dict[str, list[Outcome]] = {k: [] for k in variants}
    for q in queries:
        cochange.advance_to(q.position)   # reveal only strictly-older commits
        for label, fn in variants.items():
            t0 = time.perf_counter()
            payload = fn(ctx, q.query)
            dt = (time.perf_counter() - t0) * 1000.0
            out[label].append(outcome_from_payload(payload, dt))
    conn.close()
    return queries, out


CORPORA = [
    ("codebase-index", "."),
    ("Civitas", "../Civitas"),
    ("PoliternalSite", "../PoliternalSite"),
    ("PoliternalParkour", "../PoliternalParkour"),
    ("TerraForge", "../TerraForge"),
    ("denfry.github.io", "../denfry.github.io"),
    ("DevGraph", "../DevGraph"),
    ("WinCleaner", "../Windows-Cleaner-and-Optimizer-main"),
]

DATA = Path(__file__).parent.parent / "data"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--systems", default="hybrid,nucleus",
                    help="comma list of bm25,dense,rag,hybrid,graph,nucleus")
    ap.add_argument("--ablate", action="store_true")
    ap.add_argument("--baseline-label", default="hybrid")
    ap.add_argument("--corpus", action="append", default=None)
    ap.add_argument("--json-out", default=None)
    ap.add_argument("--per-corpus", action="store_true")
    args = ap.parse_args()

    wanted = {s.strip() for s in args.systems.split(",") if s.strip()}
    nucleus_params: dict[str, NucleusParams] = {}
    if "nucleus" in wanted:
        nucleus_params["nucleus"] = NucleusParams()
    if "nucleus13" in wanted:
        nucleus_params["nucleus13"] = NucleusParams()
    if args.ablate:
        base = NucleusParams()
        nucleus_params.update({
            "-accretion13":       NucleusParams(accrete=False),
            "-cochange13":        NucleusParams(weights=RelationWeights(cochange=0.0)),
            "-edges13":           NucleusParams(weights=RelationWeights(edge=0.0)),
            "-testlink13":        NucleusParams(weights=RelationWeights(testlink=0.0)),
            "-stem13":            NucleusParams(weights=RelationWeights(stem=0.0)),
            "-dir13":             NucleusParams(weights=RelationWeights(dirw=0.0)),
            "-coverage_sel13":    NucleusParams(coverage_select=False),
            "-hub_penalty13":     NucleusParams(hub_penalty=False),
            "-compact13":         NucleusParams(compact_completions=False),
            "combine=max13":      NucleusParams(combine="max"),
            "gate=0.0__13":       NucleusParams(min_score=0.0),
            "slots=1__13":        NucleusParams(max_completions=1),
        })
    need_dense = bool({"dense", "rag"} & wanted)

    corpora = CORPORA
    if args.corpus:
        keep = set(args.corpus)
        corpora = [c for c in CORPORA if c[0] in keep]

    all_reports: dict[str, list[EvalReport]] = {}
    for name, repo in corpora:
        qs = DATA / f"{name}.yml"
        idx = DATA / "index" / f"{name}.sqlite"
        if not qs.exists() or not idx.exists():
            print(f"[{name}] skipped (missing data)")
            continue
        t0 = time.perf_counter()
        queries, outcomes = run_corpus(
            name, Path(repo), qs, idx, wanted, nucleus_params, need_dense=need_dense)
        for label, oc in outcomes.items():
            all_reports.setdefault(label, []).append(
                aggregate(f"{label}", queries, oc, token_budget=BUDGET))
        print(f"[{name}] {len(queries)} queries, {len(outcomes)} systems, "
              f"{time.perf_counter()-t0:.1f}s")
        if args.per_corpus:
            reps = [aggregate(label, queries, oc, token_budget=BUDGET)
                    for label, oc in outcomes.items()]
            base = next((r for r in reps if r.label == args.baseline_label), None)
            print(format_table(reps, baseline=base))
            print()

    pooled = {label: pool(reps, label=label) for label, reps in all_reports.items()}
    order = [l for l in ("bm25", "dense", "rag", "graph", "hybrid", "hybrid13")
             if l in pooled]
    order += [l for l in pooled if l not in order]
    reports = [pooled[l] for l in order]
    base = pooled.get(args.baseline_label)
    print("\n=== POOLED ===")
    print(format_table(reports, baseline=base))
    if base is not None:
        for label in order:
            if label == args.baseline_label:
                continue
            print()
            print(format_significance(base, pooled[label]))

    if args.json_out:
        Path(args.json_out).write_text(json.dumps(
            {l: pooled[l].as_row() for l in order}, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
