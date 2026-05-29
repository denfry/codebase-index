"""Tree-sitter parsing: text -> symbols, intra-file call edges, and chunks."""

from __future__ import annotations

from typing import Optional

from tree_sitter import Parser, Query, QueryCursor
from tree_sitter_language_pack import get_language

from .base import Edge, ParseResult, Symbol
from .languages import CONTAINER_KINDS, has_grammar, spec_for
from .symbol_chunks import build_chunks


class UnsupportedLanguage(Exception):
    pass


def parse_file(lang: str, text: str) -> ParseResult:
    spec = spec_for(lang)
    # Tier A (hand-tuned spec) or Tier B (any loadable grammar). Only raise when no grammar
    # exists at all, so "any language with a grammar" produces symbols, not a silent fallback.
    ts_name = spec.ts_name if spec is not None else lang
    if spec is None and not has_grammar(lang):
        raise UnsupportedLanguage(lang)

    grammar = get_language(ts_name)
    parser = Parser(grammar)
    source = text.encode("utf-8")
    tree = parser.parse(source)
    if tree is None:
        raise ValueError("tree-sitter parser returned no tree")
    root = tree.root_node

    if spec is not None:
        symbols = _extract_symbols(root, lang, source)
    else:
        symbols = _extract_symbols_generic(root, source)
    edges = _extract_edges(root, symbols, source)
    if spec is not None:
        edges.extend(_extract_graph_edges(spec, grammar, root, symbols))
    del grammar
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
        name_node = _name_node(def_node)
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


# Maps a tree-sitter node `type` to a coarse symbol kind. Node types are largely unique across
# grammars, so a single table covers Java/Go/Rust/C/C++/C#/Ruby/PHP/Kotlin/JS/TS at once.
_DEF_KINDS: dict[str, str] = {
    # functions
    "function_declaration": "function",  # go, kotlin, js
    "function_definition": "function",  # c, cpp, php  (python handled separately below)
    "function_item": "function",  # rust
    "function_signature_item": "function",  # rust trait method signatures
    # methods
    "method_declaration": "method",  # go, java, csharp
    "method_definition": "method",  # js/ts
    "constructor_declaration": "method",  # java, csharp
    "method": "method",  # ruby
    # classes / type-like containers
    "class_declaration": "class",  # java, csharp, php, kotlin, js/ts
    "class_specifier": "class",  # cpp
    "class": "class",  # ruby
    "object_declaration": "class",  # kotlin
    "record_declaration": "record",  # java
    "struct_item": "struct",  # rust
    "struct_specifier": "struct",  # c, cpp
    "struct_declaration": "struct",  # csharp
    "interface_declaration": "interface",  # java, csharp, php, ts
    "trait_item": "trait",  # rust
    "trait_declaration": "trait",  # php
    "enum_declaration": "enum",  # java, csharp, ts
    "enum_item": "enum",  # rust
    "enum_specifier": "enum",  # c/cpp
    "impl_item": "impl",  # rust
    # modules / namespaces (NOT containers — a function inside stays a function, not a method)
    "mod_item": "module",  # rust
    "module": "module",  # ruby
    "namespace_definition": "module",  # cpp
    "namespace_declaration": "module",  # csharp
    "type_alias_declaration": "type",  # ts
}


def _definition_kind(node, lang: str) -> Optional[str]:
    kind = _kind(node)
    if lang == "python":
        if kind == "function_definition":
            return "function"
        if kind == "class_definition":
            return "class"
        return None
    if kind == "type_spec":  # go: refine struct/interface from the underlying type
        underlying = _field(node, "type")
        u = _kind(underlying) if underlying is not None else ""
        if u == "struct_type":
            return "struct"
        if u == "interface_type":
            return "interface"
        return "type"
    mapped = _DEF_KINDS.get(kind)
    if mapped is not None:
        return mapped
    if kind == "variable_declarator":
        value = _field(node, "value")
        if value is not None and _kind(value) in {"arrow_function", "function_expression"}:
            return "function"
    return None


# Identifier-like node types that can carry a definition's name across grammars.
_NAME_NODE_TYPES = {
    "identifier",
    "type_identifier",
    "field_identifier",
    "property_identifier",
    "simple_identifier",
    "constant",
    "name",
    "namespace_identifier",
}


def _name_node(def_node):
    """Find the name node for a definition, tolerating grammars without a "name" field.

    Handles: field "name" (most), Rust `impl_item` (field "type"), C/C++ function definitions
    (name nested under the declarator), and fieldless grammars (Kotlin) via a child scan.
    """
    named = _field(def_node, "name")
    if named is not None:
        return named
    kind = _kind(def_node)
    if kind == "impl_item":
        return _field(def_node, "type")
    if kind == "function_definition":  # c / cpp: descend the declarator chain
        decl = _field(def_node, "declarator")
        return _declarator_identifier(decl) if decl is not None else None
    for child in _named_children(def_node):
        if _kind(child) in _NAME_NODE_TYPES:
            return child
    return None


def _declarator_identifier(node):
    if node is None:
        return None
    if _kind(node) in {"identifier", "field_identifier"}:
        return node
    inner = _field(node, "declarator")
    if inner is not None:
        return _declarator_identifier(inner)
    for child in _named_children(node):
        found = _declarator_identifier(child)
        if found is not None:
            return found
    return None


def _extract_symbols_generic(root, source: bytes) -> list[Symbol]:
    """Tier B: harvest definition-like nodes from an untuned grammar.

    Any node whose `type` ends in declaration/definition/_item/_specifier and that has an
    identifier-like named child is treated as a symbol; kind is a coarse keyword mapping.
    """
    raw: list[_Sym] = []
    for node in _walk(root):
        ntype = _kind(node)
        if not ntype.endswith(("declaration", "definition", "_item", "_specifier")):
            continue
        name_node = _name_node(node)
        if name_node is None:
            continue
        raw.append(
            _Sym(
                Symbol(
                    name=_node_text(name_node, source),
                    kind=_generic_kind(ntype),
                    line_start=_row(_start_point(node)) + 1,
                    line_end=_row(_end_point(node)) + 1,
                    signature=_signature(node, source),
                ),
                node,
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
        item.symbol.qualified = (
            f"{parent.symbol.qualified or parent.symbol.name}.{item.symbol.name}"
        )
    return [item.symbol for item in raw]


def _generic_kind(ntype: str) -> str:
    low = ntype.lower()
    for key in ("class", "struct", "enum", "interface", "trait", "module", "namespace"):
        if key in low:
            return "struct" if key == "struct" else key
    return "function"


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


_EDGE_PREFIXES = {"import.": "import", "extends.": "extends", "implements.": "implements"}


def _extract_graph_edges(spec, grammar, root, symbols) -> list[Edge]:
    if not spec.imports_query:
        return []
    query = Query(grammar, spec.imports_query)
    cursor = QueryCursor(query)
    edges: list[Edge] = []
    for _pattern_idx, captures in cursor.matches(root):
        for capture_name, nodes in captures.items():
            for node in nodes:
                edge_type = next(
                    (et for pfx, et in _EDGE_PREFIXES.items() if capture_name.startswith(pfx)),
                    None,
                )
                if edge_type is None:
                    continue
                line = _row(node.start_point) + 1
                src_idx = None if edge_type == "import" else _enclosing_symbol_index(symbols, line)
                edges.append(Edge(
                    edge_type=edge_type,
                    callee_name=_text(node).strip().strip('"').strip("'"),
                    line=line,
                    src_symbol_index=src_idx,
                ))
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


_CALLEE_LEAVES = {"identifier", "property_identifier", "field_identifier", "simple_identifier"}


def _callee_node(node):
    kind = _kind(node)
    if kind == "method_invocation":  # java: obj.method(...) / method(...)
        return _field(node, "name")
    if kind == "macro_invocation":  # rust: name!(...)
        return _field(node, "macro")
    if kind not in {"call", "call_expression", "invocation_expression", "function_call_expression"}:
        return None
    # ruby `call` uses field "method"; everything else uses field "function".
    fn = _field(node, "function") or _field(node, "method")
    if fn is None:
        return None
    if _kind(fn) in _CALLEE_LEAVES:
        return fn
    # member / selector / scoped / field access: take the trailing identifier.
    attr = (
        _field(fn, "attribute")
        or _field(fn, "property")
        or _field(fn, "field")
        or _field(fn, "name")
    )
    if attr is not None and _kind(attr) in _CALLEE_LEAVES:
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
