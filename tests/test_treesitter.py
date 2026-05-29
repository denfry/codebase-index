from __future__ import annotations

from codebase_index.parsers.base import Symbol
from codebase_index.parsers.symbol_chunks import build_chunks
from codebase_index.parsers.treesitter import parse_file

PY = '''\
"""mod doc"""
import os


def refresh_access_token(refresh_token):
    """Exchange refresh for access."""
    return "access-" + refresh_token


class User:
    def __init__(self, name):
        self.name = name
'''


def test_python_symbols():
    pr = parse_file("python", PY)
    by_name = {s.name: s for s in pr.symbols}
    assert "refresh_access_token" in by_name
    fn = by_name["refresh_access_token"]
    assert fn.kind == "function"
    assert fn.line_start == 5
    assert fn.signature.startswith("def refresh_access_token(")
    assert "Exchange refresh" in (fn.docstring or "")

    assert by_name["User"].kind == "class"
    init = by_name["__init__"]
    assert init.kind == "method"
    assert init.qualified == "User.__init__"


TS = '''\
export function bootstrap(): void {
  start();
}

export class Service {
  run(): void {}
}

interface Options { x: number; }
'''


def test_typescript_symbols():
    pr = parse_file("typescript", TS)
    kinds = {s.name: s.kind for s in pr.symbols}
    assert kinds["bootstrap"] == "function"
    assert kinds["Service"] == "class"
    assert kinds["run"] == "method"
    assert kinds["Options"] == "interface"


def test_symbol_body_chunks_link_symbols():
    text = "import os\n\n\ndef a():\n    return 1\n\n\ndef b():\n    return 2\n"
    symbols = [
        Symbol(name="a", kind="function", line_start=4, line_end=5),
        Symbol(name="b", kind="function", line_start=8, line_end=9),
    ]
    chunks = build_chunks(text, symbols)
    bodies = [c for c in chunks if c.kind == "symbol_body"]
    assert len(bodies) == 2
    assert bodies[0].symbol_index == 0 and bodies[0].line_start == 4
    assert bodies[1].symbol_index == 1
    gaps = [c for c in chunks if c.kind == "window"]
    assert any(g.line_start == 1 for g in gaps)


def test_no_symbols_falls_back_to_windows():
    text = "x = 1\ny = 2\n"
    chunks = build_chunks(text, [])
    assert chunks and all(c.kind == "window" for c in chunks)
