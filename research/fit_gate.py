#!/usr/bin/env python3
"""Select the accretion gate under leave-one-repository-out.

The calibration curve is broad and monotone, so a threshold can be chosen from a
*plateau* rather than a peak -- the same discipline `retrieval/tuning.py` applies to
the product's own coefficients. Objective is net expected gold per query:

    net(tau) = ( hits@1(score >= tau) - COST * n_fire(tau) ) / n_queries

with COST = 0.0347, the measured gold density of the rank-10 slot a completion evicts.
"""
from __future__ import annotations
import json
from pathlib import Path

CACHE = Path("research/data/contrib_cache.json")
RELATIONS = ["edge", "cochange", "testlink", "stem", "dir"]
COST = 0.0347

def rows_for(qs, w):
    out = []
    for row in qs:
        cands, missed = row["cands"], set(row["missed"])
        if not cands:
            continue
        best = max(((sum(w[k]*v for k, v in acc.items()), p) for p, acc in cands.items()),
                   key=lambda t: (t[0], t[1]))
        out.append((best[0], 1 if best[1] in missed else 0))
    return out

def net(rows, n_queries, tau):
    fire = [r for r in rows if r[0] >= tau]
    return (sum(r[1] for r in fire) - COST * len(fire)) / max(1, n_queries)

def main() -> int:
    cache = json.loads(CACHE.read_text(encoding="utf-8"))
    w = {r: 1.0 for r in RELATIONS}
    names = list(cache)
    grid = [0.0, 0.2, 0.4, 0.6, 0.7, 0.826, 0.9, 1.0, 1.1, 1.3, 1.5, 2.0]

    print(f"{'held-out':22} {'tau*':>6} {'net(tau*)':>10} {'net(0)':>10} {'delta':>9}")
    print("-" * 62)
    tot_g = tot_0 = 0.0; N = 0
    taus = []
    for held in names:
        tr = [r for k in names if k != held for r in cache[k]]
        te = cache[held]
        tr_rows, te_rows = rows_for(tr, w), rows_for(te, w)
        tau = max(grid, key=lambda t: net(tr_rows, len(tr), t))
        g, z = net(te_rows, len(te), tau), net(te_rows, len(te), 0.0)
        taus.append(tau)
        tot_g += g*len(te); tot_0 += z*len(te); N += len(te)
        print(f"{held:22} {tau:>6.3f} {g:>10.5f} {z:>10.5f} {g-z:>+9.5f}")
    print("-" * 62)
    print(f"{'POOLED (held-out)':22} {'':>6} {tot_g/N:>10.5f} {tot_0/N:>10.5f} {(tot_g-tot_0)/N:>+9.5f}")
    print(f"chosen tau across folds: min={min(taus):.3f} median={sorted(taus)[len(taus)//2]:.3f} max={max(taus):.3f}")

    all_rows = rows_for([r for k in names for r in cache[k]], w)
    nq = sum(len(cache[k]) for k in names)
    print(f"\nplateau on all corpora (net gold/query vs tau):")
    for t in grid:
        fire = [r for r in all_rows if r[0] >= t]
        print(f"  tau={t:>5.3f}  fires={len(fire):>4}  hits={sum(r[1] for r in fire):>3}  "
              f"net={net(all_rows, nq, t):+.5f}")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
