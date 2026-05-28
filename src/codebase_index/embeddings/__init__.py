"""OPTIONAL, opt-in vector backend. Default is disabled (noop).

backend.py : Backend protocol -> embed(texts) -> list[vector]; pluggable.
local.py   : on-device model (sentence-transformers). No network at query time.
noop.py    : default no-op backend; vector searcher is skipped entirely when active.

An 'external' backend (sends text to an API) is refused unless embeddings.allow_external is True
AND an API key env var is present AND the user has been warned. See docs/SECURITY.md §4.
"""
