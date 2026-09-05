# Community launch kit

Drafts for the first public wave, plus the feedback loop that decides what
happens after it. Every text below uses only claims backed by logs in this
repository. Do not add numbers that are not in
[BENCHMARKS.md](BENCHMARKS.md), and do not add social proof that does not exist.

The one benchmark sentence every post may use:

> On three public repos (Flask, Gson, Fastify; 450 questions mined from git
> history) the index put the right file in its top three 55% of the time vs 30%
> for a disciplined ripgrep agent, at about the same context tokens (p < 0.001,
> raw logs and a one-command rerun in the repo).

Repository: https://github.com/denfry/codebase-index · PyPI: `pip install codebase-index`

## Pre-launch checklist (maintainer)

- [x] Enable **Discussions** (Settings → General → Features); `config.yml`,
      `SUPPORT.md` and `DEVELOPMENT.md` link to it.
- [ ] Upload `assets/social-preview.png` (Settings → Social preview).
- [x] Run `scripts/apply_labels.sh` once (needs `gh auth`).
- [x] Confirm private vulnerability reporting is enabled (Security tab).
- [ ] Record the GIF from `docs/demo.tape` (optional; the SVG card works).
- [ ] Tag the release that contains this branch, so the README, PyPI page and
      release notes agree.
- [x] Repository description (About): *Local code map for AI coding agents:
      find, trace, and predict change impact with file:line evidence. Claude
      Code · Codex · OpenCode · MCP. No network by default.*
- [x] Topics (20 max, current set is fine): `ai-agents ai-coding claude-code
      cli code-search codebase-indexing codex-cli context-engineering
      developer-tools fts5 local-first mcp opencode python rag
      semantic-code-search sqlite token-optimization tree-sitter
      cursor-alternative`. If a slot frees, swap `cursor-alternative` for
      `code-graph`; it describes the product better than a comparison.

## Hacker News

**Title** (under 80 chars, no superlatives):

> Show HN: codebase-index – a local code map so Claude Code/Codex open the right file

**Post:**

> I built this because I kept watching Claude Code and Codex grep for a keyword,
> open the wrong file, then read three whole files to recover. On anything past a
> few hundred files that was most of the token bill and a good share of the wrong
> answers.
>
> codebase-index is a Python CLI that indexes a repo into SQLite (FTS5 + Tree-sitter
> symbols + an import/call/reference/inheritance graph) and answers three questions
> with file:line evidence: where is X implemented, what calls this / how does A
> reach B, and what breaks if I change this (including "what does my current diff
> touch"). It installs as a Claude Code skill/plugin, a Codex AGENTS.md block, an
> OpenCode command, or a stdio MCP server; all four call the same service layer.
>
> Things I tried to get right:
>
> - Every answer carries its uncertainty: index freshness, result confidence,
>   graph coverage per language, and each edge tagged extracted/inferred/ambiguous,
>   so the agent can tell "nothing references this" from "the graph doesn't know".
> - Local only. No network in the base install, no telemetry; secrets excluded
>   before parsing and redacted again on output; `doctor --strict` audits that.
> - Measured, not asserted. Ranking signals ship only if they survive an ablation
>   with significance tests on a pooled multi-language query set. Against a
>   disciplined ripgrep agent on Flask, Gson and Fastify (450 questions mined from
>   git history, same tokenizer on both sides) it puts the right file in the top
>   three 55% vs 30% at about the same context tokens. Raw logs and a one-command
>   rerun are in the repo; I'd genuinely like people to run it on their own repos
>   and post the numbers, especially bad ones.
>
> What it is not: an IDE, a cloud search, or an agent. It also does not yet have
> framework-aware edges (routes → handlers → DB) or an agent task-level benchmark;
> both are on the roadmap and I say so in the README rather than implying them.
>
> https://github.com/denfry/codebase-index

## Reddit

Post once per community, days apart, with the wording matched to the audience.
Reply to every substantive comment; do not cross-post identical text.

### r/ClaudeAI (or the Claude Code community)

> **A local index skill so Claude Code opens the right file instead of grepping around**
>
> I wrote a skill + plugin that gives Claude Code a ranked, line-precise answer to
> "where is X", "who calls this", and "what breaks if I change this" before it
> opens anything. `pip install codebase-index`, `codebase-index init --target
> claude`, done; or `/plugin marketplace add denfry/codebase-index`.
>
> It's local (SQLite + Tree-sitter, no network, no telemetry), and it tells Claude
> when it isn't sure: freshness, confidence, and per-edge extracted/inferred/
> ambiguous tags. There's also a PostToolUse hook that keeps the index fresh while
> Claude edits.
>
> Numbers, since "it feels better" is worthless: on Flask/Gson/Fastify with 450
> questions mined from git history, top-3 hit rate 55% vs 30% for a disciplined
> ripgrep agent at about the same context tokens. Raw logs in the repo; the
> benchmark runs on any git repo with one command, and I'd love to see your
> results.
>
> Repo: https://github.com/denfry/codebase-index

### r/LocalLLaMA / local AI tooling

> **Local-first code retrieval + graph for coding agents (no embeddings required, MCP server included)**
>
> codebase-index builds a SQLite index of a repository: FTS5 for text, Tree-sitter
> symbols for 12 languages, and an import/call/reference/inheritance graph. It
> serves ranked file:line evidence, reference lookups, dependency paths and
> change-impact analysis over a CLI, a stdio MCP server, and skills for Claude
> Code/Codex/OpenCode. Embeddings are optional (local sentence-transformers via
> sqlite-vec); the default path is purely lexical + structural and makes zero
> network calls. External embedding APIs are refused unless you opt in three
> separate ways.
>
> Benchmarks are the part I care about most: a multi-language ablation harness
> with significance tests, and a public comparison against a ripgrep agent and a
> repo-map-style context blob on Flask/Gson/Fastify (55% vs 30% top-3 hit rate,
> tokens roughly equal). Everything reruns with one command.
>
> https://github.com/denfry/codebase-index

### r/programming

> **How I benchmarked a code index against grep without cheating (and what the first run got wrong)**
>
> Short write-up on building a retrieval layer for coding agents and the benchmark
> mistakes I made: a headline number from a private repo, token accounting that
> charged my tool for signatures and grep for whole windows, and a changelog that
> leaked commit subjects into the corpus. The fixed protocol mines ground truth from
> git history (commit subject → files changed), charges both sides with the same
> tokenizer for what actually enters context, and reports paired bootstrap CIs.
> The first honest run showed my read plan cost *more* tokens than grep, which led
> to a real fix. Code, logs, and the harness are all in the repo.
>
> https://github.com/denfry/codebase-index/blob/main/docs/BENCHMARKS.md

### r/opensource / developer tools

> **codebase-index: MIT, local, benchmarked code map for AI coding agents; looking for benchmark reproductions**
>
> The most useful contribution right now is running
> `python tests/eval/run_baselines.py --repo /path/to/your/repo` and posting the
> table with the benchmark-report issue template, especially if it's unflattering.
> Second most useful: a Tier-A language spec (Swift, Dart, Scala are the gaps).
> DEVELOPMENT.md gets you from clone to PR in about fifteen minutes.
>
> https://github.com/denfry/codebase-index

## X / Twitter

**Short announcement**

> codebase-index: a local code map for Claude Code, Codex, OpenCode and MCP.
> Find the right file, trace what calls it, predict what a change breaks. SQLite +
> Tree-sitter, no network, no telemetry. `pip install codebase-index`
> https://github.com/denfry/codebase-index

**Technical announcement**

> Benchmarked codebase-index against a disciplined ripgrep agent on Flask, Gson
> and Fastify: 450 questions mined from git history, same tokenizer on both sides.
> Top-3 hit rate 0.55 vs 0.30, MRR 0.46 vs 0.26, p<0.001, ~same context tokens.
> Raw logs + one-command rerun: https://github.com/denfry/codebase-index/blob/main/docs/BENCHMARKS.md

**Thread**

> 1/ I built codebase-index because Claude Code and Codex kept opening the wrong
> file. Not because they're bad at reading; because grep is bad at deciding.
> Here's what a local code map does differently, with numbers. 🧵
>
> 2/ Three questions, one SQLite file: FIND (ranked file:line ranges), TRACE
> (callers, shortest dependency path, each edge tagged extracted/inferred/
> ambiguous), PREDICT (blast radius of a symbol, or of your current diff).
>
> 3/ Every answer carries its uncertainty: index freshness, confidence, graph
> coverage per language. An agent can tell "nothing references this" from "the
> graph doesn't know". grep can't.
>
> 4/ Local only. No network in the base install, no telemetry. Secrets excluded
> before parsing and redacted on output. `codebase-index doctor --strict` audits
> that and fails CI if a gate is off.
>
> 5/ Benchmarks: ground truth mined from git history (commit subject → files
> changed) so neither the tool nor I wrote the answer key. Flask + Gson + Fastify,
> 450 questions, ripgrep with 80-line windows as the baseline, one tokenizer.
>
> 6/ Result: top-3 hit rate 0.55 vs 0.30, MRR 0.46 vs 0.26, p < 0.001, about the
> same context tokens per question. The first run showed my read plan cost MORE
> tokens than grep; the fix (cap reads at the definition head) is in the same PR.
>
> 7/ What it doesn't do yet: framework-aware edges (route → handler → DB), agent
> task-level evaluation, a 1M-LOC run. All on the roadmap, none implied.
>
> 8/ `pip install codebase-index`, `codebase-index init`. Works as a Claude Code
> plugin, Codex AGENTS.md block, OpenCode command, or MCP server. Please run the
> benchmark on your repo and tell me what breaks.
> https://github.com/denfry/codebase-index

## Discord (developer communities, one message)

> **codebase-index** — local code map for coding agents (Claude Code / Codex /
> OpenCode / MCP). Ranked file:line search, callers and dependency paths with
> per-edge confidence, and change-impact for a symbol or your current diff. SQLite
> + Tree-sitter, no network, no telemetry. Benchmarked vs a ripgrep agent on
> Flask/Gson/Fastify: top-3 hit rate 55% vs 30% at ~equal tokens, raw logs in the
> repo. `pip install codebase-index` · https://github.com/denfry/codebase-index
> Happy to answer questions here, and benchmark reproductions on your repos are the
> most useful feedback I can get.

## GitHub release announcement template

Use `python scripts/release_notes.py` for the body; prepend this header when a
release is worth announcing beyond the changelog.

> **codebase-index vX.Y.Z**
>
> One paragraph: what changed for a user, in plain words.
>
> **Evidence:** the metric that moved, with the log path
> (`tests/eval/results/<date>-*.md`) or "no ranking change".
>
> **Upgrade:** `pip install -U codebase-index`; run `codebase-index index` if the
> changelog lists a schema bump; installed skills auto-update on the next command
> (`codebase-index skill-update` to force, `skill-rollback` to undo).
>
> _(changelog section follows)_

## Where to publish, in order

Day 0 is the day the release with this branch is tagged.

| When | Action | Goal |
|---|---|---|
| Day 0 | Tag + PyPI publish; verify `pip install codebase-index==X.Y.Z` on a clean machine; post the GitHub release with the template above | Everything a visitor clicks works |
| Day 0 | Discord message in the Claude Code and one AI-tooling community | Early, technical feedback from people who already use skills/MCP |
| Day 1 | Reddit: Claude Code community post | Install attempts from the primary audience; watch `doctor` bug reports |
| Day 1 | X short announcement + technical announcement | Link in circulation before HN |
| Day 3 | Show HN, morning US Pacific, weekday | Sceptical readers; expect benchmark methodology questions; answer with logs, not adjectives |
| Day 3 | X thread | Reuse HN discussion points |
| Week 1 | Reddit: r/LocalLLaMA and r/programming posts (the benchmark write-up), spaced two days apart | Reach people who care about local and about methodology |
| Week 1 | Submit to awesome-claude-code, awesome-mcp-servers, awesome-code-search lists; PyPI page check | Long-tail discovery |
| Week 2 | Publish a "what people reported" note in Discussions: bugs fixed, benchmark reproductions received, what changed | Show that feedback lands somewhere |
| Week 2 | Patch release with the first-wave fixes | Convert first-week issues into visible responsiveness |
| Month 1 | Pick the highest-signal gap from the loop below and ship it (likely agent task-level benchmark or MCP client verification); post the result where the question was first asked | Retention signal, second wave |

## Feedback loop

**Collect**

- Install failures (`doctor` output) by OS and Python version.
- First-query outcomes: did `search` return a useful top-3 on the user's repo?
  Ask for `--json` output with paths redacted if needed.
- Benchmark reproductions via the benchmark-report template, including negative
  ones; each becomes a row in a Discussions thread.
- Integration requests by client (Cursor, Zed, Windsurf, VS Code): the
  unverified MCP templates need exactly these people.
- Language requests, ranked by how many repos mention them.

**Metrics that matter**, in order:

1. Repeat usage: users who run `update`/`search` on day 7 (ask in Discussions;
   there is no telemetry and there will not be).
2. Issues from people who are not the maintainer, and how many are closed
   within a week.
3. External pull requests merged.
4. Benchmark reproductions posted, with the spread of results.
5. Forks that carry commits.
6. Integration requests and confirmations ("works with Zed 0.x").
7. PyPI downloads, as a trend only.
8. Stars, as a lagging indicator.

**Do not optimise for**: stars, follower counts, being first on a list,
"AI tool of the week" placements, or any metric that a bot could move. No
purchased engagement, no automated cross-posting, no fake issues, no
"reminder" comments in other projects' threads, no unsolicited DMs.

**Respond to feedback with**: a reproduction or a log, a linked commit, or a
roadmap entry that names the gap. Never with a promise that has no issue number.
