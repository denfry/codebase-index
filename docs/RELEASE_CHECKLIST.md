# Release Checklist

A repeatable, copy-pasteable checklist for cutting a `codebase-index` release.
Tagging `v*` triggers `.github/workflows/release.yml`, which builds,
`twine check`s, runs the clean-machine smoke, publishes a **GitHub release**, and
publishes to **PyPI** via Trusted Publishing (OIDC — no stored token). A manual
`workflow_dispatch` run publishes the current `main` build to PyPI without
recreating a GitHub release (used to publish an already-tagged version).

Work top to bottom. Do not tag until every required box is checked.

## 1. Version sync (single source + the two manual mirrors)

The package version is single-sourced from `src/codebase_index/__init__.py`
(hatch dynamic version). Two files mirror it and are **not** auto-synced — bump
them by hand and verify:

- [ ] `src/codebase_index/__init__.py` → `__version__` bumped (canonical).
- [ ] `.claude-plugin/plugin.json` → `"version"` matches.
- [ ] `.claude-plugin/marketplace.json` → version matches (if present).
- [ ] `requirements.lock` → the GitHub tarball tag matches the new tag
      (`.../tags/vX.Y.Z.tar.gz`). The plugin bootstrap installs exactly this pin.
- [ ] README / QUICKSTART / INSTALLATION / FAQ / MCP install snippets reference
      the new tag (`@vX.Y.Z`).
- [ ] Skill copies + `.skill_version` stamps regenerated and in sync:

  ```bash
  python scripts/sync_skill_copies.py          # regenerate
  python scripts/sync_skill_copies.py --check   # CI gate: must pass clean
  ```

## 2. Tests and lint

- [ ] `pytest` green locally (coverage gate `--cov-fail-under=80` enforced).
- [ ] `ruff check src/ tests/` clean.
- [ ] `mypy src/codebase_index` (advisory) reviewed.
- [ ] Slow/perf tests considered: `pytest --runslow` for index/search latency.
- [ ] CI matrix green (Ubuntu/macOS/Windows × py3.11–3.13) on the release branch.

## 3. Benchmark run

- [ ] Public suite runs and reports all metric families:

  ```bash
  python tests/benchmark_public.py --workdir .tmp-public-benchmark
  ```

- [ ] If any headline number in README/COMPARISON changed, re-run the honest
      benchmark and refresh `tests/benchmark_honest_RESULTS.md` with raw logs.
      Do **not** publish a new number without a logged run (see BENCHMARKS.md).

## 4. Security / doctor checks

- [ ] `codebase-index doctor --strict` exits 0 in this repo.
- [ ] No secret/binary/generated file slipped into the index (doctor reports clean).
- [ ] External-embeddings path still refused without all three gates
      (config + key + warning) — covered by tests, eyeball SECURITY_MODEL.md if
      anything in `embeddings/` changed.
- [ ] Skill `allowed-tools` still limited to read-only subcommands (no `Bash(python *)`).

## 5. Install smoke tests

- [ ] Clean-venv build + install + init + index + search:

  ```bash
  python scripts/release_smoke.py     # build wheel, install in throwaway venv, exercise path
  ```

- [ ] `pipx install "git+https://github.com/denfry/codebase-index.git@vX.Y.Z"` on a
      clean machine → `init` → `index` → `search` works (the M9 exit criterion).
- [ ] Installer scripts sanity-checked: `tests/installer/smoke.sh` /
      `tests/installer/smoke.ps1`.

## 6. Plugin smoke tests

- [ ] `.claude-plugin/plugin.json` + `marketplace.json` validate and version-match
      (`tests/test_plugin_manifest.py`).
- [ ] `bin/cbx` / `bin/codebase-index` wrappers still enforce the subcommand
      whitelist and refuse non-whitelisted commands like `clean`
      (`tests/test_plugin_wrappers.py`).
- [ ] Plugin ↔ skill parity holds (`tests/test_plugin_skill_parity.py`).
- [ ] `SessionStart` bootstrap provisions a venv from `requirements.lock` and
      reinstalls only when the lock changes (`tests/test_bootstrap.py`).

## 7. MCP smoke tests

- [ ] `codebase-index mcp --root .` starts and registers all tools
      (`tests/test_mcp_server.py`): `healthcheck`, `search_code`, `find_symbol`,
      `find_refs`, `impact_of`, `explain_code`, `index_stats`.
- [ ] MCP and CLI agree (shared `service.py`) — vector channel + graph tier
      surfaced in both.
- [ ] `docs/MCP.md` client templates still match the shipped tool list.

## 8. Changelog and docs

- [ ] `CHANGELOG.md`: move `[Unreleased]` items under the new `vX.Y.Z` dated
      heading; add the version-compare link at the bottom.
- [ ] ROADMAP / docs reflect anything that shipped or moved.
- [ ] `docs/PRODUCT_UPGRADE_PLAN.md` status column updated for shipped items.

## 9. Tag and publish

- [ ] Commit the version bump + changelog on the release branch; open/merge PR.
- [ ] Tag: `git tag vX.Y.Z && git push origin vX.Y.Z`.
- [ ] `release.yml` build job green (test gate + `python -m build` + `twine check`
      + `release_smoke.py`).
- [ ] GitHub release created with artifacts attached; release notes reviewed.
- [ ] Post-publish: re-run `pipx install "...@vX.Y.Z"` once to confirm the tag
      resolves.

## Future hardening (not yet implemented — do not claim as done)

- [ ] PyPI publish (then `pip install codebase-index`, `uvx`, `pipx` without a Git URL).
- [ ] Homebrew tap.
- [ ] Signed release checksums (`cosign` / `minisign`).
- [ ] Published SBOM (e.g. CycloneDX) attached to each release.
- [ ] Provenance / build attestation (SLSA).

These matter for a tool that reads entire repositories, but they are roadmap
items in the current line. See `docs/PRODUCT_UPGRADE_PLAN.md` §9.
