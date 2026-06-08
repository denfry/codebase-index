# Database Schema

SQLite database structure for `codebase-index`.

## Overview

The index is stored in a single SQLite file: `.claude/cache/codebase-index/index.sqlite`

The schema is defined in `src/codebase_index/storage/schema.sql` and applied on first initialization.

## Tables

### files

Stores metadata about indexed files.

| Column | Type | Description |
|---|---|---|
| `id` | INTEGER PRIMARY KEY | Auto-incrementing file ID |
| `path` | TEXT UNIQUE NOT NULL | Relative path from project root |
| `language` | TEXT | Detected language (python, typescript, etc.) |
| `size_bytes` | INTEGER | File size in bytes |
| `content_hash` | TEXT NOT NULL | SHA-256 hash for change detection |
| `indexed_at` | TEXT | ISO 8601 timestamp of last indexing |
| `is_generated` | INTEGER DEFAULT 0 | Whether file is auto-generated |

### chunks

Stores text chunks for FTS5 indexing.

| Column | Type | Description |
|---|---|---|
| `id` | INTEGER PRIMARY KEY | Auto-incrementing chunk ID |
| `file_id` | INTEGER REFERENCES files(id) | Parent file |
| `chunk_index` | INTEGER | Position within the file |
| `line_start` | INTEGER | Starting line number (1-indexed) |
| `line_end` | INTEGER | Ending line number (1-indexed) |
| `text` | TEXT NOT NULL | Chunk text content |
| `token_estimate` | INTEGER | Approximate token count |

### symbols

Stores extracted symbols from AST parsing.

| Column | Type | Description |
|---|---|---|
| `id` | INTEGER PRIMARY KEY | Auto-incrementing symbol ID |
| `file_id` | INTEGER REFERENCES files(id) | Defining file |
| `name` | TEXT NOT NULL | Symbol name |
| `kind` | TEXT | Type: class, function, method, variable, etc. |
| `line_start` | INTEGER | Definition start line |
| `line_end` | INTEGER | Definition end line |
| `signature` | TEXT | Function/class signature if available |
| `docstring` | TEXT | Extracted docstring if available |

### edges

Stores relationships between symbols and files.

| Column | Type | Description |
|---|---|---|
| `id` | INTEGER PRIMARY KEY | Auto-incrementing edge ID |
| `source_id` | INTEGER REFERENCES symbols(id) | Source symbol (caller, importer) |
| `target_id` | INTEGER REFERENCES symbols(id) | Target symbol (callee, imported) |
| `edge_type` | TEXT | Type: call, import, reference, inheritance |
| `line` | INTEGER | Line where the edge occurs |

### modules

Stores module-level information for import resolution.

| Column | Type | Description |
|---|---|---|
| `id` | INTEGER PRIMARY KEY | Auto-incrementing module ID |
| `file_id` | INTEGER REFERENCES files(id) | File containing the module |
| `module_path` | TEXT | Resolved module path |
| `exports` | TEXT | JSON array of exported symbol names |

### fts_chunks

FTS5 virtual table for full-text search (auto-managed by triggers).

| Column | Type | Description |
|---|---|---|
| `text` | TEXT | Chunk text (indexed by FTS5) |
| `chunk_id` | INTEGER | References chunks(id) |

### vec_chunks (optional)

Vector embeddings for semantic search. Created **only** when `embeddings.enabled = true`, via the
`sqlite-vec` extension (a `vec0` virtual table).

| Column | Type | Description |
|---|---|---|
| `chunk_id` | INTEGER PRIMARY KEY | References chunks(id) |
| `embedding` | FLOAT[dim] | Embedding vector; `dim` is fixed per build by the configured model |

### vec_meta (optional)

Records which embedding model/dimension produced the vectors currently in `vec_chunks`.

| Column | Type | Description |
|---|---|---|
| `model` | TEXT | Embedding model identifier |
| `dim` | INTEGER | Vector dimension |
| `built_at` | TEXT | ISO 8601 timestamp of the embedding pass |

### vec_cache (optional)

Content-addressed embedding cache. `chunk_id`s churn on every full rebuild (chunks are deleted and
re-inserted), so this cache is keyed by `(model, content_sha)` instead — letting unchanged content
reuse its vector for free across rebuilds, so only new or changed text hits the backend.

| Column | Type | Description |
|---|---|---|
| `model` | TEXT NOT NULL | Embedding model identifier |
| `content_sha` | TEXT NOT NULL | SHA-256 of the chunk content |
| `embedding` | BLOB NOT NULL | Pre-serialized float32 vector |

Primary key: `(model, content_sha)`.

### summaries

Stores file-level summaries for quick overview.

| Column | Type | Description |
|---|---|---|
| `file_id` | INTEGER PRIMARY KEY REFERENCES files(id) | Associated file |
| `summary` | TEXT | Auto-generated or manual summary |
| `top_symbols` | TEXT | JSON array of most important symbols |

### metadata

Stores index-level metadata.

| Column | Type | Description |
|---|---|---|
| `key` | TEXT PRIMARY KEY | Metadata key |
| `value` | TEXT | Metadata value |

Common keys:
- `schema_version` — current schema version (for migration checks)
- `last_indexed_at` — timestamp of last full index
- `total_files` — number of indexed files
- `total_symbols` — number of extracted symbols
- `total_chunks` — number of text chunks
- `config_hash` — hash of the configuration used for indexing

## Indexes

| Index | Table | Columns | Purpose |
|---|---|---|---|
| `idx_files_path` | files | path | Fast path lookup |
| `idx_files_hash` | files | content_hash | Change detection |
| `idx_symbols_name` | symbols | name | Symbol name lookup |
| `idx_symbols_file` | symbols | file_id | Symbols by file |
| `idx_edges_source` | edges | source_id | Outgoing edges |
| `idx_edges_target` | edges | target_id | Incoming edges |
| `idx_chunks_file` | chunks | file_id | Chunks by file |

## FTS5 Configuration

The `fts_chunks` virtual table uses:

- **Tokenizer:** `unicode61` (default SQLite tokenizer)
- **Content:** `chunks` table (external content mode)
- **Triggers:** INSERT, UPDATE, DELETE triggers keep FTS in sync with `chunks`

### Query Syntax

FTS5 supports:
- Phrase matching: `"exact phrase"`
- Prefix matching: `auth*`
- Boolean: `auth AND login`, `auth OR login`, `auth NOT test`
- NEAR: `auth NEAR/5 login`

## Schema Migrations

The `metadata.schema_version` key tracks the current schema version. On initialization:

1. If the database doesn't exist, create it with the latest schema.
2. If the database exists, check `schema_version`:
   - If equal to current, proceed.
   - If less than current, run migrations (not yet implemented).
   - If greater than current, refuse to open (future version protection).
