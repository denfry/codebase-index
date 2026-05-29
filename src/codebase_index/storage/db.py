"""SQLite connection management: pragmas, schema application, version guard."""

from __future__ import annotations

import sqlite3
from importlib import resources
from pathlib import Path
from typing import Optional

SCHEMA_VERSION = 1


class Database:
    """Own one SQLite connection for one CLI invocation."""

    def __init__(self, path: Path | str) -> None:
        self.path = Path(path)
        self._conn: Optional[sqlite3.Connection] = None

    def open(self) -> "Database":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(self.path)
        self._conn.row_factory = sqlite3.Row
        self._apply_pragmas()
        self._apply_schema()
        self._guard_version()
        return self

    def close(self) -> None:
        if self._conn is not None:
            self._conn.commit()
            self._conn.close()
            self._conn = None

    def __enter__(self) -> "Database":
        return self.open()

    def __exit__(self, *exc: object) -> None:
        self.close()

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("Database is not open")
        return self._conn

    def get_schema_version(self) -> int:
        row = self.conn.execute("SELECT value FROM meta WHERE key = 'schema_version'").fetchone()
        return int(row[0]) if row else 0

    def _apply_pragmas(self) -> None:
        self.conn.execute("PRAGMA journal_mode = WAL")
        self.conn.execute("PRAGMA synchronous = NORMAL")
        self.conn.execute("PRAGMA foreign_keys = ON")
        self.conn.execute("PRAGMA temp_store = MEMORY")

    def _apply_schema(self) -> None:
        ddl = resources.files("codebase_index.storage").joinpath("schema.sql").read_text(
            encoding="utf-8"
        )
        self.conn.executescript(ddl)

    def _guard_version(self) -> None:
        current = self.get_schema_version()
        if current == 0:
            self.conn.execute(
                "INSERT OR REPLACE INTO meta(key, value) VALUES ('schema_version', ?)",
                (str(SCHEMA_VERSION),),
            )
            self.conn.commit()
        elif current > SCHEMA_VERSION:
            raise RuntimeError(
                f"Index schema_version {current} is newer than supported {SCHEMA_VERSION}; "
                "rebuild the index with an updated CLI."
            )

    def enable_vectors(self) -> None:
        """Load the sqlite-vec extension into this connection (optional extra)."""
        try:
            import sqlite_vec  # type: ignore[import-untyped]
        except ImportError as exc:
            raise RuntimeError(
                "Vector search needs the optional extra: pip install codebase-index[embeddings]"
            ) from exc
        self.conn.enable_load_extension(True)
        sqlite_vec.load(self.conn)
        self.conn.enable_load_extension(False)
