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

import math
import sqlite3
from collections import deque
from typing import Optional

from ..models import GraphCoverage, ImpactNode, ImpactResponse, IndexFreshness
from ..storage import repo


_CONFIDENCE_RANK = {
    "extracted": 0,
    "inferred": 1,
    "ambiguous": 2,
}


def _validated_decay(decay: float) -> float:
    """Return a finite distance-decay factor in the inclusive [0, 1] range."""
    try:
        value = float(decay)
    except (TypeError, ValueError) as exc:
        raise ValueError("decay must be a finite number between 0 and 1") from exc
    if not math.isfinite(value) or not 0.0 <= value <= 1.0:
        raise ValueError("decay must be a finite number between 0 and 1")
    return value


def _confidence_rank(confidence: Optional[str]) -> int:
    """Rank edge confidence conservatively (lower is better)."""
    return _CONFIDENCE_RANK.get(confidence or "", len(_CONFIDENCE_RANK))


def _set_optional_impact_strength(node: ImpactNode, strength: float) -> None:
    """Populate an optional model field without changing the shared schema.

    Older ImpactNode models intentionally have no score field. If a consumer
    supplies a compatible model with an ``impact_strength`` field, expose the
    calculated value; otherwise distance remains the public ranking signal.
    """
    fields = getattr(type(node), "model_fields", None)
    if fields is None:
        fields = getattr(type(node), "__fields__", {})
    if "impact_strength" in fields:
        setattr(node, "impact_strength", strength)



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


def _neighbor_sort_key(neighbor: tuple[str, int, Optional[str], Optional[str]]) -> tuple:
    """Make edge traversal independent of SQLite's unspecified row order."""
    kind, node_id, edge_type, confidence = neighbor
    return (
        _confidence_rank(confidence),
        kind,
        node_id,
        edge_type or "",
        confidence or "",
    )


def _impact_sort_key(node: ImpactNode) -> tuple:
    """Rank direct impact before transitive impact, then resolve ties safely."""
    return (
        node.distance,
        _confidence_rank(node.via_confidence),
        node.path,
        node.kind,
        node.name or "",
        node.line_start if node.line_start is not None else -1,
        node.via_edge or "",
    )


def walk_impact(
    conn: sqlite3.Connection,
    target: str,
    *,
    depth: int,
    direction: str,
    decay: float = 1.0,
) -> list[ImpactNode]:
    """Return bounded impact nodes ranked by hop distance.

    ``decay`` controls the optional strength score as ``decay ** (distance - 1)``:
    direct nodes score 1.0 and transitive nodes score progressively less.  The
    current ImpactNode schema has no score field, so its observable output uses
    stable distance ordering (direct before transitive) and confidence as a tie
    breaker.  A compatible model that declares ``impact_strength`` receives it.
    """
    decay_value = _validated_decay(decay)
    seeds = _seed_nodes(conn, target)
    if not seeds:
        return []

    seed_keys = set(seeds)
    queue: deque[tuple[str, int, int]] = deque((k, i, 0) for k, i in seeds)
    states: dict[tuple[str, int], tuple[int, int]] = {
        key: (0, 0) for key in seed_keys
    }
    nodes: dict[tuple[str, int], ImpactNode] = {}

    while queue:
        kind, node_id, dist = queue.popleft()
        state = states.get((kind, node_id))
        if state is None or state[0] != dist:
            continue
        if dist >= depth:
            continue
        for nk, nid, etype, conf in sorted(
            _neighbors(conn, kind, node_id, direction), key=_neighbor_sort_key
        ):
            key = (nk, nid)
            if key in seed_keys:
                continue
            next_dist = dist + 1
            candidate_state = (next_dist, _confidence_rank(conf))
            current_state = states.get(key)
            if current_state is not None:
                # Shorter paths always win. At equal distance, only a more
                # confident edge may replace the existing audit trail.
                if candidate_state >= current_state:
                    continue

            meta = _node_meta(conn, nk, nid)
            if meta is None:
                continue
            meta.distance = next_dist
            meta.via_edge = etype
            meta.via_confidence = conf
            _set_optional_impact_strength(
                meta, decay_value ** max(next_dist - 1, 0)
            )
            states[key] = candidate_state
            nodes[key] = meta
            # Equal-distance confidence improvements do not need another walk;
            # shorter paths can change the reachable frontier and are queued.
            if current_state is None or next_dist < current_state[0]:
                queue.append((nk, nid, next_dist))

    return sorted(nodes.values(), key=_impact_sort_key)


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
    conn: sqlite3.Connection,
    target: str,
    *,
    depth: int,
    direction: str,
    decay: float = 1.0,
) -> ImpactResponse:
    nodes = walk_impact(
        conn, target, depth=depth, direction=direction, decay=decay
    )
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
