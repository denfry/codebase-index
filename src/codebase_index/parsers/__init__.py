"""Parsers turn an eligible file into chunks + symbols.

base.py         : Parser protocol -> parse(path, text) -> (list[Chunk], list[Symbol]).
treesitter.py   : AST-based symbol extraction using tree-sitter grammars.
line_chunker.py : fallback line-window chunking for unsupported / unparseable files.
languages.py    : grammar registry + per-language node->symbol-kind maps + import/call queries.

Selection: treesitter when a grammar exists for the detected language, else line_chunker.
"""
