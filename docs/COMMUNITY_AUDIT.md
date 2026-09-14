# Community readiness audit

Date: 2026-09-04. Baseline: `main` at 1.9.0 (`b48ed14`). Every finding lists what
was wrong, why it matters for adoption, the fix, and its status on the
`chore/community-readiness` branch. Severity:

- **P0** blocks adoption or trust
- **P1** major friction
- **P2** worthwhile improvement
- **P3** polish

Status legend: **fixed** (in this branch), **partial**, **open** (needs the
maintainer or is future work).

## Summary

The engineering under the hood was already unusually careful: a shared service
layer for CLI/skill/MCP, golden snapshots for every payload, a coverage gate,
an ablation harness with significance tests. What kept a serious developer from
trusting it in the first minute was the *presentation of evidence*: the README's
headline number came from a private repository with asymmetric token
accounting, several docs showed invented output, three doc pairs contradicted
each other, and the demo image was a mock-up. Those are fixed. The remaining
gaps are things only a maintainer can do (enable Discussions, upload the social
preview, apply labels, record a GIF) and two real benchmark holes (agent
task-level evaluation, a large-monorepo run).

Scores are the maintainer-facing view; the definitions are at the end.

| Dimension | Before | After |
|---|---:|---:|
| Technical quality | 72 | 84 |
| Onboarding | 62 | 82 |
| Documentation | 58 | 82 |
| Credibility | 45 | 78 |
| Discoverability | 65 | 70 |
| Contributor readiness | 50 | 82 |
| Demo quality | 30 | 75 |
| Launch readiness | 35 | 72 |

## P0

### P0-1 Headline benchmark was not reproducible and not symmetric — fixed

- **Wrong:** README, COMPARISON and BENCHMARKS led with "recall@3 70% vs 40%,
  ~13× fewer tokens" from `tests/benchmark_honest.py` on `NewTowny`, a private
  repository on the maintainer's disk. The 13× compared index signature snippets
  (~27 tokens) with grep's 80-line windows. Nobody outside could run it.
- **Why it matters:** the first thing a Hacker News reader does with a benchmark
  claim is try to reproduce it. A private corpus plus asymmetric accounting reads
  as marketing, and it discredits the genuinely good ablation harness next to it.
- **Fix:** `tests/eval/run_baselines.py` runs on Flask, Gson and Fastify at pinned
  commits with git-derived ground truth, real ripgrep, one tokenizer on both sides,
  and significance tests. Logged run committed. Honest result: hit@3 0.547 vs 0.304
  (p < 0.001) at roughly equal tokens. The 13× claim is withdrawn everywhere; the
  old script is labelled historical.

### P0-2 Read plan cost more tokens than grep — fixed

- **Wrong:** the new benchmark found the index's follow-through reads averaged
  6.8k tokens vs 3.5k for grep, because symbol-aligned chunks can span a whole
  1,500-line class and `recommended_reads` handed that span to the agent verbatim.
- **Why it matters:** the product promise is "read less"; under fair accounting it
  was reading more.
- **Fix:** `retrieval.max_read_lines` (default 120) caps read-plan entries at the
  definition head, with additive `truncated` / `line_end_full` fields. Tokens
  3.8k, ranking quality unchanged (the "uncapped" row in the log is identical on
  every quality metric).

### P0-3 Fabricated examples in user-facing docs — fixed

- **Wrong:** QUICKSTART showed an `AuthService.ts` results table with a `Score`
  column the renderer does not print; INSTALLATION showed an invented `doctor`
  transcript; `assets/demo.png` was a mock-up with made-up paths; README's JSON
  example was invented.
- **Why it matters:** a user who runs the quick start and sees different columns
  assumes the tool is broken or the docs are stale. Either way they leave.
- **Fix:** every example is now captured output on `pallets/flask@d318b683`;
  `examples/demo/EXPECTED_OUTPUT.md` is the transcript; the hero image is an SVG
  rendered from it by a committed script.

### P0-4 Plugin wrappers refused four documented commands — fixed

- **Wrong:** `bin/cbx` and `bin/cbx.ps1` whitelisted ten subcommands; the skill
  advertised fourteen. `architecture`, `diff-impact`, `path`, `describe` failed
  from the Claude Code plugin with "refusing subcommand".
- **Why it matters:** the plugin is the lowest-friction install path and it broke
  the Trace/Predict half of the pitch.
- **Fix:** whitelists aligned; `tests/test_plugin_wrappers.py` pins all four
  wrappers to the same set.

### P0-5 Security policy had no reporting channel — fixed

- **Wrong:** SECURITY.md said "email the maintainers" with no address and listed
  1.2.x as the supported version.
- **Why it matters:** a tool that reads whole repositories must have a working
  private disclosure path; an unreachable policy is worse than none.
- **Fix:** GitHub private vulnerability reporting URL, supported line 1.9.x,
  explicit statement that checksums/SBOM are not yet shipped. **Open for
  maintainer:** confirm private vulnerability reporting is enabled in repository
  settings (Security → Policy).

### P0-6 MCP server did not start on the current SDK — fixed

- **Wrong:** `pip install "codebase-index[mcp]"` resolves `mcp>=1.0` to mcp 2.x,
  where `FastMCP` was renamed `MCPServer` and the old import path raises. The
  server printed "needs the optional extra" with the extra installed, and the
  documented `codebase-index mcp --root <repo>` form was rejected because
  `--root` was only a global option. CI never noticed: the MCP test files
  wrapped *our own module's* import in the skip guard, so on mcp 2.x all 41 MCP
  tests skipped silently.
- **Why it matters:** "MCP-ready" was on the README badge line and the MCP path
  is how Cursor/Zed/Windsurf/Claude Desktop users arrive.
- **Fix:** import `MCPServer` first, fall back to `FastMCP`; `--root` accepted on
  the subcommand; tests skip only when the SDK itself is absent. Verified against
  mcp 1.29.1 and 2.1.1 with a stdio initialize / tools/list / healthcheck
  round-trip.

## P1

### P1-1 Benchmark corpus leakage — fixed

`gen_queries.py` documented that changelog-style files were excluded from the
evaluation corpus; the harness never imported the list, and Flask's `CHANGES.rst`
was not matched at all. Fixed in both places with regression tests. The 1.9.0
version-over-version numbers were measured with the changelog in the corpus;
re-run on this repository after the fix, the shipped default still beats the
1.7.0 baseline on every metric at p ≤ 0.004, so the conclusion stands.

### P1-2 Three duplicate doc pairs with contradictions — fixed

`SCHEMA.md` vs `DATABASE_SCHEMA.md` (the latter described columns and tables that
do not exist), `RETRIEVAL.md` vs `RETRIEVAL_PIPELINE.md`, `docs/SECURITY.md` vs
`SECURITY_MODEL.md` (both claimed `doctor` checks that `doctor.py` does not
implement). One canonical page each; the others are redirect stubs.

### P1-3 Two roadmaps — fixed

Root `ROADMAP.md` (milestones, stale: said PyPI not shipped) and `docs/ROADMAP.md`
(product). Root is now a milestone history table; docs owns forward work.

### P1-4 No contributor path — fixed

CONTRIBUTING pointed at `uv sync --all-extras` (no lockfile) and `ruff format
--check` (not enforced, fails on 88 files). No architecture walk-through for a
newcomer, no recipe for the contributions the project actually wants. Added
`docs/DEVELOPMENT.md` with verified commands and recipes (language, edge kind,
ranking signal, MCP tool, CLI command), rewritten CONTRIBUTING with label → area →
starting-file table and evidence rules for ranking PRs.

### P1-5 Release notes were auto-generated PR lists — fixed

The changelog is well written but GitHub releases showed only "What's Changed".
`scripts/release_notes.py` now provides the body from the changelog section, and
an empty section fails the release job. `check_versions.py` refuses a tag whose
name does not match `__version__`.

### P1-6 Packaging only tested at tag time — fixed

`python -m build`, `twine check` and the clean-venv install smoke ran only in
`release.yml`. A `package` job now runs them on every PR.

### P1-7 Stale version pins and wrong config path across docs — fixed

`@v1.8.0` install pins, `1.4.0` doctor output, `.codeindex.json` (the config
lives at `.claude/cache/codebase-index/config.json`), FAQ MCP tool list missing
three tools, bug template placeholder `0.1.0`. All corrected;
`check_versions.py` and `check_links.py` run in CI so the next drift is caught.

### P1-8 Discussions disabled, issue chooser allowed blank issues — partial

`config.yml` now disables blank issues and links Discussions and the security
form. **Open for maintainer:** enable Discussions (Settings → General →
Features) or the link 404s; run `scripts/apply_labels.sh` once to create the
labels the templates and CONTRIBUTING refer to.

## P2

### P2-1 No demo on a real repository — fixed

`examples/demo-project/README.md` described a project that does not exist in the
repo. Replaced by `examples/demo/` on Flask with scripts for bash and PowerShell,
expected output, and `docs/DEMO.md` with VHS/asciinema recording steps.
**Open for maintainer:** record the GIF (the tape file is ready); the README
uses the static SVG until then.

### P2-2 README first screen — fixed

Twelve badges, a mock image, and a value proposition that needed the second
screen to explain "why not grep". Rebuilt: one-sentence proposition, agent list,
real terminal card, 60-second try-it, "why this exists" with the grep / repo-map
/ cloud comparison, evidence with the chart, then everything else.

### P2-3 Social preview not uploaded — open

`assets/social-preview.png` exists; `usesCustomOpenGraphImage` is false. Upload
under Settings → Social preview. Links on X/Slack/Discord render without an
image until then.

### P2-4 `docs/SEO.md` carried stale launch templates — fixed

Templates quoted v1.3.0 and `git+https` installs. Folded into
`docs/COMMUNITY_LAUNCH.md` and deleted.

### P2-5 Installer docs in Russian — fixed

`docs/installer.md` translated; flags verified against `install.sh`.
**Open:** `install.sh`, `install.ps1`, `lib/`, `adapters/` still print Russian
log/help strings. Low impact (the PyPI path is primary) but confusing for
contributors reading the scripts.

### P2-6 `explain` lacks `--limit` — open

`search` accepts `--limit`; `explain` does not, contradicting ARCHITECTURE's
"search-family commands accept `--limit`". Small, additive; left for a follow-up
PR since it changes the CLI contract and goldens.

### P2-7 MCP client configs unverified — open

Templates for Cursor / VS Code / Zed / Windsurf are marked unverified. Needs a
person with each client to confirm; the SUPPORT page asks for exactly that.

### P2-8 `workflow_dispatch` on release.yml can publish untagged builds — open

A manual run publishes whatever `main` builds to PyPI without a tag check. Low
risk while the maintainer is the only one with the button, but consider
requiring a version input.

## P3

- `pyproject.toml` keywords gained `code-graph`, `impact-analysis`,
  `claude-code-plugin`; classifiers unchanged. — fixed
- `assets/demo.png` and its generator removed; `gen_assets.py` still needs
  Windows fonts (documented). — fixed / open
- `docs/superpowers/` contains internal planning documents. They are honest
  history and cost nothing, but a newcomer may mistake them for current
  design. A one-line README in that folder would help. — open
- CRLF/LF: `.gitattributes` covers scripts; Markdown files get CRLF on Windows
  checkouts, producing noisy `git diff` warnings for Windows contributors.
  Consider `* text=auto eol=lf`. — open

## What was verified, not just read

- Full test suite green in a clean venv (`pytest`, coverage 84%), `ruff check`,
  `mypy`, `sync_skill_copies.py --check`, `check_versions.py`, `check_links.py`,
  `python -m build` + `twine check` + `release_smoke.py`.
- Every README command run on Flask at the pinned commit; output captured.
- Public baseline benchmark run twice (before and after the read cap); both logs
  kept in the raw JSON (`index (uncapped reads)` row).
- Self-repository retrieval eval re-run after the leakage fix.

## Score definitions

- **Technical quality:** tests, contracts, CI matrix, known bugs in shipped paths.
- **Onboarding:** minutes from landing to first useful result, with no guesswork.
- **Documentation:** accuracy first, then coverage, then duplication.
- **Credibility:** can a sceptic reproduce every number and every example?
- **Discoverability:** description, topics, PyPI page, social card, search terms.
- **Contributor readiness:** can a stranger land a useful PR in an evening?
- **Demo quality:** does the demo show real value on real code, reproducibly?
- **Launch readiness:** are the texts, links, and community channels ready for
  the first wave of strangers?
