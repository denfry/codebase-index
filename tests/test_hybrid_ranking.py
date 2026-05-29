import pytest

from codebase_index.retrieval.pipeline import search


def _rank_of(payload, path) -> int:
    for r in payload["results"]:
        if r["path"] == path:
            return r["rank"]
    return 10**6


CASES = [
    ("where is refresh_access_token implemented", "src/auth/token.py"),
    ("find the User class", "src/models/user.py"),
]


@pytest.mark.parametrize("query,target", CASES)
def test_hybrid_outranks_single_retrievers(seeded_index, query, target):
    conn = seeded_index.conn
    common = dict(limit=10, token_budget=1500, no_fallback=True)
    hybrid = search(conn, query, mode="hybrid", **common)
    fts = search(conn, query, mode="fts", **common)
    sym = search(conn, query, mode="symbol", **common)

    h = _rank_of(hybrid, target)
    assert h <= _rank_of(fts, target)
    assert h <= _rank_of(sym, target)
    assert hybrid["results"][0]["path"] == target


def test_budget_is_enforced(seeded_index):
    payload = search(seeded_index.conn, "token", mode="hybrid",
                     limit=10, token_budget=120, no_fallback=True)
    spent = sum(r["token_est"] for r in payload["results"] if r["snippet"])
    assert spent <= 120


def test_at_least_one_strict_improvement(seeded_index):
    conn = seeded_index.conn
    common = dict(limit=10, token_budget=1500, no_fallback=True)
    hybrid = search(conn, "refresh token access", mode="hybrid", **common)
    fts = search(conn, "refresh token access", mode="fts", **common)
    target = "src/auth/token.py"
    # Hybrid should give the target a strictly higher score due to fused signal
    hybrid_score = next(r["score"] for r in hybrid["results"] if r["path"] == target)
    fts_score = next(r["score"] for r in fts["results"] if r["path"] == target)
    assert hybrid_score > fts_score
    # And rank should be at least as good
    assert _rank_of(hybrid, target) <= _rank_of(fts, target)
