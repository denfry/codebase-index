"""Shared parser types."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Protocol


@dataclass
class Chunk:
    line_start: int
    line_end: int
    content: str
    token_est: int
    kind: str = "window"
    symbol_index: Optional[int] = None


@dataclass
class Symbol:
    name: str
    kind: str
    line_start: int
    line_end: int
    qualified: Optional[str] = None
    signature: Optional[str] = None
    parent_index: Optional[int] = None
    docstring: Optional[str] = None


@dataclass
class ParseResult:
    chunks: list[Chunk] = field(default_factory=list)
    symbols: list[Symbol] = field(default_factory=list)


class Parser(Protocol):
    def parse(self, text: str) -> ParseResult: ...
