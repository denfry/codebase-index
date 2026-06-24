# Product Upgrade Plan

> Status: living document. Created 2026-06-12 alongside the `1.3.0` line.
> This is a planning artifact, not a claims document. Anything not marked
> **Shipped** is a roadmap item and must not be advertised as done.

## 1. Positioning

**codebase-index is not an IDE and not a coding agent. It is the local
retrieval/index layer that gives terminal and MCP-based AI agents precise
codebase context.**

One-line description used everywhere:

> Local-first codebase retrieval for AI coding agents — Cursor-like codebase
> awareness for Claude Code, Codex CLI, OpenCode and MCP, without cloud indexing
> or IDE lock-in.

What that commits us to:

- We sit **below** the agent, not beside it. The agent (Claude Code, Codex CLI,
  OpenCode, any MCP client) stays the user's interface; we return ranked
  `file:line` packets it reads instead of scanning the repo.
- We are a **queryable index with a stable contract** (CLI `--json`, MCP schema),
  not a one-shot context blob baked into a single agent's prompt.
- We are **local-first and offline by default**. The only path that can leave the
  machine is opt-in external embeddings, gated three ways (see SECURITY_MODEL.md).

What we explicitly do **not** claim:

- Not a Cursor/IDE replacement.
- Not best-in-class framework-aware graph retrieval *yet* — today the graph is
  import/call/reference/inheritance, not full route→handler→service→model
  intelligence.
- Not proven at 100k/1M LOC scale — the public suite is synthetic; the only
  real-repo evidence is a single 55k LOC Java run.

## 2. Target users

| Persona | Pain today | What we give them |
|---|---|---|
| Claude Code / Codex CLI / OpenCode user on a medium-to-large repo | Agent burns context window grepping and reading whole files | Ranked `file:line` packets; the agent reads 3 files, not 60 |
| Privacy-constrained team (proprietary / regulated code) | Cloud code-intelligence is a non-starter | No network by default, no telemetry, secret redaction, ignore gates |
| MCP power user wiring multiple tools | Wants a stable, queryable code index as a tool, not a black box | stdio MCP server with a documented tool contract + `--json` CLI |
| Tooling/automation author | Needs scriptable retrieval other tools can build on | Agent-agnostic CLI with machine-readable JSON, SQLite the index lives in |

Non-users (be honest): people who want a full IDE, multi-repo enterprise code
search, or a turnkey hosted platform. Point them at Cursor / Sourcegraph.

## 3. Competitor matrix

Full prose lives in [COMPARISON.md](COMPARISON.md); this is the planning view.

| Tool | Category | Strongest at | Where we differ | Choose them when |
|---|---|---|---|---|
| Manual grep/read | Baseline | Exact ad-hoc string match | Ranking, symbols, graph, token budget | One known string, tiny scope |
| Cursor | AI IDE | Integrated editor + codebase awareness | Terminal/MCP-agnostic, offline by default, open | You live in Cursor's IDE |
| Aider repo-map | Agent context | Graph-ranked, token-budgeted map feeding Aider chat | Reusable queryable API across agents, freshness/security gates | You use Aider as your agent |
| Sourcegraph / Cody / Amp | Enterprise code intelligence | Cross-repo search/graph at org scale | Single-repo, local, lightweight, no platform/account | You need org-wide multi-repo search |
| Continue | Open-source coding agent | IDE+CLI agent with context features | Standalone retrieval index any agent can query, not an agent itself | You want the agent, not just the index |
| Codebase-Memory MCP | Local graph code-memory MCP | Broad graph engine, static binary, many languages | Simplicity, strict privacy model, token-budgeted packets, transparent Python, honest benchmarks | You need its broader graph/language reach today |

We **do not** claim to beat Codebase-Memory MCP globally. We differentiate on
simplicity, the Claude/Codex/OpenCode workflow, token-budgeted packets, a
transparent Python implementation, a strict privacy model, and honest benchmarks.

## 4. Differentiators (defensible today)

1. **Token-budgeted retrieval packets** — output is line ranges + recommended
   reads under an explicit token budget, not whole files or raw grep dumps.
   Shipped: `--token-budget`, `recommended_reads`, honest ~13× fewer answer
   tokens than an `rg`+window baseline on the 55k LOC Java run.
2. **One index, three surfaces, one service layer** — CLI, Claude/Codex/OpenCode
   skills, and stdio MCP all run through `service.py`, so they cannot drift.
3. **Strict, auditable privacy model** — no network by default, no telemetry,
   multi-gate exclusion pipeline, output-time secret redaction, `doctor` safety
   self-check with `--strict` CI gating.
4. **Freshness contract** — every search response carries an `index` block
   (`exists`/`stale`/`files_changed_since_build`) so the agent knows when to
   `update` before trusting results.
5. **Graph-coverage honesty** — Tier-A vs Tier-B languages are labeled in
   `stats`/`refs`/`impact`/`doctor`; partial-graph languages tell the agent to
   fall back to Grep rather than reading "no references" as proof.
6. **Transparent, testable implementation** — pure-Python, 80% coverage gate,
   golden CLI snapshots, public benchmark suite as a CI regression gate.

## 5. Current weaknesses (own them)

| Weakness | Impact | Plan |
|---|---|---|
| No large-scale real-repo benchmark | Can't claim 100k/1M LOC quality | Benchmark tasks §8; recruit public repos |
| Graph is import/call/ref only | `impact` misses framework wiring | ARCHITECTURE §9 + design doc `specs/2026-06-14-typed-framework-edges-design.md`; implementation behind §8 benchmark |
| ~~GitHub-only distribution~~ | **PyPI shipped in 1.6.0** — `pip install codebase-index` / `pipx` work; `uvx`/Homebrew still pending | Distribution tasks §9 (uvx/Homebrew) |
| MCP client docs unverified | Templates may be wrong per client version | Verify against each client, add per-client docs |
| Single-repo only | No monorepo/fleet context | Out of scope near-term; documented as non-goal |
| `clean` was a stub vs documented | Doc/reality gap | **Shipped in this pass** — real cache reset + test |

## 6. High-impact roadmap (ranked)

1. **Scale benchmarks on real public repos** (10k → 100k LOC), published with raw
   logs. Highest credibility lever.
2. **Typed framework edges** (route→handler→service→model, test→impl, config→consumer)
   with source spans + confidence. Biggest product-quality lever for `impact`.
   *Design approved this pass* (`specs/2026-06-14-typed-framework-edges-design.md`);
   implementation gated on the §8 graph benchmark.
3. **Distribution hardening**: PyPI publish, `uvx`/`pipx` story, signed checksums,
   SBOM. Lowers adoption friction and raises supply-chain trust.
4. **MCP contract hardening**: ✅ `schema_version` on every payload + golden
   snapshots per tool (this pass). Remaining: verified client docs, paging/progressive results.
5. **Retrieval tuning**: ✅ dampened the god-class `in_degree` tiebreak this pass
   (log curve + lower cap, validated no-regression on the public suite). Remaining:
   confirm the real-repo gain on the 3 honest Java misses (needs M12.5), per-intent weights review.
6. **Language reach**: config/IaC awareness (Dockerfile, Terraform, migrations,
   CI), plus Swift/Dart/Scala/Vue/Svelte gaps called out in FAQ.

## 7. Documentation tasks

- [x] `docs/PRODUCT_UPGRADE_PLAN.md` (this file).
- [x] README "How is this different?" section answering why-not-grep/Cursor/Aider/
      Sourcegraph/Codebase-Memory on the first screen.
- [x] `docs/COMPARISON.md` explicit rows + prose for Continue, Amp, Codebase-Memory MCP.
- [x] `docs/BENCHMARKS.md` "claims not to make yet" + TODO benchmark checklist.
- [x] `docs/RELEASE_CHECKLIST.md`.
- [ ] Verified per-client MCP setup docs (after testing each client version).
- [x] A short "trust model in 60 seconds" callout reused across README/SECURITY.

## 8. Benchmark tasks

Track in [BENCHMARKS.md](BENCHMARKS.md); none may be reported until run with logs.

- [ ] 10k LOC public repo: Recall@1/3/5, MRR, nDCG, token economy.
- [ ] 100k LOC public repo: same, plus index build time + incremental update latency.
- [ ] Multi-language public repo (≥3 Tier-A languages) with per-language breakdown.
- [ ] Head-to-head vs vanilla agent grep/read behavior (tokens + recall).
- [ ] Head-to-head vs repo-map-style context (tokens + recall).
- [ ] Graph task benchmark: `refs`, `impact`, and route→handler→service paths
      against hand-labeled ground truth.
- [ ] Publish raw logs next to every headline number, like
      `tests/benchmark_honest_RESULTS.md`.

## 9. Distribution / release tasks

- [ ] Publish to PyPI; switch docs to `pip install codebase-index` with GitHub
      pin as the reproducible alternative.
- [ ] `uvx codebase-index` and `pipx install codebase-index` once on PyPI.
- [ ] Homebrew tap.
- [ ] Signed release checksums (e.g. `cosign`/`minisign`) + published SBOM.
- [ ] Reproducible-install smoke on a clean machine per OS (extend
      `scripts/release_smoke.py`).
- [x] `docs/RELEASE_CHECKLIST.md` to make releases repeatable.

## 10. Technical improvements (ranked by impact / risk)

| # | Improvement | Impact | Risk | Status |
|---|---|---|---|---|
| 1 | Implement `clean` (documented but was a stub) | Fixes doc/reality gap | Low | **Shipped (1.3.0 line)** |
| 2 | Dampen god-class `in_degree` tiebreak in rerank | +recall on real repos | Medium (retune) | **Shipped this pass** — log dampening + lower cap; no-regression on the public suite + a targeted regression test. Real-repo gain still needs M12.5. |
| 3 | `schema_version` on every MCP payload | Stable contract | Low | **Shipped this pass** — `schema_version` + `tool` envelope on every payload (incl. errors), asserted + golden-locked. |
| 4 | Golden snapshots for each MCP tool output | Regression safety | Low | **Shipped this pass** — `tests/golden/mcp_*.json` via `tests/test_mcp_golden.py`. |
| 5 | Typed framework edges in the graph | Better `impact` | High | Design doc shipped this pass (`docs/superpowers/specs/2026-06-14-typed-framework-edges-design.md`); implementation behind the §8 benchmark. |
| 6 | Config/IaC parsers (Dockerfile, Terraform, migrations) | Coverage | Medium | **Partly shipped this pass** — Tier-C labeling for Dockerfile/Terraform/HCL/INI/Make (already FTS-indexed, now language-labeled); tree-sitter parsing of these still roadmap. |
| 7 | Paging/progressive MCP results | Big-repo UX | Medium | Roadmap (MCP.md) |

Also fixed this pass (not previously tracked): the MCP server failed to import on
`mcp>=1.27` + `pydantic>=2.10` (FastMCP auto-built a structured-output schema from
the `-> str` return annotation and raised). Tools now register as unstructured
(`structured_output=False` where supported), so the server loads on current `mcp`.

Rule for this repo: small, safe, tested changes land directly; anything that
risks destabilizing retrieval quality or the security model is documented here
first and lands behind a benchmark.
