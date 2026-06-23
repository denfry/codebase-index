"""Graph navigation: shortest path between two nodes, and a node "card".

graphify ships `path A B` (how are two things connected?) and `explain Symbol`
(what is this node?). codebase-index already uses `explain` for how-it-works
retrieval, so the node card lives under `describe` to avoid colliding with it.

Both walk the *resolved* edge graph and carry the Phase-1 confidence trail, so a
path through an `inferred`/`ambiguous` edge is visibly less certain than one
through `extracted` edges.
"""

from __future__ import annotations

import sqlite3
from collections import deque
from typing import Optional

from ..storage import repo

# BFS safety valve: stop exploring after this many nodes so `path` stays cheap on
# very large graphs (the shortest path, if short, is found long before this).
_MAX_VISITS = 20000

Node = tuple[str, int]


def _freshness(conn: sqlite3.Connection) -> dict:
    return {
        "exists": True,
        "stale": False,
        "built_at": repo.get_meta(conn, "built_at"),
        "head_commit": repo.get_meta(conn, "head_commit"),
    }


def _resolve_targets(conn: sqlite3.Connection, token: str) -> list[Node]:
    """Resolve a path/symbol token to one or more graph nodes (file or symbols)."""
    frow = repo.file_by_path(conn, token)
    if frow is not None:
        return [("file", int(frow["id"]))]
    sym_rows = repo.symbols_by_name(conn, token, exact=True)
    if sym_rows:
        return [("symbol", int(r["id"])) for r in sym_rows]
    suffix = repo.files_with_suffix(conn, token)
    if len(suffix) == 1:
        return [("file", int(suffix[0]["id"]))]
    return []


def _node_ref(conn: sqlite3.Connection, kind: str, node_id: int) -> Optional[dict]:
    if kind == "file":
        row = conn.execute("SELECT path FROM files WHERE id = ?", (node_id,)).fetchone()
        if row is None:
            return None
        return {"kind": "file", "name": row["path"].rsplit("/", 1)[-1], "path": row["path"],
                "line_start": None}
    row = conn.execute(
        "SELECT s.name AS name, s.kind AS kind, s.line_start AS line_start, f.path AS path "
        "FROM symbols s JOIN files f ON f.id = s.file_id WHERE s.id = ?",
        (node_id,),
    ).fetchone()
    if row is None:
        return None
    return {"kind": "symbol", "name": row["name"], "symbol_kind": row["kind"],
            "path": row["path"], "line_start": row["line_start"]}


def _undirected_neighbors(conn: sqlite3.Connection, kind: str, node_id: int):
    """Yield (next_kind, next_id, edge_type, confidence, direction) ignoring edge
    direction — `path` answers "how are these connected", not "who calls whom"."""
    for e in repo.incoming_edges(conn, kind, node_id):
        yield e["src_kind"], int(e["src_id"]), e["edge_type"], e["confidence"], "in"
    for e in repo.outgoing_edges(conn, kind, node_id):
        if e["dst_id"] is not None:
            yield e["dst_kind"], int(e["dst_id"]), e["edge_type"], e["confidence"], "out"


# ---------------------------------------------------------------------------
# path A B
# ---------------------------------------------------------------------------

def path_payload(conn: sqlite3.Connection, src: str, dst: str) -> dict:
    """Shortest undirected path between two nodes, with the edge audit trail."""
    src_seeds = _resolve_targets(conn, src)
    dst_seeds = set(_resolve_targets(conn, dst))
    base = {"src": src, "dst": dst, "index": _freshness(conn), "nodes": [], "steps": []}
    if not src_seeds or not dst_seeds:
        missing = src if not src_seeds else dst
        return {**base, "found": False, "reason": f"Could not resolve `{missing}` to an indexed node."}

    # Multi-source BFS from every src node; stop at the first dst node reached.
    parent: dict[Node, Optional[Node]] = {seed: None for seed in src_seeds}
    via: dict[Node, tuple] = {}
    queue: deque[Node] = deque(src_seeds)
    found: Optional[Node] = None
    visits = 0
    while queue and visits < _MAX_VISITS:
        node = queue.popleft()
        visits += 1
        if node in dst_seeds:
            found = node
            break
        for nk, nid, etype, conf, direction in _undirected_neighbors(conn, *node):
            nxt = (nk, nid)
            if nxt not in parent:
                parent[nxt] = node
                via[nxt] = (etype, conf, direction)
                queue.append(nxt)

    if found is None:
        return {**base, "found": False,
                "reason": "No path found between the two nodes in the resolved graph."}

    # Reconstruct from `found` back to a src seed.
    chain: list[Node] = []
    cur: Optional[Node] = found
    while cur is not None:
        chain.append(cur)
        cur = parent[cur]
    chain.reverse()

    nodes = [ref for n in chain if (ref := _node_ref(conn, *n)) is not None]
    steps = []
    for prev, nxt in zip(chain, chain[1:]):
        etype, conf, direction = via[nxt]
        a, b = _node_ref(conn, *prev), _node_ref(conn, *nxt)
        if a and b:
            steps.append({"from": a, "to": b, "edge_type": etype,
                          "confidence": conf, "direction": direction})
    return {**base, "found": True, "hops": len(steps), "nodes": nodes, "steps": steps}


# ---------------------------------------------------------------------------
# describe <symbol>
# ---------------------------------------------------------------------------

def describe_payload(conn: sqlite3.Connection, query: str) -> dict:
    """A node card: definition(s), callers, callees, centrality, module, god status."""
    base = {"query": query, "index": _freshness(conn)}
    sym_rows = repo.symbols_by_name(conn, query, exact=True)
    if not sym_rows:
        return {**base, "found": False,
                "reason": f"No symbol named `{query}` is indexed. Try `search` or `symbol`."}

    definitions = [
        {
            "name": r["name"],
            "qualified": r["qualified"],
            "kind": r["kind"],
            "path": r["path"],
            "line_start": r["line_start"],
            "line_end": r["line_end"],
            "signature": r["signature"],
            "in_degree": int(r["in_degree"]),
            "out_degree": int(r["out_degree"]),
        }
        for r in sym_rows
    ]
    # Primary = most-connected definition (the one worth describing in depth).
    primary_row = max(sym_rows, key=lambda r: int(r["in_degree"]) + int(r["out_degree"]))
    primary_id = int(primary_row["id"])

    callers = [
        {"path": r["path"], "line": r["line"], "confidence": r["confidence"]}
        for r in repo.refs_for_name(conn, query)
    ]
    callees = []
    for e in repo.outgoing_edges(conn, "symbol", primary_id):
        if e["dst_id"] is None:
            continue
        ref = _node_ref(conn, e["dst_kind"], int(e["dst_id"]))
        if ref is not None:
            callees.append({**ref, "edge_type": e["edge_type"], "confidence": e["confidence"]})

    module = primary_row["path"].rsplit("/", 1)[0] if "/" in primary_row["path"] else "(root)"
    god = _god_rank(conn, primary_row["name"], primary_row["path"])

    return {
        **base,
        "found": True,
        "definitions": definitions,
        "primary": {"name": primary_row["name"], "path": primary_row["path"],
                    "module": module, "god_rank": god,
                    "in_degree": int(primary_row["in_degree"]),
                    "out_degree": int(primary_row["out_degree"])},
        "callers": callers,
        "callees": callees,
    }


def _god_rank(conn: sqlite3.Connection, name: str, path: str) -> Optional[int]:
    """1-based rank of this symbol among the cached god nodes, or None."""
    from . import analysis

    summary = analysis.load_analysis(conn)
    if not summary:
        return None
    for idx, g in enumerate(summary.get("god_nodes", []), start=1):
        if g.get("name") == name and g.get("path") == path:
            return idx
    return None
