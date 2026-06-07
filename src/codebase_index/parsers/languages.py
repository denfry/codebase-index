"""Per-language tree-sitter specs."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

CONTAINER_KINDS = {"class", "interface", "enum", "struct", "trait", "impl", "record"}


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

# --- Tier A: compiled / back-end languages ------------------------------------------------------
# NOTE: symbol extraction is driven by treesitter._definition_kind (node-type mapping), not by
# defs_query. These queries are kept as compile-checked documentation of the relevant node types
# and to power graph edges (imports_query). See tests/test_languages.py.

_JAVA = LangSpec(
    name="java",
    ts_name="java",
    defs_query="""
        (class_declaration name: (identifier) @name) @def.class
        (interface_declaration name: (identifier) @name) @def.interface
        (enum_declaration name: (identifier) @name) @def.enum
        (record_declaration name: (identifier) @name) @def.record
        (method_declaration name: (identifier) @name) @def.method
        (constructor_declaration name: (identifier) @name) @def.method
    """,
    calls_query="(method_invocation name: (identifier) @callee)",
    imports_query="""
        (import_declaration (scoped_identifier) @import.module)
        (superclass (type_identifier) @extends.base)
        (super_interfaces (type_list (type_identifier) @implements.iface))
    """,
)

_GO = LangSpec(
    name="go",
    ts_name="go",
    defs_query="""
        (function_declaration name: (identifier) @name) @def.function
        (method_declaration name: (field_identifier) @name) @def.method
        (type_spec name: (type_identifier) @name) @def.type
    """,
    calls_query="(call_expression function: (identifier) @callee)",
    imports_query="(import_spec (interpreted_string_literal) @import.module)",
)

_RUST = LangSpec(
    name="rust",
    ts_name="rust",
    defs_query="""
        (function_item name: (identifier) @name) @def.function
        (struct_item name: (type_identifier) @name) @def.struct
        (enum_item name: (type_identifier) @name) @def.enum
        (trait_item name: (type_identifier) @name) @def.trait
        (impl_item type: (type_identifier) @name) @def.impl
        (mod_item name: (identifier) @name) @def.module
    """,
    calls_query="(call_expression function: (identifier) @callee)",
    imports_query="""
        (use_declaration (scoped_identifier) @import.module)
        (use_declaration (identifier) @import.module)
        (use_declaration (use_as_clause) @import.module)
        (use_declaration (scoped_use_list) @import.module)
    """,
)

_C = LangSpec(
    name="c",
    ts_name="c",
    defs_query="""
        (function_definition
            declarator: (function_declarator declarator: (identifier) @name)) @def.function
        (struct_specifier name: (type_identifier) @name) @def.struct
    """,
    calls_query="(call_expression function: (identifier) @callee)",
    imports_query="""
        (preproc_include path: (system_lib_string) @import.module)
        (preproc_include path: (string_literal) @import.module)
    """,
)

_CPP = LangSpec(
    name="cpp",
    ts_name="cpp",
    defs_query="""
        (function_definition
            declarator: (function_declarator declarator: (identifier) @name)) @def.function
        (class_specifier name: (type_identifier) @name) @def.class
        (struct_specifier name: (type_identifier) @name) @def.struct
        (namespace_definition name: (namespace_identifier) @name) @def.module
    """,
    calls_query="(call_expression function: (identifier) @callee)",
    imports_query="""
        (preproc_include path: (system_lib_string) @import.module)
        (preproc_include path: (string_literal) @import.module)
        (base_class_clause (type_identifier) @extends.base)
    """,
)

_CSHARP = LangSpec(
    name="csharp",
    ts_name="csharp",
    defs_query="""
        (class_declaration name: (identifier) @name) @def.class
        (interface_declaration name: (identifier) @name) @def.interface
        (struct_declaration name: (identifier) @name) @def.struct
        (enum_declaration name: (identifier) @name) @def.enum
        (method_declaration name: (identifier) @name) @def.method
        (constructor_declaration name: (identifier) @name) @def.method
    """,
    calls_query="(invocation_expression function: (identifier) @callee)",
    imports_query="""
        (using_directive (identifier) @import.module)
        (using_directive (qualified_name) @import.module)
        (base_list (identifier) @extends.base)
    """,
)

_RUBY = LangSpec(
    name="ruby",
    ts_name="ruby",
    defs_query="""
        (class name: (constant) @name) @def.class
        (module name: (constant) @name) @def.module
        (method name: (identifier) @name) @def.method
    """,
    calls_query="(call method: (identifier) @callee)",
    imports_query="(superclass (constant) @extends.base)",
)

_PHP = LangSpec(
    name="php",
    ts_name="php",
    defs_query="""
        (class_declaration name: (name) @name) @def.class
        (interface_declaration name: (name) @name) @def.interface
        (trait_declaration name: (name) @name) @def.trait
        (method_declaration name: (name) @name) @def.method
        (function_definition name: (name) @name) @def.function
    """,
    calls_query="(function_call_expression function: (name) @callee)",
    imports_query="""
        (namespace_use_declaration (namespace_use_clause (qualified_name) @import.module))
        (base_clause (name) @extends.base)
        (class_interface_clause (name) @implements.iface)
    """,
)

_KOTLIN = LangSpec(
    name="kotlin",
    ts_name="kotlin",
    defs_query="""
        (class_declaration (type_identifier) @name) @def.class
        (object_declaration (type_identifier) @name) @def.class
        (function_declaration (simple_identifier) @name) @def.function
    """,
    calls_query="(call_expression (simple_identifier) @callee)",
    imports_query="(import_header (identifier) @import.module)",
)

LANGS: dict[str, LangSpec] = {
    s.name: s
    for s in (
        _PYTHON,
        _JAVASCRIPT,
        _TYPESCRIPT,
        _JAVA,
        _GO,
        _RUST,
        _C,
        _CPP,
        _CSHARP,
        _RUBY,
        _PHP,
        _KOTLIN,
    )
}


def has_grammar(lang: Optional[str]) -> bool:
    """True if a tree-sitter grammar is loadable for `lang` (Tier B eligibility)."""
    if not lang:
        return False
    try:
        from tree_sitter_language_pack import get_language

        return get_language(lang) is not None
    except Exception:
        return False


def is_supported(lang: Optional[str]) -> bool:
    """A language is supported if it has a Tier-A spec OR a loadable Tier-B grammar."""
    if lang in LANGS:
        return True
    return has_grammar(lang)


def spec_for(lang: Optional[str]) -> Optional[LangSpec]:
    return LANGS.get(lang) if lang else None


def has_full_graph(lang: Optional[str]) -> bool:
    """True if `lang` has a Tier-A spec (full import/inheritance edges for refs/impact).

    Tier-B languages (a loadable grammar but no hand-tuned spec) yield symbols and
    best-effort call sites only, so their dependency graph is partial.
    """
    return spec_for(lang) is not None
