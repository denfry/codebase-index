"""Evidence memory: verifiable references to repository evidence and session reuse.

See docs/MEMORY.md. Nothing in this package stores source text; identity is a hash of
the exact bytes a span held, and validity is always re-checked against the working tree.
"""
