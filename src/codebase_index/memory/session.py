"""Evidence at retrieval time: verify each delivered snippet, reuse it within a session.

`retrieval.pipeline.search` calls the processor after ranking, budgeting and pagination
are final (docs/MEMORY.md). It never adds, removes or reorders a result, and it never
changes which results carry a snippet. It can only:

* mark a result ``stale`` when the index text it came from no longer matches the file;
* in a session, replace a snippet that session already received from byte-identical
  source with ``snippet: null, reused: true``;
* in a session, list evidence the session received earlier that has since changed.

A session tag names exactly one agent context. It is always supplied by the caller —
never inferred from a process, an environment variable or a time window — because none
of those identify what an agent still holds in its context window.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterator, Optional, Sequence, Union

from ..config import Config
from ..discovery.gates import PathGate
from . import identity as ident
from .store import MemoryStore, MemoryUnavailable, NewDelivery, utc_now
from .validate import WorkingTree, validate


@dataclass
class Session:
    tag: str
    repo_id: str
    store: Optional[MemoryStore] = None
    session_id: Optional[int] = None
    unavailable: Optional[str] = None

    @property
    def usable(self) -> bool:
        return self.store is not None and self.session_id is not None and not self.unavailable


IndexSha = Callable[[str], Optional[str]]
_STALE = "stale"


def index_sha_lookup(conn: sqlite3.Connection) -> IndexSha:
    """``files.sha256`` by path, cached for one call: the fingerprint the index was built from."""
    from ..storage import repo

    cache: dict[str, Optional[str]] = {}

    def lookup(rel: str) -> Optional[str]:
        if rel not in cache:
            row = repo.get_file(conn, rel)
            cache[rel] = row["sha256"] if row else None
        return cache[rel]

    return lookup


class EvidenceProcessor:
    def __init__(self, *, root: Path, config: Config, now: datetime,
                 session: Optional[Session] = None,
                 index_sha: Optional[IndexSha] = None) -> None:
        self.tree = WorkingTree(PathGate(root, config))
        self.config = config
        self.now = now
        self.session = session
        self.index_sha = index_sha

    def __call__(self, payload: dict, candidates: Sequence[Any]) -> None:
        session = self.session
        notices = self._notices(session) if session is not None and session.usable else []
        reused = tokens_saved = tokens_delivered = 0
        fresh: list[NewDelivery] = []

        for result, candidate in zip(payload.get("results", []), candidates):
            snippet = result.get("snippet")
            if not snippet:
                continue  # nothing was delivered for this result
            observed = self._observe(result, candidate)
            if isinstance(observed, str):  # _STALE
                result["stale"] = True
                continue
            if observed is None or session is None or not session.usable:
                continue  # derived index text is accurate but not byte-verifiable: never withheld
            rel, span, span_sha = observed
            tokens = int(result.get("token_est") or 0)
            snippet_sha = ident.sha_hex(snippet)
            if self._known(session, rel, span_sha, snippet_sha):
                result["snippet"] = None
                result["reused"] = True
                reused += 1
                tokens_saved += tokens
                continue
            fresh.append(
                NewDelivery(
                    path=rel,
                    span_sha=span_sha,
                    line_count=int(result["line_end"]) - int(result["line_start"]) + 1,
                    first_line_sha=ident.line_sha(span.split("\n", 1)[0]),
                    snippet_sha=snippet_sha,
                    full=not result.get("skeletonized")
                    and ident.is_full_span(getattr(candidate, "content", None), span),
                    line_start=int(result["line_start"]),
                    line_end=int(result["line_end"]),
                    token_est=tokens,
                )
            )
            tokens_delivered += tokens

        if session is not None:
            payload["memory"] = self._finish(
                session, fresh, notices,
                reused=reused, tokens_saved=tokens_saved, tokens_delivered=tokens_delivered,
            )

    def _observe(self, result: dict, candidate: Any) -> Union[tuple[str, str, str], str, None]:
        """Classify one delivered snippet against the working tree.

        * ``(path, span text, span sha)`` — the snippet is text these exact lines hold now;
        * ``"stale"`` — the file is gone, excluded, or its bytes differ from what was indexed;
        * ``None`` — the index is current for this file but its text was derived (config-key
          and section summaries), so it cannot be checked byte-for-byte.
        """
        try:
            rel = ident.normalize_rel_path(str(result["path"]))
        except ValueError:
            return _STALE
        view, _state, _reason = self.tree.view(rel)
        if view is None:
            return _STALE
        span = ident.span_text(view.lines, int(result["line_start"]), int(result["line_end"]))
        if span is not None and ident.content_matches(getattr(candidate, "content", None), span):
            return rel, span, ident.sha_hex(span)
        if self.index_sha is None:
            return None
        return None if self.index_sha(rel) == view.sha256 else _STALE

    def _known(self, session: Session, rel: str, span_sha: str, snippet_sha: str) -> bool:
        assert session.store is not None and session.session_id is not None
        try:
            return session.store.is_known(session.session_id, rel, span_sha, snippet_sha)
        except sqlite3.Error as exc:
            session.unavailable = f"memory store unavailable: {exc}"
            return False

    def _notices(self, session: Session) -> list[dict]:
        assert session.store is not None and session.session_id is not None
        try:
            pending = session.store.pending(session.session_id)
        except sqlite3.Error as exc:
            session.unavailable = f"memory store unavailable: {exc}"
            return []
        notices: list[dict] = []
        states: list[tuple[int, str]] = []
        for delivery in pending:
            ref = ident.EvidenceRef(delivery.path, delivery.line_start, delivery.line_end,
                                    delivery.span_sha)
            verdict = validate(ref, self.tree, first_line_sha=delivery.first_line_sha)
            if not verdict.valid:
                states.append((delivery.atom_id, verdict.state))
                notices.append({"ref": str(ref), "state": verdict.state})
        if states:
            try:
                session.store.mark_invalid(session.session_id, states)
            except (MemoryUnavailable, sqlite3.Error) as exc:
                session.unavailable = str(exc)
        return notices

    def _finish(self, session: Session, fresh: list[NewDelivery], notices: list[dict], *,
                reused: int, tokens_saved: int, tokens_delivered: int) -> dict:
        block: dict = {
            "session": session.tag,
            "reused": reused,
            "tokens_saved": tokens_saved,
            "invalidated": notices,
        }
        if not session.usable:
            block["available"] = False
            block["reason"] = session.unavailable or "memory store unavailable"
            return block
        store = session.store
        assert store is not None and session.session_id is not None
        try:
            store.record(session.repo_id, session.session_id, fresh, now=self.now)
            store.add_counters(
                session.session_id, tokens_delivered=tokens_delivered,
                tokens_saved=tokens_saved, reused=reused, invalidations=len(notices),
            )
            if store.gc_due(now=self.now):
                store.gc(now=self.now, retention_days=self.config.memory.retention_days,
                         max_deliveries=self.config.memory.max_deliveries)
        except (MemoryUnavailable, sqlite3.Error) as exc:
            # The packet is already correct; only future withholding is affected.
            block["degraded"] = str(exc)
        return block


@contextmanager
def open_evidence(*, root: Path, config: Config, memory_path: Path, tag: Optional[str],
                  now: Optional[datetime] = None,
                  index_conn: Optional[sqlite3.Connection] = None) -> Iterator[EvidenceProcessor]:
    """Processor for one retrieval call; opens the store only when a session is named."""
    now = now or utc_now()
    session: Optional[Session] = None
    store: Optional[MemoryStore] = None
    if tag is not None:
        repo_id = ident.repo_id_for(root)
        session = Session(tag=tag, repo_id=repo_id)
        try:
            store = MemoryStore.open(memory_path)
            session.store = store
            session.session_id = store.touch_session(
                repo_id, ident.session_key(repo_id, tag), now=now
            )
        except (MemoryUnavailable, sqlite3.Error) as exc:
            session.unavailable = str(exc)
    try:
        yield EvidenceProcessor(
            root=Path(root), config=config, now=now, session=session,
            index_sha=index_sha_lookup(index_conn) if index_conn is not None else None,
        )
    finally:
        if store is not None:
            store.close()
