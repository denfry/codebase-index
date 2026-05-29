# tests/test_vector_search.py
from __future__ import annotations

import pytest

from codebase_index.storage import repo

pytest.importorskip("sqlite_vec")


def _seed_vectors(conn, backend):
    """Embed each chunk's content with the fake backend and store it."""
    rows = repo.chunks_for_embedding(conn)
    vecs = backend.embed([r["content"] for r in rows])
    repo.ensure_vec_tables(conn, dim=backend.dim)
    for r, v in zip(rows, vecs):
        repo.upsert_chunk_vector(conn, int(r["id"]), v)
    conn.commit()


def test_vector_candidates_uniform_shape(seeded_index, fake_backend):
    db = seeded_index
    db.enable_vectors()
    _seed_vectors(db.conn, fake_backend)

    from codebase_index.retrieval.searchers import vector_candidates

    cands = vector_candidates(db.conn, "refresh access token", fake_backend, limit=5)
    assert cands and all(c.source == "vector" for c in cands)
    assert any(c.path == "src/auth/token.py" for c in cands)
    assert all(c.content is not None and c.token_est > 0 for c in cands)


def test_vector_candidates_paraphrase_recall(seeded_index, fake_backend):
    db = seeded_index
    db.enable_vectors()
    _seed_vectors(db.conn, fake_backend)

    from codebase_index.retrieval.searchers import vector_candidates

    cands = vector_candidates(db.conn, "renew login credentials", fake_backend, limit=5)
    assert any(c.path == "src/auth/token.py" for c in cands)


def test_pipeline_vector_mode_uses_backend(seeded_index, fake_backend):
    from codebase_index.retrieval.pipeline import search

    db = seeded_index
    db.enable_vectors()
    _seed_vectors(db.conn, fake_backend)

    payload = search(
        db.conn, "renew login credentials", mode="vector", limit=10,
        token_budget=1500, no_fallback=True, backend=fake_backend,
    )
    assert payload["mode"] == "vector"
    assert any(r["path"] == "src/auth/token.py" for r in payload["results"])


def test_pipeline_hybrid_includes_vector_when_backend_present(seeded_index, fake_backend):
    from codebase_index.retrieval.pipeline import search

    db = seeded_index
    db.enable_vectors()
    _seed_vectors(db.conn, fake_backend)

    payload = search(
        db.conn, "how does token refresh work", mode="hybrid", limit=10,
        token_budget=1500, no_fallback=True, backend=fake_backend,
    )
    assert payload["results"]


def test_pipeline_hybrid_without_backend_unchanged(seeded_index):
    from codebase_index.retrieval.pipeline import search

    payload = search(
        seeded_index.conn, "token", mode="hybrid", limit=10,
        token_budget=1500, no_fallback=True,
    )
    assert payload["mode"] == "hybrid" and payload["results"]


def _has(payload, path) -> bool:
    return any(r["path"] == path for r in payload["results"])


def test_vector_improves_recall_over_lexical_only(seeded_index, fake_backend):
    from codebase_index.retrieval.pipeline import search

    db = seeded_index
    db.enable_vectors()
    _seed_vectors(db.conn, fake_backend)

    query = "renew login credentials"
    common = dict(limit=10, token_budget=1500, no_fallback=True)

    lexical = search(db.conn, query, mode="fts", **common)
    semantic = search(db.conn, query, mode="hybrid", backend=fake_backend, **common)

    target = "src/auth/token.py"
    assert not _has(lexical, target)
    assert _has(semantic, target)


def test_disabled_pipeline_identical_to_m4(seeded_index):
    from codebase_index.retrieval.pipeline import search

    common = dict(mode="hybrid", limit=10, token_budget=1500, no_fallback=True)
    a = search(seeded_index.conn, "where is refresh_access_token implemented", **common)
    b = search(
        seeded_index.conn, "where is refresh_access_token implemented",
        backend=None, **common,
    )
    assert a == b
