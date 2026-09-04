#!/usr/bin/env python3
"""Compare the index against grep-style and repo-map-style baselines on public repositories.

    # the pinned public corpora (cloned into --workdir at fixed commits)
    python tests/eval/run_baselines.py --clone --workdir .tmp-baselines

    # any local git repository instead
    python tests/eval/run_baselines.py --repo ../some-service

    # write raw JSON + Markdown next to the other logged runs
    python tests/eval/run_baselines.py --clone --out tests/eval/results/public-baselines

Why this exists
---------------
`run_eval.py` measures the index against *its own earlier versions*; it can say
a ranking change helped, never that an index beats not having one. This script
asks the second question on repositories anyone can clone, at commits recorded
in the output, with ground truth mined from git history (`gen_queries.py`) so
neither the queries nor the answers are chosen by hand or by the retriever.

What is compared (see `baselines.py` for the exact read model)
-------------------------------------------------------------
* index            — `search()` with the shipped default tuning
* index, uncapped  — same ranking with `max_read_lines=0` (the pre-1.9.1 read plan)
* rg + window      — salient-term ripgrep, density-ranked, 80-line windows
* repo-map (2k/8k) — signature map packed under a budget, degree-ranked
* repo-map, query-aware — same map, files matching the question's identifiers first

Every side is charged with the same tokenizer for the text that enters context.
Latency is context only. Significance is reported per metric with a paired
bootstrap CI and a paired permutation p-value against the rg baseline.
"""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path

if sys.platform == "win32":  # the report uses arrows/dashes; never die on a cp1251 console
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "tests"))
sys.path.insert(0, str(REPO_ROOT / "src"))

from codebase_index import __version__  # noqa: E402
from eval import baselines, gen_queries, harness, metrics  # noqa: E402

# Public corpora: three languages, three sizes, pinned so a re-run sees the same
# tree and the same history. Update the SHA deliberately and re-log the run.
PUBLIC_CORPORA = {
    "flask": ("https://github.com/pallets/flask.git", "d318b683471101618febed18996405ad26462110"),
    "gson": ("https://github.com/google/gson.git", "b3f4ca20087f9066de4c340522ff84e0558e1ad1"),
    "fastify": ("https://github.com/fastify/fastify.git", "15ebc8e2fe6932d3e91afa84709523804f8a2537"),
}


def _git(*args: str, cwd: Path | None = None) -> str:
    return subprocess.run(
        ["git", *args], cwd=cwd, capture_output=True, text=True,
        encoding="utf-8", errors="replace", check=True,
    ).stdout.strip()


def _clone_pinned(name: str, url: str, sha: str, workdir: Path) -> Path:
    dest = workdir / name
    if not (dest / ".git").is_dir():
        print(f"cloning {url} -> {dest}", flush=True)
        _git("clone", "--quiet", url, str(dest))
    head = _git("rev-parse", "HEAD", cwd=dest)
    if head != sha:
        _git("fetch", "--quiet", "origin", sha, cwd=dest)
        _git("checkout", "--quiet", sha, cwd=dest)
    return dest


def _sig(base: list[float], cand: list[float], *, resamples: int) -> dict[str, float]:
    deltas = [c - b for b, c in zip(base, cand)]
    delta, lo, hi = metrics.paired_bootstrap_ci(deltas, resamples=resamples)
    p = metrics.paired_permutation_p(deltas, resamples=resamples)
    return {"delta": delta, "ci_lo": lo, "ci_hi": hi, "p": p}


def run_corpus(
    name: str,
    root: Path,
    queries: list[harness.EvalQuery],
    *,
    tmp: Path,
) -> dict:
    corpus = baselines.Corpus(root)
    t0 = time.perf_counter()
    db = harness.build_corpus_index(root, tmp / f"{name}.sqlite")
    build_ms = (time.perf_counter() - t0) * 1000.0
    try:
        conn = db.conn
        n_files = conn.execute("SELECT COUNT(*) FROM files").fetchone()[0]
        n_symbols = conn.execute("SELECT COUNT(*) FROM symbols").fetchone()[0]
        n_edges = conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
        map_entries = baselines.build_repo_map_entries(conn)

        per_side: dict[str, dict[str, list[float]]] = {}
        tokens: dict[str, list[int]] = {}
        packet: dict[str, list[int]] = {}
        latency: dict[str, list[float]] = {}

        def record(side: str, out: baselines.BaselineOutcome, scores: dict[str, float]) -> None:
            for k, v in scores.items():
                per_side.setdefault(side, {}).setdefault(k, []).append(v)
            tokens.setdefault(side, []).append(out.tokens)
            packet.setdefault(side, []).append(out.packet_tokens)
            latency.setdefault(side, []).append(out.latency_ms)

        for q in queries:
            idx = baselines.run_index(conn, corpus, q)
            record("index", idx, baselines.score(idx, q))
            # Same ranking, read plan uncapped (pre-1.9.1 behaviour): isolates what
            # the `max_read_lines` cap saves without touching quality.
            raw = baselines.run_index(conn, corpus, q, max_read_lines=0)
            record("index (uncapped reads)", raw, baselines.score(raw, q))
            rg = baselines.run_rg_window(corpus, q)
            record("rg+window", rg, baselines.score(rg, q))
            for budget in baselines.REPO_MAP_BUDGETS:
                for aware in (False, True):
                    label = f"repo-map {budget // 1000}k" + (" query-aware" if aware else "")
                    rm = baselines.run_repo_map(map_entries, q, budget=budget, query_aware=aware)
                    record(label, rm, baselines.score(rm, q, present_only=True))
    finally:
        db.close()

    summary = {}
    for side, cols in per_side.items():
        summary[side] = {k: statistics.fmean(v) for k, v in cols.items()}
        summary[side]["tokens_mean"] = statistics.fmean(tokens[side])
        summary[side]["tokens_median"] = statistics.median(tokens[side])
        summary[side]["packet_tokens_mean"] = statistics.fmean(packet[side])
        summary[side]["latency_p50_ms"] = metrics.percentile(latency[side], 50)
    return {
        "corpus": name,
        "root": str(root),
        "head": _git("rev-parse", "HEAD", cwd=root),
        "n_queries": len(queries),
        "index_build_ms": build_ms,
        "files_indexed": n_files,
        "symbols_indexed": n_symbols,
        "edges_indexed": n_edges,
        "summary": summary,
        "per_query": per_side,
        "tokens_per_query": tokens,
        "packet_tokens_per_query": packet,
    }


def pooled(corpora: list[dict], *, resamples: int) -> dict:
    sides = list(corpora[0]["per_query"].keys())
    per_side: dict[str, dict[str, list[float]]] = {}
    tokens: dict[str, list[int]] = {}
    packet: dict[str, list[int]] = {}
    for c in corpora:
        for side in sides:
            for k, v in c["per_query"][side].items():
                per_side.setdefault(side, {}).setdefault(k, []).extend(v)
            tokens.setdefault(side, []).extend(c["tokens_per_query"][side])
            packet.setdefault(side, []).extend(c["packet_tokens_per_query"][side])
    summary = {}
    for side, cols in per_side.items():
        summary[side] = {k: statistics.fmean(v) for k, v in cols.items()}
        summary[side]["tokens_mean"] = statistics.fmean(tokens[side])
        summary[side]["tokens_median"] = statistics.median(tokens[side])
        summary[side]["packet_tokens_mean"] = statistics.fmean(packet[side])
    significance = {
        k: _sig(per_side["rg+window"][k], per_side["index"][k], resamples=resamples)
        for k in baselines.METRICS
    }
    significance["tokens"] = _sig(
        [float(t) for t in tokens["rg+window"]], [float(t) for t in tokens["index"]],
        resamples=resamples,
    )
    return {"n_queries": sum(c["n_queries"] for c in corpora), "summary": summary,
            "index_vs_rg": significance}


def render_markdown(report: dict) -> str:
    L: list[str] = []
    L.append("# Index vs grep-style and repo-map-style baselines on public repositories\n")
    L.append(f"- **Date:** {report['date']}")
    L.append(f"- **codebase-index:** {report['version']}")
    L.append(f"- **Tokenizer (both sides):** {report['tokenizer']}")
    L.append(f"- **ripgrep:** {report['ripgrep'] or 'not found — Python scan fallback (latency not comparable)'}")
    L.append(f"- **Platform:** {report['platform']}")
    L.append(f"- **Read model:** top-{baselines.TOP_K} follow-through reads, "
             f"{baselines.WINDOW}-line grep windows, `rg` listing capped at "
             f"{baselines.LISTING_CAP} lines; repo maps packed under "
             f"{' / '.join(str(b) for b in baselines.REPO_MAP_BUDGETS)} tokens")
    L.append("- **Ground truth:** commit subject → files that commit changed "
             "(`tests/eval/gen_queries.py`), newest N localised commits per repository; "
             "changelog-style files excluded from both answers and corpus\n")

    L.append("## Corpora\n")
    L.append("| corpus | commit | files indexed | symbols | edges | queries | index build |")
    L.append("|---|---|---:|---:|---:|---:|---:|")
    for c in report["corpora"]:
        L.append(f"| {c['corpus']} | `{c['head'][:12]}` | {c['files_indexed']} | "
                 f"{c['symbols_indexed']} | {c['edges_indexed']} | {c['n_queries']} | "
                 f"{c['index_build_ms'] / 1000:.1f} s |")
    L.append("")

    def ranked_table(summary: dict, n: int, title: str) -> None:
        L.append(f"### {title} — ranked retrieval (n={n})\n")
        L.append("| method | hit@3 | recall@5 | MRR | packet / listing tokens | "
                 "+ top-3 reads (mean) | + top-3 reads (median) |")
        L.append("|---|---:|---:|---:|---:|---:|---:|")
        for side in ("index", "index (uncapped reads)", "rg+window"):
            s = summary[side]
            L.append(f"| {side} | {s['hit@3']:.3f} | {s['recall@5']:.3f} | {s['MRR']:.3f} | "
                     f"{s['packet_tokens_mean']:,.0f} | {s['tokens_mean']:,.0f} | "
                     f"{s['tokens_median']:,.0f} |")
        L.append("")
        L.append(f"### {title} — repo-map-style context (n={n})\n")
        L.append("| method | answer present in map | tokens/query |")
        L.append("|---|---:|---:|")
        for side, s in summary.items():
            if side.startswith("repo-map"):
                L.append(f"| {side} | {s['present']:.3f} | {s['tokens_mean']:,.0f} |")
        L.append("")

    ranked_table(report["pooled"]["summary"], report["pooled"]["n_queries"], "Pooled")
    L.append("### Index vs rg+window, paired significance (pooled)\n")
    L.append("| metric | delta (index − rg) | 95% CI | p | significant |")
    L.append("|---|---:|---:|---:|---|")
    for k, s in report["pooled"]["index_vs_rg"].items():
        fmt = ",.0f" if k == "tokens" else "+.3f"
        L.append(f"| {k} | {s['delta']:{fmt}} | [{s['ci_lo']:{fmt}}, {s['ci_hi']:{fmt}}] | "
                 f"{s['p']:.3f} | {'yes' if s['p'] < 0.05 else 'no'} |")
    L.append("")
    for c in report["corpora"]:
        ranked_table(c["summary"], c["n_queries"], c["corpus"])

    L.append("## How to read this\n")
    L.append("- `hit@3` is the metric that matters for an agent that opens the top three files. "
             "`recall@5` credits multi-file answers. `MRR` rewards putting the answer first.")
    L.append("- `packet / listing tokens` is what the agent sees before opening anything: "
             "the full JSON search payload for the index (snippets included), the "
             f"first {baselines.LISTING_CAP} `rg` lines for grep. `+ top-3 reads` adds the "
             "follow-through: the index's top-3 `recommended_reads` ranges in full, "
             f"or three {baselines.WINDOW}-line grep windows. Same tokenizer on every side.")
    L.append("- The index packet already carries budgeted snippets, so an agent that answers "
             "from the packet pays the first column only; an agent that re-reads every "
             "recommended range pays the second. Grep has no first-column equivalent — the "
             "listing alone rarely answers anything.")
    L.append("- A repo map is not a ranking, so it is scored on whether the answer file is "
             "*present* at all — an upper bound on what an agent could do with it.")
    L.append("- Ground truth is one commit's files; a query can have a correct answer the "
             "commit did not touch. Absolute numbers understate every method equally; "
             "read the *deltas*, and read the CI before the delta.")
    L.append("- Latency is deliberately not tabulated: the index runs in-process, ripgrep "
             "is a separate binary; neither number is a fair claim against the other.")
    L.append("- Not measured here: an LLM-driven agent exploring the repository. That "
             "needs model calls and is tracked as future work in `docs/BENCHMARKS.md`.")
    return "\n".join(L) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--repo", action="append", default=[],
                    help="local git repository to benchmark (repeatable)")
    ap.add_argument("--clone", action="store_true",
                    help="clone the pinned public corpora into --workdir")
    ap.add_argument("--only", action="append", default=[],
                    help="restrict --clone to these corpus names")
    ap.add_argument("--workdir", type=Path, default=Path(".tmp-baselines"))
    ap.add_argument("--queries-per-repo", type=int, default=150,
                    help="newest N git-derived queries per repository")
    ap.add_argument("--max-files", type=int, default=4)
    ap.add_argument("--resamples", type=int, default=5000)
    ap.add_argument("--out", type=Path, default=None,
                    help="write <out>.json and <out>.md")
    args = ap.parse_args(argv)

    roots: list[tuple[str, Path]] = []
    if args.clone:
        args.workdir.mkdir(parents=True, exist_ok=True)
        for name, (url, sha) in PUBLIC_CORPORA.items():
            if args.only and name not in args.only:
                continue
            roots.append((name, _clone_pinned(name, url, sha, args.workdir)))
    for r in args.repo:
        p = Path(r).resolve()
        roots.append((p.name, p))
    if not roots:
        ap.error("pass --clone and/or --repo")

    corpora: list[dict] = []
    with tempfile.TemporaryDirectory() as tmp:
        for name, root in roots:
            records = gen_queries.harvest(
                root, max_commits=4000, max_files=args.max_files, min_words=3,
            )[: args.queries_per_repo]
            queries = [
                harness.EvalQuery(
                    query=r["query"], category=r["category"],
                    expected_files=tuple(r["expected_files"]),
                )
                for r in records
            ]
            problems = harness.validate_queries(queries, root)
            if problems:
                print(f"ground truth invalid for {name}: {problems[:3]}", file=sys.stderr)
                return 2
            print(f"{name}: {len(queries)} queries; indexing + running...", flush=True)
            corpora.append(run_corpus(name, root, queries, tmp=Path(tmp)))
            s = corpora[-1]["summary"]
            print(f"  index     hit@3={s['index']['hit@3']:.3f} tokens={s['index']['tokens_mean']:.0f}")
            print(f"  rg+window hit@3={s['rg+window']['hit@3']:.3f} tokens={s['rg+window']['tokens_mean']:.0f}")

    report = {
        "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "version": __version__,
        "tokenizer": baselines.TOKENIZER,
        "ripgrep": baselines.rg_version(),
        "platform": f"{platform.system()} {platform.release()} / Python {platform.python_version()}",
        "corpora": corpora,
        "pooled": pooled(corpora, resamples=args.resamples),
    }
    md = render_markdown(report)
    print()
    print(md)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        slim = json.loads(json.dumps(report))
        # Per-query vectors are what a re-run compares against; keep them in the raw file.
        args.out.with_suffix(".json").write_text(json.dumps(slim, indent=2), encoding="utf-8")
        args.out.with_suffix(".md").write_text(md, encoding="utf-8")
        print(f"wrote {args.out.with_suffix('.json')} and {args.out.with_suffix('.md')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
