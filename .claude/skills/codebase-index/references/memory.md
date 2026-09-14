# Evidence Memory

Load this when you use `--session`, when a packet contains `reused`, `stale` or
`memory`, or when you want to cite evidence for later.

## What is guaranteed

Evidence is identified by the exact bytes of a file span. `reused: true` is set
only when this session already received the same text — or the whole span —
and those bytes are unchanged now. Nothing is decided by query similarity, and
memory stores no source text.

## Verdict states

| state | still true? | do this |
|---|---|---|
| `valid` | yes | use it |
| `relocated` | yes — identical content moved inside the file | use it; cite the new lines |
| `changed` | no | reread the range before relying on it |
| `ambiguous` | no — identical content now occurs more than once | reread |
| `deleted` | no — file gone; a rename or move counts as deleted | search again |
| `excluded` | no — now ignored or secret-like | do not read it |
| `unreadable` | no | search again |

## Reread even when evidence is valid

- You are about to edit and need the exact current text.
- The earlier snippet was a skeleton or a signature and you need the body.
- Your context was cleared or compacted, or you cannot see the earlier snippet.
- A tool output was truncated.

## Citing evidence across conversations

`codebase-index verify --session <tag> --json` lists everything the session
received as `path:start-end@hash` references. Keep the references next to the
conclusions they support in notes or handoffs:

```text
Refunds are capped at the invoice total [billing/refund.py:3-4@3f9a2c1b7d4e8a90]
```

Later, from any agent, check them before trusting the note:

```bash
codebase-index verify "billing/refund.py:3-4@3f9a2c1b7d4e8a90" --json
```

`all_valid: true` means every cited span still holds exactly. Otherwise reread
the invalid spans and re-derive the conclusion; do not patch the old one.
