# Contributing

Thanks for helping make `codebase-index` better. It is a local-first retrieval
and code-graph layer for AI coding agents, and it lives or dies by three
invariants:

1. **Retrieval quality is measured, not asserted.**
2. **The default path stays local and fails closed at security boundaries.**
3. **Machine-readable contracts (CLI `--json`, MCP envelopes) stay stable.**

The hands-on setup, test, benchmark and recipe guide is
[docs/DEVELOPMENT.md](docs/DEVELOPMENT.md). This page covers *what* to work on
and *how* to get it merged.

## Quick start

```bash
git clone https://github.com/denfry/codebase-index.git
cd codebase-index
python -m venv .venv && . .venv/bin/activate     # Windows: .venv\Scripts\activate
pip install -e ".[dev,mcp]"
pytest                                           # coverage gate: 80%
ruff check src tests
mypy src/codebase_index
python scripts/sync_skill_copies.py --check
```

Those four commands are exactly what CI runs. `ruff format` is not enforced.
Set `CBX_NO_SKILL_AUTO_UPDATE=1` before running the CLI inside the checkout.

## Where help is wanted

Issues are labelled by area so you can pick something that matches your
interests. `good first issue` and `help wanted` are the entry points.

| Label | What it covers | Start in |
|---|---|---|
| `benchmark` | New corpora, metrics, baselines, reproductions of published runs | `tests/eval/`, `tests/benchmark_*.py` |
| `language support` | New Tier-A `LangSpec`s, better queries for existing grammars | `src/codebase_index/parsers/languages.py` |
| `graph extraction` | New edge kinds, better resolution, edge confidence | `src/codebase_index/parsers/treesitter.py`, `src/codebase_index/graph/` |
| `retrieval quality` | Ranking signals, fusion, priors, budgeting | `src/codebase_index/retrieval/` |
| `integrations` | Claude Code, Codex CLI, OpenCode, hooks, installers | `src/codebase_index/scaffold.py`, `adapters/`, `skill_template/` |
| `mcp` | MCP tools, envelopes, client configs | `src/codebase_index/mcp/server.py`, `docs/MCP.md` |
| `documentation` | Docs, examples, demo, FAQ | `docs/`, `examples/` |

Reproducing a benchmark on a repository we have not seen is one of the most
useful contributions there is. Use the *Benchmark report* issue template even
when the result is unflattering.

## What makes a good PR

- **One concern per PR**, on a branch named `<type>/<short-description>`
  (`feat/kotlin-imports`, `fix/fts-trigger-recreate`).
- **Tests.** New behaviour has tests; bug fixes have a regression test. The
  coverage gate is 80% and CI runs on Linux, macOS and Windows with Python
  3.11–3.13.
- **Contracts.** If `--json` or an MCP payload changes, regenerate the goldens
  intentionally (`UPDATE_GOLDEN=1 pytest tests/test_cli_golden.py
  tests/test_mcp_golden.py`) and explain the diff. Removing a field or changing
  a type bumps `MCP_SCHEMA_VERSION`.
- **Changelog.** Add user-visible changes under `[Unreleased]` in
  `CHANGELOG.md`. Do not bump the version; maintainers do that at release time.
- **Skill copies.** After touching `src/codebase_index/skill_template/`, run
  `python scripts/sync_skill_copies.py` and commit the regenerated copies.
- **Conventional Commits** for messages: `feat(retrieval): ...`,
  `fix(storage): ...`, `docs(readme): ...`.

### Retrieval-quality PRs specifically

A ranking change is accepted on evidence, not on a plausible story.

1. Put the new signal behind a boolean flag on `RetrievalTuning`
   (`src/codebase_index/retrieval/tuning.py`) and add it to `ABLATABLE` in
   `tests/eval/run_eval.py`. `RetrievalTuning.baseline()` must stay unchanged.
2. Run `python tests/eval/run_eval.py --ablate` on the shipped query sets *and*
   at least one external corpus (`tests/eval/gen_queries.py` builds one from any
   git repository in two commands).
3. Paste the pooled table and the paired significance row for your flag into
   the PR description. Ship on `p < 0.05` for the pooled set; otherwise leave the
   signal off by default or drop it.
4. Report mean tokens and latency alongside quality. Winning MRR while doubling
   the token bill is not a win.

## Fork and pull request workflow

1. Fork, clone your fork as `origin`, add the canonical repo as `upstream`:

   ```bash
   git remote add upstream https://github.com/denfry/codebase-index.git
   git fetch upstream
   git switch -c <type>/<short-description> upstream/main
   ```

2. Keep unrelated changes out. Do not commit generated indexes, build
   artifacts, local configuration, credentials, or editor files.
3. Rebase onto the latest `upstream/main` before opening or updating the PR
   (do not merge `main` into your branch).
4. Run the CI commands above, push to your fork, and open the PR against
   `denfry/codebase-index:main`. Describe the problem, the solution, how you
   verified it, and any compatibility impact.
5. Never force-push once review has started unless the rewrite is necessary and
   announced in the PR.

Maintainers cut releases from `main` following
[docs/RELEASE_CHECKLIST.md](docs/RELEASE_CHECKLIST.md); the version is
single-sourced in `src/codebase_index/__init__.py`.

## Reporting issues

- Bugs: [bug report template](.github/ISSUE_TEMPLATE/bug_report.yml), with
  `codebase-index doctor` output.
- Features: [feature request template](.github/ISSUE_TEMPLATE/feature_request.yml).
- Benchmark runs: [benchmark report template](.github/ISSUE_TEMPLATE/benchmark_report.yml).
- Languages: [language support template](.github/ISSUE_TEMPLATE/language_support.yml).
- Security: **not** an issue. See [SECURITY.md](SECURITY.md).

## Code of conduct and license

This project follows the [Contributor Covenant](CODE_OF_CONDUCT.md).
Contributions are licensed under the [MIT License](LICENSE).
