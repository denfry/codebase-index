# Adding a language to symbol extraction

1. Confirm `discovery/classify.py` maps the extension to a language id, and its tree-sitter set
   includes that id.
2. Confirm `tree_sitter_language_pack.get_language("<grammar>")` works for the grammar name.
3. Append a `LangSpec` to `parsers/languages.py::LANGS` with:
   - `defs_query`: one pattern per definition kind, captured as `@def.<kind>` with the name node
     captured as `@name`. Kinds: function, method, class, interface, enum, type, var.
   - `calls_query`: capture the callee identifier as `@callee`.
4. Extend `parsers/treesitter.py` AST traversal for that grammar's definition and call node kinds
   when query execution is not stable for the installed `tree-sitter-language-pack`.
5. Add a fixture file under `tests/fixtures/sample_repo/` and a case in `tests/test_treesitter.py`.
6. Run `pytest tests/test_languages.py` so the compile-guard test catches wrong node types/fields.

Node type names vary by grammar version; inspect with
`get_parser("<grammar>").parse("...").root_node().to_sexp()` and adjust captures/traversal.
