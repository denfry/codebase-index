"""Multi-language symbol extraction (plan: make the skill actually win).

Tier A (hand-tuned): java, go, rust, c, cpp, csharp, ruby, php, kotlin.
Tier B (generic):    any grammar tree_sitter_language_pack provides.
Guardrail 1:         classify._TREE_SITTER_LANGS must not claim a language is
                     tree-sitter-parsed unless an extraction path exists.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codebase_index.discovery import classify
from codebase_index.parsers.languages import LANGS
from codebase_index.parsers.treesitter import parse_file

FIXTURES = Path(__file__).parent / "fixtures" / "multilang"


def _names(pr):
    """name -> first symbol with that name (lossy when a name is reused)."""
    out = {}
    for s in pr.symbols:
        out.setdefault(s.name, s)
    return out


def _has(pr, name, kind):
    """A symbol named `name` with kind `kind` exists (names can repeat, e.g. a class
    and its same-named constructor, or a Rust struct and its impl block)."""
    return any(s.name == name and s.kind == kind for s in pr.symbols)


def _get(pr, name, kind):
    return next(s for s in pr.symbols if s.name == name and s.kind == kind)


def test_java_symbols():
    pr = parse_file("java", (FIXTURES / "sample.java").read_text(encoding="utf-8"))
    assert _has(pr, "TownManager", "class")
    assert _has(pr, "createTown", "method")
    assert _has(pr, "removeTown", "method")
    # the constructor is its own definition, distinct from the class
    assert _has(pr, "TownManager", "method")
    create = _get(pr, "createTown", "method")
    assert create.line_start < create.line_end
    assert create.qualified == "TownManager.createTown"


def test_go_symbols():
    pr = parse_file("go", (FIXTURES / "sample.go").read_text(encoding="utf-8"))
    assert _has(pr, "Town", "struct")
    assert _has(pr, "NewTown", "function")
    assert _has(pr, "Greet", "method")


def test_rust_symbols():
    pr = parse_file("rust", (FIXTURES / "sample.rs").read_text(encoding="utf-8"))
    assert _has(pr, "Town", "struct")
    # functions inside an impl block become methods
    assert _has(pr, "new", "method")
    assert _has(pr, "greet", "method")


@pytest.mark.parametrize("lang", sorted(classify._TREE_SITTER_LANGS))
def test_registry_consistency_every_treesitter_lang_extracts(lang):
    """Guardrail 1: every lang classify labels 'treesitter' must yield >=1 symbol
    on a minimal sample (Tier A spec OR Tier B generic). Locks the registries."""
    sample = _MINIMAL_SAMPLES[lang]
    pr = parse_file(lang, sample)
    assert pr.symbols, f"{lang}: classify says treesitter but parse_file found no symbols"


def test_registry_consistency_every_tier_a_spec_is_routed_to_treesitter():
    """Guardrail 1 (reverse): a Tier-A spec is useless if classify routes the lang to
    line-chunking. Every LangSpec language must be in classify._TREE_SITTER_LANGS."""
    missing = sorted(set(LANGS) - classify._TREE_SITTER_LANGS)
    assert not missing, f"Tier-A specs not routed to tree-sitter by classify: {missing}"


def test_tier_b_generic_path_extracts_without_a_spec():
    """Tier B: a grammar-available language with NO hand-tuned spec still yields symbols."""
    assert "lua" not in LANGS  # no Tier-A spec
    pr = parse_file("lua", "local function greet(name)\n  return name\nend\n")
    assert any(s.name == "greet" for s in pr.symbols)


_MINIMAL_SAMPLES: dict[str, str] = {
    "python": "def f():\n    return 1\n",
    "javascript": "function f() { return 1; }\n",
    "typescript": "function f(): number { return 1; }\n",
    "java": "class A { void m() {} }\n",
    "go": "package p\nfunc F() {}\n",
    "rust": "fn f() {}\n",
    "c": "int f(void) { return 0; }\n",
    "cpp": "int f() { return 0; }\n",
    "csharp": "class A { void M() {} }\n",
    "ruby": "def f\nend\n",
    "php": "<?php\nfunction f() { return 1; }\n",
    "kotlin": "fun f() {}\n",
    "lua": "local function f()\n  return 1\nend\n",
}
