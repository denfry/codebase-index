#!/usr/bin/env python3
"""Is the accretion score calibrated? The last chance for a positive-EV design.

Accretion loses on average (gain 0.031 < cost 0.035 per slot). Averages hide
selectivity: if a *high* accretion score reliably predicts gold, a gated accretion
that fires rarely could still beat the slot it spends, even though firing always does
not. This measures precision as a function of the score, using the cached
contributions (no retrieval re-run needed).

Decision rule: accretion is worth keeping iff some score threshold yields
precision > 0.035 (the rank-10 gold density) on a non-trivial share of queries.
"""
from __future__ import annotations
import json, sys
from pathlib import Path

CACHE = Path("research/data/contrib_cache.json")
RELATIONS = ["edge", "cochange", "testlink", "stem", "dir"]
COST = 0.0347   # measured P(gold) at baseline rank 10 -- the cheapest slot

def main() -> int:
    cache = json.loads(CACHE.read_text(encoding="utf-8"))
    w = {r: 1.0 for r in RELATIONS}
    rows = []           # (top1_score, is_gold, n_candidates)
    for corpus, qs in cache.items():
        for row in qs:
            cands, missed = row["cands"], set(row["missed"])
            if not cands:
                continue
            scored = sorted(
                ((sum(w[k]*v for k, v in acc.items()), p) for p, acc in cands.items()),
                key=lambda t: (-t[0], t[1]))
            s, p = scored[0]
            rows.append((s, 1 if p in missed else 0, len(cands)))
    rows.sort(key=lambda t: -t[0])
    n = len(rows)
    print(f"queries with >=1 accretion candidate: {n}")
    print(f"median candidate-list size: {sorted(r[2] for r in rows)[n//2]}")
    print(f"\n{'threshold':>10} {'fires':>7} {'fire%':>7} {'hits':>5} {'precision':>10} {'vs cost':>9}")
    print("-" * 56)
    for frac in (0.02, 0.05, 0.10, 0.20, 0.30, 0.50, 0.75, 1.00):
        k = max(1, int(n * frac))
        top = rows[:k]
        hits = sum(t[1] for t in top)
        prec = hits / k
        print(f"{top[-1][0]:>10.3f} {k:>7} {frac:>6.0%} {hits:>5} {prec:>10.4f} "
              f"{prec - COST:>+9.4f}")
    # Expected net gold per query at each threshold, versus spending nothing.
    print(f"\nnet expected gold per query (gain - cost), all {n} queries as denominator:")
    for frac in (0.02, 0.05, 0.10, 0.20, 0.50, 1.00):
        k = max(1, int(n * frac))
        top = rows[:k]
        hits = sum(t[1] for t in top)
        net = (hits - COST * k) / n
        print(f"  fire on top {frac:>4.0%}: net = {net:+.5f} gold/query")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
