# Product Upgrade Plan

> Living product brief. Shipped capability is documented in README and
> CHANGELOG; forward work belongs in ROADMAP.

## Product promise

> Give AI coding agents a precise map of the codebase — locally, privately, and
> with evidence.

The product vocabulary is:

- **Find** — locate implementations and definitions.
- **Trace** — explain behavior through auditable code relationships.
- **Predict** — estimate the blast radius of a change.

`codebase-index` sits below the coding agent. It is not an IDE, a hosted search
platform, or an autonomous agent.

## Defensible differentiators

1. **Evidence-bearing retrieval** — ranked `file:line` ranges and recommended
   reads under a token budget.
2. **Queryable local graph** — callers, references, paths, architecture, and
   impact rather than a one-shot context blob.
3. **Honest uncertainty** — index freshness, result confidence, graph coverage,
   and edge confidence are part of the response contract.
4. **One implementation, several surfaces** — CLI, Skill, and MCP share the
   service layer.
5. **Auditable privacy** — network off by default, no telemetry, exclusion gates,
   output redaction, and strict diagnostics.
6. **Measured claims** — public benchmark code and raw results live with the
   product.

## Primary users

| User | Need | Product outcome |
|---|---|---|
| Terminal coding-agent user | Stop broad repo scans | Agent reads a small ranked evidence set |
| Privacy-constrained team | Keep source off hosted indexes | Local derived index and explicit network gates |
| MCP power user | Stable code-intelligence tools | Versioned, scriptable contracts |
| Tooling author | Compose retrieval into automation | JSON CLI, MCP, and local SQLite |

People who need a full AI IDE or organization-wide cross-repository search
should use products built for those jobs.

## Product experience

The ideal interaction does not require users to understand retrieval modes:

```text
Ask a repository question
        ↓
Skill routes Find / Trace / Predict
        ↓
Index self-checks freshness
        ↓
Agent reads the minimum evidence
        ↓
Answer includes citations and honest uncertainty
```

Advanced users retain direct access to the lower-level commands.

## Presentation system

The product identity uses:

- graphite backgrounds;
- blue for definitions and retrieval;
- purple for traces;
- green for verified impact and safe state;
- amber for inferred evidence;
- red only for failure and high-risk impact.

The graph-route mark represents a highlighted path through local code. Product
copy should prefer outcomes over implementation terms on the first screen;
Tree-sitter, SQLite FTS5, and ranking details belong below the core story.

Canonical short copy:

> Find implementations. Trace behavior. Predict change impact.

Canonical trust copy:

> Local by default. No telemetry. Evidence on every answer.

## Success metrics

Measure product outcomes, not command count:

- task success rate;
- Recall@1/3/5 and MRR;
- tokens and files read before the answer;
- time to an evidence-backed answer;
- citation correctness;
- graph path precision;
- false-positive impact warnings;
- clean install and first-query completion rate.

## Execution order

1. Clarify product language and reduce documentation duplication.
2. Keep the skill protocol compact through progressive references.
3. Publish stronger real-repository and task-level evaluations.
4. Add task-context and diff-impact workflows.
5. Add typed framework edges behind graph-quality gates.

See [ROADMAP.md](ROADMAP.md) for the live delivery sequence.
