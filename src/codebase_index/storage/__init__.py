"""SQLite persistence layer.

db.py     : connection management, pragmas, applying schema.sql, migrations gated on
            meta.schema_version.
schema.sql: canonical DDL (mirrors docs/SCHEMA.md).
repo.py   : typed accessors (upsert_file, replace_chunks, insert_symbols, insert_edges, FTS query,
            vector query, freshness read). All SQL lives here — no raw SQL elsewhere.
"""
