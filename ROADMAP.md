# Roadmap

`codebase-index` was built in milestone-driven slices, each delivering a runnable, tested
feature. The milestones below have shipped; forward work is tracked in the product roadmap,
[docs/ROADMAP.md](docs/ROADMAP.md), which separates *now / next / then* and does not treat an
item as a product claim until it appears in [CHANGELOG.md](CHANGELOG.md).

## Shipped milestones

| Milestone | Delivered | Since |
|---|---|---|
| M0 Repository packaging | README, docs, CI, issue templates, MIT license, changelog | 1.0.0 |
| M1 SQLite + FTS5 index | Layered ignore rules, secret/binary/generated exclusion, incremental hashing | 1.0.0 |
| M2 Tree-sitter symbols | `LangSpec` extraction for the Tier-A languages, symbol-aligned chunks, `symbol` / `refs` | 1.0.0, widened in 1.3.0 |
| M3 Hybrid retrieval | Path + symbol + FTS5 (+ optional vector) fused with RRF, confidence and fallbacks | 1.0.0 |
| M4 Graph expansion | Import / call / reference / inheritance edges, `impact` | 1.0.0 |
| M5 Token-budgeted packets | Ranked `file:line` results, `recommended_reads`, Markdown and JSON | 1.0.0 |
| M6 Optional local embeddings | `sqlite-vec`, sentence-transformers, triple-gated external backend | 1.0.0 |
| M7 Multi-CLI packaging | `init --target claude\|codex\|opencode\|auto\|all` (1.0.2); Claude Code plugin one-command install (1.3.0) | 1.0.2 |
| M8 Hooks + watch mode | PostToolUse auto-update, `watch`, `doctor` hook reporting | 1.0.0 |
| M9 Public release | Coverage gate, tagged GitHub releases, clean-machine smoke | 1.0.0 |
| M10 Distribution (PyPI part) | `pip install codebase-index`, `pipx`, Trusted Publishing | 1.6.0 |
| M11 MCP server | Stdio server (1.1.0); versioned envelopes and golden tests for every tool (1.4.0) | 1.1.0 |
| M12 Public benchmark suite | `tests/benchmark_public.py` with Recall/MRR/nDCG/token/freshness/graph metrics (1.1.0); logged run (1.4.0) | 1.1.0 |
| — Retrieval evaluation | Leak-free git-derived ground truth, multi-corpus pooling, significance tests | 1.8.0 / 1.9.0 |

## Still open (tracked in docs/ROADMAP.md)

- M10 remainder: `uvx` verification on every CI OS, Homebrew tap, signed checksums / SBOM.
- M11.5: MCP client configs verified against current client releases; paged results.
- M12.5: larger public-repository runs (a 1M-LOC / monorepo target) and an LLM-agent
  task-level evaluation. A multi-repository public baseline benchmark now exists at
  `tests/eval/run_baselines.py` with a logged run under `tests/eval/results/`.
- M13: typed framework-aware edges (routes, tests, config consumers, migrations, DI).
