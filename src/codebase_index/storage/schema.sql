-- Canonical DDL for codebase-index. Mirrors docs/SCHEMA.md. Applied by storage/db.py.
PRAGMA journal_mode = WAL;
PRAGMA synchronous   = NORMAL;
PRAGMA foreign_keys  = ON;
PRAGMA temp_store    = MEMORY;

CREATE TABLE IF NOT EXISTS files (
    id            INTEGER PRIMARY KEY,
    path          TEXT NOT NULL UNIQUE,
    lang          TEXT,
    size_bytes    INTEGER NOT NULL,
    sha256        TEXT NOT NULL,
    mtime_ns      INTEGER NOT NULL,
    git_status    TEXT,
    parser        TEXT NOT NULL,
    indexed_at    TEXT NOT NULL,
    is_generated  INTEGER NOT NULL DEFAULT 0,
    summary       TEXT
);

CREATE TABLE IF NOT EXISTS symbols (
    id            INTEGER PRIMARY KEY,
    file_id       INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    qualified     TEXT,
    kind          TEXT NOT NULL,
    line_start    INTEGER NOT NULL,
    line_end      INTEGER NOT NULL,
    signature     TEXT,
    parent_id     INTEGER REFERENCES symbols(id) ON DELETE SET NULL,
    docstring     TEXT,
    in_degree     INTEGER NOT NULL DEFAULT 0,
    out_degree    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);
CREATE INDEX IF NOT EXISTS idx_symbols_file ON symbols(file_id);
CREATE INDEX IF NOT EXISTS idx_symbols_kind ON symbols(kind);

CREATE TABLE IF NOT EXISTS chunks (
    id            INTEGER PRIMARY KEY,
    file_id       INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    line_start    INTEGER NOT NULL,
    line_end      INTEGER NOT NULL,
    kind          TEXT,
    symbol_id     INTEGER REFERENCES symbols(id) ON DELETE SET NULL,
    content       TEXT NOT NULL,
    token_est     INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chunks_file ON chunks(file_id);

CREATE TABLE IF NOT EXISTS edges (
    id            INTEGER PRIMARY KEY,
    edge_type     TEXT NOT NULL,
    src_kind      TEXT NOT NULL,
    src_id        INTEGER NOT NULL,
    dst_kind      TEXT,
    dst_id        INTEGER,
    dst_name      TEXT,
    file_id       INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    line          INTEGER,
    resolved      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_edges_src  ON edges(src_kind, src_id);
CREATE INDEX IF NOT EXISTS idx_edges_dst  ON edges(dst_kind, dst_id);
CREATE INDEX IF NOT EXISTS idx_edges_name ON edges(dst_name);
CREATE INDEX IF NOT EXISTS idx_edges_type ON edges(edge_type);

CREATE TABLE IF NOT EXISTS modules (
    id            INTEGER PRIMARY KEY,
    path          TEXT NOT NULL UNIQUE,
    kind          TEXT NOT NULL,
    summary       TEXT,
    file_count    INTEGER NOT NULL DEFAULT 0,
    symbol_count  INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS meta (
    key           TEXT PRIMARY KEY,
    value         TEXT NOT NULL
);

-- FTS5 over chunks (external content). Triggers keep it in sync.
CREATE VIRTUAL TABLE IF NOT EXISTS fts_chunks USING fts5(
    content,
    symbol_names,
    path UNINDEXED,
    content='chunks',
    content_rowid='id',
    tokenize = "unicode61 remove_diacritics 2 tokenchars '_'"
);

CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
    INSERT INTO fts_chunks(rowid, content, symbol_names, path)
    VALUES (new.id, new.content, '', (SELECT path FROM files WHERE id = new.file_id));
END;
CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
    INSERT INTO fts_chunks(fts_chunks, rowid, content, symbol_names, path)
    VALUES ('delete', old.id, old.content, '', '');
END;
CREATE TRIGGER IF NOT EXISTS chunks_au AFTER UPDATE ON chunks BEGIN
    INSERT INTO fts_chunks(fts_chunks, rowid, content, symbol_names, path)
    VALUES ('delete', old.id, old.content, '', '');
    INSERT INTO fts_chunks(rowid, content, symbol_names, path)
    VALUES (new.id, new.content, '', (SELECT path FROM files WHERE id = new.file_id));
END;

-- vec_chunks (sqlite-vec) is created at runtime ONLY when embeddings.enabled = true.
