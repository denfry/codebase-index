# Language support

`codebase-index` has three support tiers.

| Tier | Meaning | Current examples |
|---|---|---|
| Tier A | Language-specific Tree-sitter `LangSpec` with definition, call, and import/inheritance patterns | Python, JavaScript, TypeScript, Java, Go, Rust, C, C++, C#, Ruby, PHP, Kotlin |
| Tier B | Generic Tree-sitter path when a loadable grammar exists, without language-specific graph semantics | Lua |
| Tier C | Line chunks + FTS5 lexical search only | Markdown, JSON, YAML, TOML, SQL and other text/config files |

Tier A is the only tier that should be advertised as symbol-aware. Tier B can
surface useful definitions, but it is intentionally weaker and should be called
"generic Tree-sitter fallback" in docs and benchmarks.

## Current Tier-A languages

| Language | Extensions | Symbols | Calls | Imports / inheritance |
|---|---|---|---|---|
| Python | `.py` | functions, classes | yes | imports, `extends` |
| JavaScript | `.js`, `.jsx`, `.mjs`, `.cjs` | functions, classes, methods, arrow/function variables | yes | imports, `extends` |
| TypeScript | `.ts`, `.tsx` | functions, classes, methods, interfaces, enums, type aliases | yes | imports, `extends`, `implements` |
| Java | `.java` | classes, interfaces, enums, records, methods, constructors | yes | imports, `extends`, `implements` |
| Go | `.go` | functions, methods, types | yes | imports |
| Rust | `.rs` | functions, structs, enums, traits, impls, modules | yes | `use` |
| C | `.c`, `.h` | functions, structs | yes | includes |
| C++ | `.cpp`, `.cc`, `.cxx`, `.hpp`, `.hh`, `.hxx` | functions, classes, structs, namespaces | yes | includes, base classes |
| C# | `.cs` | classes, interfaces, structs, enums, methods, constructors | yes | `using`, base list |
| Ruby | `.rb` | classes, modules, methods | yes | superclass |
| PHP | `.php` | classes, interfaces, traits, methods, functions | yes | namespace use, base/interface clauses |
| Kotlin | `.kt`, `.kts` | classes, objects, functions | yes | imports |

## Important gaps

To compete with graph-first codebase memory tools, language support needs to
cover not only source files but also framework, config, database, and infra
surfaces.

High-priority code languages:

- Swift
- Dart
- Scala
- Elixir
- Clojure
- Objective-C
- Vue and Svelte component structure

High-priority non-code and framework-aware extraction:

- SQL schema-aware parsing: tables, columns, migrations, model/query consumers
- Terraform/HCL: resources, modules, variables, outputs
- Dockerfile and Compose: images, stages, exposed ports, env, volumes
- Gradle, Maven, npm/pnpm/yarn config files: packages, scripts, plugins, tasks
- CI workflows: jobs, steps, permissions, artifacts, deployment paths
- Route/config conventions for common web frameworks

## Adding a language to symbol extraction

1. Confirm `discovery/classify.py` maps the extension to a language id, and its tree-sitter set
   includes that id.
2. Confirm `tree_sitter_language_pack.get_language("<grammar>")` works for the grammar name.
3. Append a `LangSpec` to `parsers/languages.py::LANGS` with:
   - `defs_query`: one pattern per definition kind, captured as `@def.<kind>` with the name node
     captured as `@name`. Kinds: function, method, class, interface, enum, type, var.
   - `calls_query`: capture the callee identifier as `@callee`.
   - `imports_query`: capture imports as `@import.module`, base classes as `@extends.base`, and
     interfaces as `@implements.iface` when the language has them.
4. Extend `parsers/treesitter.py` AST traversal for that grammar's definition and call node kinds
   when query execution is not stable for the installed `tree-sitter-language-pack`.
5. Add fixture files under `tests/fixtures/` and cases in the language, tree-sitter, graph, and
   multi-language tests.
6. Run `pytest tests/test_languages.py tests/test_multilang_symbols.py tests/test_graph.py`.

Node type names vary by grammar version; inspect with
`get_parser("<grammar>").parse("...").root_node().to_sexp()` and adjust captures/traversal.

## Graph edges

Each `LangSpec` carries an `imports_query` capturing:

- `@import.module` — the imported module path text; source is the file.
- `@extends.base` — a base class identifier; source is the enclosing class.
- `@implements.iface` — an implemented interface; source is the class.

Cross-file resolution runs after indexing in `graph/builder.py`: symbol-target edges resolve on an
unambiguous name match; import edges resolve module paths to files by POSIX suffix
(`auth.token` -> `%/auth/token.py`, then `__init__`/`index` variants). To add a language, fill its
`imports_query`, add fixtures importing/subclassing across files, and assert edges in
`tests/test_graph.py`.
