"""End-to-end evidence memory through the service layer: retrieve -> persist -> reuse ->
edit -> invalidate. The load-bearing assertions are equivalences with the no-memory
packet, because they are what make every measured saving attributable to memory alone.
"""

from __future__ import annotations

import copy
import sqlite3

import pytest

from codebase_index.config import Config
from codebase_index.indexer.pipeline import build_index, update_index
from codebase_index.retrieval.pipeline import search
from codebase_index.service import search_payload
from codebase_index.storage.db import Database

INVOICE = '''def compute_invoice_total(lines, tax_rate):
    """Sum invoice line amounts and apply the tax rate."""
    subtotal = sum(line.amount for line in lines)
    return round(subtotal * (1 + tax_rate), 2)


def format_invoice_number(prefix, sequence):
    """Render an invoice number such as INV-000042."""
    return f"{prefix}-{sequence:06d}"
'''

REFUND = '''def issue_refund(invoice, amount):
    """Refund part of an invoice total."""
    if amount > invoice.total:
        raise ValueError("refund exceeds invoice total")
    return invoice.total - amount
'''

QUERY = "compute invoice total"


@pytest.fixture
def repo(tmp_path, monkeypatch):
    root = tmp_path / "repo"
    (root / "src" / "billing").mkdir(parents=True)
    (root / "src" / "billing" / "invoice.py").write_text(INVOICE, encoding="utf-8")
    (root / "src" / "billing" / "refund.py").write_text(REFUND, encoding="utf-8")
    monkeypatch.setenv("CBX_MEMORY_PATH", str(tmp_path / "memory.sqlite"))
    monkeypatch.delenv("CBX_MEMORY", raising=False)
    monkeypatch.delenv("CBX_DB_PATH", raising=False)
    cfg = Config()
    cfg.root = str(root)
    db_path = tmp_path / "index.sqlite"
    with Database(db_path) as db:
        build_index(cfg, db, root=root)
    return root, cfg, db_path


def _run(repo, query=QUERY, session=None):
    _root, cfg, db_path = repo
    return search_payload(db_path, cfg, query, mode="hybrid", limit=10, token_budget=1500,
                          no_fallback=False, session=session)


def _baseline(repo, monkeypatch, query=QUERY):
    monkeypatch.setenv("CBX_MEMORY", "0")
    try:
        return _run(repo, query)
    finally:
        monkeypatch.delenv("CBX_MEMORY")


def _update(repo):
    root, cfg, db_path = repo
    with Database(db_path) as db:
        update_index(cfg, db, root=root)


def _notice_states(payload):
    return {n["ref"].rsplit("@", 1)[0].rsplit(":", 1)[0]: n["state"]
            for n in payload["memory"]["invalidated"]}


def test_memory_disabled_is_identical_to_the_retrieval_pipeline(repo, monkeypatch):
    root, cfg, db_path = repo
    monkeypatch.setenv("CBX_MEMORY", "0")
    via_service = _run(repo)
    with Database(db_path) as db:
        direct = search(db.conn, QUERY, mode="hybrid", limit=10, token_budget=1500,
                        no_fallback=False, root=root, config=cfg, compact=True,
                        compact_min_reduction=0.25)
    assert via_service == direct


def test_enabled_without_session_on_a_fresh_index_is_identical(repo, monkeypatch):
    assert _run(repo) == _baseline(repo, monkeypatch)


def test_first_session_call_is_the_baseline_plus_a_memory_block(repo, monkeypatch):
    first = _run(repo, session="t1")
    assert first.pop("memory") == {"session": "t1", "reused": 0, "tokens_saved": 0,
                                   "invalidated": []}
    assert first == _baseline(repo, monkeypatch)


def test_repeat_call_withholds_exactly_what_the_session_already_holds(repo, monkeypatch):
    first = _run(repo, session="t1")
    second = _run(repo, session="t1")
    delivered = [r for r in first["results"] if r["snippet"]]
    assert delivered
    assert [r.get("reused", False) for r in second["results"]] == [
        bool(r["snippet"]) for r in first["results"]
    ]
    assert second["memory"]["reused"] == len(delivered)
    assert second["memory"]["tokens_saved"] == sum(r["token_est"] for r in delivered)

    restored = copy.deepcopy(second)
    restored.pop("memory")
    for result, original in zip(restored["results"], first["results"]):
        if result.pop("reused", False):
            result["snippet"] = original["snippet"]
    assert restored == _baseline(repo, monkeypatch)


def test_another_session_receives_everything(repo, monkeypatch):
    _run(repo, session="t1")
    other = _run(repo, session="t2")
    assert other.pop("memory")["reused"] == 0
    assert other == _baseline(repo, monkeypatch)


def test_changed_evidence_is_reported_once_and_redelivered(repo):
    root, _, _ = repo
    first = _run(repo, session="t1")
    body = next(r for r in first["results"] if r["path"] == "src/billing/refund.py")
    assert "amount > invoice.total" in body["snippet"]
    (root / "src/billing/refund.py").write_text(REFUND.replace(">", ">="), encoding="utf-8")
    _update(repo)
    second = _run(repo, session="t1")
    assert _notice_states(second).get("src/billing/refund.py") == "changed"
    redelivered = next(r for r in second["results"] if r["path"] == "src/billing/refund.py")
    assert "amount >= invoice.total" in redelivered["snippet"]
    assert not redelivered.get("reused")
    # Unchanged evidence in the same packet is still withheld...
    assert any(r.get("reused") for r in second["results"]
               if r["path"] == "src/billing/invoice.py")
    # ...and each invalidation is reported exactly once.
    assert _run(repo, session="t1")["memory"]["invalidated"] == []


def test_unindexed_edit_marks_results_stale_and_never_withholds_them(repo):
    """The index still holds the old body; the snippet is flagged, never trusted or hidden."""
    root, _, _ = repo
    _run(repo, session="t1")
    (root / "src/billing/refund.py").write_text(REFUND.replace(">", ">="), encoding="utf-8")
    second = _run(repo, session="t1")
    stale = [r for r in second["results"] if r.get("stale")]
    assert [r["path"] for r in stale] == ["src/billing/refund.py"]
    assert "amount > invoice.total" in stale[0]["snippet"]
    assert not stale[0].get("reused")
    assert _notice_states(second).get("src/billing/refund.py") == "changed"


def test_excerpt_that_still_holds_is_not_stale(repo):
    """A signature snippet stays accurate when only the body changes, so it is not flagged;
    the span changed, so it is delivered again rather than withheld."""
    root, _, _ = repo
    first = _run(repo, session="t1")
    signature = next(r for r in first["results"] if r["path"] == "src/billing/invoice.py")
    assert signature["snippet"] == "def compute_invoice_total(lines, tax_rate):"
    (root / "src/billing/invoice.py").write_text(INVOICE.replace("round(", "floor("),
                                                 encoding="utf-8")
    second = _run(repo, session="t1")
    again = next(r for r in second["results"] if r["path"] == "src/billing/invoice.py")
    assert not again.get("stale") and not again.get("reused") and again["snippet"]


def test_derived_index_text_is_flagged_only_when_the_file_really_changed(repo, tmp_path):
    """Config-key and section summaries are derived, not copied from the file, so they are
    not byte-verifiable: never recorded or withheld, and flagged stale only when the file's
    bytes differ from what was indexed. (Ranking decides whether such a chunk surfaces, so
    this drives the processor with the exact chunk the index stored.)"""
    from datetime import datetime, timezone
    from types import SimpleNamespace

    from codebase_index.memory import identity as ident
    from codebase_index.memory.session import EvidenceProcessor, Session, index_sha_lookup
    from codebase_index.memory.store import MemoryStore

    root, cfg, db_path = repo
    (root / "config.json").write_text('{"refund": {"window_days": 30}}\n', encoding="utf-8")
    _update(repo)
    derived = "config key: refund.window_days = 30"
    with Database(db_path) as db:
        stored = [r[0] for r in db.conn.execute(
            "SELECT c.content FROM chunks c JOIN files f ON f.id = c.file_id "
            "WHERE f.path = 'config.json' AND c.kind = 'doc'")]
    assert stored == [derived]

    def process(store: MemoryStore, session_id: int) -> dict:
        result = {"rank": 1, "path": "config.json", "line_start": 1, "line_end": 1,
                  "snippet": derived, "token_est": 9, "skeletonized": False}
        repo_id = ident.repo_id_for(root)
        with Database(db_path) as db:
            EvidenceProcessor(
                root=root, config=cfg, now=datetime.now(timezone.utc),
                session=Session(tag="t", repo_id=repo_id, store=store, session_id=session_id),
                index_sha=index_sha_lookup(db.conn),
            )({"results": [result]}, [SimpleNamespace(content=derived)])
        return result

    with MemoryStore.open(tmp_path / "derived.sqlite") as store:
        session_id = store.touch_session("r", "t", now=datetime.now(timezone.utc))
        fresh = process(store, session_id)
        assert "stale" not in fresh and fresh["snippet"] == derived and "reused" not in fresh
        assert store.pending(session_id) == []                      # never recorded
        (root / "config.json").write_text('{"refund": {"window_days": 14}}\n', encoding="utf-8")
        assert process(store, session_id).get("stale") is True


def test_code_that_only_moved_within_its_file_is_still_reused(repo):
    root, _, _ = repo
    first = _run(repo, session="t1")
    target = next(r for r in first["results"] if r["path"] == "src/billing/invoice.py"
                  and r["snippet"] and "def compute_invoice_total" in r["snippet"])
    (root / "src/billing/invoice.py").write_text("import math\nimport decimal\n\n\n" + INVOICE,
                                                 encoding="utf-8")
    _update(repo)
    second = _run(repo, session="t1")
    moved = [r for r in second["results"] if r["path"] == "src/billing/invoice.py"
             and (r["line_start"], r["line_end"]) == (target["line_start"] + 4,
                                                      target["line_end"] + 4)]
    assert moved and moved[0].get("reused") is True and moved[0]["snippet"] is None
    assert second["memory"]["invalidated"] == []


def test_deleted_file_evidence_is_reported(repo):
    root, _, _ = repo
    first = _run(repo, "issue refund exceeds invoice total", session="t1")
    assert any(r["path"] == "src/billing/refund.py" and r["snippet"] for r in first["results"])
    (root / "src/billing/refund.py").unlink()
    _update(repo)
    assert _notice_states(_run(repo, session="t1")).get("src/billing/refund.py") == "deleted"


def test_locked_memory_store_degrades_to_the_full_packet(repo, monkeypatch, tmp_path):
    import codebase_index.memory.store as store_mod

    monkeypatch.setattr(store_mod, "BUSY_TIMEOUT_MS", 50)
    _run(repo, session="t1")
    holder = sqlite3.connect(tmp_path / "memory.sqlite", isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")
    try:
        second = _run(repo, session="t1")
    finally:
        holder.execute("ROLLBACK")
        holder.close()
    block = second.pop("memory")
    assert block["available"] is False and block["reused"] == 0
    assert second == _baseline(repo, monkeypatch)


def test_session_with_memory_disabled_says_so(repo, monkeypatch):
    monkeypatch.setenv("CBX_MEMORY", "0")
    assert _run(repo, session="t1")["memory"] == {
        "session": "t1", "available": False, "reason": "memory is disabled"}


def test_malformed_session_tag_is_rejected(repo):
    with pytest.raises(ValueError):
        _run(repo, session="not a tag!")


def test_session_survives_an_index_rebuild_with_unchanged_sources(repo):
    root, cfg, db_path = repo
    first = _run(repo, session="t1")
    for suffix in ("", "-wal", "-shm"):
        sidecar = db_path.with_name(db_path.name + suffix)
        if sidecar.exists():
            sidecar.unlink()
    with Database(db_path) as db:
        build_index(cfg, db, root=root)
    second = _run(repo, session="t1")
    assert second["memory"]["reused"] == sum(1 for r in first["results"] if r["snippet"])


def test_memory_store_never_contains_delivered_text_or_the_tag(repo, tmp_path):
    first = _run(repo, session="privacy-canary-tag")
    _run(repo, session="privacy-canary-tag")
    blob = b"".join(p.read_bytes() for p in tmp_path.glob("memory.sqlite*"))
    assert b"privacy-canary-tag" not in blob
    for result in first["results"]:
        for line in (result["snippet"] or "").splitlines():
            if len(line.strip()) >= 16:
                assert line.strip().encode() not in blob
