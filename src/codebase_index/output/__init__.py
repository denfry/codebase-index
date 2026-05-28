"""Result rendering. Both renderers consume models.SearchResponse so output stays consistent.

markdown.py : compact Markdown for Claude — tight results table + fenced snippets +
              recommended_reads list + fallback suggestions. Optimized for low token count.
json.py     : machine-readable JSON (what the skill parses with --json).
"""
