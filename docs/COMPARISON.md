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
| Sourcegraph / Cody / Amp | Enterprise-scale code intelligence across many repos | Cloud/account setup and heavier platform surface |
| Continue | Open-source coding agent for IDE + CLI | An agent with context features, not a standalone retrieval index |
| Codebase-Memory MCP | Local graph-based code-memory over MCP | Broader/heavier graph engine; different simplicity/privacy tradeoffs |
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

## When to choose what

Honest, per-tool guidance. None of these are attacks — each tool is good at the
job it was built for. The question is which layer you actually need.

### Manual grep / read

- **Good at:** exact string matching, zero setup, always live, universally
  available. For a single known identifier in a small scope, nothing beats `rg`.
- **Where codebase-index differs:** ranking, symbol awareness (definition vs
  call), graph expansion to related files, and token-budgeted line ranges instead
  of every matching line.
- **Choose grep when:** you know the exact string, the repo is small, or you only
  need one match.
- **Choose codebase-index when:** the question is conceptual ("where is auth
  implemented?"), the repo is large, or an AI agent will pay for every irrelevant
  line it reads.

### Cursor

- **Good at:** an integrated AI IDE with strong, low-friction codebase awareness
  for people who work inside Cursor.
- **Where codebase-index differs:** it is a local, open retrieval layer for
  **terminal and MCP** agents, offline by default, with no IDE lock-in and a
  scriptable CLI/JSON/MCP contract.
- **Choose Cursor when:** you want an AI-native IDE and are comfortable with a
  proprietary, IDE-centric workflow.
- **Choose codebase-index when:** your agent is Claude Code, Codex CLI, OpenCode,
  or any MCP client in the terminal, and you want code to stay on your machine.

### Aider repo-map

- **Good at:** a compact, graph-ranked, token-budgeted repository map that feeds
  Aider's chat context well. It is not "just grep" — it ranks with a graph
  algorithm over source and dependencies.
- **Where codebase-index differs:** it is a reusable, queryable index rather than
  context injection for one agent. CLI/JSON/MCP commands return ranked `file:line`
  ranges, symbols, references, and `impact` that any shell-capable agent can
  consume, with freshness checks and security/ignore gates.
- **Choose Aider repo-map when:** Aider is your agent and you want its built-in
  context with nothing extra to run.
- **Choose codebase-index when:** you want one index shared across multiple agents
  (Claude Code, Codex, OpenCode, MCP) with a stable, scriptable contract.

### Sourcegraph / Cody / Amp

- **Good at:** enterprise-grade, cross-repo code intelligence, search, and code
  graph at organization scale, with mature platform features.
- **Where codebase-index differs:** single-repo, local, and lightweight — no
  server, no account, no code leaving the machine by default. It is a retrieval
  layer for an agent, not a platform.
- **Choose Sourcegraph/Cody/Amp when:** you need org-wide search across many
  repositories, team features, and are fine with a hosted/account-based platform.
- **Choose codebase-index when:** you want per-repo retrieval for a terminal/MCP
  agent with a strict local-first privacy model and minimal moving parts.

### Continue

- **Good at:** an open-source coding **agent** with IDE and CLI integrations and
  built-in context features. It is a full assistant, not just an index.
- **Where codebase-index differs:** it is the **retrieval/index layer itself**,
  not an agent. It exposes a CLI/JSON/MCP contract that an agent (including, in
  principle, agents like Continue) can query, and it focuses on token-budgeted
  packets and a strict privacy model rather than on being the chat surface.
- **Choose Continue when:** you want the agent — an open assistant to drive your
  edits.
- **Choose codebase-index when:** you already have an agent and want to give it
  precise, local, ranked codebase context.

### Codebase-Memory MCP

This is the closest direct alternative, so the comparison is the most careful.

- **Good at:** a broader graph engine with a static binary, wide language and
  agent coverage, and more advanced graph features than codebase-index ships
  today.
- **Where codebase-index differs — and we do not claim to beat it globally:**
  - **Simplicity and safety:** a small pure-Python surface, a multi-gate exclusion
    pipeline, output-time secret redaction, and a `doctor --strict` self-check.
  - **Strict privacy model:** no telemetry, no network by default; external
    embeddings are opt-in and gated three ways.
  - **Token-budgeted retrieval packets:** ranked `file:line` ranges and
    `recommended_reads` under an explicit budget, tuned for the Claude/Codex/
    OpenCode workflow.
  - **Transparency:** readable Python, 80% coverage gate, golden CLI snapshots,
    and a public benchmark suite wired as a CI regression gate.
  - **Honest benchmarks:** we publish raw logs (see the 55k LOC Java run) and mark
    unproven scale/graph claims as roadmap.
- **Choose Codebase-Memory MCP when:** you need its broader graph engine,
  static-binary distribution, or wider language/agent reach today.
- **Choose codebase-index when:** you want a simpler, privacy-strict, transparent
  retrieval layer tuned for terminal AI agents with token-budgeted output and
  benchmarks you can audit.

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
