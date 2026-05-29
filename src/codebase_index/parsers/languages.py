"""Per-language tree-sitter specs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

CONTAINER_KINDS = {"class", "interface", "enum"}


_PY_IMPORTS = """
    (import_from_statement module_name: (dotted_name) @import.module)
    (import_statement name: (dotted_name) @import.module)
    (class_definition superclasses: (argument_list (identifier) @extends.base))
"""

_JS_IMPORTS = """
    (import_statement source: (string (string_fragment) @import.module))
    (class_declaration (class_heritage (identifier) @extends.base))
"""

_TS_IMPORTS = """
    (import_statement source: (string (string_fragment) @import.module))
    (class_declaration (class_heritage
        (extends_clause value: (identifier) @extends.base)))
    (class_declaration (class_heritage
        (implements_clause (type_identifier) @implements.iface)))
"""


@dataclass(frozen=True)
class LangSpec:
    name: str
    ts_name: str
    defs_query: str
    calls_query: str
    imports_query: str = ""


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
    imports_query=_PY_IMPORTS,
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
    imports_query=_JS_IMPORTS,
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
    imports_query=_TS_IMPORTS,
)

LANGS: dict[str, LangSpec] = {s.name: s for s in (_PYTHON, _JAVASCRIPT, _TYPESCRIPT)}


def is_supported(lang: Optional[str]) -> bool:
    return lang in LANGS


def spec_for(lang: Optional[str]) -> Optional[LangSpec]:
    return LANGS.get(lang) if lang else None
