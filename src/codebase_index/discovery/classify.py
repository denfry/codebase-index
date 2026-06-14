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
    # Config / IaC (Tier C: line-chunk + FTS, no tree-sitter spec). These were already
    # indexed as unknown-language text; labeling them surfaces infra files in `stats`
    # and lets agents scope searches to config without a tree-sitter grammar.
    ".tf": "terraform",
    ".tfvars": "terraform",
    ".hcl": "hcl",
    ".ini": "ini",
    ".cfg": "ini",
    ".conf": "ini",
    ".properties": "ini",
}

# Extension-less or specially-named config/IaC files, matched on the lowercased
# filename (and a `name.suffix` form, e.g. `web.Dockerfile`). Kept separate from
# the suffix table because these carry their identity in the name, not the suffix.
_LANG_BY_NAME = {
    "dockerfile": "dockerfile",
    "containerfile": "dockerfile",
    "makefile": "make",
    "gnumakefile": "make",
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
    pure = PurePosixPath(path)
    suffix = pure.suffix.lower()
    if suffix:
        lang = _LANG_BY_SUFFIX.get(suffix)
        if lang is not None:
            return lang
    name = pure.name.lower()
    if name in _LANG_BY_NAME:
        return _LANG_BY_NAME[name]
    # `web.Dockerfile`, `base.dockerfile`, etc.: identity is the suffix-as-name.
    if suffix and suffix[1:] in _LANG_BY_NAME:
        return _LANG_BY_NAME[suffix[1:]]
    return None


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


# Directory names that mark a test tree, and filename patterns for test modules.
# Matched on whole path segments / filename stems — NOT a bare substring — so
# `contest/`, `latest.py`, or `testimonials.ts` are never mistaken for tests.
_TEST_DIRS = {"test", "tests", "__tests__", "__test__", "testing", "spec", "specs", "e2e"}


def is_test_path(path: str) -> bool:
    pure = PurePosixPath(path.replace("\\", "/"))
    if any(part.lower() in _TEST_DIRS for part in pure.parts[:-1]):
        return True
    name = pure.name.lower()
    stem = name.split(".", 1)[0]
    if stem == "test" or stem.startswith("test_") or stem.endswith("_test"):
        return True
    return ".test." in name or ".spec." in name
