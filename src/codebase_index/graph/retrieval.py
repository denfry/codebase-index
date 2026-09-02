"""Bounded graph-based candidate retrieval.

The retriever deliberately works from the lexical/symbol candidates already found by
other retrievers.  It only follows indexed, resolved SQLite edges from those seeds;
it never enumerates the repository's complete node set.
"""

from __future__ import annotations

import math
import sqlite3
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Iterable, Optional

from ..retrieval.types import Candidate

Node = tuple[str, int]

# Confidence is both a ranking signal and an audit trail.  A malformed/unknown value
# is treated conservatively rather than being presented as an exact relationship.
_CONFIDENCE_WEIGHT = {
    "extracted": 1.0,
    "inferred": 0.75,
    "ambiguous": 0.35,
}


@dataclass(frozen=True)
class _Edge:
    source: Node
    target: Node
    edge_type: str
    confidence: str
    line: Optional[int]
    edge_id: int
    direction: str


def _safe_float(value: object, default: float) -> float:
    try:
        if not isinstance(value, (str, bytes, bytearray, int, float)):
            return default
        number = float(value)
    except (TypeError, ValueError):
        return default
    return number if math.isfinite(number) else default


def _safe_int(value: object, default: int = 0) -> int:
    try:
        if not isinstance(value, (str, bytes, bytearray, int, float)):
            return default
        return int(value)
    except (TypeError, ValueError):
        return default

def _row_value(row: object, key: str, index: int, default: object = None) -> object:
    """Read sqlite Row and tuple rows alike (useful for small test connections)."""
    try:
        if isinstance(row, sqlite3.Row):
            return row[key]
        return row[index]  # type: ignore[index]
    except (IndexError, KeyError, TypeError):
        return default


def _execute(conn: sqlite3.Connection, sql: str, params: tuple[object, ...]) -> list[object]:
    """Execute a read, making absent/partial tables a harmless empty graph."""
    try:
        return list(conn.execute(sql, params).fetchall())
    except (AttributeError, sqlite3.Error, TypeError, ValueError):
        return []


def _edge_execute(
    conn: sqlite3.Connection,
    primary_sql: str,
    fallback_sql: str,
    params: tuple[object, ...],
) -> list[object]:
    """Read edge rows, tolerating pre-confidence/partial edge tables."""
    try:
        return list(conn.execute(primary_sql, params).fetchall())
    except (AttributeError, sqlite3.Error, TypeError, ValueError):
        return _execute(conn, fallback_sql, params)




def _seed_nodes(conn: sqlite3.Connection, candidate: Candidate) -> list[Node]:
    path = getattr(candidate, "path", None)
    if not isinstance(path, str) or not path:
        return []
    files = _execute(conn, "SELECT id FROM files WHERE path = ? LIMIT 1", (path,))
    if not files:
        return []
    file_id = _safe_int(_row_value(files[0], "id", 0), -1)
    if file_id < 0:
        return []

    symbol_name = getattr(candidate, "symbol", None)
    if isinstance(symbol_name, str) and symbol_name:
        line = _safe_int(getattr(candidate, "line_start", 0), 0)
        rows = _execute(
            conn,
            """
            SELECT s.id
            FROM symbols AS s JOIN files AS f ON f.id = s.file_id
            WHERE f.path = ? AND s.name = ?
            ORDER BY CASE WHEN s.line_start = ? THEN 0 ELSE 1 END,
                     s.line_start, s.id
            LIMIT 1
            """,
            (path, symbol_name, line),
        )
        if not rows:
            rows = _execute(
                conn,
                """
                SELECT s.id
                FROM symbols AS s JOIN files AS f ON f.id = s.file_id
                WHERE f.path = ? AND s.name = ?
                ORDER BY s.id
                LIMIT 1
                """,
                (path, symbol_name),
            )
        if rows:
            symbol_id = _safe_int(_row_value(rows[0], "id", 0), -1)
            if symbol_id >= 0:
                return [("symbol", symbol_id)]
    return [("file", file_id)]


def _edge_rows(
    conn: sqlite3.Connection,
    node: Node,
    *,
    limit: int,
    direction: str,
) -> list[_Edge]:
    kind, node_id = node
    # Separate indexed lookups retain SQLite's idx_edges_src/idx_edges_dst plans.
    incoming: list[object] = []
    outgoing: list[object] = []
    if direction in ("up", "both"):
        incoming = _edge_execute(
            conn,
            """
            SELECT id, edge_type, src_kind, src_id, confidence, line
            FROM edges
            WHERE resolved = 1 AND dst_kind = ? AND dst_id = ?
            ORDER BY src_kind, src_id, edge_type, id
            LIMIT ?
            """,
            """
            SELECT id, edge_type, src_kind, src_id, NULL AS confidence, line
            FROM edges
            WHERE resolved = 1 AND dst_kind = ? AND dst_id = ?
            ORDER BY src_kind, src_id, edge_type, id
            LIMIT ?
            """,
            (kind, node_id, limit),
        )
    if direction in ("down", "both"):
        outgoing = _edge_execute(
            conn,
            """
            SELECT id, edge_type, dst_kind, dst_id, confidence, line
            FROM edges
            WHERE resolved = 1 AND src_kind = ? AND src_id = ? AND dst_id IS NOT NULL
            ORDER BY dst_kind, dst_id, edge_type, id
            LIMIT ?
            """,
            """
            SELECT id, edge_type, dst_kind, dst_id, NULL AS confidence, line
            FROM edges
            WHERE resolved = 1 AND src_kind = ? AND src_id = ? AND dst_id IS NOT NULL
            ORDER BY dst_kind, dst_id, edge_type, id
            LIMIT ?
            """,
            (kind, node_id, limit),
        )
    edges: list[_Edge] = []
    for row in incoming:
        nk = _row_value(row, "src_kind", 2)
        ni = _safe_int(_row_value(row, "src_id", 3), -1)
        if nk not in ("file", "symbol") or ni < 0:
            continue
        edges.append(
            _Edge(
                source=(str(nk), ni),
                target=node,
                edge_type=str(_row_value(row, "edge_type", 1) or "unknown"),
                confidence=str(_row_value(row, "confidence", 4) or "unknown").lower(),
                line=(lambda x: _safe_int(x) if x is not None else None)(_row_value(row, "line", 5)),
                edge_id=_safe_int(_row_value(row, "id", 0), -1),
                direction="incoming",
            )
        )
    for row in outgoing:
        nk = _row_value(row, "dst_kind", 2)
        ni = _safe_int(_row_value(row, "dst_id", 3), -1)
        if nk not in ("file", "symbol") or ni < 0:
            continue
        edges.append(
            _Edge(
                source=node,
                target=(str(nk), ni),
                edge_type=str(_row_value(row, "edge_type", 1) or "unknown"),
                confidence=str(_row_value(row, "confidence", 4) or "unknown").lower(),
                line=(lambda x: _safe_int(x) if x is not None else None)(_row_value(row, "line", 5)),
                edge_id=_safe_int(_row_value(row, "id", 0), -1),
                direction="outgoing",
            )
        )
    # A malformed database can expose duplicate rows through both indexes. Keep all
    # provenance but make traversal order stable.
    edges.sort(key=lambda e: (e.target, e.edge_type, e.confidence, e.edge_id, e.direction))
    return edges


def _node_metadata(conn: sqlite3.Connection, node: Node) -> Optional[dict[str, object]]:
    kind, node_id = node
    if kind == "file":
        rows = _execute(
            conn, "SELECT path, is_generated, summary FROM files WHERE id = ? LIMIT 1", (node_id,)
        )
        if not rows:
            rows = _execute(
                conn,
                "SELECT path, 0 AS is_generated, NULL AS summary "
                "FROM files WHERE id = ? LIMIT 1",
                (node_id,),
            )
        if not rows:
            return None
        row = rows[0]
        path = _row_value(row, "path", 0)
        if not isinstance(path, str) or not path:
            return None
        return {
            "path": path,
            "line_start": 1,
            "line_end": 1,
            "kind": "file",
            "symbol": None,
            "content": _row_value(row, "summary", 2),
            "is_generated": bool(_row_value(row, "is_generated", 1, 0)),
        }

    rows = _execute(
        conn,
        """
        SELECT s.name, s.kind, s.line_start, s.line_end, s.signature,
               f.path, f.is_generated
        FROM symbols AS s JOIN files AS f ON f.id = s.file_id
        WHERE s.id = ? LIMIT 1
        """,
        (node_id,),
    )
    if not rows:
        rows = _execute(
            conn,
            """
            SELECT s.name, s.kind, s.line_start, s.line_end, NULL AS signature,
                   f.path, 0 AS is_generated
            FROM symbols AS s JOIN files AS f ON f.id = s.file_id
            WHERE s.id = ? LIMIT 1
            """,
            (node_id,),
        )
    if not rows:
        rows = _execute(
            conn,
            """
            SELECT s.name, 'symbol' AS kind, 1 AS line_start, 1 AS line_end,
                   NULL AS signature, f.path, 0 AS is_generated
            FROM symbols AS s JOIN files AS f ON f.id = s.file_id
            WHERE s.id = ? LIMIT 1
            """,
            (node_id,),
        )
    if not rows:
        return None
    row = rows[0]
    path = _row_value(row, "path", 5)
    name = _row_value(row, "name", 0)
    if not isinstance(path, str) or not path or not isinstance(name, str):
        return None
    return {
        "path": path,
        "line_start": max(1, _safe_int(_row_value(row, "line_start", 2), 1)),
        "line_end": max(1, _safe_int(_row_value(row, "line_end", 3), 1)),
        "kind": _row_value(row, "kind", 1),
        "symbol": name,
        "content": _row_value(row, "signature", 4),
        "is_generated": bool(_row_value(row, "is_generated", 6, 0)),
    }


def _provenance(edges: Iterable[_Edge]) -> str:
    parts: list[str] = []
    for edge in sorted(edges, key=lambda e: (e.edge_type, e.confidence, e.line or 0, e.edge_id)):
        confidence = edge.confidence if edge.confidence in _CONFIDENCE_WEIGHT else "unknown"
        line = f", line={edge.line}" if edge.line is not None else ""
        direction = "<-" if edge.direction == "incoming" else "->"
        parts.append(f"{direction}{edge.edge_type} (confidence={confidence}{line})")
    return "; ".join(dict.fromkeys(parts)) or "unknown edge provenance"


def graph_candidates(
    conn: sqlite3.Connection,
    seeds: Iterable[Candidate],
    *,
    depth: int = 2,
    node_cap: int = 50,
    damping: float = 0.85,
    iterations: int = 12,
    direction: str = "both",
) -> list[Candidate]:
    """Return bounded, deterministic graph neighbors of lexical/symbol *seeds*.

    ``direction`` controls traversal from each seed: ``up`` follows incoming
    edges (callers/importers), ``down`` follows outgoing edges (callees/imports),
    and ``both`` preserves the general related-code behavior.
    Personalized PageRank is evaluated only on the bounded depth-limited
    subgraph. Seed candidates themselves are excluded.
    """
    if conn is None:
        return []
    if direction not in {"up", "down", "both"}:
        raise ValueError("direction must be 'up', 'down', or 'both'")
    depth = max(0, _safe_int(depth))
    node_cap = max(0, _safe_int(node_cap))
    iterations = max(0, _safe_int(iterations))
    damping = min(1.0, max(0.0, _safe_float(damping, 0.85)))
    if depth == 0 or node_cap == 0 or iterations == 0:
        return []

    seed_scores: dict[Node, float] = defaultdict(float)
    seed_keys: set[tuple[str, int, int]] = set()
    for candidate in seeds or ():
        if not isinstance(candidate, Candidate):
            continue
        try:
            seed_keys.add(candidate.key())
        except (AttributeError, TypeError):
            pass
        nodes = _seed_nodes(conn, candidate)
        score = max(0.0, _safe_float(getattr(candidate, "score", 0.0), 0.0))
        for node in nodes:
            seed_scores[node] = max(seed_scores[node], score)
    if not seed_scores:
        return []

    # Candidate lists are normally already small.  Sorting here makes results
    # independent of input order and bounds fan-out when a caller supplies many hits.
    ordered_seeds = sorted(seed_scores, key=lambda n: n)
    seed_total = sum(seed_scores.values())
    if seed_total <= 0.0:
        teleport = {node: 1.0 / len(ordered_seeds) for node in ordered_seeds}
    else:
        teleport = {node: seed_scores[node] / seed_total for node in ordered_seeds}

    distances: dict[Node, int] = {node: 0 for node in ordered_seeds}
    adjacency: dict[Node, dict[Node, float]] = defaultdict(dict)
    via: dict[Node, list[_Edge]] = defaultdict(list)
    queue: deque[Node] = deque(ordered_seeds)
    # Seeds are retained; node_cap limits graph nodes returned, while this bound
    # prevents a depth walk from accumulating an unbounded frontier.
    max_discovered = len(ordered_seeds) + node_cap
    while queue and len(distances) <= max_discovered:
        node = queue.popleft()
        distance = distances[node]
        if distance >= depth:
            continue
        for edge in _edge_rows(
            conn, node, limit=max(1, node_cap), direction=direction
        ):
            neighbor = edge.source if edge.direction == "incoming" else edge.target
            if neighbor not in distances:
                if len(distances) >= max_discovered:
                    continue
                distances[neighbor] = distance + 1
                queue.append(neighbor)
                via[neighbor].append(edge)
            elif distances[neighbor] == distance + 1:
                via[neighbor].append(edge)
            weight = _CONFIDENCE_WEIGHT.get(edge.confidence, 0.5)
            adjacency[node][neighbor] = adjacency[node].get(neighbor, 0.0) + weight
            if direction == "both":
                adjacency[neighbor][node] = adjacency[neighbor].get(node, 0.0) + weight

    if not adjacency:
        return []

    rank = dict(teleport)
    for node in distances:
        rank.setdefault(node, 0.0)
    for _ in range(iterations):
        next_rank = {node: (1.0 - damping) * teleport.get(node, 0.0) for node in rank}
        dangling = 0.0
        for node, score in rank.items():
            neighbors = adjacency.get(node, {})
            total = sum(neighbors.values())
            if total <= 0.0:
                dangling += score
                continue
            for neighbor, weight in neighbors.items():
                next_rank[neighbor] = next_rank.get(neighbor, 0.0) + damping * score * weight / total
        if dangling:
            for node, probability in teleport.items():
                next_rank[node] = next_rank.get(node, 0.0) + damping * dangling * probability
        rank = next_rank

    out: list[tuple[float, Candidate]] = []
    seen: set[tuple[str, int, int]] = set(seed_keys)
    for node, score in rank.items():
        if node in seed_scores or node not in via:
            continue
        metadata = _node_metadata(conn, node)
        if metadata is None:
            continue
        provenance = _provenance(via[node])
        base_content = metadata["content"] if isinstance(metadata["content"], str) else ""
        content = f"{base_content}\n[graph provenance: {provenance}]" if base_content else (
            f"[graph provenance: {provenance}]"
        )
        candidate = Candidate(
            path=str(metadata["path"]),
            line_start=_safe_int(metadata["line_start"], 1),
            line_end=_safe_int(metadata["line_end"], 1),
            source="graph",
            score=float(score),
            kind=metadata["kind"] if isinstance(metadata["kind"], str) else None,
            symbol=metadata["symbol"] if isinstance(metadata["symbol"], str) else None,
            content=content,
            is_generated=bool(metadata["is_generated"]),
            reason=(
                f"graph propagation distance={distances[node]}; "
                f"provenance={provenance}"
            ),
        )
        if candidate.key() in seen:
            continue
        seen.add(candidate.key())
        out.append((score, candidate))

    out.sort(key=lambda item: (-item[0], item[1].path, item[1].line_start, item[1].line_end))
    return [candidate for _, candidate in out[:node_cap]]


# Descriptive alias for callers that prefer the operation-oriented name.
retrieve_graph_candidates = graph_candidates
