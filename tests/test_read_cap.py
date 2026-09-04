"""`recommended_reads` entries are capped at `max_read_lines` (additive fields only)."""

from __future__ import annotations

from codebase_index.retrieval.pipeline import _bounded_read


def test_short_entry_is_untouched():
    entry = {"path": "a.py", "line_start": 10, "line_end": 40}
    assert _bounded_read(entry, 120) is entry


def test_long_entry_is_capped_and_annotated():
    entry = {"path": "Big.java", "line_start": 1, "line_end": 1500}
    out = _bounded_read(entry, 120)
    assert out == {
        "path": "Big.java",
        "line_start": 1,
        "line_end": 120,
        "line_end_full": 1500,
        "truncated": True,
    }
    assert entry["line_end"] == 1500, "input must not be mutated"


def test_zero_disables_the_cap():
    entry = {"path": "Big.java", "line_start": 1, "line_end": 1500}
    assert _bounded_read(entry, 0) is entry


def test_search_applies_cap_through_config(tmp_path):
    """End to end on a synthetic file whose only symbol spans 300 lines."""
    from pathlib import Path

    from codebase_index.config import Config
    from codebase_index.indexer.pipeline import build_index
    from codebase_index.retrieval.pipeline import search
    from codebase_index.storage.db import Database

    root = tmp_path / "repo"
    (root / "src").mkdir(parents=True)
    body = "\n".join(f"    x{i} = {i}  # frobnicate widget" for i in range(298))
    (root / "src" / "widget.py").write_text(
        f"class WidgetFrobnicator:\n    '''Frobnicates widgets.'''\n{body}\n", encoding="utf-8"
    )
    cfg = Config(root=str(root))
    cfg.embeddings.enabled = False
    db = Database(tmp_path / "idx.sqlite").open()
    try:
        build_index(cfg, db, root=Path(root))
        # A budget of 1 token guarantees the hit lands in recommended_reads, not a snippet.
        capped = search(db.conn, "WidgetFrobnicator", mode="hybrid", limit=5,
                        token_budget=1, no_fallback=True, max_read_lines=50)
        full = search(db.conn, "WidgetFrobnicator", mode="hybrid", limit=5,
                      token_budget=1, no_fallback=True, max_read_lines=0)
    finally:
        db.close()
    capped_reads = [r for r in capped["recommended_reads"] if r.get("truncated")]
    assert capped_reads, capped["recommended_reads"]
    assert all(r["line_end"] - r["line_start"] + 1 == 50 for r in capped_reads)
    assert not any(r.get("truncated") for r in full["recommended_reads"])
