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
        SELECT e.edge_type, e.resolved, e.line, e.dst_name, e.confidence,
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
    from collections import Counter, defaultdict

    from .analysis import detect_communities, weighted_degree

    nodes: dict[str, dict[str, Any]] = {}
    edges: list[dict[str, Any]] = []
    adj: dict[str, Counter] = defaultdict(Counter)
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
                "confidence": row["confidence"] if "confidence" in row.keys() else "extracted",
            }
        )
        if src_key != dst_key:
            adj[src_key][dst_key] += 1
            adj[dst_key][src_key] += 1

    # Colour by module and size by centrality, computed on the displayed subgraph.
    # The analysis functions are generic over the node key type, so string keys work.
    communities = detect_communities(adj)
    degree = weighted_degree(adj)
    for key, node in nodes.items():
        node["community"] = communities.get(key, -1)
        node["degree"] = degree.get(key, 0)
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
.edge.inferred {{ stroke-dasharray:5 3; }}            /* heuristic-resolved */
.edge.ambiguous {{ stroke:#ef4444; stroke-dasharray:2 3; }}  /* unresolved target */
.node {{ cursor:pointer; }}
.node circle {{ stroke:#1f2937; stroke-width:1.5; }}
.node.file circle {{ stroke-width:2.5; }}
.node text {{ font-size:11px; fill:#111827; }}
.dim {{ opacity:.12; }}
.selected circle {{ stroke:#111827; stroke-width:3; }}
.legend {{ font-size:11px; color:#475569; display:flex; gap:14px; align-items:center; flex-wrap:wrap; }}
.legend b {{ color:#1f2937; }}
.legend svg {{ width:34px; height:8px; vertical-align:middle; }}
</style>
</head>
<body>
<header>
<h1>codebase-index graph</h1>
<input id="filter" placeholder="Filter nodes or edges">
<span id="counts"></span>
<span class="legend">
  <span><b>colour</b> = module</span>
  <span><b>size</b> = connectivity</span>
  <span><svg><line x1="0" y1="4" x2="34" y2="4" stroke="#94a3b8" stroke-width="1.3"/></svg> extracted</span>
  <span><svg><line x1="0" y1="4" x2="34" y2="4" stroke="#94a3b8" stroke-width="1.3" stroke-dasharray="5 3"/></svg> inferred</span>
  <span><svg><line x1="0" y1="4" x2="34" y2="4" stroke="#ef4444" stroke-width="1.3" stroke-dasharray="2 3"/></svg> ambiguous</span>
</span>
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
// Stable, readable categorical palette; community id indexes into it.
const PALETTE = ['#2563eb','#059669','#d97706','#7c3aed','#db2777','#0891b2',
                 '#65a30d','#dc2626','#4f46e5','#ca8a04','#0d9488','#9333ea'];
function colorFor(n) {{
  const c = n.community;
  if (c === undefined || c < 0) return '#cbd5e1';
  return PALETTE[c % PALETTE.length];
}}
function radiusFor(n) {{ return (n.name ? 8 : 11) + Math.min(14, Math.sqrt(n.degree || 0) * 2); }}
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
    line.setAttribute('class', 'edge ' + (e.confidence || 'extracted'));
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
    c.setAttribute('r', radiusFor(n));
    c.setAttribute('fill', colorFor(n));
    c.setAttribute('fill-opacity', '0.85');
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


# ---------------------------------------------------------------------------
# Interop exports — GraphML (Gephi/yEd), DOT (Graphviz), Cypher (Neo4j).
# All reuse _edge_rows + _graph_data, so they carry the same community/degree/
# confidence enrichment as the HTML view. Pure-stdlib, zero dependencies.
# ---------------------------------------------------------------------------

def _collect(conn, *, target, depth, direction, limit) -> dict[str, Any]:
    return _graph_data(_edge_rows(conn, target=target, depth=depth, direction=direction, limit=limit))


def _write(output: Path, text: str) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(text, encoding="utf-8")


def export_graph_graphml(
    conn: sqlite3.Connection, output: Path, *,
    target: str | None = None, depth: int = 2, direction: str = "both", limit: int = 500,
) -> dict[str, int]:
    """GraphML for Gephi / yEd / NetworkX. Node ids are dense (n0, n1, …)."""
    from xml.sax.saxutils import escape, quoteattr

    data = _collect(conn, target=target, depth=depth, direction=direction, limit=limit)
    ids = {n["id"]: f"n{i}" for i, n in enumerate(data["nodes"])}
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<graphml xmlns="http://graphml.graphdrawing.org/xmlns">',
    ]
    for k, ty in (("kind", "string"), ("name", "string"), ("path", "string"),
                  ("community", "long"), ("degree", "long")):
        lines.append(f'  <key id="{k}" for="node" attr.name="{k}" attr.type="{ty}"/>')
    for k in ("edge_type", "confidence"):
        lines.append(f'  <key id="{k}" for="edge" attr.name="{k}" attr.type="string"/>')
    lines.append('  <graph edgedefault="directed">')
    for n in data["nodes"]:
        lines.append(f'    <node id={quoteattr(ids[n["id"]])}>')
        lines.append(f'      <data key="kind">{escape(n.get("kind") or "")}</data>')
        lines.append(f'      <data key="name">{escape(n.get("name") or "")}</data>')
        lines.append(f'      <data key="path">{escape(n.get("path") or "")}</data>')
        lines.append(f'      <data key="community">{int(n.get("community", -1))}</data>')
        lines.append(f'      <data key="degree">{int(n.get("degree", 0))}</data>')
        lines.append("    </node>")
    for i, e in enumerate(data["edges"]):
        s = ids.get(e["source"])
        t = ids.get(e["target"])
        if s is None or t is None:
            continue
        lines.append(f'    <edge id="e{i}" source={quoteattr(s)} target={quoteattr(t)}>')
        lines.append(f'      <data key="edge_type">{escape(e["type"])}</data>')
        lines.append(f'      <data key="confidence">{escape(e.get("confidence") or "")}</data>')
        lines.append("    </edge>")
    lines += ["  </graph>", "</graphml>", ""]
    _write(output, "\n".join(lines))
    return {"nodes": len(data["nodes"]), "edges": len(data["edges"])}


def export_graph_dot(
    conn: sqlite3.Connection, output: Path, *,
    target: str | None = None, depth: int = 2, direction: str = "both", limit: int = 500,
) -> dict[str, int]:
    """Graphviz DOT. Edge style encodes confidence (solid/dashed/dotted)."""
    data = _collect(conn, target=target, depth=depth, direction=direction, limit=limit)
    ids = {n["id"]: f"n{i}" for i, n in enumerate(data["nodes"])}
    style = {"extracted": "solid", "inferred": "dashed", "ambiguous": "dotted"}

    def esc(s: str) -> str:
        return s.replace("\\", "\\\\").replace('"', '\\"')

    lines = ["digraph codebase_index {", "  rankdir=LR;", '  node [shape=box, fontsize=10];']
    for n in data["nodes"]:
        lbl = esc(f'{n["name"]}\n{n["path"]}' if n.get("name") else (n.get("path") or ""))
        lines.append(f'  {ids[n["id"]]} [label="{lbl}"];')
    for e in data["edges"]:
        s = ids.get(e["source"])
        t = ids.get(e["target"])
        if s is None or t is None:
            continue
        st = style.get(e.get("confidence") or "extracted", "solid")
        lines.append(f'  {s} -> {t} [label="{esc(e["type"])}", style={st}];')
    lines += ["}", ""]
    _write(output, "\n".join(lines))
    return {"nodes": len(data["nodes"]), "edges": len(data["edges"])}


def export_graph_neo4j(
    conn: sqlite3.Connection, output: Path, *,
    target: str | None = None, depth: int = 2, direction: str = "both", limit: int = 500,
) -> dict[str, int]:
    """Cypher script (MERGE statements) to load the graph into Neo4j / FalkorDB."""
    data = _collect(conn, target=target, depth=depth, direction=direction, limit=limit)

    def lit(s: str) -> str:
        return "'" + (s or "").replace("\\", "\\\\").replace("'", "\\'") + "'"

    lines = ["// codebase-index graph export for Neo4j / FalkorDB"]
    for n in data["nodes"]:
        node_label = "Symbol" if n.get("name") else "File"
        lines.append(
            f"MERGE (:{node_label} {{key:{lit(n['id'])}, name:{lit(n.get('name') or '')}, "
            f"path:{lit(n.get('path') or '')}, community:{int(n.get('community', -1))}, "
            f"degree:{int(n.get('degree', 0))}}});"
        )
    for e in data["edges"]:
        rel = (e["type"] or "edge").upper()
        lines.append(
            f"MATCH (a {{key:{lit(e['source'])}}}), (b {{key:{lit(e['target'])}}}) "
            f"MERGE (a)-[:{rel} {{confidence:{lit(e.get('confidence') or 'extracted')}}}]->(b);"
        )
    lines.append("")
    _write(output, "\n".join(lines))
    return {"nodes": len(data["nodes"]), "edges": len(data["edges"])}
