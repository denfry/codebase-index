# Command Reference

Load this reference only when the intent table in `SKILL.md` is insufficient.

## Retrieval

```bash
codebase-index search "<query>" --json
codebase-index explain "<topic or flow>" --json
```

Useful search options:

- `--mode hybrid|fts|symbol|vector`
- `--token-budget <tokens>`
- `--limit <count>`
- `--offset <pagination offset>`
- `--raw` to disable snippet skeletonization
- `--no-fallback` to suppress fallback suggestions

`explain` uses the HOW_IT_WORKS intent and a larger default token budget. Prefer
it over repeatedly rewording a broad search.

## Code graph

```bash
codebase-index architecture --json
codebase-index refs "<symbol>" --json
codebase-index impact "<file-or-symbol>" --direction up --depth 2 --json
codebase-index diff-impact --base HEAD --direction up --depth 2 --json
codebase-index path "<source>" "<target>" --json
codebase-index describe "<file-or-symbol>" --json
```

- `architecture` reads module analysis cached at index time.
- `refs` finds definitions, calls, and graph-backed references.
- `impact` walks dependents (`up`), dependencies (`down`), or both.
- `diff-impact` aggregates impact for tracked changes relative to a verified
  Git commit; new or excluded files are reported as unresolved.
- `path` returns the shortest known dependency/call chain.
- `describe` returns a node card with callers, callees, module, and centrality.

Use `graph` only for a visualization intended for a person:

```bash
codebase-index graph "<target>" --direction both --depth 2 --output graph.html
```

For headless work, use `--output`; do not use `--open`. Exports also support
`--format graphml|dot|neo4j`.

## Index health

```bash
codebase-index stats --json
codebase-index doctor
codebase-index update
codebase-index index
```

Run `stats` and `doctor` when several unrelated queries have low confidence.
Low symbol counts or partial graph coverage can explain weak results.

## Query examples

```bash
codebase-index search "auth token refresh" --json
codebase-index search "AuthService class" --mode symbol --json
codebase-index search "connection reset by peer" --mode fts --json
codebase-index explain "checkout flow" --json
codebase-index impact "User" --direction up --depth 2 --json
codebase-index path "ApiController" "Database" --json
```
