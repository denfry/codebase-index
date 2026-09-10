#!/usr/bin/env python3
"""Slot economics: what does a completion slot cost, and is any slot cheap enough?

Accretion buys recall by spending a rank slot. Whether that trade is ever positive is
an arithmetic question that can be answered without running the retriever end to end:

    gain(slot) = P(top accretion candidate is gold the baseline top-10 missed)
    cost(slot) = P(the baseline result evicted from that slot was gold)

If gain < cost at every slot, no amount of tuning saves the design and it should be
reported as refuted. If some slots are free -- because the baseline did not fill them
-- then accretion has a positive-expected-value niche and the design survives in a
narrower form than proposed.
"""

from __future__ import annotations

import argparse
import sqlite3
from collections import Counter
from pathlib import Path

from codebase_index.retrieval.tuning import RetrievalTuning
from research.nucleus import baselines
from research.nucleus.evalrun import CORPORA, DATA, load_queries
from research.nucleus.relations import CoChangeModel, RelationGraph, load_static_edges
from research.nucleus.search import NucleusParams, ObligationIndex, accrete


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--anchor-head", type=int, default=3)
    args = ap.parse_args()

    rank_gold = Counter()      # baseline rank -> # gold
    rank_seen = Counter()      # baseline rank -> # queries that filled it
    nfiles_hist = Counter()
    recovery_at = Counter()
    n_queries = 0
    free_slot_queries = 0
    free_slot_recovery = 0

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
        obl = ObligationIndex(conn)
        params = NucleusParams(anchor_head=args.anchor_head, min_score=0.0)

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
            if not gold:
                continue
            n_queries += 1
            nfiles_hist[len(base_files)] += 1
            for i, p in enumerate(base_files, start=1):
                rank_seen[i] += 1
                if p in gold:
                    rank_gold[i] += 1

            missed = gold - set(base_files)
            head = base_files[: args.anchor_head]
            anchors = list(dict.fromkeys(head))
            if not anchors:
                continue
            ranked = accrete(conn, anchors=anchors, graph=graph, obligations=obl,
                             params=params, exclude=set(head), query_terms=set())
            paths = [p for p, _s, _pa in ranked]
            for c in (1, 2, 3):
                recovery_at[c] += sum(1 for p in paths[:c] if p in missed)
            if len(base_files) < 10:
                free_slot_queries += 1
                free_slot_recovery += sum(1 for p in paths[:1] if p in missed)
        conn.close()

    print(f"\n=== baseline gold density by rank (n={n_queries} queries) ===")
    print(f"{'rank':>5} {'filled':>7} {'gold':>6} {'P(gold)':>9}")
    for i in range(1, 11):
        s, g = rank_seen[i], rank_gold[i]
        print(f"{i:>5} {s:>7} {g:>6} {g/max(1,s):>9.4f}")

    print(f"\n=== how many distinct files the baseline actually returns ===")
    for k in sorted(nfiles_hist):
        print(f"  {k:>2} files: {nfiles_hist[k]:>4} queries "
              f"({nfiles_hist[k]/max(1,n_queries):>6.1%})")
    under = sum(v for k, v in nfiles_hist.items() if k < 10)
    print(f"  fewer than 10: {under}/{n_queries} = {under/max(1,n_queries):.1%}")

    print("\n=== the trade ===")
    for c in (1, 2, 3):
        print(f"  recovery@{c} (gold the baseline missed, per query): "
              f"{recovery_at[c]/max(1,n_queries):.4f}")
    last = rank_seen[10]
    print(f"  cost of evicting rank 10:  P(gold) = {rank_gold[10]/max(1,last):.4f}")
    print(f"  cost of evicting rank 4:   P(gold) = {rank_gold[4]/max(1,rank_seen[4]):.4f}")
    print(f"\n  queries with a FREE slot (<10 files returned): {free_slot_queries}"
          f" ({free_slot_queries/max(1,n_queries):.1%})")
    print(f"  gold recovered into free slots by top-1 accretion: {free_slot_recovery}"
          f"  ({free_slot_recovery/max(1,free_slot_queries):.4f} per such query)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
