"""HTML graph export for the indexed call/import/reference graph."""

from __future__ import annotations

import json
import math
import sqlite3
from pathlib import Path
from typing import Any

from .expand import impact_lookup


def _edge_rows(
    conn: sqlite3.Connection,
    *,
    target: str | None,
    depth: int,
    direction: str,
    limit: int,
) -> list[sqlite3.Row]:
    params: list[Any] = []
    where = "WHERE e.resolved = 1"
    if target:
        impact = impact_lookup(conn, target, depth=depth, direction=direction)
        paths = set(impact.files)
        if "/" in target or "\\" in target:
            paths.add(target.replace("\\", "/"))
        if paths:
            placeholders = ",".join("?" for _ in paths)
            where += (
                f" AND (src_file.path IN ({placeholders}) "
                f"OR src_sym_file.path IN ({placeholders}) "
                f"OR dst_file.path IN ({placeholders}) "
                f"OR dst_sym_file.path IN ({placeholders}))"
            )
            ordered = sorted(paths)
            params.extend(ordered)
            params.extend(ordered)
            params.extend(ordered)
            params.extend(ordered)

    params.append(limit)
    return conn.execute(
        f"""
        SELECT e.edge_type, e.resolved, e.line, e.dst_name,
               e.src_kind, e.dst_kind,
               src_file.path AS src_file_path,
               src_sym_file.path AS src_symbol_file_path,
               src_sym.name AS src_symbol_name,
               src_sym.kind AS src_symbol_kind,
               dst_file.path AS dst_file_path,
               dst_sym.name AS dst_symbol_name,
               dst_sym.kind AS dst_symbol_kind,
               dst_sym_file.path AS dst_symbol_file_path
        FROM edges e
        LEFT JOIN files src_file ON e.src_kind = 'file' AND src_file.id = e.src_id
        LEFT JOIN symbols src_sym ON e.src_kind = 'symbol' AND src_sym.id = e.src_id
        LEFT JOIN files src_sym_file ON src_sym_file.id = src_sym.file_id
        LEFT JOIN files dst_file ON e.dst_kind = 'file' AND dst_file.id = e.dst_id
        LEFT JOIN symbols dst_sym ON e.dst_kind = 'symbol' AND dst_sym.id = e.dst_id
        LEFT JOIN files dst_sym_file ON dst_sym_file.id = dst_sym.file_id
        {where}
        ORDER BY e.edge_type, COALESCE(src_file.path, src_sym_file.path), e.line
        LIMIT ?
        """,
        params,
    ).fetchall()


def _node_key(kind: str, path: str, name: str | None = None) -> str:
    return f"{kind}:{path}:{name or ''}"


def _graph_data(rows: list[sqlite3.Row]) -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    for row in rows:
        src_path = row["src_file_path"] or row["src_symbol_file_path"] or ""
        src_name = row["src_symbol_name"]
        src_kind = row["src_symbol_kind"] or "file"
        dst_path = row["dst_file_path"] or row["dst_symbol_file_path"] or ""
        dst_name = row["dst_symbol_name"]
        dst_kind = row["dst_symbol_kind"] or row["dst_kind"] or "file"
        if not src_path or not dst_path:
            continue

        src_key = _node_key("symbol" if src_name else "file", src_path, src_name)
        dst_key = _node_key("symbol" if dst_name else "file", dst_path, dst_name)
        nodes.setdefault(
            src_key,
            {"id": src_key, "path": src_path, "name": src_name, "kind": src_kind},
        )
        nodes.setdefault(
            dst_key,
            {"id": dst_key, "path": dst_path, "name": dst_name, "kind": dst_kind},
        )
        edges.append(
            {
                "source": src_key,
                "target": dst_key,
                "type": row["edge_type"],
                "line": row["line"],
            }
        )
    return {"nodes": list(nodes.values()), "edges": edges}


def _layout(nodes: list[dict[str, Any]], width: int = 1200, height: int = 760) -> None:
    radius = min(width, height) * 0.38
    cx = width / 2
    cy = height / 2
    count = max(1, len(nodes))
    for idx, node in enumerate(nodes):
        angle = 2 * math.pi * idx / count
        node["x"] = round(cx + radius * math.cos(angle), 2)
        node["y"] = round(cy + radius * math.sin(angle), 2)


def export_graph_html(
    conn: sqlite3.Connection,
    output: Path,
    *,
    target: str | None = None,
    depth: int = 2,
    direction: str = "both",
    limit: int = 500,
) -> dict[str, int]:
    rows = _edge_rows(conn, target=target, depth=depth, direction=direction, limit=limit)
    data = _graph_data(rows)
    _layout(data["nodes"])
    payload = json.dumps(data).replace("</", "<\\/")
    title = "codebase-index graph" + (f" - {target}" if target else "")
    html = f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
body {{ margin:0; font:14px system-ui, Segoe UI, sans-serif; color:#1f2937; background:#f8fafc; }}
header {{ padding:14px 18px; border-bottom:1px solid #d1d5db; background:#fff; display:flex; gap:14px; align-items:center; }}
h1 {{ font-size:18px; margin:0; font-weight:650; }}
input {{ width:320px; max-width:40vw; padding:8px 10px; border:1px solid #cbd5e1; border-radius:6px; }}
main {{ display:grid; grid-template-columns:minmax(0,1fr) 420px; min-height:calc(100vh - 58px); }}
svg {{ width:100%; height:calc(100vh - 58px); background:#fff; }}
aside {{ border-left:1px solid #d1d5db; overflow:auto; background:#f8fafc; }}
table {{ width:100%; border-collapse:collapse; font-size:12px; }}
th,td {{ text-align:left; padding:8px; border-bottom:1px solid #e5e7eb; vertical-align:top; }}
th {{ position:sticky; top:0; background:#f1f5f9; z-index:1; }}
.edge {{ stroke:#94a3b8; stroke-width:1.3; }}
.node {{ cursor:pointer; }}
.node circle {{ fill:#fff; stroke:#2563eb; stroke-width:2; }}
.node.file circle {{ stroke:#059669; }}
.node text {{ font-size:11px; fill:#111827; }}
.dim {{ opacity:.12; }}
.selected circle {{ fill:#dbeafe; }}
</style>
</head>
<body>
<header>
<h1>codebase-index graph</h1>
<input id="filter" placeholder="Filter nodes or edges">
<span id="counts"></span>
</header>
<main>
<svg id="graph" viewBox="0 0 1200 760" role="img" aria-label="code graph"></svg>
<aside>
<table>
<thead><tr><th>type</th><th>source</th><th>target</th><th>line</th></tr></thead>
<tbody id="edgeRows"></tbody>
</table>
</aside>
</main>
<script id="graph-data" type="application/json">{payload}</script>
<script>
const data = JSON.parse(document.getElementById('graph-data').textContent);
const svg = document.getElementById('graph');
const rows = document.getElementById('edgeRows');
const counts = document.getElementById('counts');
const byId = new Map(data.nodes.map(n => [n.id, n]));
function label(n) {{ return n.name ? `${{n.name}} (${{n.path}})` : n.path; }}
function draw(filter = '') {{
  svg.textContent = '';
  rows.textContent = '';
  const q = filter.toLowerCase();
  const visibleNode = n => !q || label(n).toLowerCase().includes(q);
  const visibleEdge = e => {{
    const s = byId.get(e.source), t = byId.get(e.target);
    return !q || e.type.toLowerCase().includes(q) || label(s).toLowerCase().includes(q) || label(t).toLowerCase().includes(q);
  }};
  for (const e of data.edges.filter(visibleEdge)) {{
    const s = byId.get(e.source), t = byId.get(e.target);
    const line = document.createElementNS('http://www.w3.org/2000/svg', 'line');
    line.setAttribute('x1', s.x); line.setAttribute('y1', s.y);
    line.setAttribute('x2', t.x); line.setAttribute('y2', t.y);
    line.setAttribute('class', 'edge');
    svg.appendChild(line);
    const tr = document.createElement('tr');
    for (const val of [e.type, label(s), label(t), e.line || '']) {{
      const td = document.createElement('td'); td.textContent = val; tr.appendChild(td);
    }}
    rows.appendChild(tr);
  }}
  for (const n of data.nodes.filter(visibleNode)) {{
    const g = document.createElementNS('http://www.w3.org/2000/svg', 'g');
    g.setAttribute('class', `node ${{n.name ? 'symbol' : 'file'}}`);
    g.setAttribute('transform', `translate(${{n.x}},${{n.y}})`);
    const c = document.createElementNS('http://www.w3.org/2000/svg', 'circle');
    c.setAttribute('r', n.name ? 12 : 16);
    const txt = document.createElementNS('http://www.w3.org/2000/svg', 'text');
    txt.setAttribute('x', 18); txt.setAttribute('y', 4);
    txt.textContent = n.name || n.path.split('/').pop();
    g.appendChild(c); g.appendChild(txt);
    g.addEventListener('click', () => document.getElementById('filter').value = n.name || n.path);
    svg.appendChild(g);
  }}
  counts.textContent = `${{data.nodes.length}} nodes / ${{data.edges.length}} edges`;
}}
document.getElementById('filter').addEventListener('input', e => draw(e.target.value));
draw();
</script>
</body>
</html>
"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")
    return {"nodes": len(data["nodes"]), "edges": len(data["edges"])}
