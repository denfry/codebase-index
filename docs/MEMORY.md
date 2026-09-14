# Evidence memory

Evidence memory is the 2.0 answer to one question: **is what the agent read earlier
still true?** It identifies every delivered snippet by the exact bytes of its span,
re-checks those bytes against the working tree on later calls, withholds snippets the
same session already holds, and reports evidence that has changed. It never decides
anything by query similarity and it stores no source text.

## Evidence references

A reference is `path:start-end@hash`. The hash covers the bytes of lines `start..end`
under the indexer's own line model (universal newlines); only line terminators are
normalised. References are printed by `verify` and can be kept next to the conclusions
they support:

```text
Refunds are capped at the invoice total [billing/refund.py:3-4@3f9a2c1b7d4e8a90]
```

References are untrusted input. Absolute paths, drive letters, `..` segments and NUL
are rejected before any filesystem access, and every read goes through the same
`PathGate` the indexer uses, so a reference can never reach a file the walker would
refuse (ignored paths, dependency and build directories, secret filenames, oversized
or binary files, symlinks that resolve outside the repository).

## Verdicts

| state | still true? | meaning |
|---|---|---|
| `valid` | yes | bytes unchanged at the same lines |
| `relocated` | yes | identical bytes occur exactly once elsewhere in the same file |
| `changed` | no | bytes at the span differ and the text occurs nowhere else |
| `ambiguous` | no | identical bytes now occur more than once |
| `deleted` | no | file gone; a rename or move counts as deleted |
| `excluded` | no | the path is now ignored, secret-like or outside the repository |
| `unreadable` | no | the file could not be read |

`all_valid` is true only when every verdict is `valid` or `relocated`; it is false for an
empty or unknown set.

## Sessions

A session is a tag the caller chooses, one per agent conversation. Sessions are never
inferred from a process, an environment variable or a time window, because none of
those identify what an agent still holds in context.

```bash
codebase-index search "refund cap" --session auth-fix-1 --json
codebase-index explain "how are refunds capped" --session auth-fix-1 --json
codebase-index verify --session auth-fix-1 --json
codebase-index verify "billing/refund.py:3-4@3f9a2c1b7d4e8a90" --strict
```

With a session:

- a snippet the session already received from byte-identical source is replaced by
  `snippet: null, reused: true`. A skeleton is withheld only when the same skeleton or
  the whole span was delivered before;
- evidence the session received earlier that has since changed is reported once under
  `memory.invalidated`;
- ranking, budgeting and pagination are untouched. The evidence hook runs after they
  are final, and restoring the withheld snippets reproduces the no-memory packet
  exactly (asserted by tests and by the benchmark on every task).

Without a session the packet is unchanged except for `stale: true` on a result whose
index text no longer matches the working tree. Index text that is derived rather than
copied (config-key chunks, Markdown section summaries) is never flagged: a mismatch
counts as stale only when the file's current hash differs from the one the index was
built from.

## Storage

`memory.sqlite` lives next to `index.sqlite` (override with `CBX_MEMORY_PATH`). It is a
separate file because rebuilds and `clean` delete the index, and so that ledger writes
never queue behind an update transaction. It holds hashes, paths, line numbers, token
counts and timestamps only; session tags are stored hashed. A newer schema is refused
without touching the file, a corrupt file is moved aside rather than deleted, lock
contention degrades to no-memory output instead of blocking, and GC only removes rows.

Configuration (`.codeindex.json`, not part of `config_hash`):

```json
{ "memory": { "enabled": true, "retention_days": 14, "max_deliveries": 50000 } }
```

`CBX_MEMORY=0` or `memory.enabled: false` disables everything and gives 1.10.0 output
byte for byte.

Maintenance is CLI-only and is not exposed to the skill wrappers or MCP, like `clean`:

```bash
codebase-index memory gc                     # drop expired sessions, compact
codebase-index memory clear --session TAG    # forget one session
codebase-index memory clear --yes            # forget everything
```

`stats`, `doctor`, MCP `index_stats` and `healthcheck` carry an additive `memory` block
(counts, schema, size; never paths or content).

## What was measured

The sequential real-history benchmark (`tests/eval/memory_eval.py`) replays a
repository's own commits: each git-derived query runs against the tree at the parent of
its commit, consecutive queries form sessions of K tasks, and the repository evolves
inside a session. The logged run over this repository is in
`tests/eval/results/2026-09-14-evidence-memory.md`; the summary is in
[BENCHMARKS.md](BENCHMARKS.md#evidence-memory).
