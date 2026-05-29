"""Per-language tree-sitter specs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

CONTAINER_KINDS = {"class", "interface", "enum"}


@dataclass(frozen=True)
class LangSpec:
    name: str
    ts_name: str
    defs_query: str
    calls_query: str


_PYTHON = LangSpec(
    name="python",
    ts_name="python",
    defs_query="""
        (function_definition name: (identifier) @name) @def.function
        (class_definition    name: (identifier) @name) @def.class
    """,
    calls_query="""
        (call function: (identifier) @callee)
        (call function: (attribute attribute: (identifier) @callee))
    """,
)

_JS_DEFS = """
    (function_declaration name: (identifier) @name) @def.function
    (class_declaration    name: (identifier) @name) @def.class
    (method_definition    name: (property_identifier) @name) @def.method
    (variable_declarator  name: (identifier) @name value: (arrow_function)) @def.function
    (variable_declarator  name: (identifier) @name value: (function_expression)) @def.function
"""
_JS_CALLS = """
    (call_expression function: (identifier) @callee)
    (call_expression function: (member_expression property: (property_identifier) @callee))
"""

_JAVASCRIPT = LangSpec(
    name="javascript",
    ts_name="javascript",
    defs_query=_JS_DEFS,
    calls_query=_JS_CALLS,
)

_TS_DEFS = """
    (function_declaration name: (identifier) @name) @def.function
    (class_declaration    name: (type_identifier) @name) @def.class
    (method_definition    name: (property_identifier) @name) @def.method
    (variable_declarator  name: (identifier) @name value: (arrow_function)) @def.function
    (interface_declaration name: (type_identifier) @name) @def.interface
    (enum_declaration      name: (identifier) @name) @def.enum
    (type_alias_declaration name: (type_identifier) @name) @def.type
"""

_TYPESCRIPT = LangSpec(
    name="typescript",
    ts_name="typescript",
    defs_query=_TS_DEFS,
    calls_query=_JS_CALLS,
)

LANGS: dict[str, LangSpec] = {s.name: s for s in (_PYTHON, _JAVASCRIPT, _TYPESCRIPT)}


def is_supported(lang: Optional[str]) -> bool:
    return lang in LANGS


def spec_for(lang: Optional[str]) -> Optional[LangSpec]:
    return LANGS.get(lang) if lang else None
