"""Correctness tests for the NUCLEUS prototype.

Run explicitly (not part of the product suite, which is scoped to `tests/`):

    python -m pytest research/test_nucleus.py --no-cov -q

The first test is the load-bearing one. Every headline delta in
`research/experiments.md` is "NUCLEUS vs the shipped pipeline", which is only a valid
attribution if NUCLEUS with accretion disabled *is* the shipped pipeline. If that
equivalence ever breaks, the benchmark is measuring an unrelated reimplementation and
the numbers mean nothing.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from codebase_index.retrieval.pipeline import search
from research.nucleus.relations import (
    CoChangeModel, RelationGraph, core_stem, is_testish, load_static_edges, stem_tokens,
)
from research.nucleus.search import NucleusParams, ObligationIndex, nucleus_search

INDEX = Path(__file__).parent / "data" / "index" / "codebase-index.sqlite"

QUERIES = [
    "redact secrets before output",
    "incremental index update",
    "graph edge confidence",
    "token budget for snippets",
    "fuzzy symbol matching",
]


requires_index = pytest.mark.skipif(
    not INDEX.exists(), reason="run research/build_indexes.py first"
)


@pytest.fixture()
def conn():
    c = sqlite3.connect(INDEX)
    c.row_factory = sqlite3.Row
    yield c
    c.close()


@requires_index
@pytest.mark.parametrize("q", QUERIES)
def test_accretion_off_reproduces_shipped_pipeline(conn, q):
    """NUCLEUS(accrete=False) must equal codebase_index's own search(), result by result."""
    theirs = search(conn, q, mode="hybrid", limit=10, token_budget=1500,
                    no_fallback=True, explain=False)
    ours = nucleus_search(conn, q, limit=10, token_budget=1500,
                          params=NucleusParams(accrete=False))

    def shape(payload):
        return [
            (r["path"], r["line_start"], r["line_end"], r["token_est"],
             (r.get("snippet") or "")[:200])
            for r in payload["results"]
        ]

    assert shape(ours) == shape(theirs)
    assert ours["intent"] == theirs["intent"]
    assert ours["confidence"] == theirs["confidence"]


@requires_index
def test_accretion_changes_the_page(conn):
    """Sanity: with a relation graph present, accretion actually does something."""
    files = [r[0].replace("\\", "/") for r in conn.execute("SELECT path FROM files")]
    graph = RelationGraph(files, static=load_static_edges(INDEX),
                          cochange=CoChangeModel(commits=[]))
    obl = ObligationIndex(conn)
    changed = 0
    for q in QUERIES:
        off = nucleus_search(conn, q, limit=10, token_budget=1500,
                             params=NucleusParams(accrete=False))
        on = nucleus_search(conn, q, limit=10, token_budget=1500, graph=graph,
                            obligations=obl, params=NucleusParams())
        if [r["path"] for r in off["results"]] != [r["path"] for r in on["results"]]:
            changed += 1
    assert changed > 0, "accretion never altered any page — the graph is not wired in"


@requires_index
def test_anchor_head_is_never_displaced(conn):
    """The design's central safety property, asserted rather than asserted-in-prose.

    A completion may only take a slot a lower-ranked baseline result would have held.
    If this fails, NUCLEUS has reintroduced exactly the failure mode that made this
    repository ship `graph_source = False`.
    """
    files = [r[0].replace("\\", "/") for r in conn.execute("SELECT path FROM files")]
    graph = RelationGraph(files, static=load_static_edges(INDEX),
                          cochange=CoChangeModel(commits=[]))
    obl = ObligationIndex(conn)
    params = NucleusParams()
    for q in QUERIES:
        off = nucleus_search(conn, q, limit=10, token_budget=1500,
                             params=NucleusParams(accrete=False))
        on = nucleus_search(conn, q, limit=10, token_budget=1500, graph=graph,
                            obligations=obl, params=params)
        head = params.anchor_head
        assert [r["path"] for r in on["results"][:head]] == \
               [r["path"] for r in off["results"][:head]]


def test_cochange_model_refuses_lookahead():
    """The no-lookahead guarantee is a property of the data structure, not a habit."""
    m = CoChangeModel(commits=[(5, ["a.py", "b.py"]), (3, ["a.py", "c.py"])])
    m.advance_to(4)
    assert m.confidence("a.py", "b.py") > 0        # commit at position 5 is older
    assert m.confidence("a.py", "c.py") == 0.0     # position 3 is newer, must be unseen
    with pytest.raises(ValueError):
        m.advance_to(9)                            # rewinding would reveal the future


def test_relation_primitives():
    assert core_stem("tests/test_service.py") == "service"
    assert core_stem("src/Service.java") == "service"
    assert is_testish("tests/test_service.py")
    assert not is_testish("src/service.py")
    assert "service" in stem_tokens("src/user_service.py")
    assert "user" in stem_tokens("src/UserService.java")
