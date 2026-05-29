"""Fallback chunker: overlapping fixed-size line windows."""

from __future__ import annotations

from .base import Chunk

_CHARS_PER_TOKEN = 4


def estimate_tokens(text: str) -> int:
    return max(1, round(len(text) / _CHARS_PER_TOKEN))


def chunk_text(text: str, *, window_lines: int, overlap_lines: int) -> list[Chunk]:
    if not text or not text.strip():
        return []
    if overlap_lines >= window_lines:
        overlap_lines = window_lines - 1
    stride = window_lines - overlap_lines

    lines = text.splitlines()
    chunks: list[Chunk] = []
    start = 0
    while start < len(lines):
        end = min(start + window_lines, len(lines))
        body = "\n".join(lines[start:end])
        chunks.append(
            Chunk(
                line_start=start + 1,
                line_end=end,
                content=body,
                token_est=estimate_tokens(body),
                kind="window",
            )
        )
        if end >= len(lines):
            break
        start += stride
    return chunks
