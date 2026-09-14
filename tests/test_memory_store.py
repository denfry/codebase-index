"""memory.sqlite: schema/migrations, ledger semantics, scoping, GC, recovery, locking."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone

import pytest

from codebase_index.memory.store import (
    SCHEMA_VERSION,
    MemoryStore,
    MemoryUnavailable,
    NewDelivery,
)

NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)


def _item(path="src/a.py", span="s" * 64, snippet="p" * 64, full=True, start=1, end=5, tokens=40):
    return NewDelivery(path=path, span_sha=span, line_count=end - start + 1,
                       first_line_sha="f" * 16, snippet_sha=snippet, full=full,
                       line_start=start, line_end=end, token_est=tokens)


@pytest.fixture
def store(tmp_path):
    with MemoryStore.open(tmp_path / "memory.sqlite") as s:
        yield s


def test_open_creates_current_schema_and_is_idempotent(tmp_path):
    path = tmp_path / "memory.sqlite"
    with MemoryStore.open(path) as s:
        assert s.schema_version == SCHEMA_VERSION
    with MemoryStore.open(path) as s:
        assert s.schema_version == SCHEMA_VERSION
        assert s.recovered_from is None


def test_migrations_run_in_order_inside_transactions(tmp_path):
    path = tmp_path / "memory.sqlite"
    with MemoryStore.open(path):
        pass
    from codebase_index.memory.store import MIGRATIONS

    future = {**MIGRATIONS, 2: ("ALTER TABLE atoms ADD COLUMN note TEXT",)}
    with MemoryStore.open(path, migrations=future, schema_version=2) as s:
        assert s.schema_version == 2
        cols = [r[1] for r in s.conn.execute("PRAGMA table_info(atoms)")]
        assert "note" in cols

    broken = {**MIGRATIONS, 2: ("ALTER TABLE nope ADD COLUMN x TEXT",)}
    other = tmp_path / "other.sqlite"
    with MemoryStore.open(other):
        pass
    with pytest.raises(MemoryUnavailable):
        MemoryStore.open(other, migrations=broken, schema_version=2)
    with MemoryStore.open(other) as s:
        assert s.schema_version == 1  # failed migration rolled back, nothing half-applied


def test_newer_schema_is_refused_without_touching_the_file(tmp_path):
    path = tmp_path / "memory.sqlite"
    with MemoryStore.open(path) as s:
        s.conn.execute("UPDATE meta SET value = '99' WHERE key = 'schema_version'")
    before = path.read_bytes()
    with pytest.raises(MemoryUnavailable, match="newer"):
        MemoryStore.open(path)
    assert path.read_bytes() == before


def test_corrupt_store_is_preserved_and_replaced(tmp_path):
    path = tmp_path / "memory.sqlite"
    path.write_bytes(b"this is not a sqlite database" * 100)
    with MemoryStore.open(path) as s:
        assert s.recovered_from is not None
        assert (tmp_path / s.recovered_from).read_bytes().startswith(b"this is not")
        assert s.schema_version == SCHEMA_VERSION


def test_known_requires_full_span_or_identical_snippet(store):
    sid = store.touch_session("repo", "tag", now=NOW)
    store.record("repo", sid, [_item(full=False, snippet="a" * 64)], now=NOW)
    assert store.is_known(sid, "src/a.py", "s" * 64, "a" * 64)
    assert not store.is_known(sid, "src/a.py", "s" * 64, "b" * 64)   # different skeleton
    store.record("repo", sid, [_item(full=True, snippet="c" * 64)], now=NOW)
    assert store.is_known(sid, "src/a.py", "s" * 64, "b" * 64)       # whole span delivered
    assert not store.is_known(sid, "src/a.py", "t" * 64, "c" * 64)   # other bytes


def test_invalidated_delivery_is_not_known_until_redelivered(store):
    sid = store.touch_session("repo", "tag", now=NOW)
    store.record("repo", sid, [_item()], now=NOW)
    atom_id = store.pending(sid)[0].atom_id
    store.mark_invalid(sid, [(atom_id, "changed")])
    assert not store.is_known(sid, "src/a.py", "s" * 64, "p" * 64)
    assert store.pending(sid) == []
    store.record("repo", sid, [_item()], now=NOW)
    assert store.is_known(sid, "src/a.py", "s" * 64, "p" * 64)


def test_sessions_and_repositories_are_isolated(store):
    a = store.touch_session("repoA", "tag", now=NOW)
    b = store.touch_session("repoB", "tag", now=NOW)
    other = store.touch_session("repoA", "tag2", now=NOW)
    store.record("repoA", a, [_item()], now=NOW)
    assert not store.is_known(b, "src/a.py", "s" * 64, "p" * 64)
    assert not store.is_known(other, "src/a.py", "s" * 64, "p" * 64)
    assert store.find_session("repoB", "missing") is None
    assert store.stats("repoA")["deliveries"] == 1
    assert store.stats("repoB")["deliveries"] == 0


def test_counters_and_stats(store):
    sid = store.touch_session("repo", "tag", now=NOW)
    store.touch_session("repo", "tag", now=NOW)
    store.record("repo", sid, [_item(), _item(path="src/b.py")], now=NOW)
    store.add_counters(sid, tokens_delivered=80, tokens_saved=40, reused=1, invalidations=2)
    stats = store.stats("repo")
    assert stats["sessions"] == 1 and stats["atoms"] == 2 and stats["deliveries"] == 2
    assert (stats["tokens_delivered"], stats["tokens_saved"]) == (80, 40)
    assert (stats["reused"], stats["invalidations"]) == (1, 2)
    assert stats["bytes"] > 0


def test_gc_expires_old_sessions_and_orphan_atoms_but_keeps_recent(store):
    old = store.touch_session("repo", "old", now=NOW - timedelta(days=30))
    new = store.touch_session("repo", "new", now=NOW)
    store.record("repo", old, [_item(path="src/old.py")], now=NOW - timedelta(days=30))
    store.record("repo", new, [_item(path="src/new.py")], now=NOW)
    result = store.gc(now=NOW, retention_days=14, max_deliveries=1000)
    assert result == {"expired_sessions": 1, "capped_sessions": 0, "orphan_atoms": 1}
    assert store.is_known(new, "src/new.py", "s" * 64, "p" * 64)
    assert store.stats("repo")["atoms"] == 1
    assert not store.gc_due(now=NOW)


def test_gc_caps_total_deliveries_by_least_recent_use(store):
    for day in range(5):
        sid = store.touch_session("repo", f"s{day}", now=NOW - timedelta(days=4 - day))
        store.record("repo", sid, [_item(path=f"src/{day}_{i}.py") for i in range(3)],
                     now=NOW)
    result = store.gc(now=NOW, retention_days=365, max_deliveries=7)
    assert result["capped_sessions"] == 3
    assert store.stats("repo")["deliveries"] == 6
    assert store.find_session("repo", "s4") is not None


def test_gc_only_shrinks_what_is_known(store):
    """GC never adds knowledge: every key known after GC was known before it."""
    keys = []
    for day in range(4):
        sid = store.touch_session("repo", f"s{day}", now=NOW - timedelta(days=day * 10))
        store.record("repo", sid, [_item(path=f"src/{day}.py")], now=NOW)
        keys.append((sid, f"src/{day}.py"))
    before = {k for k in keys if store.is_known(k[0], k[1], "s" * 64, "p" * 64)}
    store.gc(now=NOW, retention_days=15, max_deliveries=2)
    after = {k for k in keys if store.is_known(k[0], k[1], "s" * 64, "p" * 64)}
    assert after <= before and len(after) < len(before)


def test_clear_one_session_or_whole_repository(store):
    a = store.touch_session("repo", "a", now=NOW)
    b = store.touch_session("repo", "b", now=NOW)
    elsewhere = store.touch_session("other", "a", now=NOW)
    for sid, repo in ((a, "repo"), (b, "repo"), (elsewhere, "other")):
        store.record(repo, sid, [_item()], now=NOW)
    assert store.clear("repo", "a") == 1
    assert store.find_session("repo", "b") is not None
    assert store.clear("repo") == 1
    assert store.stats("repo")["atoms"] == 0
    assert store.stats("other")["deliveries"] == 1


def test_first_line_hint_by_reference_prefix(store):
    sid = store.touch_session("repo", "tag", now=NOW)
    store.record("repo", sid, [_item(span="abcdef0123456789" + "0" * 48)], now=NOW)
    assert store.first_line_hint("repo", "src/a.py", "abcdef0123456789") == "f" * 16
    assert store.first_line_hint("repo", "src/a.py", "ffff000011112222") is None
    assert store.first_line_hint("other", "src/a.py", "abcdef0123456789") is None


def test_lock_contention_degrades_instead_of_blocking_forever(tmp_path):
    path = tmp_path / "memory.sqlite"
    with MemoryStore.open(path):
        pass
    holder = sqlite3.connect(path, isolation_level=None)
    holder.execute("BEGIN IMMEDIATE")
    try:
        with MemoryStore.open(path, busy_timeout_ms=50) as s:
            with pytest.raises(MemoryUnavailable, match="busy"):
                s.touch_session("repo", "tag", now=NOW)
    finally:
        holder.execute("ROLLBACK")
        holder.close()


def test_store_contains_no_source_text(tmp_path):
    path = tmp_path / "memory.sqlite"
    secret_line = "AWS_SECRET_ACCESS_KEY = 'wJalrXUtnFEMI/K7MDENG/bPxRfiCYEXAMPLEKEY'"
    with MemoryStore.open(path) as s:
        sid = s.touch_session("repo", "tag-sha", now=NOW)
        s.record("repo", sid, [_item()], now=NOW)
        s.conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    blob = b"".join(p.read_bytes() for p in tmp_path.iterdir() if p.is_file())
    assert secret_line.encode() not in blob
    assert b"wJalrXUtnFEMI" not in blob
