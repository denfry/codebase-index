---
name: codebase-index
description: Use before answering repository questions about architecture, implementation, symbols, references, dependencies, refactoring impact, data flow, or bugs. Query the local hybrid index first so the agent reads only evidence-bearing file:line ranges instead of scanning the repository, and verify evidence gathered earlier before relying on it.
allowed-tools: Bash(codebase-index search *), Bash(codebase-index explain *), Bash(codebase-index architecture *), Bash(codebase-index symbol *), Bash(codebase-index refs *), Bash(codebase-index impact *), Bash(codebase-index diff-impact *), Bash(codebase-index path *), Bash(codebase-index describe *), Bash(codebase-index verify *), Bash(codebase-index graph *), Bash(codebase-index stats *), Bash(codebase-index doctor *), Bash(codebase-index update *), Bash(codebase-index index *), Bash(cbx *), Read, Grep, Glob
---

# Codebase Index

Use the local index before reading repository files. It answers with ranked,
numbered lines, so most answers need no Read and no Grep at all.

## Route the question — always `--compact`

| Intent | Command |
|---|---|
| Where / how does X work? | `codebase-index search "X" --compact --session <tag>` |
| Overview of a feature | `codebase-index explain "X" --compact --session <tag>` |
| Every caller / call site of X | `codebase-index refs "Owner.member" --compact` |
| What breaks if X changes (incl. other modules) | `codebase-index impact "Owner.member" --compact` |
| Find a definition | `codebase-index symbol "X"` |
| A class: members, who uses it | `codebase-index describe "Class" --json` |
| What does my diff affect? | `codebase-index diff-impact --json` |
| Is what I read earlier still true? | `codebase-index verify --session <tag> --json` |

`--compact` prints `path:start-end symbol` per result with the matching lines
numbered underneath (`  24| public static final String FILE_ID = ...`). Cite
those lines as `path:24` directly. Read a range only when the lines shown do not
answer the question — and then only that range, never the whole file.

Name members as `Owner.member` (`TownService.refresh`, `activation::place`,
`CoreError::ObjectDamaged`) so same-named methods of other types are excluded.
`refs --compact` lines are `path:line kind caller -> target`: the list of call
sites with the calling function is usually the whole answer. Add
`--exclude-tests` for production-only lists and `--path <prefix>` for one module.
`kind reference` is a non-call use, e.g. an enum variant matched in a `match` arm.

`impact --compact` starts with `# module <m>: build files depending on it: ...`
— the answer to "does another module depend on this", with no build-file grep.

## Protocol

1. Pick one session tag per conversation (e.g. `auth-fix-1`); pass it to
   `search`/`explain`. Results already sent in this session print as
   `(already sent)` — use your earlier copy.
2. A header saying `index stale` → run `codebase-index update` once; `NO INDEX`
   → `codebase-index index`.
3. Batch independent questions into one Bash call (`cmd1; echo ---; cmd2`).
4. `# partial:` on refs/impact means the list may be incomplete. For
   `Owner.member` it lists `possible_call` sites (calls on a variable the index
   cannot type), nearest first: check those few lines, do not grep the repo.
5. Before relying on evidence from earlier in a long task, run
   `codebase-index verify --session <tag> --json`.
6. Grep only when the index returns nothing relevant or for non-code text.

Edge confidence: `extracted` exact, `inferred` heuristic (receiver matched a
type), `ambiguous` unresolved. Never present an inferred chain as certain.

## Answer

Lead with the answer, then the minimum `file:line` evidence. State uncertainty
only when evidence is partial, inferred or stale.

Options and JSON fields: [references/commands.md](references/commands.md),
[references/response-contract.md](references/response-contract.md),
session memory: [references/memory.md](references/memory.md).
