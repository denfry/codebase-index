from codebase_index.retrieval.pipeline import search


def test_search_payload_shape(seeded_index):
    payload = search(seeded_index.conn, "where is refresh_access_token implemented",
                     mode="hybrid", limit=10, token_budget=1500, no_fallback=False)
    assert payload["intent"] == "locate_impl"
    assert payload["confidence"] in {"high", "medium", "low"}
    assert payload["results"][0]["path"] == "src/auth/token.py"
    assert "recommended_reads" in payload


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
