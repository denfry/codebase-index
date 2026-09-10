"""Signature test for 2.0: a query-keyed cache serves a stale fact; evidence memory cannot.

    T0  an agent learns fact X (sessions last 3600 s) from evidence E
    T1  an unrelated commit lands               -> E is still true: both reuse it
    T2  E changes (sessions now last 900 s)
    T3  a semantically similar question is asked
        query-keyed cache  -> similar question, cache hit, serves X = 3600 (stale)
        evidence memory    -> E's bytes changed: reports E invalid, delivers 900

Deterministic: real git history, a token-overlap similarity for the cache, no model.
"""

from __future__ import annotations

import re
import subprocess
from pathlib import Path

from codebase_index.config import Config
from codebase_index.indexer.pipeline import build_index, update_index
from codebase_index.service import search_payload, verify_payload
from codebase_index.storage.db import Database

POLICY = '''"""Session lifetime policy."""

SESSION_TTL_SECONDS = 3600  # idle login session lifetime in seconds
'''
BILLING = "def invoice_total(lines):\n    return sum(lines)\n"


class QueryKeyedCache:
    """What a semantic cache does: reuse an answer when the question looks similar."""

    def __init__(self, threshold: float = 0.5) -> None:
        self.threshold = threshold
        self.entries: list[tuple[set[str], dict]] = []

    @staticmethod
    def _words(query: str) -> set[str]:
        return set(re.findall(r"[a-z0-9]+", query.lower()))

    def get(self, query: str):
        words = self._words(query)
        for key, packet in self.entries:
            if len(words & key) / len(words | key) >= self.threshold:
                return packet
        return None

    def put(self, query: str, packet: dict) -> None:
        self.entries.append((self._words(query), packet))


def _git(root: Path, *args: str) -> None:
    subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com",
                    "-c", "core.autocrlf=false", "-C", str(root), *args],
                   check=True, capture_output=True)


def _policy_text(packet: dict) -> str:
    return "\n".join(r["snippet"] or "" for r in packet["results"]
                     if r["path"] == "auth/policy.py")


def test_query_keyed_cache_goes_stale_where_evidence_memory_does_not(tmp_path, monkeypatch):
    for var in ("CBX_DB_PATH", "CBX_MEMORY", "CBX_ROOT"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("CBX_MEMORY_PATH", str(tmp_path / "memory.sqlite"))
    root = tmp_path / "repo"
    (root / "auth").mkdir(parents=True)
    (root / "billing").mkdir()
    (root / "auth" / "policy.py").write_bytes(POLICY.encode())
    (root / "billing" / "invoice.py").write_bytes(BILLING.encode())
    _git(root, "init", "-q")
    _git(root, "add", "-A")
    _git(root, "commit", "-q", "-m", "initial")
    cfg = Config()
    cfg.root = str(root)
    db_path = tmp_path / "index.sqlite"
    with Database(db_path) as db:
        build_index(cfg, db, root=root)

    def update() -> None:
        with Database(db_path) as db:
            update_index(cfg, db, root=root)

    def ask(query: str) -> dict:
        return search_payload(db_path, cfg, query, mode="hybrid", limit=10, token_budget=1500,
                              no_fallback=False, session="agent")

    cache = QueryKeyedCache()

    # T0 — learn X from E
    t0_query = "session ttl seconds lifetime"
    t0 = ask(t0_query)
    assert "3600" in _policy_text(t0)
    cache.put(t0_query, t0)

    # T1 — unrelated commit: E still holds, so reuse is correct for both designs
    (root / "billing" / "invoice.py").write_bytes(BILLING.replace("sum(lines)", "sum(lines, 0)").encode())
    _git(root, "commit", "-q", "-am", "unrelated billing change")
    update()
    t1 = ask(t0_query)
    assert t1["memory"]["invalidated"] == []
    assert any(r.get("reused") for r in t1["results"] if r["path"] == "auth/policy.py")
    assert cache.get(t0_query) is t0

    # T2 — E changes: the fact is no longer true
    (root / "auth" / "policy.py").write_bytes(POLICY.replace("3600", "900").encode())
    _git(root, "commit", "-q", "-am", "shorten sessions")
    update()

    # T3 — a semantically similar question
    t3_query = "session ttl lifetime in seconds"
    cached = cache.get(t3_query)
    assert cached is not None, "the cache must consider these questions similar"
    assert "3600" in _policy_text(cached)            # the cache serves the stale fact
    assert "900" in (root / "auth" / "policy.py").read_text()

    t3 = ask(t3_query)
    assert "900" in _policy_text(t3) and "3600" not in _policy_text(t3)
    assert not any(r.get("reused") for r in t3["results"] if r["path"] == "auth/policy.py")
    stale_refs = [n for n in t3["memory"]["invalidated"] if n["ref"].startswith("auth/policy.py:")]
    assert [n["state"] for n in stale_refs] == ["changed"]
    assert verify_payload(cfg, [stale_refs[0]["ref"]])["evidence"][0]["state"] == "changed"
