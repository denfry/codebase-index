# Installation Guide: codebase-index for AI CLIs

This page explains how to install `codebase-index` and make it available in Claude Code, Codex CLI, or OpenCode.

## Choose Your Path

- New user: use **Option 1**.
- Working across many repos: use **Option 2**.
- CLI-only usage (without skill scaffolding): use **Option 3**.
- Advanced local features (watch/embeddings): use **Option 4**.

## Requirements

- **Python**: 3.10 or later
- **OS**: macOS, Linux, Windows
- **Disk**: ~50 MB for the package + SQLite index (varies by project size)
- **Memory**: ~200 MB during indexing (varies by project size)

## Installation Methods

### Option 1: Install via `init` command (recommended)

Install the package and scaffold the skill into your project:

```bash
cd your-project
pip install codebase-index
codebase-index init
codebase-index index
```

In an interactive terminal, `init` opens a target picker and marks detected CLIs.
For automation, use `--target claude|codex|opencode|auto|all`.

This writes the selected CLI instructions (`.claude/skills/...`, Codex `AGENTS.md`
plus `.codex/skills/...`, or OpenCode command/agent files), a resolved `config.json`,
and adds the cache directory to `.gitignore`. Use `--force` to overwrite an existing
install, or `--with-hooks` to auto-merge the Claude Code PostToolUse update hook into
`.claude/settings.json` (a reviewable example is also written as a reference copy).

### Option 2: Install as a reusable local skill

Clone once and symlink into multiple projects:

```bash
# Clone to a central location
git clone https://github.com/denfry/codebase-index.git ~/codebase-index

# Install the Python package
cd ~/codebase-index
pip install -e .

# Symlink into each project
ln -s ~/codebase-index/skill ~/.claude/skills/codebase-index
```

### Option 3: Install as a Python package

```bash
# Using pip
pip install codebase-index

# Using pipx (isolated environment)
pipx install codebase-index

# Using uv
uv tool install codebase-index

# From source (editable mode)
git clone https://github.com/denfry/codebase-index.git
cd codebase-index
pip install -e ".[dev]"
```

### Option 4: Install with optional extras

```bash
# With local embeddings support
pip install -e ".[embeddings-local]"

# With file watching support
pip install -e ".[watch]"

# With all optional features
pip install -e ".[embeddings-local,watch,dev]"
```

### Verify a clean install

On a machine with only Python + pipx:

```bash
pipx install codebase-index
cd /path/to/your/repo
codebase-index init           # writes .claude/skills/codebase-index/ + .gitignore rules
codebase-index index          # builds .claude/cache/codebase-index/index.sqlite
codebase-index --json search "<a term from your code>"   # -> {"index": {"exists": true, ...}}
```

If `search` returns `"exists": true` with results, the install is healthy. Maintainers can run the
same path automatically with `python scripts/release_smoke.py`.

## Verify Installation

```bash
codebase-index --help
codebase-index doctor
```

Expected output:

```
=== codebase-index Doctor ===

[OK] Python 3.12 (requires 3.10+)
[OK] codebase-index package installed (v1.0.2)
[OK] tree-sitter is available
[INFO] Cache directory not yet created: ...
[INFO] Skill not installed in .claude/skills/
[INFO] No config file (using defaults)

All checks passed.
```

## Claude Code Setup

After installing the Python package, ensure the skill is available to Claude Code:

1. The skill directory should be at `.claude/skills/codebase-index/` in your project.
2. The `SKILL.md` file must be present in the skill directory.
3. Claude Code will automatically detect and use the skill for codebase questions.

If the skill is not detected:

```bash
# Run the install script
python skill/scripts/install.py

# Or manually copy
cp -r skill/ .claude/skills/codebase-index/
```

## Post-Tool-Use Hooks (optional)

To keep the index fresh after edits, you can enable a PostToolUse hook in Claude Code. Run `codebase-index init --with-hooks` to **auto-merge** the hook into `.claude/settings.json` (a reviewable example is also written to `.claude/skills/codebase-index/examples/hooks/settings.json` as a reference copy). The merge is idempotent — running `init --with-hooks` again won't duplicate the hook.

Use `codebase-index doctor` to verify which hooks are enabled. For heavy editing sessions, consider `watch` mode instead (see below).

```json
{
  "hooks": {
    "PostToolUse": [
      {
        "matcher": "Edit|Write|MultiEdit",
        "hooks": [
          {
            "type": "command",
            "command": "codebase-index update --quiet >/dev/null 2>&1 &",
            "timeout": 5
          }
        ]
      }
    ]
  }
}
```

## Watch Mode (optional)

For heavy editing sessions, `watch` mode keeps the index fresh via a debounced filesystem observer. Requires the `[watch]` extra:

```bash
pip install "codebase-index[watch]"
codebase-index watch --debounce 500
```

The watcher coalesces bursts of file edits into a single incremental `update` after a quiet window, so it never blocks or thrashes the edit loop. Ctrl-C to stop. Without `watchdog` installed, `watch` exits with a clear error and install guidance.

## Cache Location

The index is stored in:

```
.claude/cache/codebase-index/
├── index.sqlite      # SQLite database with FTS5
├── config.json       # Resolved configuration
└── logs/             # Indexing logs (if enabled)
```

This directory is in the default `.gitignore` and should never be committed.

## Troubleshooting

### "codebase-index: command not found"

Ensure the package is installed and in your PATH:

```bash
pip show codebase-index
python -m codebase_index --help
```

If using `pipx`:

```bash
pipx ensurepath
source ~/.bashrc  # or ~/.zshrc
```

### "tree-sitter not available"

Symbol extraction requires tree-sitter:

```bash
pip install tree-sitter tree-sitter-language-pack
```

### Index is stale after file changes

Run an incremental update (mtime/sha/git aware, safe to run from a hook or watcher):

```bash
codebase-index update
```

Narrow to git-changed files since a ref:

```bash
codebase-index update --since HEAD~1
```

Force re-check of every file:

```bash
codebase-index update --all
```

Or a full rebuild:

```bash
codebase-index index
```

### Skill not detected by Claude Code

1. Verify the skill directory exists: `.claude/skills/codebase-index/SKILL.md`
2. Check Claude Code settings for skill discovery paths.
3. Run `codebase-index doctor` to verify the installation.

### External embeddings warning

If `doctor` warns about external embeddings, check your config:

```bash
cat .codeindex.json | grep allow_external
```

Set `allow_external` to `false` to disable external API calls.

## Recommended Flow for First-Time Users

```bash
pip install codebase-index
cd your-project
codebase-index init
codebase-index index
codebase-index doctor
codebase-index search "where is authentication implemented?"
```

If the command returns ranked results and recommended reads, your setup is complete.
