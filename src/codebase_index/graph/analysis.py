"""Architecture analytics over the resolved edge graph — zero external deps.

This is the codebase-index take on graphify's community detection / god nodes /
surprising connections, implemented in pure, deterministic Python so the core
install stays dependency-free and the results are stable across runs (which
matters for the golden-snapshot tests and CI).

What it computes from the in-memory adjacency of resolved edges:

  * communities  - label propagation groups tightly-connected nodes into
                   "modules". Deterministic: nodes are visited in a fixed key
                   order and ties break to the smallest label, so the same graph
                   always yields the same partition.
  * god nodes    - the most-connected nodes (weighted degree). These are the
                   symbols/files most of the codebase leans on.
  * surprising   - edges that bridge two otherwise weakly-connected communities.
                   The cross-module links you would not think to look for.
  * questions    - template-generated starting questions seeded from the god
                   nodes and the bridges, mirroring graphify's GRAPH_REPORT.

The summary is cached in meta['graph_analysis'] by refresh_analysis() at build
time; the `architecture` command and HTML export read it back instantly.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from typing import Any, Optional

from ..storage import repo

# How many items to keep in the cached summary. Bounded so the meta JSON stays
# small even on very large repos.
MAX_GOD_NODES = 20
MAX_SURPRISING = 12
MAX_QUESTIONS = 8
TOP_NODES_PER_COMMUNITY = 5
MAX_COMMUNITIES_IN_SUMMARY = 40
# A community smaller than this is noise for reporting (isolated/leaf nodes).
MIN_REPORTED_COMMUNITY = 2
# A pair of communities joined by at most this many edges is a "bridge".
BRIDGE_MAX_EDGES = 2
# Cap on local-move passes; the partition almost always settles in 2-4.
_LOCAL_MOVE_PASSES = 20

ANALYSIS_META_KEY = "graph_analysis"

Node = tuple[str, int]  # (kind, id)


# ---------------------------------------------------------------------------
# Graph construction
# ---------------------------------------------------------------------------

def build_adjacency(
    edges: list[sqlite3.Row],
    key_fn=None,
) -> tuple[dict[Any, Counter], dict[tuple[Any, Any], int]]:
    """Undirected weighted adjacency + per-edge multiplicity, from resolved edges.

    Self-loops are dropped (they distort degree and never bridge communities).

    ``key_fn(kind, id) -> hashable | None`` maps an edge endpoint to a node key
    (returning None drops the edge). analyze() passes a *content* key
    (kind:path:name:line) so the partition is identical across platforms — symbol
    ids depend on file-walk order, which differs between OSes. The default keys by
    (kind, id), used by the algorithm unit tests.
    """
    def kf(kind: str, nid: int):
        return key_fn(kind, nid) if key_fn is not None else (kind, nid)

    adj: dict[Any, Counter] = defaultdict(Counter)
    edge_weight: dict[tuple[Any, Any], int] = defaultdict(int)
    for e in edges:
        src = kf(e["src_kind"], int(e["src_id"]))
        dst = kf(e["dst_kind"], int(e["dst_id"]))
        if src is None or dst is None or src == dst:
            continue
        adj[src][dst] += 1
        adj[dst][src] += 1
        edge_weight[_canonical_pair(src, dst)] += 1
    return adj, edge_weight


def _canonical_pair(a: Any, b: Any) -> tuple[Any, Any]:
    return (a, b) if a <= b else (b, a)


# The graph algorithms below are generic over the node-key type: analyze() calls
# them with (kind, id) tuples; the HTML/interop export reuses them with string
# keys. Typing the key as Any keeps both call sites valid.
def weighted_degree(adj: dict[Any, Counter]) -> dict[Any, int]:
    return {node: sum(neighbors.values()) for node, neighbors in adj.items()}


# ---------------------------------------------------------------------------
# Community detection — deterministic label propagation
# ---------------------------------------------------------------------------

def detect_communities(adj: dict[Any, Counter]) -> dict[Any, int]:
    """Partition nodes into communities by greedy modularity. Returns {node: id}.

    This is the local-moving phase of the Louvain method, made deterministic:
    every node starts alone, then in a fixed key order each node moves to the
    neighbouring community that yields the largest modularity gain (ties break to
    the smallest community id). Passes repeat until no node moves. Unlike label
    propagation it does not collapse two cliques joined by a single bridge — the
    bridge's gain cannot beat the dense intra-clique structure. Labels are
    renumbered to dense, size-ranked ids so community 0 is always the largest.
    """
    nodes = sorted(adj.keys())
    if not nodes:
        return {}

    deg = weighted_degree(adj)
    two_m = sum(deg.values())  # = 2 * total edge weight
    if two_m == 0:
        return _renumber_by_size({node: idx for idx, node in enumerate(nodes)})

    comm: dict[Any, int] = {node: idx for idx, node in enumerate(nodes)}
    # Σ_tot per community: total weighted degree of its members.
    sigma_tot: dict[int, int] = {idx: deg[node] for idx, node in enumerate(nodes)}

    for _ in range(_LOCAL_MOVE_PASSES):
        moved = False
        for node in nodes:
            ki = deg[node]
            ci = comm[node]
            # Detach node from its current community.
            sigma_tot[ci] -= ki

            # Weight from node into each neighbouring community.
            links: Counter = Counter()
            for neighbor, w in adj[node].items():
                if neighbor != node:
                    links[comm[neighbor]] += w

            # Pick the community maximising  w_in - Σ_tot * k_i / (2m).
            # Baseline = staying isolated (its own now-empty community), gain 0.
            best_c = ci
            best_gain = links.get(ci, 0) - sigma_tot[ci] * ki / two_m
            for c, w_in in sorted(links.items()):
                gain = w_in - sigma_tot[c] * ki / two_m
                if gain > best_gain + 1e-12:
                    best_gain, best_c = gain, c

            comm[node] = best_c
            sigma_tot[best_c] += ki
            if best_c != ci:
                moved = True
        if not moved:
            break

    return _renumber_by_size(comm)


def _renumber_by_size(label: dict[Any, int]) -> dict[Any, int]:
    """Renumber raw labels to dense ids ordered by community size (desc), then by
    smallest member key — so the mapping is stable run to run."""
    members: dict[int, list[Any]] = defaultdict(list)
    for node, lbl in label.items():
        members[lbl].append(node)
    order = sorted(members, key=lambda lbl: (-len(members[lbl]), min(members[lbl])))
    remap = {old: new for new, old in enumerate(order)}
    return {node: remap[lbl] for node, lbl in label.items()}


def modularity(adj: dict[Any, Counter], communities: dict[Any, int]) -> float:
    """Newman modularity Q of the partition — a quality score in roughly [-0.5, 1].

    Higher means the communities capture more edge density than chance. Reported
    so the user can judge how meaningful the module split is.
    """
    m2 = sum(sum(neighbors.values()) for neighbors in adj.values())  # = 2 * |E|
    if m2 == 0:
        return 0.0
    deg = weighted_degree(adj)
    q = 0.0
    for node, neighbors in adj.items():
        ci = communities[node]
        for neighbor, weight in neighbors.items():
            if communities[neighbor] == ci:
                q += weight - deg[node] * deg[neighbor] / m2
    return round(q / m2, 4)


# ---------------------------------------------------------------------------
# Node labelling
# ---------------------------------------------------------------------------

def _node_index(conn: sqlite3.Connection) -> dict[Node, dict]:
    """(kind, id) -> display metadata {kind, name, path, degree fields}."""
    rows = repo.all_graph_nodes(conn)
    index: dict[Node, dict] = {}
    for f in rows["file"]:
        index[("file", int(f["id"]))] = {
            "kind": "file",
            "name": f["path"].rsplit("/", 1)[-1],
            "path": f["path"],
        }
    for s in rows["symbol"]:
        index[("symbol", int(s["id"]))] = {
            "kind": "symbol",
            "name": s["name"],
            "symbol_kind": s["kind"],
            "path": s["path"],
            "line_start": s["line_start"],
            "in_degree": int(s["in_degree"]),
            "out_degree": int(s["out_degree"]),
        }
    return index


def _stable_key(meta: dict) -> str:
    """A platform-stable node key from content, not from the volatile symbol id.

    Symbol ids are assigned in file-walk order, which differs across OSes; keying
    the graph by path/name/line keeps communities and god-node ranking identical
    everywhere (so the golden snapshots hold on Linux/macOS/Windows alike).
    """
    if meta["kind"] == "file":
        return f"file::{meta['path']}"
    return f"symbol::{meta['path']}::{meta['name']}::{meta.get('line_start', '')}"


def _dir_of(path: str) -> str:
    return path.rsplit("/", 1)[0] if "/" in path else "(root)"


def _is_test_path(path: str) -> bool:
    """Test files cluster with the code they exercise; don't let them name the module."""
    lower = path.lower()
    parts = lower.split("/")
    if any(p in ("test", "tests", "__tests__", "spec", "specs") for p in parts):
        return True
    base = parts[-1]
    return base.startswith("test_") or base.startswith("test.") or "_test." in base or ".test." in base


def label_community(members: list[Any], node_index: dict[Any, dict]) -> str:
    """Name a community by the directory most of its (non-test) nodes live in.

    A 2-5 word, plain-language module name is what graphify asks an LLM for; here
    we derive it deterministically from the dominant source directory, which for
    code is a strong proxy for "what this module is". Test paths are discounted so
    a cluster of production symbols isn't mislabelled "tests" just because its test
    files outnumber it; a community that is *only* tests still gets named for them.
    """
    prod: Counter = Counter()
    allp: Counter = Counter()
    for node in members:
        meta = node_index.get(node)
        if not (meta and meta.get("path")):
            continue
        d = _dir_of(meta["path"])
        allp[d] += 1
        if not _is_test_path(meta["path"]):
            prod[d] += 1
    dirs = prod or allp
    if not dirs:
        return "module"
    # Most common dir; tie -> shortest then lexicographically smallest (stable).
    top = min(dirs.items(), key=lambda kv: (-kv[1], len(kv[0]), kv[0]))
    return top[0]


# ---------------------------------------------------------------------------
# God nodes / surprising connections / questions
# ---------------------------------------------------------------------------

def god_nodes(
    adj: dict[Any, Counter],
    communities: dict[Any, int],
    node_index: dict[Any, dict],
    *,
    limit: int = MAX_GOD_NODES,
) -> list[dict]:
    """Most-connected nodes by weighted degree (the load-bearing ones)."""
    deg = weighted_degree(adj)
    ranked = sorted(deg, key=lambda n: (-deg[n], str(n)))
    out: list[dict] = []
    for node in ranked[:limit]:
        meta = node_index.get(node)
        if meta is None:
            continue
        out.append(
            {
                "kind": meta["kind"],
                "name": meta["name"],
                "path": meta.get("path"),
                "degree": deg[node],
                "community": communities.get(node, -1),
            }
        )
    return out


def surprising_connections(
    edge_weight: dict[tuple[Any, Any], int],
    communities: dict[Any, int],
    node_index: dict[Any, dict],
    *,
    limit: int = MAX_SURPRISING,
) -> list[dict]:
    """Edges that bridge two communities barely connected to each other.

    For each unordered community pair we count how many edges cross between them;
    a pair joined by only a handful of edges is a surprising structural link. We
    surface the actual endpoint pair for each such bridge.
    """
    pair_edges: dict[tuple[int, int], list[tuple[Any, Any]]] = defaultdict(list)
    for (a, b), _w in edge_weight.items():
        ca, cb = communities.get(a, -1), communities.get(b, -1)
        if ca == cb or ca < 0 or cb < 0:
            continue
        key = (ca, cb) if ca < cb else (cb, ca)
        pair_edges[key].append((a, b))

    bridges = [
        (pair, endpoints)
        for pair, endpoints in pair_edges.items()
        if len(endpoints) <= BRIDGE_MAX_EDGES
    ]
    # Rarest bridges first (a single edge between modules is the most surprising),
    # then by community-pair id for stability.
    bridges.sort(key=lambda item: (len(item[1]), item[0]))

    out: list[dict] = []
    for (ca, cb), endpoints in bridges[:limit]:
        a, b = sorted(endpoints)[0]
        ma, mb = node_index.get(a), node_index.get(b)
        if ma is None or mb is None:
            continue
        out.append(
            {
                "from": {"kind": ma["kind"], "name": ma["name"], "path": ma.get("path")},
                "to": {"kind": mb["kind"], "name": mb["name"], "path": mb.get("path")},
                "from_community": ca,
                "to_community": cb,
                "edge_count": len(endpoints),
            }
        )
    return out


def suggest_questions(
    gods: list[dict],
    surprising: list[dict],
    community_labels: dict[int, str],
    *,
    limit: int = MAX_QUESTIONS,
) -> list[str]:
    """Starter questions seeded from the structure, like graphify's report."""
    questions: list[str] = []
    for g in gods[:3]:
        if g["kind"] == "symbol":
            questions.append(f"How does `{g['name']}` work?")
            questions.append(f"What breaks if `{g['name']}` changes?")
        else:
            questions.append(f"What is the role of `{g['name']}` in the architecture?")
    for s in surprising[:3]:
        la = community_labels.get(s["from_community"], f"community {s['from_community']}")
        lb = community_labels.get(s["to_community"], f"community {s['to_community']}")
        if la != lb:
            questions.append(f"How is `{la}` connected to `{lb}`?")
    # De-dup, preserve order.
    seen: set[str] = set()
    deduped: list[str] = []
    for q in questions:
        if q not in seen:
            seen.add(q)
            deduped.append(q)
    return deduped[:limit]


# ---------------------------------------------------------------------------
# Top-level entry points
# ---------------------------------------------------------------------------

def analyze(conn: sqlite3.Connection) -> dict:
    """Compute the full architecture-analytics summary (does not persist it)."""
    edges = repo.all_resolved_edges(conn)
    id_index = _node_index(conn)  # (kind, id) -> meta

    # Key the graph by stable content keys, not by volatile symbol ids, so the
    # result is identical across platforms. node_index then maps that stable key
    # back to display metadata.
    node_index: dict[str, dict] = {}

    def key_fn(kind: str, nid: int):
        meta = id_index.get((kind, nid))
        if meta is None:
            return None
        k = _stable_key(meta)
        node_index.setdefault(k, meta)
        return k

    adj, edge_weight = build_adjacency(edges, key_fn)

    communities = detect_communities(adj)
    members: dict[int, list[str]] = defaultdict(list)
    for node, cid in communities.items():
        members[cid].append(node)

    community_labels = {cid: label_community(nodes, node_index) for cid, nodes in members.items()}
    deg = weighted_degree(adj)

    community_summaries: list[dict] = []
    reported = sorted(members, key=lambda cid: (-len(members[cid]), cid))
    for cid in reported:
        nodes = members[cid]
        if len(nodes) < MIN_REPORTED_COMMUNITY:
            continue
        top = sorted(nodes, key=lambda n: (-deg.get(n, 0), str(n)))[:TOP_NODES_PER_COMMUNITY]
        community_summaries.append(
            {
                "id": cid,
                "label": community_labels[cid],
                "size": len(nodes),
                "top_nodes": [
                    {
                        "kind": node_index[n]["kind"],
                        "name": node_index[n]["name"],
                        "path": node_index[n].get("path"),
                        "degree": deg.get(n, 0),
                    }
                    for n in top
                    if n in node_index
                ],
            }
        )
        if len(community_summaries) >= MAX_COMMUNITIES_IN_SUMMARY:
            break

    gods = god_nodes(adj, communities, node_index)
    surprising = surprising_connections(edge_weight, communities, node_index)
    questions = suggest_questions(gods, surprising, community_labels)

    return {
        "node_count": len(adj),
        "edge_count": sum(edge_weight.values()),
        "community_count": sum(1 for nodes in members.values() if len(nodes) >= MIN_REPORTED_COMMUNITY),
        "modularity": modularity(adj, communities),
        "communities": community_summaries,
        "god_nodes": gods,
        "surprising": surprising,
        "questions": questions,
    }


def refresh_analysis(conn: sqlite3.Connection) -> dict:
    """Compute and cache the analysis summary into meta['graph_analysis']."""
    summary = analyze(conn)
    repo.set_meta(conn, ANALYSIS_META_KEY, json.dumps(summary, ensure_ascii=False))
    return summary


def load_analysis(conn: sqlite3.Connection) -> Optional[dict]:
    """Read the cached analysis summary, or None if the build never produced one."""
    raw = repo.get_meta(conn, ANALYSIS_META_KEY)
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (ValueError, TypeError):
        return None
