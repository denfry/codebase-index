#!/usr/bin/env python3
"""Run the retrieval benchmark and ablation sweep.

    python tests/eval/run_eval.py                       # baseline vs shipped default
    python tests/eval/run_eval.py --ablate              # + one-signal-off sweep
    python tests/eval/run_eval.py --repo <path> --queries <file.yml>

The index is built once and shared by every variant, so reported deltas isolate
ranking changes from indexing variance.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from dataclasses import fields
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests"))
sys.path.insert(0, str(REPO_ROOT / "src"))

from eval import harness  # noqa: E402
from codebase_index.retrieval.tuning import RetrievalTuning  # noqa: E402

# Signals swept by --ablate. Numeric parameters are excluded: turning off a bool
# answers "does this signal earn its complexity", which is the decision we make.
ABLATABLE = ("soft_lexical", "query_expansion", "fuzzy_symbols", "graph_source",
             "mmr", "dedup", "source_priors")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=str(REPO_ROOT),
                    help="corpus to index and query (default: this repository)")
    ap.add_argument("--queries", default="self_repo",
                    help="query set name under tests/eval/queries or a path")
    ap.add_argument("--ablate", action="store_true",
                    help="also run a one-signal-off sweep")
    ap.add_argument("--limit", type=int, default=harness.DEFAULT_LIMIT)
    ap.add_argument("--token-budget", type=int, default=harness.DEFAULT_BUDGET)
    ap.add_argument("--repeats", type=int, default=3,
                    help="latency repeats per query (quality is unaffected)")
    ap.add_argument("--json", dest="as_json", action="store_true")
    args = ap.parse_args(argv)

    root = Path(args.repo).resolve()
    queries = harness.load_queries(args.queries)
    problems = harness.validate_queries(queries, root)
    if problems:
        print("Ground-truth validation FAILED:", file=sys.stderr)
        for p in problems:
            print(f"  - {p}", file=sys.stderr)
        return 2

    print(f"corpus: {root}")
    print(f"queries: {len(queries)} from {args.queries}")
    print("building index (once, shared by all variants)...", flush=True)

    with tempfile.TemporaryDirectory() as tmp:
        db = harness.build_corpus_index(root, Path(tmp) / "eval.sqlite")
        try:
            variants: list[tuple[str, RetrievalTuning]] = [
                ("baseline (1.7.0)", RetrievalTuning.baseline()),
                ("default (all signals)", RetrievalTuning()),
            ]
            if args.ablate:
                default = RetrievalTuning()
                known = {f.name for f in fields(default)}
                for flag in ABLATABLE:
                    if flag in known:
                        variants.append((f"  -{flag}", default.without(flag)))

            reports = []
            for label, tuning in variants:
                print(f"running: {label}", flush=True)
                reports.append(
                    harness.evaluate(
                        db.conn, queries, tuning=tuning, label=label,
                        limit=args.limit, token_budget=args.token_budget,
                        repeats=args.repeats,
                    )
                )
        finally:
            db.close()

    if args.as_json:
        print(json.dumps([r.as_row() for r in reports], indent=2))
        return 0

    print()
    print(harness.format_table(reports, baseline=reports[0]))
    print()
    print("Per-category MRR (default config):")
    for cat, val in reports[1].per_category.items():
        print(f"  {cat:14} {val:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
