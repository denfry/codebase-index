"""Impact analysis: bounded BFS over the resolved edge graph.

Direction semantics:
  up   -> dependents (who is affected if the target changes): incoming edges.
  down -> dependencies (what the target relies on): outgoing edges.
  both -> union of the two.

Target resolution: an exact file path -> a file node (seeded together with all
symbols defined in that file, so importers AND subclassers surface). Otherwise a
symbol name -> all symbol nodes with that name. A path suffix is the last resort.
"""

from __future__ import annotations

import sqlite3
from collections import deque
from typing import Optional

from ..models import GraphCoverage, ImpactNode, ImpactResponse, IndexFreshness
from ..storage import repo


def _freshness(conn: sqlite3.Connection) -> IndexFreshness:
    return IndexFreshness(
        exists=True,
        stale=False,
        built_at=repo.get_meta(conn, "built_at"),
        head_commit=repo.get_meta(conn, "head_commit"),
    )


def _seed_nodes(conn: sqlite3.Connection, target: str) -> list[tuple[str, int]]:
    """Resolve a target string to one or more (kind, id) start nodes."""
    frow = repo.file_by_path(conn, target)
    if frow is not None:
        seeds = [("file", int(frow["id"]))]
        seeds += [("symbol", int(s["id"])) for s in repo.symbols_in_file(conn, int(frow["id"]))]
        return seeds

    sym_rows = repo.symbols_by_name(conn, target, exact=True)
    if sym_rows:
        return [("symbol", int(r["id"])) for r in sym_rows]

    suffix = repo.files_with_suffix(conn, target)
    if len(suffix) == 1:
        fid = int(suffix[0]["id"])
        return [("file", fid)] + [
            ("symbol", int(s["id"])) for s in repo.symbols_in_file(conn, fid)
        ]
    return []


def _neighbors(conn, kind, node_id, direction):
    """Yield (next_kind, next_id, edge_type, confidence) for the requested direction(s)."""
    if direction in ("up", "both"):
        for e in repo.incoming_edges(conn, kind, node_id):
            yield e["src_kind"], int(e["src_id"]), e["edge_type"], e["confidence"]
    if direction in ("down", "both"):
        for e in repo.outgoing_edges(conn, kind, node_id):
            if e["dst_id"] is not None:
                yield e["dst_kind"], int(e["dst_id"]), e["edge_type"], e["confidence"]


def _node_meta(conn, kind, node_id) -> Optional[ImpactNode]:
    if kind == "file":
        row = conn.execute("SELECT path FROM files WHERE id = ?", (node_id,)).fetchone()
        if row is None:
            return None
        return ImpactNode(kind="file", path=row["path"], distance=0)
    row = conn.execute(
        "SELECT s.name AS name, s.line_start AS line_start, f.path AS path "
        "FROM symbols s JOIN files f ON f.id = s.file_id WHERE s.id = ?",
        (node_id,),
    ).fetchone()
    if row is None:
        return None
    return ImpactNode(kind="symbol", path=row["path"], name=row["name"],
                      line_start=row["line_start"], distance=0)


def walk_impact(
    conn: sqlite3.Connection, target: str, *, depth: int, direction: str
) -> list[ImpactNode]:
    seeds = _seed_nodes(conn, target)
    if not seeds:
        return []
    visited: set[tuple[str, int]] = set(seeds)
    queue: deque[tuple[str, int, int]] = deque((k, i, 0) for k, i in seeds)
    out: list[ImpactNode] = []

    while queue:
        kind, node_id, dist = queue.popleft()
        if dist >= depth:
            continue
        for nk, nid, etype, conf in _neighbors(conn, kind, node_id, direction):
            if (nk, nid) in visited:
                continue
            visited.add((nk, nid))
            meta = _node_meta(conn, nk, nid)
            if meta is None:
                continue
            meta.distance = dist + 1
            meta.via_edge = etype
            meta.via_confidence = conf
            out.append(meta)
            queue.append((nk, nid, dist + 1))
    return out


def _target_paths(conn: sqlite3.Connection, target: str) -> list[str]:
    """The file path(s) the target resolves to, for coverage classification."""
    if repo.file_by_path(conn, target) is not None:
        return [target]
    sym_rows = repo.symbols_by_name(conn, target, exact=True)
    if sym_rows:
        return [r["path"] for r in sym_rows]
    suffix = repo.files_with_suffix(conn, target)
    if len(suffix) == 1:
        return [suffix[0]["path"]]
    return []


def impact_lookup(
    conn: sqlite3.Connection, target: str, *, depth: int, direction: str
) -> ImpactResponse:
    nodes = walk_impact(conn, target, depth=depth, direction=direction)
    best: dict[str, int] = {}
    for n in nodes:
        if n.path not in best or n.distance < best[n.path]:
            best[n.path] = n.distance
    files = sorted(best, key=lambda p: (best[p], p))
    return ImpactResponse(
        target=target, direction=direction, depth=depth,
        index=_freshness(conn), nodes=nodes, files=files,
        coverage=GraphCoverage.for_paths(_target_paths(conn, target)),
    )
