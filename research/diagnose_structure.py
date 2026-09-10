#!/usr/bin/env python3
"""Go/no-go diagnostic for necessity-based retrieval.

The premise of "compute the required set" rather than "rank similar documents" is
that the members of a required set are *related to each other* by something
computable. If a commit's files are mutually unrelated by every cheap relation,
then no completion mechanism can ever recover the members that lexical retrieval
misses, and the whole research direction is dead.

This script measures that premise before anything is built. For every
multi-file ground-truth answer it asks: given one gold file (the "anchor"), is
each *other* gold file reachable by

  * dir        - same directory
  * stem       - shared identifier tokens in the file name
  * testlink   - one is the test/spec of the other (or vice versa)
  * edge       - a resolved import/call/reference edge links the two files in
                 the code graph (direction ignored)
  * cochange   - the two files changed together in history STRICTLY BEFORE the
                 query's own commit (no lookahead, so the number is what a
                 deployed system could actually have known)

Reported as *reachability*: the fraction of non-anchor gold files that at least
one relation connects to the anchor set. That is the ceiling on what any
completion stage can add.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import subprocess
import sys
from collections import Counter, defaultdict
from pathlib import Path

import yaml

_WORD = re.compile(r"[A-Za-z][A-Za-z0-9]*")
_TEST_MARK = re.compile(r"(?:^|[._-])(?:test|tests|spec|specs)(?:$|[._-])", re.I)


def git(repo: Path, *args: str) -> str:
    p = subprocess.run(
        ["git", "-C", str(repo), *args],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if p.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)}: {p.stderr.strip()}")
    return p.stdout


def commit_order(repo: Path) -> dict[str, int]:
    """sha12 -> position, 0 = newest. Larger position == older."""
    shas = [s.strip() for s in git(repo, "log", "--format=%H").splitlines() if s.strip()]
    return {s[:12]: i for i, s in enumerate(shas)}


def commit_filesets(repo: Path) -> list[tuple[str, list[str]]]:
    """[(sha12, [paths])] newest first, merges excluded (matching gen_queries)."""
    raw = git(repo, "log", "--no-merges", "--name-only",
              "--pretty=format:%x01%H", "--diff-filter=ACMR")
    out: list[tuple[str, list[str]]] = []
    for rec in raw.split("\x01"):
        rec = rec.strip("\n")
        if not rec:
            continue
        head, _, body = rec.partition("\n")
        files = [ln.strip() for ln in body.splitlines() if ln.strip()]
        if files:
            out.append((head.strip()[:12], files))
    return out


def stem_tokens(path: str) -> set[str]:
    base = path.rsplit("/", 1)[-1]
    base = base.split(".", 1)[0]
    # camelCase / snake_case / kebab-case -> lowercase tokens
    parts = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", base).replace("_", " ").replace("-", " ")
    return {w.lower() for w in _WORD.findall(parts) if len(w) > 2}


def core_stem(path: str) -> str:
    """File stem with test/spec markers stripped, for test<->impl pairing."""
    base = path.rsplit("/", 1)[-1].split(".", 1)[0]
    base = re.sub(r"^(?:test|spec)[._-]?", "", base, flags=re.I)
    base = re.sub(r"[._-]?(?:test|tests|spec|specs)$", "", base, flags=re.I)
    return base.lower()


def is_testish(path: str) -> bool:
    return bool(_TEST_MARK.search(path)) or "/test" in path.lower()


def static_edges(index_path: Path) -> set[frozenset[str]]:
    """Undirected file-level adjacency from resolved import/call/reference edges.

    Symbol targets are lifted to their defining file: the unit of the ground truth
    is a file, so a call edge into a symbol is evidence about that symbol's file.
    Self-loops are dropped (a file importing itself carries no completion signal).
    """
    if not index_path or not index_path.exists():
        return set()
    conn = sqlite3.connect(index_path)
    try:
        rows = conn.execute(
            """
            SELECT src.path AS a,
                   CASE WHEN e.dst_kind = 'file' THEN df.path ELSE sf.path END AS b
            FROM edges AS e
            JOIN files AS src ON src.id = e.file_id
            LEFT JOIN files   AS df ON e.dst_kind = 'file'   AND df.id = e.dst_id
            LEFT JOIN symbols AS s  ON e.dst_kind = 'symbol' AND s.id  = e.dst_id
            LEFT JOIN files   AS sf ON sf.id = s.file_id
            WHERE e.resolved = 1
            """
        ).fetchall()
    except sqlite3.Error:
        return set()
    finally:
        conn.close()
    out: set[frozenset[str]] = set()
    for a, b in rows:
        if a and b and a != b:
            out.add(frozenset((a, b)))
    return out


def related(a: str, b: str, cochange: set[frozenset[str]],
            edges: set[frozenset[str]]) -> set[str]:
    rels: set[str] = set()
    da, db = a.rsplit("/", 1)[0] if "/" in a else "", b.rsplit("/", 1)[0] if "/" in b else ""
    if da == db:
        rels.add("dir")
    ta, tb = stem_tokens(a), stem_tokens(b)
    if ta & tb:
        rels.add("stem")
    if (is_testish(a) != is_testish(b)) and core_stem(a) == core_stem(b) and core_stem(a):
        rels.add("testlink")
    if frozenset((a, b)) in edges:
        rels.add("edge")
    if frozenset((a, b)) in cochange:
        rels.add("cochange")
    return rels


def analyse(repo: Path, queries_path: Path, name: str,
            index_path: Path | None = None) -> dict:
    edges = static_edges(index_path) if index_path else set()
    records = yaml.safe_load(queries_path.read_text(encoding="utf-8")) or []
    order = commit_order(repo)
    history = commit_filesets(repo)

    # Pre-index history by position so the temporal filter is a slice, not a scan.
    hist_by_pos: list[tuple[int, list[str]]] = []
    for sha, files in history:
        pos = order.get(sha)
        if pos is not None:
            hist_by_pos.append((pos, files))

    sizes = Counter()
    rel_hits: Counter[str] = Counter()
    n_targets = 0
    n_reachable = 0
    n_multi = 0
    cochange_only = 0
    edge_only = 0
    unreachable_examples: list[tuple[str, str, str]] = []
    hist_depth: list[int] = []

    for rec in records:
        gold = list(dict.fromkeys(rec.get("expected_files", [])))
        sizes[len(gold)] += 1
        if len(gold) < 2:
            continue
        n_multi += 1
        qpos = order.get(rec.get("commit", ""), None)
        if qpos is None:
            continue
        # Co-change pairs observable strictly before this commit (pos > qpos).
        prior = [f for pos, f in hist_by_pos if pos > qpos]
        hist_depth.append(len(prior))
        pairs: set[frozenset[str]] = set()
        for files in prior:
            if len(files) > 40:      # sweeping commits couple everything; ignore
                continue
            for i, x in enumerate(files):
                for y in files[i + 1:]:
                    pairs.add(frozenset((x, y)))

        # Every gold file gets a turn as the anchor; the rest are targets.
        for anchor in gold:
            for target in gold:
                if target == anchor:
                    continue
                n_targets += 1
                rels = related(anchor, target, pairs, edges)
                if rels:
                    n_reachable += 1
                    for r in rels:
                        rel_hits[r] += 1
                    if rels == {"cochange"}:
                        cochange_only += 1
                    if rels == {"edge"}:
                        edge_only += 1
                elif len(unreachable_examples) < 5:
                    unreachable_examples.append((rec["query"][:60], anchor, target))

    return {
        "corpus": name,
        "queries": len(records),
        "multi_file_queries": n_multi,
        "size_hist": dict(sorted(sizes.items())),
        "anchor_target_pairs": n_targets,
        "reachable": n_reachable,
        "reachability": (n_reachable / n_targets) if n_targets else 0.0,
        "by_relation": {k: v / n_targets for k, v in rel_hits.items()} if n_targets else {},
        "cochange_only_share": (cochange_only / n_targets) if n_targets else 0.0,
        "edge_only_share": (edge_only / n_targets) if n_targets else 0.0,
        "n_static_edges": len(edges),
        "median_prior_commits": (
            sorted(hist_depth)[len(hist_depth) // 2] if hist_depth else 0
        ),
        "unreachable_examples": unreachable_examples,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--corpus", action="append", required=True,
                    help="name|repo_path|queries.yml[|index.sqlite]")
    args = ap.parse_args()

    rows = []
    for spec in args.corpus:
        parts = spec.split("|")
        name, repo, qs = parts[0], parts[1], parts[2]
        idx = Path(parts[3]) if len(parts) > 3 else None
        try:
            rows.append(analyse(Path(repo), Path(qs), name, idx))
        except Exception as exc:  # a corpus that cannot be read must not hide the rest
            print(f"[{name}] FAILED: {type(exc).__name__}: {exc}", file=sys.stderr)

    print(f"\n{'corpus':22} {'q':>4} {'multi':>6} {'pairs':>6} {'reach':>7} "
          f"{'dir':>6} {'stem':>6} {'test':>6} {'coch':>6} {'coch-only':>9} {'hist':>5}")
    print("-" * 100)
    tot_pairs = tot_reach = 0
    agg_rel: Counter[str] = Counter()
    agg_conly = 0
    agg_eonly = 0
    for r in rows:
        b = r["by_relation"]
        print(f"{r['corpus']:22} {r['queries']:>4} {r['multi_file_queries']:>6} "
              f"{r['anchor_target_pairs']:>6} {r['reachability']:>7.3f} "
              f"{b.get('dir',0):>6.3f} {b.get('stem',0):>6.3f} {b.get('testlink',0):>6.3f} "
              f"{b.get('edge',0):>6.3f} {b.get('cochange',0):>6.3f} "
              f"{r['edge_only_share']:>7.3f} {r['cochange_only_share']:>7.3f} "
              f"{r['median_prior_commits']:>5}")
        tot_pairs += r["anchor_target_pairs"]
        tot_reach += r["reachable"]
        for k, v in b.items():
            agg_rel[k] += v * r["anchor_target_pairs"]
        agg_conly += r["cochange_only_share"] * r["anchor_target_pairs"]
        agg_eonly += r["edge_only_share"] * r["anchor_target_pairs"]
    if tot_pairs:
        print("-" * 112)
        print(f"{'POOLED':22} {'':>4} {'':>6} {tot_pairs:>6} {tot_reach/tot_pairs:>7.3f} "
              f"{agg_rel['dir']/tot_pairs:>6.3f} {agg_rel['stem']/tot_pairs:>6.3f} "
              f"{agg_rel['testlink']/tot_pairs:>6.3f} {agg_rel['edge']/tot_pairs:>6.3f} "
              f"{agg_rel['cochange']/tot_pairs:>6.3f} "
              f"{agg_eonly/tot_pairs:>7.3f} {agg_conly/tot_pairs:>7.3f}")

    print("\ngold-set size distribution (pooled):")
    total_sizes: Counter = Counter()
    for r in rows:
        for k, v in r["size_hist"].items():
            total_sizes[k] += v
    n_all = sum(total_sizes.values())
    for k in sorted(total_sizes):
        print(f"  |gold|={k}: {total_sizes[k]:>4} ({total_sizes[k]/n_all:.1%})")
    multi = sum(v for k, v in total_sizes.items() if k >= 2)
    print(f"  multi-file share: {multi}/{n_all} = {multi/n_all:.1%}")

    print("\nunreachable examples (query | anchor | target):")
    for r in rows[:3]:
        for q, a, t in r["unreachable_examples"][:3]:
            print(f"  [{r['corpus']}] {q!r}\n      {a}\n   -> {t}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
