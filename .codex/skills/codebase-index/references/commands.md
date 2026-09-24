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
- `--session <tag>` to name this conversation's context: unchanged evidence it
  already received comes back as `reused: true` without the snippet, and
  evidence that changed is listed under `memory.invalidated`

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
  For a method whose name several types share, pass `Owner.member`
  (`TownService.refresh`, or `module::fn` for a top-level function); each site
  names its `caller` and the `target` it resolved to. Calls the index cannot type
  (`chest.holdings().take(..)`) come back as `possible_call`, nearest first, with
  `coverage.partial: true`: read those before claiming a complete list.
  `impact` and `symbol` accept the same form.
  Filters: `--exclude-tests`, `--path <prefix>` (repeatable). `--compact` prints
  `path:line kind caller -> target [confidence]`, one site per line.
- `search`, `explain` and `impact` also take `--compact`: agent text instead of
  JSON. For search/explain, each result is `path:start-end symbols` followed by up
  to eight numbered lines that carry the match (rarer query words first);
  evidence already sent to the session prints as `(already sent)`. For impact,
  one `d<hops> path:line name via edge` line per node, after a
  `# module ...` line naming the build files that depend on the target's module.
- `symbol` returns exact matches alone when there are any and reports how many
  prefix matches it left out (`more_prefix_matches`); `--exact` drops them.
- `describe` on a class, enum, struct or trait also lists its `members` and
  folds their edges into `used_by` / `uses` (code outside the type).
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

## Evidence

```bash
codebase-index verify --session <tag> --json
codebase-index verify "<path:start-end@hash>" ... --json
```

- `verify` is read-only and needs no index: it checks evidence against the
  working tree. `all_valid` is true only when every checked span still holds.
- `--strict` exits 1 when anything is invalid (useful in scripts).
- See [memory.md](memory.md) for verdict states and when to reread.

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
