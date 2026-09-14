"""Persistent evidence memory: ``memory.sqlite``, separate from the index.

Separate because ``index --rebuild``, schema-triggered rebuilds and ``clean`` delete
``index.sqlite``, and because ledger writes at search time must not queue behind a long
``update`` transaction on the same WAL.

The store is content-free: paths, line numbers, hashes, token counts and timestamps.
No source text, query, prompt or session tag is ever written.
"""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterator, Optional, Sequence

SCHEMA_VERSION = 1
BUSY_TIMEOUT_MS = 2000


class MemoryUnavailable(RuntimeError):
    """Memory cannot serve this call. Retrieval continues without withholding anything."""


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


def iso(moment: datetime) -> str:
    return moment.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


_V1 = (
    "CREATE TABLE IF NOT EXISTS meta (key TEXT PRIMARY KEY, value TEXT NOT NULL)",
    """CREATE TABLE IF NOT EXISTS atoms (
        id             INTEGER PRIMARY KEY,
        repo_id        TEXT NOT NULL,
        path           TEXT NOT NULL,
        span_sha       TEXT NOT NULL,
        line_count     INTEGER NOT NULL,
        first_line_sha TEXT NOT NULL,
        first_seen_at  TEXT NOT NULL,
        UNIQUE (repo_id, path, span_sha)
    )""",
    """CREATE TABLE IF NOT EXISTS sessions (
        id               INTEGER PRIMARY KEY,
        repo_id          TEXT NOT NULL,
        tag_sha          TEXT NOT NULL,
        created_at       TEXT NOT NULL,
        last_used_at     TEXT NOT NULL,
        calls            INTEGER NOT NULL DEFAULT 0,
        tokens_delivered INTEGER NOT NULL DEFAULT 0,
        tokens_saved     INTEGER NOT NULL DEFAULT 0,
        reused           INTEGER NOT NULL DEFAULT 0,
        invalidations    INTEGER NOT NULL DEFAULT 0,
        UNIQUE (repo_id, tag_sha)
    )""",
    """CREATE TABLE IF NOT EXISTS deliveries (
        session_id    INTEGER NOT NULL REFERENCES sessions(id) ON DELETE CASCADE,
        atom_id       INTEGER NOT NULL REFERENCES atoms(id) ON DELETE CASCADE,
        snippet_sha   TEXT NOT NULL,
        full          INTEGER NOT NULL,
        line_start    INTEGER NOT NULL,
        line_end      INTEGER NOT NULL,
        token_est     INTEGER NOT NULL,
        delivered_at  TEXT NOT NULL,
        invalid_state TEXT,
        PRIMARY KEY (session_id, atom_id, snippet_sha)
    )""",
    "CREATE INDEX IF NOT EXISTS idx_deliveries_atom ON deliveries(atom_id)",
    "CREATE INDEX IF NOT EXISTS idx_sessions_used ON sessions(last_used_at)",
)

# version -> statements that bring a store from version-1 to version. Applied in order,
# each inside one transaction together with the version bump.
MIGRATIONS: dict[int, Sequence[str]] = {1: _V1}


@dataclass(frozen=True)
class NewDelivery:
    path: str
    span_sha: str
    line_count: int
    first_line_sha: str
    snippet_sha: str
    full: bool
    line_start: int
    line_end: int
    token_est: int


@dataclass(frozen=True)
class Delivery:
    atom_id: int
    path: str
    span_sha: str
    line_count: int
    first_line_sha: str
    line_start: int
    line_end: int


class MemoryStore:
    def __init__(self, conn: sqlite3.Connection, path: Path, recovered_from: Optional[str]):
        self.conn = conn
        self.path = path
        self.recovered_from = recovered_from

    # -- lifecycle -------------------------------------------------------------------
    @classmethod
    def open(cls, path: Path | str, *, migrations: Optional[dict[int, Sequence[str]]] = None,
             schema_version: int = SCHEMA_VERSION,
             busy_timeout_ms: Optional[int] = None) -> "MemoryStore":
        """Open (creating or migrating) a store, or raise ``MemoryUnavailable``.

        A file SQLite cannot read as a database is moved aside to
        ``memory.sqlite.corrupt-<timestamp>`` — preserved, never deleted — and a fresh
        store is created. A lock or I/O failure is *not* corruption and is reported as
        unavailable without touching the file.
        """
        path = Path(path)
        migrations = MIGRATIONS if migrations is None else migrations
        if busy_timeout_ms is None:
            busy_timeout_ms = BUSY_TIMEOUT_MS
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
        except OSError as exc:
            raise MemoryUnavailable(f"cannot create memory directory: {exc}") from exc
        recovered: Optional[str] = None
        try:
            conn = cls._connect_and_migrate(path, migrations, schema_version, busy_timeout_ms)
        except sqlite3.OperationalError as exc:
            raise MemoryUnavailable(f"memory store unavailable: {exc}") from exc
        except sqlite3.DatabaseError:
            recovered = _quarantine(path)
            try:
                conn = cls._connect_and_migrate(path, migrations, schema_version, busy_timeout_ms)
            except sqlite3.Error as exc:
                raise MemoryUnavailable(f"memory store unavailable after recovery: {exc}") from exc
        return cls(conn, path, recovered)

    @staticmethod
    def _connect_and_migrate(path: Path, migrations: dict[int, Sequence[str]],
                             schema_version: int, busy_timeout_ms: int) -> sqlite3.Connection:
        conn = sqlite3.connect(path, isolation_level=None, timeout=busy_timeout_ms / 1000)
        try:
            conn.execute(f"PRAGMA busy_timeout = {int(busy_timeout_ms)}")
            conn.execute("PRAGMA journal_mode = WAL")
            conn.execute("PRAGMA synchronous = NORMAL")
            conn.execute("PRAGMA foreign_keys = ON")
            current = _stored_version(conn)
            if current > schema_version:
                raise MemoryUnavailable(
                    f"memory store schema {current} is newer than this version supports "
                    f"({schema_version}); upgrade codebase-index or run `memory clear`"
                )
            for version in range(current + 1, schema_version + 1):
                with _transaction(conn):
                    for statement in migrations[version]:
                        conn.execute(statement)
                    conn.execute(
                        "INSERT INTO meta(key, value) VALUES ('schema_version', ?) "
                        "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                        (str(version),),
                    )
        except BaseException:
            conn.close()
            raise
        return conn

    def close(self) -> None:
        self.conn.close()

    def __enter__(self) -> "MemoryStore":
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def schema_version(self) -> int:
        return _stored_version(self.conn)

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        try:
            with _transaction(self.conn):
                yield self.conn
        except sqlite3.OperationalError as exc:
            raise MemoryUnavailable(f"memory store busy: {exc}") from exc

    # -- sessions --------------------------------------------------------------------
    def touch_session(self, repo_id: str, tag_sha: str, *, now: datetime) -> int:
        stamp = iso(now)
        with self._write() as conn:
            conn.execute(
                "INSERT INTO sessions(repo_id, tag_sha, created_at, last_used_at, calls) "
                "VALUES (?, ?, ?, ?, 1) ON CONFLICT(repo_id, tag_sha) DO UPDATE SET "
                "last_used_at = excluded.last_used_at, calls = calls + 1",
                (repo_id, tag_sha, stamp, stamp),
            )
            row = conn.execute(
                "SELECT id FROM sessions WHERE repo_id = ? AND tag_sha = ?", (repo_id, tag_sha)
            ).fetchone()
        return int(row[0])

    def find_session(self, repo_id: str, tag_sha: str) -> Optional[int]:
        row = self.conn.execute(
            "SELECT id FROM sessions WHERE repo_id = ? AND tag_sha = ?", (repo_id, tag_sha)
        ).fetchone()
        return int(row[0]) if row else None

    def is_known(self, session_id: int, path: str, span_sha: str, snippet_sha: str) -> bool:
        """Was exactly this text — or the whole unchanged span — delivered to this session?

        Deliveries later found invalid never count, even if the bytes come back: the
        agent was told that evidence changed, so it gets the text again.
        """
        row = self.conn.execute(
            "SELECT 1 FROM deliveries d JOIN atoms a ON a.id = d.atom_id "
            "WHERE d.session_id = ? AND a.path = ? AND a.span_sha = ? "
            "AND d.invalid_state IS NULL AND (d.full = 1 OR d.snippet_sha = ?) LIMIT 1",
            (session_id, path, span_sha, snippet_sha),
        ).fetchone()
        return row is not None

    def pending(self, session_id: int) -> list[Delivery]:
        """Distinct evidence delivered to this session and not yet reported invalid."""
        return self._deliveries(session_id, "AND d.invalid_state IS NULL")

    def delivered(self, session_id: int) -> list[Delivery]:
        """Every distinct piece of evidence delivered to this session, valid or not."""
        return self._deliveries(session_id, "")

    def _deliveries(self, session_id: int, condition: str) -> list[Delivery]:
        rows = self.conn.execute(
            "SELECT a.id, a.path, a.span_sha, a.line_count, a.first_line_sha, "
            "       MIN(d.line_start), MIN(d.line_end) "
            "FROM deliveries d JOIN atoms a ON a.id = d.atom_id "
            f"WHERE d.session_id = ? {condition} "
            "GROUP BY a.id ORDER BY a.path, MIN(d.line_start)",
            (session_id,),
        ).fetchall()
        return [Delivery(int(r[0]), r[1], r[2], int(r[3]), r[4], int(r[5]), int(r[6]))
                for r in rows]

    def record(self, repo_id: str, session_id: int, items: Sequence[NewDelivery], *,
               now: datetime) -> None:
        if not items:
            return
        stamp = iso(now)
        with self._write() as conn:
            for item in items:
                conn.execute(
                    "INSERT INTO atoms(repo_id, path, span_sha, line_count, first_line_sha, "
                    "first_seen_at) VALUES (?, ?, ?, ?, ?, ?) "
                    "ON CONFLICT(repo_id, path, span_sha) DO NOTHING",
                    (repo_id, item.path, item.span_sha, item.line_count,
                     item.first_line_sha, stamp),
                )
                atom_id = conn.execute(
                    "SELECT id FROM atoms WHERE repo_id = ? AND path = ? AND span_sha = ?",
                    (repo_id, item.path, item.span_sha),
                ).fetchone()[0]
                conn.execute(
                    "INSERT INTO deliveries(session_id, atom_id, snippet_sha, full, line_start, "
                    "line_end, token_est, delivered_at, invalid_state) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL) "
                    "ON CONFLICT(session_id, atom_id, snippet_sha) DO UPDATE SET "
                    "full = MAX(full, excluded.full), line_start = excluded.line_start, "
                    "line_end = excluded.line_end, token_est = excluded.token_est, "
                    "delivered_at = excluded.delivered_at, invalid_state = NULL",
                    (session_id, atom_id, item.snippet_sha, int(item.full), item.line_start,
                     item.line_end, item.token_est, stamp),
                )

    def mark_invalid(self, session_id: int, states: Sequence[tuple[int, str]]) -> None:
        if not states:
            return
        with self._write() as conn:
            conn.executemany(
                "UPDATE deliveries SET invalid_state = ? WHERE session_id = ? AND atom_id = ?",
                [(state, session_id, atom_id) for atom_id, state in states],
            )

    def add_counters(self, session_id: int, *, tokens_delivered: int, tokens_saved: int,
                     reused: int, invalidations: int) -> None:
        with self._write() as conn:
            conn.execute(
                "UPDATE sessions SET tokens_delivered = tokens_delivered + ?, "
                "tokens_saved = tokens_saved + ?, reused = reused + ?, "
                "invalidations = invalidations + ? WHERE id = ?",
                (tokens_delivered, tokens_saved, reused, invalidations, session_id),
            )

    def first_line_hint(self, repo_id: str, path: str, sha_prefix: str) -> Optional[str]:
        """Relocation hint for a printed reference, when this store has seen the evidence."""
        rows = self.conn.execute(
            "SELECT first_line_sha FROM atoms WHERE repo_id = ? AND path = ? "
            "AND span_sha >= ? AND span_sha < ? LIMIT 2",
            (repo_id, path, sha_prefix, sha_prefix + "g"),
        ).fetchall()
        return rows[0][0] if len(rows) == 1 else None

    # -- observability and maintenance -----------------------------------------------
    def stats(self, repo_id: str) -> dict:
        one = self.conn.execute
        sessions = one(
            "SELECT COUNT(*), COALESCE(SUM(tokens_delivered),0), COALESCE(SUM(tokens_saved),0), "
            "COALESCE(SUM(reused),0), COALESCE(SUM(invalidations),0), MAX(last_used_at) "
            "FROM sessions WHERE repo_id = ?", (repo_id,),
        ).fetchone()
        atoms = one("SELECT COUNT(*) FROM atoms WHERE repo_id = ?", (repo_id,)).fetchone()[0]
        deliveries = one(
            "SELECT COUNT(*) FROM deliveries d JOIN sessions s ON s.id = d.session_id "
            "WHERE s.repo_id = ?", (repo_id,),
        ).fetchone()[0]
        last_gc = one("SELECT value FROM meta WHERE key = 'last_gc_at'").fetchone()
        return {
            "schema_version": self.schema_version,
            "sessions": int(sessions[0]),
            "atoms": int(atoms),
            "deliveries": int(deliveries),
            "tokens_delivered": int(sessions[1]),
            "tokens_saved": int(sessions[2]),
            "reused": int(sessions[3]),
            "invalidations": int(sessions[4]),
            "last_used_at": sessions[5],
            "last_gc_at": last_gc[0] if last_gc else None,
            "bytes": _file_bytes(self.path),
        }

    def gc_due(self, *, now: datetime, every: timedelta = timedelta(days=1)) -> bool:
        row = self.conn.execute("SELECT value FROM meta WHERE key = 'last_gc_at'").fetchone()
        return row is None or row[0] < iso(now - every)

    def gc(self, *, now: datetime, retention_days: int, max_deliveries: int) -> dict:
        """Delete expired sessions, sessions beyond the size cap, and orphaned atoms.

        Only rows are removed. Validity is recomputed from the working tree on every
        check, so GC can make memory withhold less, never make it withhold wrongly.
        """
        cutoff = iso(now - timedelta(days=max(0, retention_days)))
        with self._write() as conn:
            expired = conn.execute(
                "DELETE FROM sessions WHERE last_used_at < ?", (cutoff,)
            ).rowcount
            total = conn.execute("SELECT COUNT(*) FROM deliveries").fetchone()[0]
            capped = 0
            if total > max_deliveries:
                for session_id, count in conn.execute(
                    "SELECT s.id, COUNT(d.atom_id) FROM sessions s "
                    "LEFT JOIN deliveries d ON d.session_id = s.id "
                    "GROUP BY s.id ORDER BY s.last_used_at, s.id"
                ).fetchall():
                    if total <= max_deliveries:
                        break
                    conn.execute("DELETE FROM sessions WHERE id = ?", (session_id,))
                    total -= count
                    capped += 1
            orphans = conn.execute(
                "DELETE FROM atoms WHERE id NOT IN (SELECT DISTINCT atom_id FROM deliveries)"
            ).rowcount
            conn.execute(
                "INSERT INTO meta(key, value) VALUES ('last_gc_at', ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
                (iso(now),),
            )
        return {"expired_sessions": max(0, expired), "capped_sessions": capped,
                "orphan_atoms": max(0, orphans)}

    def clear(self, repo_id: str, tag_sha: Optional[str] = None) -> int:
        with self._write() as conn:
            if tag_sha is None:
                removed = conn.execute(
                    "DELETE FROM sessions WHERE repo_id = ?", (repo_id,)
                ).rowcount
                conn.execute("DELETE FROM atoms WHERE repo_id = ?", (repo_id,))
            else:
                removed = conn.execute(
                    "DELETE FROM sessions WHERE repo_id = ? AND tag_sha = ?", (repo_id, tag_sha)
                ).rowcount
                conn.execute(
                    "DELETE FROM atoms WHERE id NOT IN (SELECT DISTINCT atom_id FROM deliveries)"
                )
        return max(0, removed)

    def vacuum(self) -> None:
        try:
            self.conn.execute("VACUUM")
        except sqlite3.OperationalError as exc:
            raise MemoryUnavailable(f"memory store busy: {exc}") from exc


@contextmanager
def _transaction(conn: sqlite3.Connection) -> Iterator[None]:
    conn.execute("BEGIN IMMEDIATE")
    try:
        yield
    except BaseException:
        conn.execute("ROLLBACK")
        raise
    conn.execute("COMMIT")


def _stored_version(conn: sqlite3.Connection) -> int:
    has_meta = conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'meta'"
    ).fetchone()
    if not has_meta:
        return 0
    row = conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
    return int(row[0]) if row else 0


def _file_bytes(path: Path) -> int:
    return sum(
        p.stat().st_size
        for p in (path, path.with_name(path.name + "-wal"), path.with_name(path.name + "-shm"))
        if p.exists()
    )


def _quarantine(path: Path, clock: Callable[[], datetime] = utc_now) -> str:
    """Move an unreadable store (and its WAL sidecars) aside; return the new name."""
    suffix = clock().strftime("%Y%m%dT%H%M%SZ")
    target = path.with_name(f"{path.name}.corrupt-{suffix}")
    for extra in ("", "-wal", "-shm"):
        src = path.with_name(path.name + extra)
        if src.exists():
            src.replace(target.with_name(target.name + extra))
    return target.name
