"""Indexing orchestration.

pipeline.py    : full + incremental build = discovery -> parse -> store chunks/symbols ->
                 graph build -> summaries -> FTS sync -> (optional) embeddings.
incremental.py : decide which files to (re)process from sha256 + mtime_ns + git status; handle
                 deletions (cascade) and config_hash changes (rebuild affected rows).
summarize.py   : file/module/package summaries (heuristic/extractive by default; pluggable later).
"""
