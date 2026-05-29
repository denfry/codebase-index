"""Symbol-aligned chunking with fallback line windows."""

from __future__ import annotations

from .base import Chunk, Symbol
from .line_chunker import chunk_text, estimate_tokens

_GAP_WINDOW = 80
_GAP_OVERLAP = 0


def build_chunks(text: str, symbols: list[Symbol]) -> list[Chunk]:
    if not text.strip():
        return []
    if not symbols:
        return chunk_text(text, window_lines=80, overlap_lines=10)

    lines = text.splitlines()
    top = sorted(
        [s for s in symbols if s.parent_index is None],
        key=lambda s: s.line_start,
    )

    chunks: list[Chunk] = []
    cursor = 1
    for symbol in top:
        symbol_index = symbols.index(symbol)
        if symbol.line_start > cursor:
            chunks.extend(_gap(lines, cursor, symbol.line_start - 1))
        body = "\n".join(lines[symbol.line_start - 1 : symbol.line_end])
        chunks.append(
            Chunk(
                line_start=symbol.line_start,
                line_end=symbol.line_end,
                content=body,
                token_est=estimate_tokens(body),
                kind="symbol_body",
                symbol_index=symbol_index,
            )
        )
        cursor = max(cursor, symbol.line_end + 1)
    if cursor <= len(lines):
        chunks.extend(_gap(lines, cursor, len(lines)))
    return chunks


def _gap(lines: list[str], start: int, end: int) -> list[Chunk]:
    segment = "\n".join(lines[start - 1 : end])
    if not segment.strip():
        return []
    out: list[Chunk] = []
    for chunk in chunk_text(segment, window_lines=_GAP_WINDOW, overlap_lines=_GAP_OVERLAP):
        out.append(
            Chunk(
                line_start=start + chunk.line_start - 1,
                line_end=start + chunk.line_end - 1,
                content=chunk.content,
                token_est=chunk.token_est,
                kind="window",
            )
        )
    return out
