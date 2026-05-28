"""File discovery + ignore rules + classification.

walker.py    : walk the project root, yield candidate paths.
ignore.py    : merge .gitignore/.cursorignore/.claudeignore/.codeindexignore + built-in denylist
               via pathspec; expose `is_ignored(path) -> bool`.
classify.py  : language detection, binary/size/secret gates, generated-file detection.

Hard guarantee: secrets, binaries, build/dependency dirs, and oversized files never leave this
layer as indexable candidates. See docs/SECURITY.md §2.
"""
