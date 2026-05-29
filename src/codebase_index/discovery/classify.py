"""Pure file classification helpers for discovery gates."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Optional

_LANG_BY_SUFFIX = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".js": "javascript",
    ".jsx": "javascript",
    ".mjs": "javascript",
    ".cjs": "javascript",
    ".go": "go",
    ".java": "java",
    ".rs": "rust",
    ".c": "c",
    ".h": "c",
    ".cpp": "cpp",
    ".cc": "cpp",
    ".cxx": "cpp",
    ".hpp": "cpp",
    ".hh": "cpp",
    ".hxx": "cpp",
    ".cs": "csharp",
    ".rb": "ruby",
    ".php": "php",
    ".kt": "kotlin",
    ".kts": "kotlin",
    ".lua": "lua",
    ".md": "markdown",
    ".json": "json",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".toml": "toml",
    ".sql": "sql",
}

# Authoritative set of *code* languages routed to tree-sitter (Guardrail 1). Every entry MUST
# have a working extraction path — a Tier-A LangSpec or the Tier-B generic walker. This is
# enforced by tests/test_multilang_symbols.py (registry consistency), so the two registries
# cannot silently drift. Note: yaml/json/markdown/toml/sql have grammars too but are *data/prose*
# (Tier C) and deliberately stay on the line-chunk + FTS floor.
#
# `lua` here has no Tier-A spec on purpose: it exercises the Tier-B generic path end-to-end.
_TREE_SITTER_LANGS = {
    "python",
    "typescript",
    "javascript",
    "go",
    "java",
    "rust",
    "c",
    "cpp",
    "csharp",
    "ruby",
    "php",
    "kotlin",
    "lua",
}

_SECRET_NAMES = {
    ".env",
    "id_rsa",
    "id_ed25519",
    "credentials.json",
    "service-account.json",
    "secrets.json",
}

_SECRET_SUFFIXES = (".pem", ".key", ".p12", ".pfx")


def detect_language(path: str) -> Optional[str]:
    return _LANG_BY_SUFFIX.get(PurePosixPath(path).suffix.lower())


def parser_for(lang: Optional[str]) -> str:
    return "treesitter" if lang in _TREE_SITTER_LANGS else "line"


def is_secret_filename(path: str) -> bool:
    name = PurePosixPath(path).name.lower()
    if name in _SECRET_NAMES or name.startswith(".env."):
        return True
    return name.endswith(_SECRET_SUFFIXES)


def looks_binary(data: bytes) -> bool:
    return b"\x00" in data


def is_generated(path: str) -> bool:
    name = PurePosixPath(path).name.lower()
    return (
        ".generated." in name
        or name.endswith(".generated")
        or name.endswith(".min.js")
        or name.endswith(".min.css")
    )
