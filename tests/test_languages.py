from __future__ import annotations

import pytest
from tree_sitter_language_pack import get_language

from codebase_index.parsers.languages import LANGS, is_supported, spec_for


def test_supported_set():
    assert is_supported("python")
    assert is_supported("typescript")
    assert is_supported("javascript")
    assert not is_supported("cobol")
    assert spec_for("ruby") is None


@pytest.mark.parametrize("lang", sorted(LANGS))
def test_every_query_compiles_against_its_grammar(lang):
    spec = spec_for(lang)
    grammar = get_language(spec.ts_name)
    grammar.query(spec.defs_query)
    grammar.query(spec.calls_query)
