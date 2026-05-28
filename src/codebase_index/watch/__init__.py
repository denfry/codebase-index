"""OPTIONAL live indexing (extra: watch).

watcher.py : watchdog-based observer that debounces filesystem events and calls the incremental
             indexer asynchronously. Never required; `update` (manual or via hook) is the default.
"""
