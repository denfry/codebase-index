"""Extract document-style chunks from non-code content for FTS5 indexing.

Produces chunks of kind="doc" from:
- Markdown headings (# Heading)
- README sections (first 200 chars under each heading)
- Test function names (test_* in Python)
- Function/class docstrings
- Exception messages (raise X("message"))
- Config keys (.codeindex.json, pyproject.toml)
"""

from __future__ import annotations

import json
import re
from typing import Optional

from ..parsers.base import Chunk

_MD_HEADING_RE = re.compile(r'^(#{1,6})\s+(.+)$', re.MULTILINE)
_TEST_FUNC_RE = re.compile(r'def\s+(test_\w+)\s*\(', re.MULTILINE)
_DOCSTRING_RE = re.compile(r'(?:def|class)\s+\w+[\s\S]*?("""[\s\S]*?""")')
_EXCEPTION_RE = re.compile(r'raise\s+\w+\s*\(\s*["\'](.+?)["\']', re.MULTILINE)


def extract_doc_chunks(text: str, rel_path: str, lang: Optional[str]) -> list[Chunk]:
    """Extract all doc-style chunks from a file."""
    chunks: list[Chunk] = []

    if lang == "markdown":
        chunks.extend(_extract_md_headings(text))
        chunks.extend(_extract_readme_sections(text))
    elif lang == "python":
        chunks.extend(_extract_test_names(text))
        chunks.extend(_extract_docstrings(text))
        chunks.extend(_extract_exception_messages(text))
    elif lang in ("json", "toml"):
        chunks.extend(_extract_config_keys(text, lang))
    elif rel_path.endswith(".py"):
        chunks.extend(_extract_test_names(text))
        chunks.extend(_extract_docstrings(text))
        chunks.extend(_extract_exception_messages(text))

    return chunks


def _extract_md_headings(text: str) -> list[Chunk]:
    """Extract markdown headings as searchable chunks."""
    chunks = []
    for match in _MD_HEADING_RE.finditer(text):
        line_num = text[:match.start()].count('\n') + 1
        heading = match.group(0).strip()
        token_est = max(1, len(heading) // 4)
        chunks.append(Chunk(
            line_start=line_num,
            line_end=line_num,
            content=heading,
            token_est=token_est,
            kind="doc",
        ))
    return chunks


def _extract_readme_sections(text: str) -> list[Chunk]:
    """Extract first 200 chars under each markdown heading."""
    chunks = []
    headings = list(_MD_HEADING_RE.finditer(text))

    for i, match in enumerate(headings):
        heading_text = match.group(0).strip()
        start = match.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        section_body = text[start:end].strip()[:200]

        if section_body:
            line_start = text[:match.start()].count('\n') + 1
            line_end = text[:start + len(section_body)].count('\n') + 1
            content = f"{heading_text}: {section_body}"
            token_est = max(1, len(content) // 4)
            chunks.append(Chunk(
                line_start=line_start,
                line_end=line_end,
                content=content,
                token_est=token_est,
                kind="doc",
            ))

    return chunks


def _extract_test_names(text: str) -> list[Chunk]:
    """Extract test function names as searchable chunks."""
    chunks = []
    for match in _TEST_FUNC_RE.finditer(text):
        line_num = text[:match.start()].count('\n') + 1
        func_name = match.group(1)
        token_est = max(1, len(func_name) // 4)
        chunks.append(Chunk(
            line_start=line_num,
            line_end=line_num,
            content=f"test function: {func_name}",
            token_est=token_est,
            kind="doc",
        ))
    return chunks


def _extract_docstrings(text: str) -> list[Chunk]:
    """Extract function/class docstrings as searchable chunks."""
    chunks = []
    for match in _DOCSTRING_RE.finditer(text):
        line_start = text[:match.start()].count('\n') + 1
        docstring = match.group(1).strip('"""').strip()
        if docstring and len(docstring) > 10:
            line_end = text[:match.end()].count('\n') + 1
            token_est = max(1, len(docstring) // 4)
            chunks.append(Chunk(
                line_start=line_start,
                line_end=line_end,
                content=docstring[:500],
                token_est=token_est,
                kind="doc",
            ))
    return chunks


def _extract_exception_messages(text: str) -> list[Chunk]:
    """Extract exception messages as searchable chunks."""
    chunks = []
    for match in _EXCEPTION_RE.finditer(text):
        line_num = text[:match.start()].count('\n') + 1
        msg = match.group(1)
        token_est = max(1, len(msg) // 4)
        chunks.append(Chunk(
            line_start=line_num,
            line_end=line_num,
            content=f"exception: {msg}",
            token_est=token_est,
            kind="doc",
        ))
    return chunks


def _extract_config_keys(text: str, lang: str) -> list[Chunk]:
    """Extract config keys from JSON/TOML files."""
    chunks = []
    if lang == "json":
        try:
            data = json.loads(text)
            keys = _flatten_json_keys(data)
            for key_path, value in keys:
                line_est = 1
                content = f"config key: {key_path} = {_truncate_value(value)}"
                token_est = max(1, len(content) // 4)
                chunks.append(Chunk(
                    line_start=line_est,
                    line_end=line_est,
                    content=content,
                    token_est=token_est,
                    kind="doc",
                ))
        except json.JSONDecodeError:
            pass
    elif lang == "toml":
        for match in re.finditer(r'^([\w.]+)\s*=', text, re.MULTILINE):
            line_num = text[:match.start()].count('\n') + 1
            key = match.group(1)
            content = f"config key: {key}"
            token_est = max(1, len(content) // 4)
            chunks.append(Chunk(
                line_start=line_num,
                line_end=line_num,
                content=content,
                token_est=token_est,
                kind="doc",
            ))
    return chunks


def _flatten_json_keys(data, prefix: str = "") -> list[tuple[str, str]]:
    """Flatten nested JSON into dot-notation key paths."""
    result = []
    if isinstance(data, dict):
        for k, v in data.items():
            path = f"{prefix}.{k}" if prefix else k
            if isinstance(v, (dict, list)):
                result.extend(_flatten_json_keys(v, path))
            else:
                result.append((path, v))
    elif isinstance(data, list):
        for i, v in enumerate(data):
            path = f"{prefix}[{i}]"
            if isinstance(v, (dict, list)):
                result.extend(_flatten_json_keys(v, path))
            else:
                result.append((path, v))
    return result


def _truncate_value(value, max_len: int = 100) -> str:
    s = str(value)
    return s if len(s) <= max_len else s[:max_len] + "..."
