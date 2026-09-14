#!/usr/bin/env python3
"""Why does accretion lose? Split the failure into generation vs ranking vs displacement.

The pooled benchmark says NUCLEUS(default) is worse than the incumbent. Three very
different causes produce that same number, and they have opposite fixes:

  generation   the gold file the baseline missed is never even proposed as a
               completion candidate -> the relation union is too narrow
  ranking      it is proposed but scored below the completions actually inserted
               -> the relation weights are wrong
  displacement the completions inserted are fine, but they evict baseline results
               that were themselves gold -> the slot policy is too aggressive

This measures all three on the same sweep, with the same no-lookahead history.
"""

from __future__ import annotations

import argparse
import sqlite3
import statistics
from collections import Counter
from pathlib import Path

from codebase_index.retrieval.tuning import RetrievalTuning
from research.nucleus import baselines
from research.nucleus.evalrun import CORPORA, DATA, load_queries
from research.nucleus.relations import CoChangeModel, RelationGraph, load_static_edges
from research.nucleus.search import NucleusParams, ObligationIndex, accrete


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", action="append", default=None)
    ap.add_argument("--anchor-head", type=int, default=3)
    ap.add_argument("--min-score", type=float, default=0.0,
                    help="0 disables the gate so generation can be measured")
    args = ap.parse_args()

    corpora = CORPORA if not args.corpus else [c for c in CORPORA if c[0] in set(args.corpus)]

    tot = Counter()
    acc_ranks: list[int] = []
    prec_at = Counter()
    n_slots_eval = 0

    for name, repo in corpora:
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
        params = NucleusParams(anchor_head=args.anchor_head, min_score=args.min_score)

        for q in queries:
            cochange.advance_to(q.position)
            cands, _pool = baselines.product_candidates(
                conn, q.query, limit=10, tuning=RetrievalTuning())
            base_files: list[str] = []
            for c in cands[:10]:
                p = c.path.replace("\\", "/")
                if p not in base_files:
                    base_files.append(p)
            gold = set(q.expected_files)
            if not gold:
                continue
            tot["queries"] += 1

            missed = gold - set(base_files)
            tot["gold_total"] += len(gold)
            tot["gold_missed_by_baseline"] += len(missed)

            head = base_files[: args.anchor_head]
            anchors = list(dict.fromkeys(head))
            if not anchors:
                continue
            ranked = accrete(conn, anchors=anchors, graph=graph, obligations=obl,
                             params=params, exclude=set(head), query_terms=set())
            ranked_paths = [p for p, _s, _pa in ranked]
            rank_of = {p: i for i, p in enumerate(ranked_paths)}

            for gfile in missed:
                if gfile in rank_of:
                    tot["missed_generated"] += 1
                    acc_ranks.append(rank_of[gfile])
                else:
                    tot["missed_not_generated"] += 1

            # Precision of the slots accretion would actually claim.
            for k in (1, 3, 5):
                top = ranked_paths[:k]
                if top:
                    prec_at[f"hits@{k}"] += sum(1 for p in top if p in gold)
                    prec_at[f"slots@{k}"] += len(top)
            if ranked_paths:
                n_slots_eval += 1

            # Displacement: baseline results at ranks anchor_head..10 that are gold
            # and would be pushed past rank 10 by 3 insertions.
            tail = base_files[args.anchor_head:]
            evicted = tail[max(0, len(tail) - 3):]
            tot["evicted_gold"] += sum(1 for p in evicted if p in gold)
            tot["evicted_total"] += len(evicted)
        conn.close()

    print("\n=== accretion failure decomposition ===")
    print(f"queries                        {tot['queries']}")
    print(f"gold files (total)             {tot['gold_total']}")
    print(f"gold missed by baseline top-10 {tot['gold_missed_by_baseline']}"
          f"  ({tot['gold_missed_by_baseline']/max(1,tot['gold_total']):.1%} of gold)")
    gen = tot["missed_generated"]
    nogen = tot["missed_not_generated"]
    print(f"  ... proposed by accretion    {gen}"
          f"  ({gen/max(1,gen+nogen):.1%})   <- generation recall")
    print(f"  ... never proposed           {nogen}  ({nogen/max(1,gen+nogen):.1%})")
    if acc_ranks:
        acc_ranks.sort()
        print(f"  rank of proposed gold within accretion list: "
              f"median={statistics.median(acc_ranks):.0f} "
              f"p25={acc_ranks[len(acc_ranks)//4]} p75={acc_ranks[3*len(acc_ranks)//4]}")
        for k in (1, 3, 5, 10, 20):
            print(f"    within top-{k:<2}: {sum(1 for r in acc_ranks if r < k)}"
                  f"/{len(acc_ranks)} ({sum(1 for r in acc_ranks if r < k)/len(acc_ranks):.1%})")
    print("\nprecision of the slots accretion claims (vs full gold set):")
    for k in (1, 3, 5):
        h, s = prec_at[f"hits@{k}"], prec_at[f"slots@{k}"]
        print(f"  P@{k} = {h}/{s} = {h/max(1,s):.3f}")
    print(f"\ndisplacement: of the last 3 baseline slots, "
          f"{tot['evicted_gold']}/{tot['evicted_total']} = "
          f"{tot['evicted_gold']/max(1,tot['evicted_total']):.3f} are gold")
    print("  ^ accretion must beat THIS precision to be worth a slot")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
