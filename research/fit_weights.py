#!/usr/bin/env python3
"""Fit the relation weights under leave-one-repository-out.

The first benchmark run used weights of 1.0 for everything, which is not a
configuration so much as an absence of one, and the accretion ranking was
correspondingly poor (median rank 17 for gold that *was* generated). Hand-picking
coefficients on the same corpora that report the result is how a benchmark gets gamed
by accident, so weights are selected exactly the way this repository selects its
ranking parameters: choose on N-1 corpora, score on the held-out one, pool the folds.

Objective: `recovery@C` -- the mean number of gold files, per query, that the top-C
accretion candidates recover *from among the gold the baseline's top-10 already
missed*. That is precisely the quantity a completion slot exists to buy, and it maps
monotonically onto recall@10.

Because `contributions()` is linear in the weights, the whole fit runs over a cached
table of per-relation contributions: the graph is walked once, then tens of thousands
of weight vectors are scored as dot products.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import replace
from pathlib import Path

from codebase_index.retrieval.tuning import RetrievalTuning
from research.nucleus import baselines
from research.nucleus.evalrun import CORPORA, DATA, load_queries
from research.nucleus.relations import (
    CoChangeModel, RelationGraph, RelationWeights, load_static_edges,
)
from research.nucleus.search import NucleusParams, ObligationIndex, contributions

RELATIONS = ["edge", "cochange", "testlink", "stem", "dir"]
CACHE = DATA / "contrib_cache.json"


def build_cache(anchor_head: int = 3) -> dict:
    """corpus -> [ {gold_missed: [...], cands: {path: {rel: value}}} ] per query."""
    cache: dict[str, list] = {}
    for name, repo in CORPORA:
        qs, idx = DATA / f"{name}.yml", DATA / "index" / f"{name}.sqlite"
        if not qs.exists() or not idx.exists():
            continue
        queries = load_queries(qs, Path(repo))
        conn = sqlite3.connect(idx)
        conn.row_factory = sqlite3.Row
        files = [r[0].replace("\\", "/") for r in conn.execute("SELECT path FROM files")]
        cochange = CoChangeModel.from_repo(Path(repo))
        graph = RelationGraph(files, static=load_static_edges(idx), cochange=cochange)
        params = NucleusParams(anchor_head=anchor_head, min_score=0.0)
        rows = []
        for q in queries:
            cochange.advance_to(q.position)
            cands, _ = baselines.product_candidates(
                conn, q.query, limit=10, tuning=RetrievalTuning())
            base_files: list[str] = []
            for c in cands[:10]:
                p = c.path.replace("\\", "/")
                if p not in base_files:
                    base_files.append(p)
            gold = set(q.expected_files)
            missed = sorted(gold - set(base_files))
            head = base_files[:anchor_head]
            anchors = list(dict.fromkeys(head))
            if not anchors or not missed:
                # Queries whose gold the baseline already has contribute nothing to
                # the objective: there is nothing left for a completion to recover.
                # They still matter for *cost*, which the gate (fitted separately)
                # and the end-to-end benchmark account for.
                rows.append({"missed": missed, "cands": {}})
                continue
            contrib = contributions(anchors=anchors, graph=graph, params=params,
                                    exclude=set(head))
            rows.append({"missed": missed,
                         "cands": {p: {k: round(v, 6) for k, v in acc.items()}
                                   for p, acc in contrib.items()}})
        cache[name] = rows
        conn.close()
        print(f"[{name}] cached {len(rows)} queries")
    return cache


def recovery(rows: list, w: dict[str, float], *, c: int) -> float:
    """Mean gold files recovered per query by the top-`c` accretion candidates."""
    total = 0.0
    for row in rows:
        cands = row["cands"]
        if not cands:
            continue
        missed = set(row["missed"])
        if not missed:
            continue
        scored = sorted(
            ((sum(w.get(k, 0.0) * v for k, v in acc.items()), p) for p, acc in cands.items()),
            key=lambda t: (-t[0], t[1]),
        )
        total += sum(1 for _s, p in scored[:c] if p in missed)
    return total / max(1, len(rows))


def coordinate_ascent(train: list, *, c: int, passes: int = 4) -> dict[str, float]:
    grid = [0.0, 0.15, 0.3, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 4.0]
    w = {r: 1.0 for r in RELATIONS}
    best = recovery(train, w, c=c)
    for _ in range(passes):
        improved = False
        for r in RELATIONS:
            cur = w[r]
            for v in grid:
                if v == cur:
                    continue
                trial = dict(w)
                trial[r] = v
                # L1-normalise so the fitted vector's *scale* stays comparable and the
                # gate threshold keeps meaning the same thing across folds.
                s = sum(trial.values()) or 1.0
                trial = {k: val * len(RELATIONS) / s for k, val in trial.items()}
                score = recovery(train, trial, c=c)
                if score > best + 1e-9:
                    best, w, improved = score, trial, True
        if not improved:
            break
    return w


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--rebuild", action="store_true")
    ap.add_argument("--c", type=int, default=1, help="completion slots to fit for")
    args = ap.parse_args()

    if args.rebuild or not CACHE.exists():
        cache = build_cache()
        CACHE.write_text(json.dumps(cache), encoding="utf-8")
    else:
        cache = json.loads(CACHE.read_text(encoding="utf-8"))

    names = list(cache)
    uniform = {r: 1.0 for r in RELATIONS}

    print(f"\n=== leave-one-repository-out, objective = recovery@{args.c} ===")
    print(f"{'held-out':22} {'uniform':>9} {'fitted':>9} {'delta':>9}   weights chosen on the rest")
    print("-" * 108)
    tot_u = tot_f = 0.0
    n = 0
    folds = []
    for held in names:
        train = [r for k in names if k != held for r in cache[k]]
        test = cache[held]
        w = coordinate_ascent(train, c=args.c)
        u, f = recovery(test, uniform, c=args.c), recovery(test, w, c=args.c)
        folds.append((held, u, f, w))
        wq = len(test)
        tot_u += u * wq
        tot_f += f * wq
        n += wq
        print(f"{held:22} {u:>9.4f} {f:>9.4f} {f-u:>+9.4f}   "
              + " ".join(f"{k}={v:.2f}" for k, v in w.items()))
    print("-" * 108)
    print(f"{'POOLED (held-out)':22} {tot_u/n:>9.4f} {tot_f/n:>9.4f} {(tot_f-tot_u)/n:>+9.4f}")
    print(f"folds improved: {sum(1 for _h,u,f,_w in folds if f > u)}/{len(folds)}; "
          f"regressed: {sum(1 for _h,u,f,_w in folds if f < u)}")

    full = coordinate_ascent([r for k in names for r in cache[k]], c=args.c)
    print("\nweights fitted on ALL corpora (what would ship, reported as fitted):")
    print("  " + "  ".join(f"{k}={v:.3f}" for k, v in full.items()))
    print(f"  in-sample recovery@{args.c}: "
          f"{recovery([r for k in names for r in cache[k]], full, c=args.c):.4f} "
          f"(uniform {recovery([r for k in names for r in cache[k]], uniform, c=args.c):.4f})")

    # Stability across folds is the honest read on whether these weights mean
    # anything: a coefficient that swings wildly between folds is noise.
    print("\nper-relation weight across folds (min / median / max):")
    for r in RELATIONS:
        vals = sorted(w[r] for _h, _u, _f, w in folds)
        print(f"  {r:10} {vals[0]:.2f} / {vals[len(vals)//2]:.2f} / {vals[-1]:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
