# Quick Start: Install and Run codebase-index in 5 Minutes

Use this guide if you are new to `codebase-index` and want the fastest path to your first useful search result.

## Before You Start

- Python 3.11+
- A local project directory (`your-project`)
- Terminal access (macOS, Linux, or Windows PowerShell)

## Step 1: Install

```bash
pip install codebase-index
```

Or from source:

```bash
git clone https://github.com/denfry/codebase-index.git
cd codebase-index
pip install -e .
```

## Step 2: Initialize

Navigate to your project and initialize the index:

```bash
cd your-project
codebase-index init
```

In an interactive terminal, `init` shows a CLI picker for Claude Code, Codex CLI,
OpenCode, or all detected targets. For scripted setup, pass an explicit target:

```bash
codebase-index init --target auto      # install into detected CLI targets
codebase-index init --target codex     # install Codex AGENTS.md + resources
codebase-index init --target claude    # install Claude Code skill
```

This creates the cache directory, configuration, and the selected CLI instructions.

## Step 3: Build the Index

```bash
codebase-index index
```

The examples below are real output from indexing
[pallets/flask](https://github.com/pallets/flask) at commit `d318b683` with
codebase-index 1.9.0:

```
Indexed 230 files (0 pruned).
  parse failures: 0; tree-sitter files with 0 symbols: 17
```

## Step 4: Run Your First Search

```bash
codebase-index search "where is the session cookie signed and saved" --limit 5
```

```
**Query:** where is the session cookie signed and saved
**Intent:** `locate_impl` · **Confidence:** medium

| # | Path | Lines | Reason |
|---|------|-------|--------|
| 1 | `src/flask/sessions.py` | 24-54 | in src/flask/ · 2 callers · source prior +0.08 |
| 2 | `src/flask/sessions.py` | 284-385 | in src/flask/ · 2 callers · source prior +0.08 |
| 3 | `src/flask/sessions.py` | 57-80 | in src/flask/ · 1 callers · source prior +0.08 |
| 4 | `tests/test_basic.py` | 542-600 | source prior -0.06 · generated/test demoted |
| 5 | `tests/test_reqctx.py` | 201-249 | source prior -0.06 · generated/test demoted |

`src/flask/sessions.py:284-385`
```
class SecureCookieSessionInterface(SessionInterface):
```
...

**Recommended reads:**
- `src/flask/sessions.py:24-54`
- `src/flask/sessions.py:284-385`
```

Rank 2 is the class that signs and saves the cookie. Add `--json` for the
machine-readable packet agents consume.

## Step 5: Use with Your AI CLI

When installed for Claude Code, Codex CLI, or OpenCode, the generated instructions
tell the agent to use the local index for codebase questions.

Simply ask:

```
Where is user authentication implemented?
```

The agent will:
1. Query the local index
2. Read only the recommended line ranges
3. Answer with precise file:line citations

## Interpreting Results

- **Intent** — how the query was classified (`locate_impl`, `how_it_works`, `impact`, ...);
  it selects the retriever mix.
- **Confidence** — `high`: answer from the evidence; `medium`: read the recommended
  ranges and confirm the key claim; `low`: follow the fallback suggestions (ripgrep
  patterns) instead of trusting the list.
- **#, Path, Lines** — rank and the exact line range that matched. Start with ranks 1–3.
- **Reason** — why it ranked: exact symbol match, callers, path match, and the source
  prior (implementation code is preferred over tests and documentation).
- **Snippets** — budgeted, often skeletonized (unrelated body lines folded) and
  secret-redacted.
- **Recommended reads** — the read plan: exact ranges to open, capped at 120 lines
  each (`truncated: true` in JSON when a longer symbol was cut at its head).

## What Success Looks Like

After this quick start, you should have:

- Local index files in `.claude/cache/codebase-index/`
- Search results with ranked files and line ranges
- A repeatable workflow for symbol lookup and impact checks

## Next Steps

- Look up a specific symbol: `codebase-index symbol "AuthService"`
- Find callers: `codebase-index refs "AuthService.login"`
- Check impact: `codebase-index impact "src/auth/AuthService.ts"`
- Check the current diff: `codebase-index diff-impact`
- View stats: `codebase-index stats`
- Run diagnostics: `codebase-index doctor`

For full setup details, see [INSTALLATION.md](INSTALLATION.md).  
To understand internals, see [ARCHITECTURE.md](ARCHITECTURE.md).
