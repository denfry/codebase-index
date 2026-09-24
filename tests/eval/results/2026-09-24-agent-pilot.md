# Agent pilot: the same questions with and without the skill (2.1.0)

A first task-level measurement: a coding agent answers code questions once with the
`codebase-index` skill and once with Grep/Read/shell only, and we count what it spent.
It is a **pilot**, not a benchmark result: one repository, five questions, three runs
per arm, one model. Treat the numbers as a direction, not a general claim.

## Setup

- **Repository:** `terra-incognita` (private): a Minecraft mod monorepo, 5,904 indexed
  files (985 Java in 18 Gradle modules, a Rust launcher workspace, Python tools).
- **Agent:** Claude Code `general-purpose` subagents, model `claude-opus-5-5`, run in
  parallel, each in a fresh context. Token counts are the harness's per-subagent
  totals; tool output is the character count of every tool result in the transcript.
- **Skill arm:** must invoke the `codebase-index` skill (2.1.0 template, user-level copy)
  and use the CLI first; Grep only as a fallback; a unique `--session` tag per run.
- **Control arm:** must not use `codebase-index`; Grep, Glob, Read, grep/sed/find only.
- Both arms: the index was fresh; graphify was forbidden; no edits.

### Questions (ground truth verified by hand against the tree)

1. How does the town treasury work: storage and persistence, deposit, withdraw, who may
   withdraw? (`Treasury.java`, `TreasuryService.java`, `TreasuryRules.java`)
2. Every production call site of `TreasuryService.treasurerDeparted`. (7 sites)
3. What breaks if `TownService.refresh(MinecraftServer)` changes signature, and does any
   other Gradle module depend on it? (14 call sites incl. 6 unqualified; no dependent
   module; `settings.gradle.kts:40` only includes it)
4. Every production call site of `Holdings.take(ItemStack, int)`. (2 sites, both
   through `chest.holdings().take(..)`; other `take` methods excluded)
5. Rust launcher: what `place` does on a hash mismatch, the verifying function, the
   error, every caller, and where the error is handled. (`fsx::copy_verified`,
   `CoreError::ObjectDamaged`, callers `activation.rs:236,248`, `presets.rs:75`,
   handled at `engine.rs:470,644`)

## Results

| arm | run | tokens | tool calls | tool output (chars) | wall time | correct |
|---|---|---:|---:|---:|---:|---|
| skill 2.1.0 | A | 82,092 | 9 | 50,565 | 78 s | 5/5 (said "15" for 14 listed sites) |
| skill 2.1.0 | B | 83,473 | 11 | 52,584 | 85 s | 5/5 |
| skill 2.1.0 | C | 85,017 | 7 | 57,785 | 266 s | 5/5 |
| grep only | A | 103,238 | 11 | 107,592 | 78 s | 5/5 |
| grep only | B | 107,099 | 12 | 113,460 | 271 s | 5/5 (said "15" for 14 listed sites) |
| grep only | C | 98,657 | 13 | 92,981 | 96 s | 5/5 |

| arm | mean tokens | range | mean tool calls | median wall time |
|---|---:|---|---:|---:|
| **skill 2.1.0** | **83,527** | 82,092–85,017 | **9.0** | 85 s |
| grep only | 103,000 | 98,657–107,099 | 12.0 | 96 s |
| Δ | **−18.9%** | ranges do not overlap | **−25%** | |

Wall time is dominated by queueing when six agents run at once (one run per arm took
over four minutes), so it is reported but not compared.

### Before this release

The same five questions with the previous skill (2.0.0-era template, `--json`
everywhere) cost 96,102 / 102,248 / 103,528 tokens and 15 / 19 / 16 tool calls: parity
with grep on tokens and more tool calls. The difference between the two skill runs is
the 2.1.0 work: `--compact` output with numbered lines (agents stopped re-reading files
or grepping for line numbers), exact `Owner.member` refs with counts, build-module
information in `impact`, and a shorter skill.

## Caveats

- One private repository and five questions, four of them lookups by an exact name,
  which is where Grep is strongest. Natural-language questions are measured by the
  retrieval eval instead (see `2026-09-24-retrieval-2.1.0.txt`).
- Three runs per arm; the control arm's token range across earlier rounds was
  91.8k–108.5k, so single-run comparisons are noise.
- Both arms made one counting slip in the prose around a correct list; `refs --compact`
  now prints the total in its header.
