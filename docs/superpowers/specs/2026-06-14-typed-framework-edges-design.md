# Typed Framework Edges — Design

> **Status:** Design draft (2026-06-14). Implementation NOT started.
> **Author:** denfry
> **Milestone:** Product roadmap **M13 — Code intelligence graph** (extends ARCHITECTURE.md §9).
> **Why a design doc first:** `PRODUCT_UPGRADE_PLAN.md` §10 marks typed edges *High risk* and the
> repo rule is "anything that risks destabilizing retrieval quality or the security model is
> documented here first and lands behind a benchmark." This is that document.

## 1. Problem

The graph today has four edge types — `import`, `call`, `reference`, `extends`/`implements`
(see `storage/schema.sql` `edges.edge_type`). They power `refs`, bounded `impact`, and the rerank
centrality bonus. They do **not** capture how modern frameworks actually wire code together, so
`impact "routes/users.ts"` misses the handler→service→repository→model chain a human would trace.

ARCHITECTURE.md §9 lists the target typed edges:

- HTTP route → handler → service → repository → model
- test → fixture → implementation
- interface/trait → implementation (partially covered today by `implements`)
- config key → consumer
- migration → model → query
- event producer → event consumer
- DI container / framework wiring
- frontend component → hook/store/api client
- error string / log message → throw site → handler

## 2. Why the current edge mechanism is not enough

The existing capture-prefix mechanism (`treesitter._EDGE_PREFIXES`, e.g. `@import.module`) emits an
edge whose target is an **identifier captured from the AST**, resolved later by symbol name or
module path (`graph/builder.resolve_edges`). That works for imports and inheritance because the
target *is* a named symbol/module in the same repo.

Framework edges break this assumption in two ways:

1. **The link is a string literal, not a symbol.** `@app.get("/users/{id}")` ties a URL pattern to a
   handler function. There is no `"/users/{id}"` symbol to resolve to. The edge is really
   *"this function is the handler for this route"* — an attribute of the handler plus a
   route-string key that only matches another route-string elsewhere (e.g. a client `fetch`).
2. **Resolution is heuristic and framework-specific.** "service" is a naming/DI convention, not a
   language construct. Precision varies by framework, so edges need **confidence** and
   **provenance** so agents can treat a Spring `@Autowired` edge differently from a guessed
   `*Service` name match.

A naive "add a `route` prefix" would emit unresolvable edges that pollute `impact`. We need a new,
explicitly-typed, confidence-bearing edge path.

## 3. Schema changes

Extend `edges` (additive — bumps `storage/db.SCHEMA_VERSION`, with a migration that backfills
defaults so old indexes rebuild rather than guess):

```sql
ALTER TABLE edges ADD COLUMN confidence REAL NOT NULL DEFAULT 1.0;  -- 0..1; 1.0 = exact AST/import
ALTER TABLE edges ADD COLUMN resolver   TEXT;                       -- provenance, e.g. 'fastapi.decorator'
ALTER TABLE edges ADD COLUMN dst_key    TEXT;                       -- non-symbol join key (route string, event name, config key)
CREATE INDEX idx_edges_dstkey ON edges(dst_key);
```

New `edge_type` values (open-ended TEXT, no enum migration needed): `route`, `handler`,
`test_target`, `config_consumer`, `migration_model`, `event`, `di_wire`, `component_dep`,
`log_site`. Existing four edge types keep `confidence = 1.0` and `resolver = NULL`, so all current
behavior is byte-for-byte unchanged.

`dst_key` is the join column for string-keyed edges: a `route` edge from a handler and a
`component_dep` edge from a client both carry `dst_key = "GET /users/{id}"`; the builder pairs
producers and consumers by `dst_key` instead of by symbol name.

## 4. Resolver architecture

A new `parsers/frameworks/` package, each module a `FrameworkResolver`:

```python
class FrameworkResolver(Protocol):
    name: str                       # provenance string, e.g. "fastapi"
    def detects(self, file: FileMeta, imports: list[str]) -> bool: ...
    def edges(self, tree, symbols, source) -> list[TypedEdge]: ...   # carries confidence + resolver
```

Detection is import-gated (only run the FastAPI resolver on files importing `fastapi`/`starlette`),
so cost is proportional to relevant files and an unrecognized stack adds nothing. First resolvers,
chosen for coverage-per-effort:

| Resolver | Edge(s) | Confidence basis |
|---|---|---|
| `fastapi` / `flask` | `route` (decorator → handler) | 1.0 (explicit decorator) |
| `express` | `route` (`app.get(path, handler)`) | 0.9 (handler ref may be inline) |
| `pytest` | `test_target` (test → impl by import + name) | 0.7 (name heuristic) |
| `spring` | `di_wire` (`@Autowired`/constructor) | 0.95 |

Each resolver is independently testable against a fixture file and contributes a labeled row to the
graph benchmark (§6). New frameworks are added without touching the core — same spirit as the
Tier-A `LangSpec` registry.

## 5. Surfacing & honesty

- `impact` / `refs` responses gain a per-edge `confidence` + `resolver` and group results as
  **precise** (≥0.9) vs **heuristic** (<0.9), mirroring the existing `GraphCoverage.partial`
  honesty signal — agents trust precise edges and treat heuristic ones as leads, not proof.
- `stats` reports which framework resolvers fired and how many typed edges each produced.
- `doctor` notes when typed edges exist but no resolver matched the repo's stack (so a missing
  resolver is visible, not silent).
- Rerank: typed edges are **excluded** from the `in_degree` centrality bonus initially (they would
  re-introduce the god-class skew this release just dampened); revisit only behind the benchmark.

## 6. Benchmark gate (required before merge)

`tests/benchmark_public.py` already has a `graph_tasks` section (`route→handler→service` is an
explicit TODO in `PRODUCT_UPGRADE_PLAN.md` §8). Before any resolver lands:

1. Add hand-labeled framework-graph cases (route→handler→service→model paths) to the public fixture
   and to a real multi-framework repo case.
2. Report `graph_tasks.pass_rate` **before/after**, plus retrieval `recall@k`/`MRR`/`nDCG` to prove
   no retrieval regression (the gate this release's rerank change passed).
3. Publish raw logs next to the headline number (the §8 "no-overclaim procedure").

A resolver merges only if it raises graph pass-rate **without** lowering retrieval metrics.

## 7. Phasing

- **Phase 1** — schema columns + migration + the `route`/`handler` pair for one Python framework
  (FastAPI), `dst_key` pairing, confidence/provenance plumbing, benchmark cases. Smallest
  end-to-end vertical slice.
- **Phase 2** — Express + Flask routes; `test_target`; surface precise/heuristic split in
  `impact`/`refs`.
- **Phase 3** — `config_consumer`, `migration_model`, `event`, `di_wire`; per-resolver `stats`.
- **Phase 4** — frontend `component_dep`, `log_site`; rerank integration (behind the benchmark).

## 8. Non-goals

- Not a type checker or a full call-graph resolver across dynamic dispatch.
- Not cross-repo / monorepo graph (single-repo remains the product boundary).
- No network or LLM-assisted resolution — resolvers stay static, local, and deterministic so the
  privacy model (SECURITY.md) is untouched.
