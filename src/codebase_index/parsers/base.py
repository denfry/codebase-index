"""Shared parser types."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import PurePosixPath
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
class Edge:
    edge_type: str
    callee_name: str
    line: int
    src_symbol_index: Optional[int] = None
    # What the call was made on, e.g. 'TownService' for `TownService.refresh(x)`;
    # None for a bare call or a receiver that is not a plain (dotted) name.
    receiver: Optional[str] = None


def module_name(path: str) -> str:
    """The name code uses for the module a file defines: `activation` for
    `src/activation.rs`, `auth` for `auth/__init__.py` or `auth/mod.rs`."""
    p = PurePosixPath(path)
    if p.stem in ("mod", "__init__", "index") and p.parent.name:
        return p.parent.name
    return p.stem


def names_a_type(receiver: Optional[str]) -> bool:
    """True when a call receiver reads as a type name: `TownService`, `Foo`.

    Not a variable (`town`), `this`/`self`, Rust's `Self` (the enclosing type), or
    a constant (`WOOD`, `MAX_SIZE`): those say nothing about which type is called.
    """
    return (
        receiver is not None
        and receiver[:1].isupper()
        and receiver != "Self"
        and not receiver.isupper()
    )


@dataclass
class ParseResult:
    chunks: list[Chunk] = field(default_factory=list)
    symbols: list[Symbol] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)


class Parser(Protocol):
    def parse(self, text: str) -> ParseResult: ...
