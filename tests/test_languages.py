from __future__ import annotations

import pytest
from tree_sitter_language_pack import get_language

from codebase_index.parsers.languages import LANGS, is_supported, spec_for


def test_supported_set():
    assert is_supported("python")
    assert is_supported("typescript")
    assert is_supported("javascript")
    # Tier A now covers the common back-end languages.
    assert is_supported("java")
    assert spec_for("ruby") is not None
    # Tier B: any loadable grammar counts as supported even without a hand-tuned spec.
    assert is_supported("lua")
    assert spec_for("lua") is None
    # No grammar at all -> not supported.
    assert not is_supported("notalang_xyz")


@pytest.mark.parametrize("lang", sorted(LANGS))
def test_every_query_compiles_against_its_grammar(lang):
    spec = spec_for(lang)
    grammar = get_language(spec.ts_name)
    grammar.query(spec.defs_query)
    grammar.query(spec.calls_query)


def test_every_imports_query_compiles_against_its_grammar():
    from tree_sitter_language_pack import get_language

    from codebase_index.parsers.languages import LANGS, spec_for

    for lang in sorted(LANGS):
        spec = spec_for(lang)
        # imports_query must exist and compile (raises on a wrong node type/field)
        get_language(spec.ts_name).query(spec.imports_query)


def test_python_imports_query_has_module_and_base_captures():
    from codebase_index.parsers.languages import spec_for

    q = spec_for("python").imports_query
    assert "@import.module" in q
    assert "@extends.base" in q
