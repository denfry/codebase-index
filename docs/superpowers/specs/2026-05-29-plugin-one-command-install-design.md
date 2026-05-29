# One-Command Install via Claude Code Plugin — Design

> **Status:** Design approved (2026-05-29). Implementation NOT started.
> **Author:** denfry
> **Supersedes/extends:** M7 (skill packaging). Sits before M8/M9 as milestone **M7.5 — Plugin distribution**.

## Goal

Let a user install the `codebase-index` skill into Claude Code with a **single action**, with no
manual `pip` / `init` / `index` typing:

- **Command:** `/plugin install codebase-index@<marketplace>` (after community acceptance:
  `/plugin install codebase-index@claude-community`).
- **AI request:** "установи скилл codebase-index" → Claude runs
  `/plugin marketplace add <owner>/<repo>` + `/plugin install codebase-index`.

Everything else — provisioning the Python environment and the first index build — happens
automatically. The **only** prerequisite is Python 3.10+ on the machine (a plugin cannot ship a
Python runtime); the bootstrap surfaces a clear error if it is missing.

## The core constraint

Per the Claude Code plugin spec, **installing a plugin only copies files** (skills, hooks, MCP,
bin) into the plugin cache. It does **not** run `pip install`. The skill, however, depends on the
`codebase_index` Python CLI.

The official, policy-compliant resolution (documented in the plugins reference under "Persistent
data directory") is a **`SessionStart` hook that provisions dependencies once into
`${CLAUDE_PLUGIN_DATA}`** — a persistent directory that survives plugin updates — using the
"diff the bundled manifest against the stored copy, reinstall when they differ" pattern.

## Architecture

The repository becomes a Claude Code plugin. Layout (everything at plugin root except the
manifest):

```
.claude-plugin/
  plugin.json              # manifest: name=codebase-index, version, description, author, repository
  marketplace.json         # repo is its own marketplace (install from git owner/repo)
skills/
  codebase-index/SKILL.md  # current skill, adapted to call the cbx wrapper
hooks/
  hooks.json               # SessionStart → scripts/bootstrap
scripts/
  bootstrap.sh             # POSIX: provision venv in CLAUDE_PLUGIN_DATA
  bootstrap.ps1            # Windows equivalent
bin/
  cbx                      # POSIX wrapper on PATH → exec venv CLI
  cbx.ps1                  # Windows wrapper
README.md                  # transparency: what bootstrap does, prerequisites
requirements.lock          # pinned package version(s) — the bootstrap diff sentinel
```

Mechanisms relied upon (from the spec):

- **`bin/`** is automatically added to the Bash tool's `PATH` while the plugin is enabled. So
  `SKILL.md` calls plain `cbx search ...`, and the wrapper proxies into
  `${CLAUDE_PLUGIN_DATA}/venv` rather than any global CLI.
- **`${CLAUDE_PLUGIN_DATA}`** resolves to `~/.claude/plugins/data/<id>/` and outlives plugin
  versions — the venv lives there.
- **`${CLAUDE_PLUGIN_ROOT}`** points at the (ephemeral, per-version) install dir — used only to
  read bundled scripts and the pin file, never to write state.

## Bootstrap (SessionStart hook)

`hooks/hooks.json` runs `scripts/bootstrap.{sh,ps1}` on `SessionStart`. Logic (official
diff-pattern):

1. Compare the bundled pin file (`${CLAUDE_PLUGIN_ROOT}/requirements.lock`) with the stored copy in
   `${CLAUDE_PLUGIN_DATA}`. **Match → exit immediately** (warm start, ~0 ms).
2. Missing / differ → create or update the venv:
   - if `uv` is available → `uv venv` + `uv pip install codebase-index==<pinned>` (fast,
     cross-platform);
   - else → `python -m venv` + `pip install codebase-index==<pinned>` (fallback).
3. On success, copy the pin file into the data dir (marks success). On install failure, delete the
   copied pin file so the next session retries.
4. No Python 3.10+ → clear stderr message with remediation steps.

Delivery decision: **uv + PyPI** with a `python -m venv` + `pip` fallback. Requires network on the
first install and the package published to PyPI (M9 dependency). The pinned version guarantees
reproducibility.

This is what removes "many commands": installing the package is a side effect of the first session
start, not a user action.

## First index build & relationship to existing code

- `SKILL.md` already implements the freshness contract: `index.exists: false → run index`,
  `stale: true → update`. So the **first codebase question** auto-builds the index — no separate
  `index` command for the user.
- `cbx` stays a whitelist wrapper (as in the M7 plan): allows
  `search/symbol/refs/impact/stats/update/index`, refuses `clean/init/watch`. The only change is
  that the binary resolves from the venv in `PLUGIN_DATA`.
- Existing M7 work (`skill_template/`, the wheel, `init`) is **not** discarded: `init` remains the
  standalone (non-plugin) install path. The M9 PyPI release becomes a dependency of the plugin path
  — the bootstrap installs the package from there.

## Distribution, policy, testing

- **Marketplace:** first ship an in-repo `marketplace.json` so the plugin installs via
  `owner/repo`. In parallel, submit to `claude-community` (run `claude plugin validate` before
  submission) to reach the final true "one command" form.
- **Plugin policy:** the bootstrap hook runs unsandboxed at user trust — permitted, but requires
  transparency: the `README.md` and a first-run message describe what is downloaded from PyPI and
  where it is stored. The pinned package version keeps installs reproducible.
- **Testing:**
  - `claude plugin validate` passes.
  - Manifest + `marketplace.json` schema/parse test.
  - Bootstrap script test: creates the venv, diff-pattern is idempotent (second run is a no-op),
    `uv`-absent path falls back to `python -m venv`, failure path removes the stored pin file.
  - E2E: `claude --plugin-dir ./` → ask a codebase question → compact `recommended_reads` returned;
    `cbx clean` exits non-zero.

## Scope

New slice **M7.5 — Plugin distribution**, layered on top of M7 and not breaking M8/M9.

**In scope:** `plugin.json`, in-repo `marketplace.json`, `SessionStart` bootstrap
(`bootstrap.sh`/`.ps1`), `bin/cbx`(+`.ps1`) resolving the venv, README transparency section, tests,
`claude plugin validate` green.

**Out of scope / deferred:** PyPI publication itself (M9 — the bootstrap depends on it); community
marketplace acceptance (external review timeline); hooks/watch auto-update (M8); vendoring
platform-specific wheels for fully offline install.

## Open prerequisites

- The package must be on PyPI under a pinned version before the plugin path works end-to-end (M9).
  Until then, the bootstrap can be pointed at a git ref or a bundled wheel for testing.
