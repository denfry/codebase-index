"""Hybrid retrieval engine. See docs/RETRIEVAL.md for the full pipeline.

intent.py    : classify the query into an Intent + retriever weights + graph strategy.
searchers.py : path / symbol / fts / vector searchers -> uniform Candidate lists.
fusion.py    : Reciprocal Rank Fusion across retriever lists (rrf_k, per-intent weights).
rerank.py    : feature-based reordering (symbol-kind, path proximity, centrality, recency) +
               produces the human-readable `reason` per result.
budget.py    : greedy token-budgeted assembly of snippets vs. recommended_reads; secret redaction.
"""
