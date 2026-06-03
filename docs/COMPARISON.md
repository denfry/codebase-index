# Comparison

This page compares `codebase-index` with adjacent code search and agent-context
tools by criteria that matter for repository-level AI work.

## Summary

`codebase-index` is strongest when you want a local, scriptable retrieval layer
for terminal agents or MCP clients. It is not an IDE and not a cloud code-search
platform.

| Tool | Best fit | Main tradeoff |
|---|---|---|
| codebase-index | Local CLI/skill/MCP retrieval for Claude Code, Codex CLI, OpenCode, and MCP clients | Broad framework-aware graph is still a roadmap item |
| Cursor indexing | Integrated AI IDE workflow | Proprietary and tied to Cursor |
| Aider repo-map | Aider chat sessions with compact repository context | Context map, not a reusable local search API |
| Sourcegraph Cody | Enterprise-scale code intelligence across many repos | Cloud/account setup and heavier platform surface |
| Serena / MCP tools | MCP-first local tool integration | Quality and schemas vary by server |
| Manual grep/read | Exact ad hoc search | No ranking, graph, symbol contract, or token budgeting |

## Criteria

| Criterion | Why it matters |
|---|---|
| Agent interface | Determines whether Claude Code, Codex, Cursor, VS Code, or other agents can use it directly |
| Retrieval granularity | File-level maps are cheap; symbol and line-range retrieval saves more tokens |
| Offline guarantee | Private repos often cannot leave the machine |
| Benchmarked quality | Claims need objective tasks, not only tiny fixtures |
| Multi-repo support | Monorepos and service fleets need cross-repo context |
| Language coverage | Agents need source, configs, migrations, CI, and infra |
| Security posture | The tool reads whole repositories, so ignore rules, redaction, telemetry, and supply chain matter |
| Update model | Stale indexes create wrong answers |
| Extensibility | Stable CLI/JSON/MCP contracts let other tools build on the index |

## Detailed matrix

| Criterion | codebase-index | Cursor indexing | Aider repo-map | Sourcegraph Cody | Serena / MCP tools | Manual grep/read |
|---|---|---|---|---|---|---|
| Agent interface | CLI, Claude Code skill, Codex instructions, OpenCode resources, stdio MCP server | Cursor IDE | Aider CLI | IDE + Sourcegraph platform | MCP clients | Any shell-capable agent |
| Retrieval granularity | File, symbol, line range, references, impact graph | IDE-managed code context | Repo map of important files/classes/functions/signatures within token budget | Code search and code graph | Varies by server | File/line text matches |
| Offline guarantee | Default local/offline; external embeddings opt-in | Local IDE indexing plus model/provider behavior depends on setup | Local repo map; model calls depend on Aider config | Cloud by default | Varies; often local | Local |
| Benchmarked quality | Public suite with Recall@1/3/5, MRR, nDCG, tokens, freshness, graph tasks; honest 55k LOC Java run | Public methodology not portable to this repo | No direct local benchmark here | Enterprise/product claims; not benchmarked here | Varies | Baseline only |
| Multi-repo support | Single repo today | Workspace/project scoped | Current chat repo/worktree | Strong cross-repo support | Varies | Manual |
| Language coverage | Tier-A: 12 code languages; Tier-B generic path; configs mostly FTS | IDE proprietary | Tree-sitter repo map support as provided by Aider | Broad enterprise language coverage | Varies | Any text |
| Security posture | `.gitignore`/`.codeindexignore`, secret filename gates, redaction, no telemetry, no network by default | Proprietary behavior; depends on settings | Local map, but model provider path depends on Aider config | Requires platform trust and account policy | Varies by server | No built-in redaction |
| Update model | Manual `index`/`update`, hooks, optional watcher | IDE-managed | Rebuilt as Aider manages context | Platform-managed | Varies | Always live but manual |
| Extensibility | CLI `--json`; MCP schema v1.0; SQLite local DB | Limited external contract | Aider internals/context | Sourcegraph APIs | MCP by design | Shell pipelines |

## Aider repo-map clarification

Aider repo-map should not be described as "just grep" or as lacking ranking.
Aider's documentation describes a repository map that includes important classes,
functions, and signatures, selected to fit a token budget and ranked with a graph
algorithm over source files and dependencies.

The meaningful distinction is different:

- Aider repo-map is optimized to feed Aider's chat context.
- `codebase-index` is a reusable local retrieval API: CLI commands return ranked
  file:line ranges, symbols, references, JSON, and impact results that any
  shell-capable agent can consume.
- Aider's map is good context injection; `codebase-index` aims to be a queryable
  index with freshness checks, ignore/security gates, and agent-readable packets.

## Competitive benchmark bar

Tiny fixture benchmarks are useful smoke tests, not product evidence. The
competitive bar now includes graph-first systems that report evaluations over
dozens of real repositories, large language coverage, answer-quality scoring,
token savings, and tool-call reductions.

`codebase-index` now includes a public benchmark suite (`tests/benchmark_public.py`) with:

- Retrieval quality: Recall@1/3/5, MRR, nDCG
- Agent usefulness: answer-correctness proxy on the public fixture, plus real-repo recall gate in the honest benchmark
- Token economy: tokens saved versus grep/read, Aider repo-map style context, and vanilla agent exploration
- Languages: separate results for Python, TypeScript, Java, Go, Rust, C#, PHP, and other supported languages
- Freshness: latency from file edit to usable updated result
- Graph tasks: callers, impact, architecture trace, route -> handler -> service -> DB

The suite is CI-friendly and synthetic today. Real public 10k/100k/1M LOC scale targets remain
the next benchmark milestone.

## Positioning

`codebase-index` is:

- **Not** a replacement for Cursor or any IDE.
- **Not** a claim of best-in-class graph retrieval yet; the graph is still closer to import/call/reference analysis than full framework intelligence.
- **A local retrieval layer** that makes terminal coding agents better at finding the right files while keeping code on the user's machine by default.
