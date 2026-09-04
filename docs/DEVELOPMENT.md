# Development guide

Everything you need to make a first contribution in about fifteen minutes. For
the full design see [ARCHITECTURE.md](ARCHITECTURE.md); this page is the
hands-on version.

## 1. Map of the code (two minutes)

```
src/codebase_index/
├── cli.py              Typer commands; every command delegates to service.py
├── service.py          shared CLI/MCP layer: db resolution, search/impact/stats payloads
├── discovery/          walker.py (file walk), ignore.py (.gitignore & co), classify.py (language, secrets, binary, generated)
├── parsers/            languages.py (LangSpec per language), treesitter.py (symbols + edges), line_chunker.py
├── indexer/            pipeline.py (build_index / update_index), freshness.py
├── graph/              builder.py (edge resolution), expand.py (impact), analysis.py, navigate.py, export.py
├── retrieval/          pipeline.py (search), searchers.py, fusion.py, rerank.py, priors.py, tuning.py, budget.py, skeleton.py
├── storage/            db.py, schema.sql, repo.py (typed SQL accessors)
├── mcp/server.py       stdio MCP server over the same service layer
├── output/             markdown.py, json.py, redact.py
└── skill_template/     canonical skill source; copies under .claude/ .codex/ .opencode/ skill/ skills/ are generated
```

Query path in one line: `retrieval/pipeline.py::search` → `detect_intent` →
`_run_retrievers` (path, symbol, FTS5, optional vector, optional graph) → `fuse`
(RRF) → `rerank` → dedup / diversify → token budget → payload.

## 2. Set up (three minutes)

Python 3.11+ and git are the only prerequisites.

```bash
git clone https://github.com/denfry/codebase-index.git
cd codebase-index
python -m venv .venv
. .venv/bin/activate            # Windows: .venv\Scripts\activate
pip install -e ".[dev,mcp]"
```

`dev` brings pytest, ruff, mypy, pyyaml and the `mcp` SDK; `mcp` is listed
separately so the server extra stays installable on its own. Optional extras:
`embeddings`, `embeddings-local`, `watch`, `build`.

Before running the CLI **inside this checkout**, export
`CBX_NO_SKILL_AUTO_UPDATE=1`. Without it the skill auto-updater may rewrite the
committed `.skill_version` stamps when the installed package metadata is stale.
`tests/conftest.py` sets this for pytest automatically.

## 3. Run the checks (what CI runs)

CI (`.github/workflows/ci.yml`) runs exactly these:

```bash
ruff check src tests
mypy src/codebase_index
python scripts/sync_skill_copies.py --check
pytest                                  # coverage gate: --cov-fail-under=80 (pyproject.toml)
pytest tests/test_perf_smoke.py --runslow --no-cov   # Linux + 3.12 only
```

Notes:

- `ruff format` is **not** enforced; running `ruff format --check` on the
  current tree reports many files. Format new code if you like, but do not
  reformat files you are not otherwise touching.
- Tests marked `slow` are skipped unless you pass `--runslow`
  (`tests/conftest.py::pytest_addoption`).
- Golden snapshots live in `tests/golden/*.json`. When an output contract
  changes on purpose, regenerate them and review the diff:

  ```bash
  UPDATE_GOLDEN=1 pytest tests/test_cli_golden.py tests/test_mcp_golden.py
  ```

  `tests/golden_utils.py` masks timestamps, commit SHAs and the package version
  so snapshots are stable across machines; `schema_version` is deliberately not
  masked because it is the contract under test.
- The skill copies gate: anything under `src/codebase_index/skill_template/` or
  the version in `src/codebase_index/__init__.py` must be propagated with
  `python scripts/sync_skill_copies.py` (no flag) before committing.

Run a single test file quickly without the coverage gate:

```bash
pytest tests/test_fusion.py -q --no-cov
```

## 4. Try the CLI on a fixture

```bash
export CBX_NO_SKILL_AUTO_UPDATE=1
codebase-index --root tests/fixtures/sample_repo index
codebase-index --root tests/fixtures/sample_repo search "refresh token" --json
codebase-index --root tests/fixtures/sample_repo impact User
```

`tests/fixtures/sample_repo/` deliberately contains files that must never be
indexed (`.env`, `secrets.pem`, `huge.json`, `logo.png`); see
`tests/fixtures/README.md`.

## 5. Benchmark workflow

The project rule is *measure improvements, do not assert them*. Three surfaces
exist; know which one you are using.

| Surface | Command | Use it for |
|---|---|---|
| Retrieval eval (ranking gate) | `python tests/eval/run_eval.py` | Any change that can move ranking |
| Public synthetic suite | `python tests/benchmark_public.py --workdir .tmp-public-benchmark` | Metric-shape regression check (`tests/test_public_benchmark.py` wraps it in CI) |
| Older single-repo script | `python tests/benchmark_honest.py --repo <path>` | Index vs `rg`+window token/recall comparison against one repository |

The retrieval eval (`tests/eval/`):

- `harness.py` builds one index per corpus into a temp dir (`build_corpus_index`)
  and reuses it for every variant, then computes recall@5/10, MRR, nDCG@10,
  hit@3, P@5, MAP, `useful@budget`, mean tokens, duplicate rate, and latency
  percentiles (`evaluate`, `format_table`, `pool`).
- `metrics.py` holds the IR metrics plus `paired_bootstrap_ci` and
  `paired_permutation_p` (seeded, reproducible).
- `gen_queries.py` mints leak-free ground truth from git history (commit subject
  → files that commit changed):

  ```bash
  python tests/eval/gen_queries.py --repo ../some-repo --out /tmp/some-repo.yml
  python tests/eval/run_eval.py --corpus ../some-repo:/tmp/some-repo.yml --ablate
  ```

- `run_eval.py --ablate` runs a one-signal-off sweep over the boolean flags in
  `ABLATABLE` and prints a paired significance table for each row.

Checked-in query sets: `tests/eval/queries/self_repo.yml` (hand-written) and
`self_repo_git.yml` (generated). See [tests/eval/README.md](../tests/eval/README.md).

## 6. Recipes

### Add a language (Tier A symbol extraction)

1. `src/codebase_index/discovery/classify.py`: add the extension to
   `_LANG_BY_SUFFIX` and the language id to `_TREE_SITTER_LANGS`.
2. `src/codebase_index/parsers/languages.py`: add a `LangSpec(name, ts_name,
   defs_query, calls_query, imports_query)` and register it in `LANGS`.
   Definitions are captured as `@def.<kind>` with the name node as `@name`;
   calls capture `@callee`; imports/inheritance capture `@import.module`,
   `@extends.base`, `@implements.iface` (mapped by `_EDGE_PREFIXES` in
   `parsers/treesitter.py`).
3. If the grammar's node kinds are not covered by `_definition_kind` /
   `_name_node` / `_callee_node` in `parsers/treesitter.py`, extend them.
4. Add a fixture under `tests/fixtures/multilang/` and cases in
   `tests/test_languages.py` (query compiles against the grammar) and
   `tests/test_multilang_symbols.py` (`test_registry_consistency_every_treesitter_lang_extracts`
   is parametrised over the registry, so a language with zero symbols fails loudly).
5. Update the tier table in [LANGUAGES.md](LANGUAGES.md).

```bash
pytest tests/test_languages.py tests/test_multilang_symbols.py tests/test_graph.py -q --no-cov
```

### Add a graph edge kind

Edges are rows in the `edges` table (`storage/schema.sql`): `edge_type`,
`src_kind`/`src_id`, `dst_kind`/`dst_id`/`dst_name`, `line`, `resolved`, and a
`confidence` of `extracted`, `inferred`, or `ambiguous`.

1. Emit the edge from `parsers/treesitter.py::_extract_graph_edges` (query
   captures) or `_extract_edges` (calls). Today's types are `call`, `reference`,
   `import`, `extends`, `implements`.
2. Resolve it in `graph/builder.py::resolve_edges`. Symbol-target types are in
   `_SYMBOL_EDGE_TYPES` and resolve only on a repo-unique name; imports resolve
   by path suffix. Anything that cannot be pinned to one target is marked
   `ambiguous` by `repo.mark_ambiguous_edges`. Never guess.
3. Make sure `graph/expand.py` (impact), `graph/navigate.py` (path/describe) and
   `graph/export.py` (HTML/GraphML/DOT/Neo4j) do the right thing with the new
   type, and document it in [SCHEMA.md](SCHEMA.md) and [LANGUAGES.md](LANGUAGES.md).
4. Add tests in `tests/test_graph.py` / `tests/test_graph_coverage.py`; goldens
   that include edges (`impact_*`, `mcp_impact_of*`, `path_*`) may need
   regeneration.

### Change retrieval ranking

1. Put every new signal behind a boolean on `RetrievalTuning`
   (`src/codebase_index/retrieval/tuning.py`). Defaults are the shipped
   configuration; `RetrievalTuning.baseline()` must keep reproducing the 1.7.0
   behaviour, otherwise the ablation table is meaningless.
2. Wire it in `retrieval/pipeline.py::search` (candidate generation, `fuse`,
   `rerank`, selection) or in `retrieval/rerank.py` / `retrieval/priors.py`
   (`source_role_prior`, capped by `MAX_ABS_PRIOR` so priors stay tiebreakers).
3. Add the flag to `ABLATABLE` in `tests/eval/run_eval.py`.
4. Run `python tests/eval/run_eval.py --ablate` on at least two corpora
   (`--corpus`), and paste the pooled table plus the significance row into the
   PR. A signal ships only if its row is significant (p < 0.05) on the pooled
   set; otherwise it stays off by default or is removed.
5. Unit tests: `tests/test_fusion.py`, `tests/test_hybrid_ranking.py`,
   `tests/test_priors.py`, `tests/test_diversity.py`.

### Add an MCP tool

1. `src/codebase_index/mcp/server.py`: decorate a function with `@_tool()` and
   return `_emit("<tool_name>", payload)`. The `_emit` envelope adds
   `schema_version` and `tool`; error paths must use it too
   (`_no_index_payload()` is the standard no-index body).
2. Do the real work in `service.py` so the CLI command and the MCP tool share
   one implementation.
3. Register the tool in `tests/test_mcp_server.py::test_mcp_server_has_expected_tools`
   and in the envelope parametrisation there; add a golden case in
   `tests/test_mcp_golden.py` and generate `tests/golden/mcp_<name>.json` with
   `UPDATE_GOLDEN=1`.
4. Document it in the tool table of [MCP.md](MCP.md). Bump `MCP_SCHEMA_VERSION`
   only for a breaking change (field removal or type change).

### Add a CLI command

Add it in `cli.py`, delegate to `service.py`, support `--json`, and if the skill
should be allowed to call it, add it to the `ALLOWED` whitelist in
`src/codebase_index/skill_template/scripts/cbx` and `cbx.ps1`, then run
`python scripts/sync_skill_copies.py` and update `references/commands.md` in the
template. Add a golden in `tests/test_cli_golden.py` for `--json` output.

## 7. Release process (maintainers)

The version is single-sourced in `src/codebase_index/__init__.py`
(`__version__`); `pyproject.toml` reads it through hatch dynamic versioning.
Two mirrors are kept in sync by `scripts/sync_skill_copies.py`:
`.claude-plugin/plugin.json` (`version`) and `requirements.lock` (release tag
tarball). Tagging `vX.Y.Z` triggers `.github/workflows/release.yml`: test gate,
build, `twine check`, `scripts/release_smoke.py` (clean venv install → init →
index → search), GitHub release, and PyPI publish via Trusted Publishing.

Follow [RELEASE_CHECKLIST.md](RELEASE_CHECKLIST.md) top to bottom. Contributors
never bump the version; they add entries under `[Unreleased]` in
`CHANGELOG.md`.

## 8. Where to ask

Open a [discussion](https://github.com/denfry/codebase-index/discussions) for
design questions, an issue for bugs and concrete proposals, and read
[CONTRIBUTING.md](../CONTRIBUTING.md) for the PR workflow.
