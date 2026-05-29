# Installation Guide

Complete installation instructions for `codebase-index`.

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

This writes `.claude/skills/codebase-index/` (SKILL.md + `scripts/cbx`/`cbx.ps1`), a resolved `config.json`, and adds the cache directory to `.gitignore`. Use `--force` to overwrite an existing install, or `--with-hooks` to also write a reviewable PostToolUse hooks example.

### Option 2: Install as a reusable local skill

Clone once and symlink into multiple projects:

```bash
# Clone to a central location
git clone https://github.com/<OWNER>/claude-code-codebase-index-skill.git ~/codebase-index

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
git clone https://github.com/<OWNER>/claude-code-codebase-index-skill.git
cd claude-code-codebase-index-skill
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

## Verify Installation

```bash
codebase-index --help
codebase-index doctor
```

Expected output:

```
=== codebase-index Doctor ===

[OK] Python 3.12 (requires 3.10+)
[OK] codebase-index package installed (v0.1.0)
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

To keep the index fresh after edits, you can enable a PostToolUse hook in Claude Code. Run `codebase-index init --with-hooks` to write a reviewable example to `.claude/skills/codebase-index/examples/hooks/settings.json`. After reviewing, merge the relevant section into your project's `.claude/settings.json`:

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

Run an incremental update:

```bash
codebase-index update
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
