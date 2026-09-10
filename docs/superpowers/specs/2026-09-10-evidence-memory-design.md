# Evidence memory — 2.0 design

Status: Phase B design, written before implementation. Inputs: `research/2.0-audit.md`,
`research/experiments.md`. Every decision below names the evidence or requirement it
rests on; alternatives that were considered and rejected are listed in §15.

## 1. Goal

Let a coding agent stop re-receiving repository evidence it already holds, **only while
that evidence is provably unchanged**, and tell it exactly which evidence it holds has
become stale. Make any piece of evidence citable by a short reference that any agent can
re-verify later.

Non-goals for 2.0: storing agent conclusions or prose; semantic or query-keyed caching;
changing ranking; graph/co-change expansion; cross-repository memory; an LLM in the loop.

## 2. The central observation

The research measured that 42% of evidence tokens repeat across a workload. A repeated
atom can only be *withheld* from a consumer that still holds the earlier copy in its
context window. Across independent contexts (a new session, a subagent, a different
tool) the text must be sent again — no store can change that. So 2.0 separates two
things the research merged:

| Value | Where it applies | Mechanism |
|---|---|---|
| Token reuse | Within one agent context | Session ledger: omit a snippet already delivered to this context, if its source bytes are unchanged |
| Validity | Everywhere, any time later | Content-addressed evidence references re-verified against the working tree |

## 3. Concepts

**Evidence atom.** A contiguous span of one file, identified by the exact bytes it held
when it was delivered: `(repo, path, span_sha256)`. Line numbers are a locator, not
identity.

**Evidence reference.** A self-describing, verifiable string:
`<path>:<start>-<end>@<first 16 hex of span sha256>`, e.g.
`src/auth/service.py:42-81@3f9a2c1b7d4e8a90`. It can be stored anywhere (agent notes, a
PR description, another tool's memory) and verified without the memory database.

**Session.** An opaque tag naming *one agent context*. Snippets are only ever withheld from
the session they were delivered to. Tags are supplied explicitly by the caller.

**Delivery.** A snippet that was actually placed in a packet (inside the token budget)
and verified against the working tree at delivery time.

**Verdict states.**

| State | Valid? | Meaning |
|---|---|---|
| `valid` | yes | Bytes at the recorded locator are identical |
| `relocated` | yes | Identical bytes occur exactly once elsewhere in the same file |
| `changed` | no | The bytes no longer occur in the file |
| `ambiguous` | no | The bytes occur more than once in the file; identity cannot be established |
| `deleted` | no | The file no longer exists |
| `excluded` | no | The path is now rejected by the discovery gates (ignore/secret/binary/size) |
| `unreadable` | no | I/O error |

Every uncertain case resolves to *invalid* (requirement: prefer false invalidation to
stale reuse).

## 4. Identity and the line model

The indexer reads text with `read_text(errors="ignore")` (universal newlines) and chunks
with `str.splitlines()` (audit §4.2). Hashing uses the same line model so that a snippet
and its hashed span are the same lines:

```
raw     = file bytes
text    = raw.decode("utf-8", "surrogateescape")          # invalid bytes stay visible
text    = text.replace("\r\n", "\n").replace("\r", "\n")  # universal newlines
lines   = text.splitlines()                               # chunker line model
span    = "\n".join(lines[start-1:end])
sha     = sha256(span.encode("utf-8", "surrogateescape"))
```

Only line terminators are normalised (a CRLF checkout of identical code is identical
evidence). Whitespace, comments and case are **not** normalised: a strict hash cannot
confuse two different programs, and fuzzy similarity is never used as proof (§15).
`surrogateescape` means a change to an undecodable byte still changes the hash.

Repository scope: `repo_id = sha256("repo:" + canonical root)`, where the canonical root is
the resolved absolute POSIX path, case-folded on Windows. Rows from another `repo_id` are
never read. Moving a checkout directory therefore starts a fresh scope (a false
invalidation, never a false reuse).

## 5. Validation

```
validate(ref, root, gates, hint=None):
    if gates reject path:            return excluded        # never open excluded files
    if path missing:                 return deleted
    lines = line_model(read(path))
    if sha(lines[start-1:end]) == ref.sha:  return valid(start, end)
    candidates = hint.first_line_sha ? {i : sha(lines[i]) == first_line_sha}
                                     : bounded scan of all starts (≤ 200k line-steps)
    matches    = {i in candidates : sha(lines[i:i+n]) == ref.sha}
    |matches| == 1 → relocated(i+1, i+n);  > 1 → ambiguous;  0 → changed
    (bounded scan exhausted → changed, conservatively)
```

A reference's hash prefix (64 bits) is compared as a prefix; stored rows compare the full
256-bit hash.

**Cross-file moves are not reused.** `src/a.py → src/core/a.py` yields `deleted` for the
old reference. The path is part of what the agent was told (imports and module identity
change with it), and the new location is found by ordinary retrieval. Identical short
text in an unrelated file must never validate a reference (requirement 38).

**Symbol evolution** follows from byte identity: a rename, signature change, body change or
doc change inside the span is `changed`; a split or merge changes the bytes and is
`changed`; code that only shifted inside its file is `relocated`. No attempt is made to
decide semantic equivalence.

## 6. Where evidence is minted — and per-result verification

`retrieval.pipeline.search` gains an optional `evidence` hook invoked after budgeting and
pagination with the delivered page and the candidates behind it. `None` (the default for
library callers) leaves the function byte-identical.

For each result that carries a snippet, the hook reads the working-tree file (through the
gates), computes the span hash, and checks that the index content the snippet was built
from is present in the current span (equality for chunk results; containment for
signature/doc results). This closes audit finding §4.3 per result:

- consistent → the snippet reflects current bytes; it is eligible to be a delivery;
- inconsistent → the result is marked `"stale": true` (index entry older than the file) and
  is never recorded or withheld.

With a fresh index nothing is added to the packet, so default output is unchanged.

## 7. Reuse: session-scoped withholding

With a session tag, for each verified result:

```
atom  = (repo_id, path, span_sha)
known = ledger[session] has atom with (full == true  or  snippet_sha == sha(snippet))
if known:    snippet → null, result.reused = true, tokens_saved += token_est
else:        deliver snippet; ledger[session] += (atom, snippet_sha, full)
```

- `full` is true when the delivered snippet text is the entire span. A skeleton or a bare
  signature only covers part of the span, so it can only satisfy a later request for the
  *same* snippet text. Query-dependent skeletons therefore never hide lines the agent did
  not see.
- **Budget accounting is unchanged**: a withheld snippet still consumes its budget in
  `apply_budget`, so the page, the ranks, which results carry snippets and
  `recommended_reads` are identical to the no-memory packet. The only differences are
  `snippet: null` + `reused: true` on withheld results and a `memory` block. Tokens saved
  are therefore pure savings with identical coverage, which keeps attribution exact.
  Reinvesting freed budget is a separate, later experiment.
- A session with an empty ledger produces the no-memory packet plus the `memory` block.

**Invalidation notices.** On each session call, deliveries not yet reported invalid are
re-validated (using the stored first-line hash for relocation). Newly invalid ones are
listed once:

```json
"memory": {
  "session": "auth-fix",
  "reused": 2, "tokens_saved": 412,
  "invalidated": [{"ref": "src/auth/service.py:42-81@3f9a2c1b7d4e8a90", "state": "changed"}]
}
```

**Why sessions are explicit.** An MCP server process outlives `/clear` and survives context
compaction; a CLI process knows nothing about the caller; a time window would let two
parallel agents withhold evidence from each other; subagents have fresh contexts but may
inherit environment variables. None of these identify an agent context, so the caller
names it (`--session`, `CBX_SESSION`, MCP `session`). Documented rule: a session tag is
used by exactly one context and is replaced after `/clear`, compaction, or whenever the
agent cannot see earlier snippets.

## 8. Claims depend on evidence; memory does not store claims

A conclusion ("auth uses JWT and Redis") belongs to the agent. 2.0 makes its dependency
set checkable instead of caching it: the agent cites references next to its note, and
`verify` reports whether every dependency still holds (`all_valid`). The store keeps
atoms independent of sessions, so a later `claims → atoms` table can reference them
without redesign. No conclusion text, prompt, or reasoning is stored.

## 9. Storage

A separate SQLite file, `.claude/cache/codebase-index/memory.sqlite` (override
`CBX_MEMORY_PATH`; when only `CBX_DB_PATH` is set, next to that DB).

Why not tables in `index.sqlite`: `index --rebuild`, schema-triggered rebuilds and `clean`
delete that file (audit §4.1), which would destroy memory on every rebuild (requirement
7.6); and search-time ledger writes would contend with `update`'s long write transaction
on the same WAL. A second file in the same cache directory reuses the existing SQLite
pattern with none of those couplings, and leaves the 1.x index schema untouched, so
upgrading requires no reindex.

Schema v1 (content-free — no source text is ever stored):

```sql
meta(key PRIMARY KEY, value)                                 -- schema_version, last_gc_at
atoms(id PK, repo_id, path, span_sha, line_count, first_line_sha,
      first_seen_at, last_state, last_checked_at,
      UNIQUE(repo_id, path, span_sha))
sessions(id PK, repo_id, tag_sha, created_at, last_used_at,
         tokens_delivered, tokens_saved, reused, UNIQUE(repo_id, tag_sha))
deliveries(session_id → sessions ON DELETE CASCADE, atom_id → atoms ON DELETE CASCADE,
           snippet_sha, full, line_start, line_end, token_est, delivered_at,
           invalid_state NULL, PRIMARY KEY(session_id, atom_id, snippet_sha))
```

- Session tags are stored as `sha256(repo_id + tag)`; the tag itself is never persisted.
- **Migrations**: ordered `MIGRATIONS[v] → callable`, applied in one `BEGIN IMMEDIATE`
  transaction; `user_version`-style guard in `meta`. A newer on-disk version disables
  memory for that process (search still works, reported by `stats`/`doctor`), it never
  downgrades.
- **Corruption**: `sqlite3.DatabaseError` on open → the file is renamed to
  `memory.sqlite.corrupt-<UTC timestamp>` (preserved, not deleted), a fresh store is
  created, and `doctor` reports it.
- **Concurrency**: WAL, `busy_timeout` 2000 ms, short `BEGIN IMMEDIATE` writes, idempotent
  upserts. A lock timeout degrades that call to "no withholding, no ledger write" — the
  packet is still correct, only larger.
- **Bounded growth**: `memory.retention_days` (14) removes sessions not used within the
  window; orphan atoms are removed; `memory.max_deliveries` (50 000) drops the least
  recently used sessions beyond the cap. GC runs at most daily on a session write, and via
  `memory gc`. GC only deletes rows; it cannot make evidence valid, because validity is
  computed from the working tree on every check.

## 10. Branches, worktrees, dirty trees

Validity is byte equality with the **current working tree**, never a commit. Consequences:

- Dirty, staged and unstaged edits are what is validated against; `HEAD` is irrelevant.
- `git checkout`/rebase: evidence whose bytes are identical on the new branch stays valid
  (it is the same text); anything else is `changed`/`deleted`.
- Each worktree has its own cache directory, hence its own memory; sharing across worktrees
  is not attempted.
- New files have no prior evidence; deleted files yield `deleted`; renames yield `deleted`
  for the old path.

## 11. Public surface

| Surface | Addition |
|---|---|
| `search`, `explain` | `--session TAG` (env `CBX_SESSION`) |
| `verify` (new, read-only) | `codebase-index verify [REF ...] [--session TAG] [--strict] [--json]`: verdict per reference or per session delivery, `all_valid`; `--strict` exits 1 when anything is invalid |
| `memory gc`, `memory clear` (new, maintenance) | Explicit GC; delete one session or all memory (`--yes`) |
| `stats`, `doctor` | Additive `memory` block / `memory_store` finding |
| MCP | `session` parameter on `search_code`/`explain_code`; `verify_evidence(refs, session)`; memory block in `index_stats`/`healthcheck`. No GC/clear over MCP (same policy as `clean`). |
| Skill | `verify` allowed; `memory` not allowed (like `clean`) |

MCP `schema_version` stays 1: every change is an additive field. No CLI command, flag or
JSON field is removed or retyped.

Config: `memory.enabled` (true), `memory.retention_days` (14), `memory.max_deliveries`
(50 000); env `CBX_MEMORY=0` disables everything, giving 1.10.0 output byte-for-byte. Not
part of `config_hash`.

## 12. Security

- The store holds hashes, paths, line numbers, token counts and timestamps. It holds **no
  source text**, so no secret can be persisted by it through any path.
- Gates (ignore files, built-in denylist, secret filenames, size, NUL sniff) run before any
  working-tree read performed by validation; an excluded path is reported `excluded`,
  never opened, and its rows are purged by GC.
- Snippet content still comes only from the index and still passes redaction; memory adds
  no new content path to the agent.
- Session tags are hashed; prompts, queries and conclusions are not stored.
- Everything stays local; no new dependency, no network.

## 13. Failure modes

| Failure | Behaviour |
|---|---|
| Memory DB locked / read-only / corrupt / newer schema | Packet without withholding; reason in `stats`/`doctor`; corrupt file preserved |
| Index stale for a result | `stale: true`, snippet delivered, no ledger write |
| Packet truncated by the agent harness after a ledger write | Later call may withhold what was never seen. Mitigation: default budgets stay far below harness limits; documented rule to start a new session when output was truncated |
| Session tag reused by another context | Withholding from a context that lacks the text. Mitigation: documented one-context rule; tags are caller-chosen, never inferred |
| Hash prefix collision on a bare reference | 64-bit prefix; stored rows use full 256-bit hashes |
| Parallel calls in one session | Both may deliver (duplicate tokens); neither withholds unseen text |

## 14. Guarantees and tests

Invariants, each backed by a test:

1. Same bytes → same `span_sha`, independent of line endings and position.
2. Changed bytes → never `valid`/`relocated` under the old reference.
3. Repository A rows are invisible to repository B.
4. Deleted or excluded files → never valid; excluded files never opened.
5. `CBX_MEMORY=0` → payload byte-identical to 1.10.0 for every query in the eval sets.
6. Memory enabled, no session, fresh index → byte-identical to (5).
7. Session with empty ledger → (5) plus a `memory` block; after re-filling withheld
   snippets, identical to (5).
8. GC never changes a verdict; after GC the set of withheld snippets can only shrink.
9. Rebuilding the index with unchanged sources keeps every reference valid.
10. Excluded content (`.env`, keys, ignored paths) never reaches `memory.sqlite`
    (byte scan of the DB file).
11. Deterministic stale-context scenario (§16.2): a query-keyed cache serves the stale fact;
    evidence memory reports `changed` and re-delivers current text.

Lifecycle tests use real git repositories: edit, insert-above (relocation), rename, delete,
move across files, branch switch, detached HEAD, worktree, dirty/staged/unstaged, new
file, rebase. Randomised property tests use a seeded `random.Random` (no new dependency).

## 15. Rejected alternatives

| Alternative | Reason |
|---|---|
| Query-similarity (semantic) cache | 20.5–69.1% stale on real history; the key omits the dependency |
| Store snippet text in memory | Duplicates the index, creates a second secret-retention surface, unnecessary: validation needs only hashes |
| Memory tables inside `index.sqlite` | Destroyed by rebuild/`clean`; write contention with `update` |
| Automatic session per MCP process / time window | Does not identify an agent context (`/clear`, compaction, parallel agents) |
| Normalised (whitespace/comment-insensitive) identity | Can equate different programs; similarity is never proof |
| Cross-file relocation by content | Path is part of the evidence; short identical text in unrelated files would validate |
| Whole-file atoms | 1.36× less surviving reuse at 10 commits (research H4) |
| Reinvest withheld budget into more results | Changes the page and confounds attribution; deferred to a separate experiment |
| Contract slices / accretion / co-change in the default packet | Negative slot economics and lower useful-per-token (research Exp. 1–7) |
| Emitting a reference on every result by default | ~5–9% packet tokens for a feature most calls do not use; references are available from `verify --session` |

## 16. Benchmark plan (Phase D)

### 16.1 Sequential real-history replay (`tests/eval/memory_eval.py`)

For each corpus: a `git clone --shared --no-checkout` into a temp dir (source repositories
are never modified); queries ordered oldest-first by their commit; for task *i* the tree is
checked out at the **parent** of the task's commit, the index is updated incrementally,
and the retrieval call is made. Tasks are grouped into sessions of *K* consecutive tasks
(K ∈ {1, 5, 10, 25, all}). The repository really evolves between tasks.

Arms, all on identical packets:

| Arm | Description |
|---|---|
| A | Read the full files of every delivered result (the "just reread the file" baseline) |
| A-mem | A with file-hash memory: skip a file already read in the session and unchanged |
| B | 1.10.0 packets, no memory |
| S | Unsafe dedup: withhold any result whose `(path, start, end)` was delivered in the session, no validation (models "trust what you saw") |
| C | 2.0 validated session memory |

The oracle is independent of the memory code: the harness keeps every snippet text it has
handed to each session, and a withheld snippet counts as **stale** unless the text B would
deliver now equals a text previously delivered to that session (or is contained in a
previously delivered full span).

Metrics (defined in `docs/MEMORY.md`): evidence/token reuse rate, validated and stale reuse
rate, invalidation precision/recall, survival by commit distance, unique-atom ratio,
repeat-read reduction (A vs A-mem), useful@budget per arm (stale evidence counts as absent),
packet tokens (serialised JSON / 4, so notice and marker overhead is billed), latency.
Paired bootstrap CIs over tasks.

### 16.2 Deterministic stale-context test

T0 deliver evidence E proving fact X · T1 unrelated commit (E still `valid`, withheld) · T2
edit E so X is false · T3 semantically similar query. Expected: a query-keyed cache returns
the T0 packet (stale X); memory reports `changed` for E and delivers the current text.

### 16.3 Regression and performance

The 8-corpus retrieval eval re-run back-to-back with the pinned 1.10.0 commit (identical
ranking expected by construction); latency p50/p95 with memory off, on without session, and
on with session; `verify` latency; GC time; `memory.sqlite` size after the replay.

## 17. Decisions deferred to measurement

- Whether withholding produces material savings at realistic session lengths (if not, 2.0
  ships verification only and says so — or is not released as 2.0).
- The primary session length reported (all K are published).
- Whether a notice's token cost ever outweighs the tokens it saves.
