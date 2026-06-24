from codebase_index.retrieval.pipeline import search


def test_search_payload_shape(seeded_index):
    payload = search(seeded_index.conn, "where is refresh_access_token implemented",
                     mode="hybrid", limit=10, token_budget=1500, no_fallback=False)
    assert payload["intent"] == "locate_impl"
    assert payload["confidence"] in {"high", "medium", "low"}
    assert payload["results"][0]["path"] == "src/auth/token.py"
    assert "recommended_reads" in payload


def test_search_zero_token_budget_uses_intent_default(seeded_index):
    payload = search(seeded_index.conn, "where is refresh_access_token implemented",
                     mode="hybrid", limit=10, token_budget=0, no_fallback=False)

    assert payload["intent"] == "locate_impl"
    assert any(r["snippet"] for r in payload["results"])


def test_low_confidence_emits_fallback(seeded_index):
    payload = search(seeded_index.conn, "nonexistent_symbol_xyz",
                     mode="hybrid", limit=10, token_budget=1500, no_fallback=False)
    assert payload["confidence"] == "low"
    assert payload["fallback_suggestions"]["ripgrep"]


def test_no_fallback_flag_suppresses_suggestions(seeded_index):
    payload = search(seeded_index.conn, "nonexistent_symbol_xyz",
                     mode="hybrid", limit=10, token_budget=1500, no_fallback=True)
    assert payload["fallback_suggestions"] == {}


def test_single_mode_runs_only_one_retriever(seeded_index):
    payload = search(seeded_index.conn, "token", mode="fts",
                     limit=10, token_budget=1500, no_fallback=False)
    assert payload["mode"] == "fts"
    assert payload["results"]


# ── pagination ────────────────────────────────────────────────────────────────

def test_offset_zero_matches_default(seeded_index):
    """offset=0 produces identical results to no offset."""
    default = search(seeded_index.conn, "auth token", mode="hybrid",
                     limit=5, token_budget=1500, no_fallback=True)
    paged = search(seeded_index.conn, "auth token", mode="hybrid",
                   limit=5, token_budget=1500, no_fallback=True, offset=0)
    assert default["results"] == paged["results"]
    assert "pagination" not in default
    assert "pagination" not in paged


def test_offset_returns_different_results(seeded_index):
    """offset > 0 skips leading results."""
    page0 = search(seeded_index.conn, "auth token", mode="hybrid",
                   limit=2, token_budget=1500, no_fallback=True, offset=0)
    page1 = search(seeded_index.conn, "auth token", mode="hybrid",
                   limit=2, token_budget=1500, no_fallback=True, offset=2)
    paths0 = [r["path"] for r in page0["results"]]
    paths1 = [r["path"] for r in page1["results"]]
    # Pages must not start with the same top result (offset shifts the window).
    assert paths0[:1] != paths1[:1]


def test_pagination_metadata_present_on_offset(seeded_index):
    """Pagination block appears when offset > 0 or has_more is True."""
    payload = search(seeded_index.conn, "auth token", mode="hybrid",
                     limit=2, token_budget=1500, no_fallback=True, offset=2)
    assert "pagination" in payload
    assert payload["pagination"]["offset"] == 2
    assert payload["pagination"]["limit"] == 2


def test_pagination_next_offset(seeded_index):
    """next_offset is set when has_more is True, None otherwise."""
    payload = search(seeded_index.conn, "auth", mode="hybrid",
                     limit=1, token_budget=1500, no_fallback=True, offset=0)
    pag = payload.get("pagination")
    if pag and pag["has_more"]:
        assert pag["next_offset"] == 1
    elif pag:
        assert pag["next_offset"] is None


def test_recommended_reads_within_page(seeded_index):
    """recommended_reads only references results in the current page."""
    payload = search(seeded_index.conn, "auth token", mode="hybrid",
                     limit=3, token_budget=1500, no_fallback=True, offset=0)
    result_keys = {(r["path"], r["line_start"], r["line_end"]) for r in payload["results"]}
    for rec in payload["recommended_reads"]:
        assert (rec["path"], rec["line_start"], rec["line_end"]) in result_keys


# ── snippet skeletonization ─────────────────────────────────────────────────

def test_search_skeletonizes_code_by_default(seeded_index):
    # mode=fts so the fts candidate (full body) is not fused with the
    # signature-only symbol candidate; the large ratelimit body is skeletonized.
    payload = search(seeded_index.conn, "ratelimit_bucket_refill", mode="fts",
                     limit=5, token_budget=1500, no_fallback=True)
    assert payload["results"]
    assert any(r.get("skeletonized") for r in payload["results"])


def test_search_compact_false_disables_skeleton(seeded_index):
    payload = search(seeded_index.conn, "ratelimit_bucket_refill", mode="fts",
                     limit=5, token_budget=1500, no_fallback=True, compact=False)
    assert payload["results"]
    assert all(not r.get("skeletonized") for r in payload["results"])
