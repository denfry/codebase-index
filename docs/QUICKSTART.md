# Quick Start: Install and Run codebase-index in 5 Minutes

Use this guide if you are new to `codebase-index` and want the fastest path to your first useful search result.

## Before You Start

- Python 3.10+
- A local project directory (`your-project`)
- Terminal access (macOS, Linux, or Windows PowerShell)

## Step 1: Install

```bash
pip install codebase-index
```

Or from source:

```bash
git clone https://github.com/<OWNER>/claude-code-codebase-index-skill.git
cd claude-code-codebase-index-skill
pip install -e .
```

## Step 2: Initialize

Navigate to your project and initialize the index:

```bash
cd your-project
codebase-index init
```

This creates the cache directory and configuration.

## Step 3: Build the Index

```bash
codebase-index index
```

You should see output like:

```
Indexing...
  Discovered 142 files (excluded 23 sensitive/generated)
  Extracted 891 symbols
  Built 2,340 chunks
  Index built in 3.2s
```

## Step 4: Run Your First Search

```bash
codebase-index search "where is authentication implemented?"
```

Expected output:

```
Top matches:
┌──────┬──────────────────────────┬──────────────────┬───────┬────────────────────────────┐
│ Rank │ Path                     │ Symbols          │ Score │ Reason                     │
├──────┼──────────────────────────┼──────────────────┼───────┼────────────────────────────┤
│    1 │ src/auth/AuthService.ts  │ AuthService      │  0.92 │ exact symbol match         │
│    2 │ src/routes/auth.ts       │ login, logout    │  0.78 │ FTS match · 4 callers      │
│    3 │ src/middleware/auth.ts   │ requireAuth      │  0.65 │ path match · FTS match     │
└──────┴──────────────────────────┴──────────────────┴───────┴────────────────────────────┘

Recommended reads:
  1. src/auth/AuthService.ts:12-148
  2. src/routes/auth.ts:20-91
  3. src/middleware/auth.ts:5-42
```

## Step 5: Use with Claude Code

When the skill is installed (`.claude/skills/codebase-index/`), Claude Code will automatically use the index for codebase questions.

Simply ask Claude:

```
Where is user authentication implemented?
```

Claude will:
1. Query the local index
2. Read only the recommended line ranges
3. Answer with precise file:line citations

## Interpreting Results

Each result includes:

- **Rank** — position in the result list (start with 1-3)
- **Path** — file location
- **Symbols** — extracted symbols in the matched region
- **Score** — relevance score (0.0 to 1.0)
- **Reason** — why this result ranked (e.g., "exact symbol match")
- **Recommended reads** — exact line ranges to open

## What Success Looks Like

After this quick start, you should have:

- Local index files in `.claude/cache/codebase-index/`
- Search results with ranked files and line ranges
- A repeatable workflow for symbol lookup and impact checks

## Next Steps

- Look up a specific symbol: `codebase-index symbol "AuthService"`
- Find callers: `codebase-index refs "AuthService.login"`
- Check impact: `codebase-index impact "src/auth/AuthService.ts"`
- View stats: `codebase-index stats`
- Run diagnostics: `codebase-index doctor`

For full setup details, see [INSTALLATION.md](INSTALLATION.md).  
To understand internals, see [ARCHITECTURE.md](ARCHITECTURE.md).
