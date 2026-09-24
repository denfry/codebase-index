#!/usr/bin/env python3
"""Run the retrieval benchmark, ablation sweep, and significance tests.

    python tests/eval/run_eval.py                        # baseline vs shipped default
    python tests/eval/run_eval.py --ablate               # + one-signal-off sweep
    python tests/eval/run_eval.py --corpus <path>:<queries>   # add an external corpus
    python tests/eval/run_eval.py --repo <path> --queries <file.yml>

Each corpus is indexed once and shared by every variant, so reported deltas
isolate ranking changes from indexing variance.

Why more than one corpus
------------------------
The shipped query sets are Python and self-hosted. Tuning a ranker against a
single repository in a single language is how you get numbers that only move on
that repository. Pass `--corpus` to pool additional repositories into one
benchmark; `tests/eval/gen_queries.py` mints an objective query set for any git
repository, so adding one is a two-command operation:

    python tests/eval/gen_queries.py --repo ../some-java-service --out /tmp/svc.yml
    python tests/eval/run_eval.py --corpus ../some-java-service:/tmp/svc.yml --ablate

Why significance
----------------
Query sets of this size have a noise floor of several MRR points. Every non-baseline
row is accompanied by a paired bootstrap CI and permutation p-value against the
shipped default, because a delta column alone cannot tell an improvement from a
reshuffle. Signals are kept on the strength of that test, not the sign of the delta.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from dataclasses import fields, replace
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests"))
sys.path.insert(0, str(REPO_ROOT / "src"))

from eval import harness  # noqa: E402
from codebase_index.retrieval.tuning import RetrievalTuning  # noqa: E402

# Signals swept by --ablate. Numeric parameters are excluded: turning off a bool
# answers "does this signal earn its complexity", which is the decision we make.
ABLATABLE = (
    "soft_lexical",
    "query_expansion",
    "name_cooccurrence",
    "fuzzy_symbols",
    "graph_source",
    "mmr",
    "dedup",
    "source_priors",
    "file_agreement",
    "resource_priors",
    "stem_match",
)

# Rows are looked up by label rather than position, so adding a variant cannot
# silently repoint the significance tests at the wrong column.
PREVIOUS_LABEL = "previous release (1.9.0)"
DEFAULT_LABEL = "default (all signals)"


def _parse_corpus(spec: str) -> tuple[Path, str]:
    """Split `<repo path>:<query set>`, tolerating a Windows drive letter."""
    head, sep, tail = spec.rpartition(":")
    if not sep or (len(head) == 1 and head.isalpha()):
        raise argparse.ArgumentTypeError(
            f"--corpus expects '<repo>:<queries>', got {spec!r}"
        )
    return Path(head).resolve(), tail


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", default=str(REPO_ROOT),
                    help="primary corpus to index and query (default: this repository)")
    ap.add_argument("--queries", default="self_repo",
                    help="query set name under tests/eval/queries or a path")
    ap.add_argument("--corpus", action="append", default=[], metavar="REPO:QUERIES",
                    help="additional corpus to pool into the benchmark (repeatable)")
    ap.add_argument("--ablate", action="store_true",
                    help="also run a one-signal-off sweep")
    ap.add_argument("--limit", type=int, default=harness.DEFAULT_LIMIT)
    ap.add_argument("--token-budget", type=int, default=harness.DEFAULT_BUDGET)
    ap.add_argument("--repeats", type=int, default=3,
                    help="latency repeats per query (quality is unaffected)")
    ap.add_argument("--resamples", type=int, default=5000,
                    help="bootstrap/permutation resamples for significance testing")
    ap.add_argument("--json", dest="as_json", action="store_true")
    args = ap.parse_args(argv)

    corpora: list[tuple[str, Path, str]] = [
        (Path(args.repo).resolve().name, Path(args.repo).resolve(), args.queries)
    ]
    for spec in args.corpus:
        root, queries = _parse_corpus(spec)
        corpora.append((root.name, root, queries))

    loaded: list[tuple[str, Path, list]] = []
    for name, root, query_spec in corpora:
        queries = harness.load_queries(query_spec)
        problems = harness.validate_queries(queries, root)
        if problems:
            print(f"Ground-truth validation FAILED for {name}:", file=sys.stderr)
            for p in problems:
                print(f"  - {p}", file=sys.stderr)
            return 2
        loaded.append((name, root, queries))
        print(f"corpus: {name} ({root}) — {len(queries)} queries from {query_spec}")

    total = sum(len(q) for _, _, q in loaded)
    print(f"pooled: {total} queries across {len(loaded)} corpora")

    variants: list[tuple[str, RetrievalTuning]] = [
        ("baseline (1.7.0)", RetrievalTuning.baseline()),
        # The previous release, pinned. "Is this better than 1.7.0" and "is this
        # better than what we shipped last" are different questions, and only the
        # second one decides whether a change belongs in the next release.
        (PREVIOUS_LABEL, RetrievalTuning.v190()),
        (DEFAULT_LABEL, RetrievalTuning()),
    ]
    if args.ablate:
        default = RetrievalTuning()
        known = {f.name for f in fields(default)}
        for flag in ABLATABLE:
            if flag in known:
                variants.append((f"  -{flag}", default.without(flag)))

    # variant label -> per-corpus reports, pooled after every corpus is measured.
    collected: dict[str, list[harness.EvalReport]] = {label: [] for label, _ in variants}
    per_corpus_default: dict[str, harness.EvalReport] = {}

    with tempfile.TemporaryDirectory() as tmp:
        for name, root, queries in loaded:
            print(f"building index for {name} (once, shared by all variants)...", flush=True)
            db = harness.build_corpus_index(root, Path(tmp) / f"{name}.sqlite")
            try:
                for label, tuning in variants:
                    print(f"  running: {label}", flush=True)
                    report = harness.evaluate(
                        db.conn, queries, tuning=tuning, label=label,
                        limit=args.limit, token_budget=args.token_budget,
                        repeats=args.repeats,
                    )
                    collected[label].append(report)
                    if label == DEFAULT_LABEL:
                        # Relabel so the per-corpus table identifies the repository
                        # rather than repeating the variant name on every row.
                        per_corpus_default[name] = replace(report, label=name)
            finally:
                db.close()

    reports = [harness.pool(collected[label], label=label) for label, _ in variants]
    by_label = {rep.label: rep for rep in reports}
    default = by_label[DEFAULT_LABEL]
    previous = by_label[PREVIOUS_LABEL]
    ablations = [rep for rep in reports if rep.label.startswith("  -")]

    if args.as_json:
        payload = {
            "pooled": [r.as_row() for r in reports],
            "per_corpus_default": {k: v.as_row() for k, v in per_corpus_default.items()},
            "per_category_default": default.per_category,
        }
        print(json.dumps(payload, indent=2))
        return 0

    print()
    print(harness.format_table(reports, baseline=reports[0]))

    # The release decision is default vs the previous release, so that is the
    # comparison printed first and in full.
    print()
    print(harness.format_significance(previous, default, resamples=args.resamples))

    if ablations:
        print()
        print("Ablation significance (each row vs the shipped default):")
        for rep in ablations:
            print()
            print(harness.format_significance(default, rep, resamples=args.resamples))

    if len(loaded) > 1:
        print()
        print("Per-corpus (default config):")
        print(harness.format_table(list(per_corpus_default.values())))

    print()
    print("Per-category MRR (default config):")
    for cat, val in default.per_category.items():
        print(f"  {cat:14} {val:.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
