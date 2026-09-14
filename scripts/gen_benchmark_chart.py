#!/usr/bin/env python3
"""Render the logged public-baseline benchmark as an SVG bar chart.

    python scripts/gen_benchmark_chart.py \
        tests/eval/results/2026-09-04-public-baselines.json --out assets/benchmark.svg

Reads the raw JSON that `tests/eval/run_baselines.py --out` wrote, so the chart
can never drift from the logged run. Stdlib only.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from xml.sax.saxutils import escape

FONT = "-apple-system, BlinkMacSystemFont, 'Segoe UI', Helvetica, Arial, sans-serif"
INK = "#1f2328"
MUTED = "#656d76"
GRID = "#d0d7de"
INDEX = "#0969da"     # index
RG = "#8c959f"        # grep baseline
CARD = "#ffffff"
BORDER = "#d0d7de"


def bar_panel(x: int, y: int, w: int, h: int, title: str, rows: list[tuple[str, float, float]],
              *, vmax: float, fmt: str, unit: str = "") -> str:
    """Horizontal grouped bars: for each row label, an index bar and an rg bar."""
    out = [f'<text x="{x}" y="{y}" font-size="14" font-weight="600" fill="{INK}">{escape(title)}</text>']
    label_w = 70
    plot_x = x + label_w
    plot_w = w - label_w - 70
    row_h = 40
    top = y + 14
    # grid lines
    for i in range(0, 5):
        gx = plot_x + plot_w * i / 4
        out.append(f'<line x1="{gx:.1f}" y1="{top}" x2="{gx:.1f}" y2="{top + row_h * len(rows)}" stroke="{GRID}" stroke-width="1"/>')
        out.append(f'<text x="{gx:.1f}" y="{top + row_h * len(rows) + 14}" font-size="10" fill="{MUTED}" text-anchor="middle">{(vmax * i / 4):{fmt}}{unit}</text>')
    for i, (label, a, b) in enumerate(rows):
        ry = top + i * row_h
        out.append(f'<text x="{x}" y="{ry + 24}" font-size="12" fill="{INK}">{escape(label)}</text>')
        for j, (val, colour) in enumerate(((a, INDEX), (b, RG))):
            bw = plot_w * min(val, vmax) / vmax
            by = ry + 6 + j * 15
            out.append(f'<rect x="{plot_x}" y="{by}" width="{bw:.1f}" height="12" rx="2" fill="{colour}"/>')
            out.append(f'<text x="{plot_x + bw + 6:.1f}" y="{by + 10}" font-size="11" fill="{INK}">{val:{fmt}}{unit}</text>')
    return "\n".join(out)


def render(report: dict) -> str:
    pooled = report["pooled"]["summary"]
    n = report["pooled"]["n_queries"]
    corpora = report["corpora"]
    sig = report["pooled"]["index_vs_rg"]

    W, H = 960, 470
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}" height="{H}" viewBox="0 0 {W} {H}" font-family="{FONT}">',
        '<title>codebase-index vs rg+window on public repositories</title>',
        f'<rect width="{W}" height="{H}" rx="10" fill="{CARD}" stroke="{BORDER}"/>',
        f'<text x="24" y="34" font-size="18" font-weight="600" fill="{INK}">Index vs disciplined grep on public repositories</text>',
        f'<text x="24" y="54" font-size="12" fill="{MUTED}">'
        f'{escape(", ".join(c["corpus"] for c in corpora))} at pinned commits · {n} git-derived queries · '
        f'codebase-index {escape(report["version"])} · {escape(report["date"])} · same tokenizer on both sides</text>',
        # legend
        f'<rect x="700" y="26" width="12" height="12" rx="2" fill="{INDEX}"/><text x="718" y="37" font-size="12" fill="{INK}">codebase-index</text>',
        f'<rect x="820" y="26" width="12" height="12" rx="2" fill="{RG}"/><text x="838" y="37" font-size="12" fill="{INK}">rg + 80-line windows</text>',
    ]

    # Panel 1: hit@3 per corpus + pooled
    rows = [(c["corpus"], c["summary"]["index"]["hit@3"], c["summary"]["rg+window"]["hit@3"]) for c in corpora]
    rows.append(("pooled", pooled["index"]["hit@3"], pooled["rg+window"]["hit@3"]))
    parts.append(bar_panel(24, 90, 440, 200, "hit@3 — answer file among the top 3", rows, vmax=1.0, fmt=".2f"))

    # Panel 2: MRR per corpus + pooled
    rows = [(c["corpus"], c["summary"]["index"]["MRR"], c["summary"]["rg+window"]["MRR"]) for c in corpora]
    rows.append(("pooled", pooled["index"]["MRR"], pooled["rg+window"]["MRR"]))
    parts.append(bar_panel(500, 90, 440, 200, "MRR — how high the first correct file ranks", rows, vmax=1.0, fmt=".2f"))

    # Panel 3: tokens (packet/listing + top-3 reads), pooled
    rows = [
        ("packet", pooled["index"]["packet_tokens_mean"], pooled["rg+window"]["packet_tokens_mean"]),
        ("+ reads", pooled["index"]["tokens_mean"], pooled["rg+window"]["tokens_mean"]),
    ]
    vmax = max(r[1] for r in rows + [("", 0, 0)]) * 1.15
    vmax = max(vmax, max(r[2] for r in rows) * 1.15)
    parts.append(bar_panel(24, 320, 440, 110, "context tokens per query (pooled mean)", rows, vmax=round(vmax, -2), fmt=",.0f"))

    # Significance box
    y = 320
    parts.append(f'<text x="500" y="{y}" font-size="14" font-weight="600" fill="{INK}">Paired significance, index − rg (pooled)</text>')
    for i, (k, s) in enumerate(sig.items()):
        fmt = ",.0f" if k == "tokens" else "+.3f"
        p_text = "< 0.001" if s["p"] < 0.001 else f"= {s['p']:.3f}"
        line = f'{k}: {s["delta"]:{fmt}}   95% CI [{s["ci_lo"]:{fmt}}, {s["ci_hi"]:{fmt}}]   p {p_text}'
        parts.append(f'<text x="500" y="{y + 22 + i * 18}" font-size="12" fill="{INK}" font-family="ui-monospace, Consolas, monospace">{escape(line)}</text>')
    parts.append(f'<text x="500" y="{y + 22 + len(sig) * 18 + 10}" font-size="11" fill="{MUTED}">Ground truth: commit subject → files that commit changed. Raw run: tests/eval/results/.</text>')
    parts.append(f'<text x="500" y="{y + 22 + len(sig) * 18 + 26}" font-size="11" fill="{MUTED}">Latency is not charted: in-process index vs a separate ripgrep binary is not a fair pair.</text>')
    parts.append("</svg>")
    return "\n".join(parts) + "\n"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("results", type=Path)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args(argv)
    report = json.loads(args.results.read_text(encoding="utf-8"))
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(render(report), encoding="utf-8")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
