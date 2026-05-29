"""Tree-sitter parsing: text -> symbols, intra-file call edges, and chunks."""

from __future__ import annotations

from typing import Optional

from tree_sitter_language_pack import get_language, get_parser

from .base import Edge, ParseResult, Symbol
from .languages import CONTAINER_KINDS, spec_for
from .symbol_chunks import build_chunks


class UnsupportedLanguage(Exception):
    pass


def parse_file(lang: str, text: str) -> ParseResult:
    spec = spec_for(lang)
    if spec is None:
        raise UnsupportedLanguage(lang)

    grammar = get_language(spec.ts_name)
    parser = get_parser(spec.ts_name)
    tree = parser.parse(text)
    if tree is None:
        raise ValueError("tree-sitter parser returned no tree")
    root_attr = tree.root_node
    root = root_attr() if callable(root_attr) else root_attr

    del grammar
    source = text.encode("utf-8")
    symbols = _extract_symbols(root, lang, source)
    edges = _extract_edges(root, symbols, source)
    chunks = build_chunks(text, symbols)
    return ParseResult(chunks=chunks, symbols=symbols, edges=edges)


def _row(point) -> int:
    return point.row if hasattr(point, "row") else point[0]


def _text(node) -> str:
    raw = getattr(node, "text", None)
    if callable(raw):
        raw = raw()
    if isinstance(raw, bytes):
        return raw.decode("utf-8", errors="ignore")
    return raw if isinstance(raw, str) else ""


class _Sym:
    __slots__ = ("symbol", "start_byte", "end_byte")

    def __init__(self, symbol: Symbol, def_node) -> None:
        self.symbol = symbol
        self.start_byte, self.end_byte = _byte_range(def_node)


def _extract_symbols(root, lang: str, source: bytes) -> list[Symbol]:
    raw: list[_Sym] = []
    for def_node in _walk(root):
        kind = _definition_kind(def_node, lang)
        if kind is None:
            continue
        name_node = _field(def_node, "name")
        if name_node is None:
            continue
        raw.append(
            _Sym(
                Symbol(
                    name=_node_text(name_node, source),
                    kind=kind,
                    line_start=_row(_start_point(def_node)) + 1,
                    line_end=_row(_end_point(def_node)) + 1,
                    signature=_signature(def_node, source),
                    docstring=_python_docstring(def_node, source) if lang == "python" else None,
                ),
                def_node,
            )
        )

    raw.sort(key=lambda item: (item.start_byte, -(item.end_byte - item.start_byte)))
    for item in raw:
        parent = _enclosing(raw, item)
        if parent is None:
            item.symbol.qualified = item.symbol.name
            continue
        item.symbol.parent_index = raw.index(parent)
        if item.symbol.kind == "function" and parent.symbol.kind in CONTAINER_KINDS:
            item.symbol.kind = "method"
        item.symbol.qualified = f"{parent.symbol.qualified or parent.symbol.name}.{item.symbol.name}"
    return [item.symbol for item in raw]


def _definition_kind(node, lang: str) -> Optional[str]:
    kind = _kind(node)
    if lang == "python":
        if kind == "function_definition":
            return "function"
        if kind == "class_definition":
            return "class"
        return None
    if kind == "function_declaration":
        return "function"
    if kind == "class_declaration":
        return "class"
    if kind == "method_definition":
        return "method"
    if kind == "interface_declaration":
        return "interface"
    if kind == "enum_declaration":
        return "enum"
    if kind == "type_alias_declaration":
        return "type"
    if kind == "variable_declarator":
        value = _field(node, "value")
        if value is not None and _kind(value) in {"arrow_function", "function_expression"}:
            return "function"
    return None


def _signature(def_node, source: bytes) -> str:
    return _node_text(def_node, source).splitlines()[0].strip().rstrip("{").strip()


def _python_docstring(def_node, source: bytes) -> Optional[str]:
    body = _field(def_node, "body")
    if body is None:
        return None
    for stmt in _named_children(body):
        if _kind(stmt) == "string":
            return _node_text(stmt, source).strip().strip('"').strip("'").strip()
        if _kind(stmt) == "expression_statement":
            children = _named_children(stmt)
            if children and _kind(children[0]) == "string":
                return _node_text(children[0], source).strip().strip('"').strip("'").strip()
        break
    return None


def _enclosing(raw: list[_Sym], child: _Sym) -> Optional[_Sym]:
    best: Optional[_Sym] = None
    for other in raw:
        if other is child:
            continue
        if other.start_byte <= child.start_byte and other.end_byte >= child.end_byte:
            other_span = other.end_byte - other.start_byte
            child_span = child.end_byte - child.start_byte
            if other_span <= child_span:
                continue
            if best is None or other_span < best.end_byte - best.start_byte:
                best = other
    return best


def _extract_edges(root, symbols: list[Symbol], source: bytes) -> list[Edge]:
    edges: list[Edge] = []
    for node in _walk(root):
        callee = _callee_node(node)
        if callee is None:
            continue
        line = _row(_start_point(callee)) + 1
        edges.append(
            Edge(
                edge_type="call",
                callee_name=_node_text(callee, source),
                line=line,
                src_symbol_index=_enclosing_symbol_index(symbols, line),
            )
        )
    return edges


def _enclosing_symbol_index(symbols: list[Symbol], line: int) -> Optional[int]:
    best_idx: Optional[int] = None
    best_span: Optional[int] = None
    for idx, symbol in enumerate(symbols):
        if symbol.line_start <= line <= symbol.line_end:
            span = symbol.line_end - symbol.line_start
            if best_span is None or span < best_span:
                best_idx = idx
                best_span = span
    return best_idx


def _callee_node(node):
    kind = _kind(node)
    if kind not in {"call", "call_expression"}:
        return None
    fn = _field(node, "function")
    if fn is None:
        return None
    if _kind(fn) in {"identifier", "property_identifier"}:
        return fn
    attr = _field(fn, "attribute") or _field(fn, "property")
    if attr is not None and _kind(attr) in {"identifier", "property_identifier"}:
        return attr
    return None


def _kind(node) -> str:
    value = getattr(node, "type", None)
    if value is None:
        value = getattr(node, "kind", None)
    resolved = value() if callable(value) else value
    return resolved if isinstance(resolved, str) else ""


def _field(node, name: str):
    return node.child_by_field_name(name)


def _start_point(node):
    value = getattr(node, "start_point", None)
    if value is None:
        value = getattr(node, "start_position", None)
    return value() if callable(value) else value


def _end_point(node):
    value = getattr(node, "end_point", None)
    if value is None:
        value = getattr(node, "end_position", None)
    return value() if callable(value) else value


def _byte_range(node) -> tuple[int, int]:
    start = getattr(node, "start_byte", None)
    end = getattr(node, "end_byte", None)
    if start is not None and end is not None:
        return (start() if callable(start) else start, end() if callable(end) else end)
    br = node.byte_range()
    return br.start, br.end


def _node_text(node, source: bytes) -> str:
    start, end = _byte_range(node)
    return source[start:end].decode("utf-8", errors="ignore")


def _named_children(node) -> list[object]:
    children = getattr(node, "named_children", None)
    if children is not None:
        return list(children() if callable(children) else children)
    count = node.named_child_count() if callable(node.named_child_count) else node.named_child_count
    return [node.named_child(i) for i in range(count)]


def _walk(node):
    yield node
    for child in _named_children(node):
        yield from _walk(child)
