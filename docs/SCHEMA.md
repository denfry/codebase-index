# Database Schema

Single SQLite database at `.claude/cache/codebase-index/index.sqlite`. WAL mode, foreign keys on.
The DDL below is the canonical source mirrored by `src/codebase_index/storage/schema.sql`.

## Pragmas

```sql
PRAGMA journal_mode = WAL;
PRAGMA synchronous   = NORMAL;
PRAGMA foreign_keys  = ON;
PRAGMA temp_store    = MEMORY;
```

## Core tables

```sql
-- One row per indexed file. Hash + mtime drive incremental re-indexing.
CREATE TABLE files (
    id            INTEGER PRIMARY KEY,
    path          TEXT NOT NULL UNIQUE,        -- repo-relative, POSIX separators
    lang          TEXT,                        -- detected language (NULL if unknown)
    size_bytes    INTEGER NOT NULL,
    sha256        TEXT NOT NULL,               -- content hash for change detection
    mtime_ns      INTEGER NOT NULL,
    git_status    TEXT,                        -- clean|modified|untracked|staged
    parser        TEXT NOT NULL,               -- 'treesitter' | 'line'
    indexed_at    TEXT NOT NULL,               -- ISO8601
    is_generated  INTEGER NOT NULL DEFAULT 0,
    summary       TEXT                         -- short file-level summary
);

-- Text spans. For tree-sitter files chunks align to symbol bodies; otherwise line windows.
CREATE TABLE chunks (
    id            INTEGER PRIMARY KEY,
    file_id       INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    line_start    INTEGER NOT NULL,
    line_end      INTEGER NOT NULL,
    kind          TEXT,                        -- 'symbol_body' | 'window' | 'doc'
    symbol_id     INTEGER REFERENCES symbols(id) ON DELETE SET NULL,
    content       TEXT NOT NULL,               -- raw text (secret-redacted before snippet output)
    token_est     INTEGER NOT NULL,            -- estimated tokens, for budgeting
    symbol_names  TEXT NOT NULL DEFAULT ''     -- denormalized symbol name, FTS-indexed (mirrored by triggers)
);
CREATE INDEX idx_chunks_file ON chunks(file_id);

-- Symbols extracted via tree-sitter (definitions).
CREATE TABLE symbols (
    id            INTEGER PRIMARY KEY,
    file_id       INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    name          TEXT NOT NULL,
    qualified     TEXT,                        -- e.g. module.Class.method
    kind          TEXT NOT NULL,               -- function|method|class|interface|enum|var|const|type|module
    line_start    INTEGER NOT NULL,
    line_end      INTEGER NOT NULL,
    signature     TEXT,                        -- one-line signature / declaration
    parent_id     INTEGER REFERENCES symbols(id) ON DELETE SET NULL,  -- enclosing scope
    docstring     TEXT,
    in_degree     INTEGER NOT NULL DEFAULT 0,  -- denormalized graph centrality (callers/importers)
    out_degree    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_symbols_name ON symbols(name);
CREATE INDEX idx_symbols_file ON symbols(file_id);
CREATE INDEX idx_symbols_kind ON symbols(kind);

-- Graph edges: imports / calls / references / inheritance / dependencies.
-- src is always a known symbol or file; dst may be unresolved (dst_id NULL, dst_name kept).
CREATE TABLE edges (
    id            INTEGER PRIMARY KEY,
    edge_type     TEXT NOT NULL,               -- import|call|reference|extends|implements|depends
    src_kind      TEXT NOT NULL,               -- 'symbol' | 'file'
    src_id        INTEGER NOT NULL,
    dst_kind      TEXT,                         -- 'symbol' | 'file' | NULL if unresolved
    dst_id        INTEGER,
    dst_name      TEXT,                         -- raw target text (for unresolved edges)
    file_id       INTEGER NOT NULL REFERENCES files(id) ON DELETE CASCADE,
    line          INTEGER,
    resolved      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX idx_edges_src ON edges(src_kind, src_id);
CREATE INDEX idx_edges_dst ON edges(dst_kind, dst_id);
CREATE INDEX idx_edges_name ON edges(dst_name);
CREATE INDEX idx_edges_type ON edges(edge_type);

-- Module / package level summaries for architecture-intent queries.
CREATE TABLE modules (
    id            INTEGER PRIMARY KEY,
    path          TEXT NOT NULL UNIQUE,        -- directory or package path
    kind          TEXT NOT NULL,               -- 'module' | 'package'
    summary       TEXT,
    file_count    INTEGER NOT NULL DEFAULT 0,
    symbol_count  INTEGER NOT NULL DEFAULT 0
);

-- Index-wide metadata (one row, or key/value).
CREATE TABLE meta (
    key           TEXT PRIMARY KEY,
    value         TEXT NOT NULL
);
-- keys: schema_version, built_at, head_commit, config_hash, embeddings_enabled, ...
```

## Full-text search (FTS5)

```sql
-- External-content FTS over chunks.
CREATE VIRTUAL TABLE fts_chunks USING fts5(
    content,
    symbol_names,            -- denormalized: names of symbols in this chunk
    path UNINDEXED,
    content='chunks',
    content_rowid='id',
    tokenize = "unicode61 remove_diacritics 2"
);
-- Triggers keep fts_chunks in sync with chunks (INSERT/UPDATE/DELETE). bm25() used for ranking.
```

> Note: underscores are token separators, so `snake_case` identifiers are searchable by their
> parts. camelCase splitting is handled at query time; a true custom tokenizer (APSW) is deferred.

## Optional vector table (opt-in only)

Created **only** when `embeddings.enabled = true`. Uses the `sqlite-vec` extension so vectors stay
in the same local DB — no external service.

```sql
CREATE VIRTUAL TABLE vec_chunks USING vec0(
    chunk_id INTEGER PRIMARY KEY,
    embedding FLOAT[384]        -- dimension depends on configured model
);
-- A side table records which embedding model/dim produced these vectors:
CREATE TABLE vec_meta (model TEXT, dim INTEGER, built_at TEXT);
-- Content-addressed embedding cache, keyed by (model, content SHA-256):
CREATE TABLE vec_cache (
    model       TEXT NOT NULL,
    content_sha TEXT NOT NULL,
    embedding   BLOB NOT NULL,  -- pre-serialized float32 vector
    PRIMARY KEY (model, content_sha)
);
```

If embeddings are disabled, none of `vec_chunks`, `vec_meta`, or `vec_cache` exist and the vector
searcher is skipped.

### Embedding reuse via `vec_cache`

`chunk_id`s churn on every full rebuild because `replace_chunks` deletes and re-inserts rows, so a
`chunk_id`-keyed store alone would re-embed the entire repository each time. The embedding pass
therefore hashes each chunk's content (SHA-256) and looks it up in `vec_cache` under the active
model name. Only content never embedded under that model is sent to the (potentially slow or paid)
backend; everything else is copied straight from the cache into `vec_chunks`. Newly computed vectors
are written back to `vec_cache` so subsequent rebuilds reuse them. The reported "embedded" count
reflects cache **misses** — i.e. the work actually performed.

## Migrations

`meta.schema_version` gates migrations in `storage/db.py`. On version mismatch the CLI either
migrates in place (for additive changes) or, for breaking changes, prompts a `index --rebuild`.

## Incremental indexing keys

A file is re-processed when **any** of: `sha256` differs, `mtime_ns` differs (cheap pre-check), or
git status changed. Deleted files cascade-delete their chunks/symbols/edges. `config_hash` change
(e.g. new language enabled, embeddings toggled) forces a full rebuild of affected rows.
