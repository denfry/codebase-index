#!/usr/bin/env python3
"""H3/H4: soundness and survival of evidence-keyed agent memory.

Two questions, both answered against real history with no model in the loop:

  1. How often would a query-keyed ("semantic") cache serve a stale answer? That is
     exactly `1 - survival`, because such a cache reuses on question identity and
     therefore reuses every entry whose evidence has since moved.

  2. Does evidence granularity change survival multiplicatively (H4)? File-keyed and
     span-keyed memories are both perfectly sound; they differ only in how much valid
     reuse they retain, and the gap is the cost of the lazy implementation choice.

Conclusions are not synthetic: each benchmark query is run through the shipped
retriever, and the spans it actually returns are recorded as that conclusion's
evidence. This is what an agent would really have read.
"""

from __future__ import annotations

import argparse
import sqlite3
import statistics
from pathlib import Path

from codebase_index.retrieval.tuning import RetrievalTuning
from research.nucleus import baselines
from research.nucleus.evalrun import BUDGET, CORPORA, DATA, load_queries
from research.nucleus.memory import Conclusion, Span, changed_regions, survives

HORIZONS = (1, 2, 5, 10, 20, 50)


def collect(name: str, repo: Path, top_k: int) -> list[Conclusion]:
    qs, idx = DATA / f"{name}.yml", DATA / "index" / f"{name}.sqlite"
    if not qs.exists() or not idx.exists():
        return []
    queries = load_queries(qs, repo)
    conn = sqlite3.connect(idx)
    conn.row_factory = sqlite3.Row
    out: list[Conclusion] = []
    for q in queries:
        cands, _ = baselines.product_candidates(
            conn, q.query, limit=top_k, tuning=RetrievalTuning())
        payload = baselines.finalize(cands, query=q.query, token_budget=BUDGET,
                                     limit=top_k)
        spans, tokens = [], 0
        for r in payload["results"]:
            if not r.get("snippet"):
                continue          # not placed in context, so not evidence
            spans.append(Span(r["path"].replace("\\", "/"), int(r["line_start"]),
                              int(r["line_end"]), int(r.get("token_est") or 0)))
            tokens += int(r.get("token_est") or 0)
        if spans:
            out.append(Conclusion(task=q.query, spans=tuple(spans), tokens=tokens))
    conn.close()
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top-k", type=int, default=5,
                    help="results an agent is assumed to actually read")
    ap.add_argument("--corpus", action="append", default=None)
    args = ap.parse_args()

    corpora = CORPORA if not args.corpus else [c for c in CORPORA if c[0] in set(args.corpus)]

    rows: dict[str, dict[int, tuple[float, float, int]]] = {}
    pooled: dict[int, list[tuple[bool, bool]]] = {h: [] for h in HORIZONS}
    span_counts: list[int] = []
    file_counts: list[int] = []

    for name, repo in corpora:
        repo_p = Path(repo)
        cons = collect(name, repo_p, args.top_k)
        if not cons:
            continue
        span_counts += [len(c.spans) for c in cons]
        file_counts += [len(c.files) for c in cons]
        rows[name] = {}
        for h in HORIZONS:
            changed, hunks = changed_regions(repo_p, h)
            if not changed and h > 1:
                # Shallow history: no commit at that depth. Skip rather than report
                # a spurious 100% survival.
                continue
            sf = [survives(c, changed, hunks, granularity="file") for c in cons]
            ss = [survives(c, changed, hunks, granularity="span") for c in cons]
            rows[name][h] = (statistics.fmean(sf), statistics.fmean(ss), len(cons))
            pooled[h] += list(zip(sf, ss))

    print(f"\n=== evidence survival (top-{args.top_k} results treated as evidence) ===")
    print("survival = fraction of conclusions whose evidence was NOT disturbed")
    print("unsound  = what a query-keyed semantic cache would serve stale = 1 - survival\n")
    print(f"{'corpus':22} {'h':>4} {'n':>5} {'file-keyed':>11} {'span-keyed':>11} "
          f"{'span/file':>10} {'semantic unsound':>17}")
    print("-" * 90)
    for name, hs in rows.items():
        for h, (sf, ss, n) in sorted(hs.items()):
            ratio = (ss / sf) if sf > 0 else float("nan")
            print(f"{name:22} {h:>4} {n:>5} {sf:>11.3f} {ss:>11.3f} {ratio:>10.2f} "
                  f"{1-ss:>17.3f}")
    print("-" * 90)
    print(f"{'POOLED':22} {'h':>4} {'n':>5} {'file-keyed':>11} {'span-keyed':>11} "
          f"{'span/file':>10} {'semantic unsound':>17}")
    for h in HORIZONS:
        pairs = pooled[h]
        if not pairs:
            continue
        sf = statistics.fmean([1.0 if a else 0.0 for a, _ in pairs])
        ss = statistics.fmean([1.0 if b else 0.0 for _, b in pairs])
        ratio = (ss / sf) if sf > 0 else float("nan")
        print(f"{'':22} {h:>4} {len(pairs):>5} {sf:>11.3f} {ss:>11.3f} {ratio:>10.2f} "
              f"{1-ss:>17.3f}")

    if span_counts:
        print(f"\nevidence footprint: {statistics.fmean(span_counts):.1f} spans across "
              f"{statistics.fmean(file_counts):.1f} files per conclusion")

    # --- multi-agent sharing --------------------------------------------------
    # Content addressing gives dedup for free: two agents that read the same span
    # name it with the same key. This measures how much of a realistic workload is
    # actually shared, i.e. the ceiling on what a shared memory can save.
    print("\n=== evidence sharing across the task workload ===")
    print(f"{'corpus':22} {'tasks':>6} {'atoms':>7} {'distinct':>9} {'shared%':>8} "
          f"{'tok gross':>10} {'tok dedup':>10} {'saving':>7}")
    print("-" * 88)
    tot = [0, 0, 0, 0, 0]
    for name, repo in corpora:
        cons = collect(name, Path(repo), args.top_k)
        if not cons:
            continue
        seen: dict[tuple[str, int, int], int] = {}
        tok: dict[tuple[str, int, int], int] = {}
        gross = 0
        for c in cons:
            for sp in c.spans:
                k = (sp.path, sp.start, sp.end)
                seen[k] = seen.get(k, 0) + 1
                tok[k] = sp.tokens
                gross += sp.tokens
        atoms = sum(seen.values())
        distinct = len(seen)
        shared = sum(1 for v in seen.values() if v > 1)
        dedup = sum(tok.values())
        print(f"{name:22} {len(cons):>6} {atoms:>7} {distinct:>9} "
              f"{shared/max(1,distinct):>7.1%} {gross:>10} {dedup:>10} "
              f"{1-dedup/max(1,gross):>6.1%}")
        tot[0] += len(cons); tot[1] += atoms; tot[2] += distinct
        tot[3] += gross; tot[4] += dedup
    print("-" * 88)
    print(f"{'POOLED':22} {tot[0]:>6} {tot[1]:>7} {tot[2]:>9} {'':>8} "
          f"{tot[3]:>10} {tot[4]:>10} {1-tot[4]/max(1,tot[3]):>6.1%}")
    print("\n  'saving' = tokens a content-addressed shared memory never re-sends,")
    print("  because a second agent asking a different question reads an atom the")
    print("  first agent already materialised. Dedup, not compression.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
