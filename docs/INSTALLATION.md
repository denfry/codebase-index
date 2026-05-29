# Installation Guide

Complete installation instructions for `codebase-index`.

## Requirements

- **Python**: 3.10 or later
- **OS**: macOS, Linux, Windows
- **Disk**: ~50 MB for the package + SQLite index (varies by project size)
- **Memory**: ~200 MB during indexing (varies by project size)

## Installation Methods

### Option 1: Install as a Claude Code Skill (recommended)

Clone the repository directly into your project's skills directory:

```bash
cd your-project
git clone https://github.com/<OWNER>/claude-code-codebase-index-skill.git .claude/skills/codebase-index
cd .claude/skills/codebase-index
pip install -e .
python -m codebase_index doctor
```

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

## Configuration

Create a `.codeindex.json` file in your project root:

```json
{
  "index": {
    "max_file_bytes": 1048576,
    "chunk_size": 500,
    "chunk_overlap": 50
  },
  "embeddings": {
    "backend": "noop",
    "allow_external": false
  },
  "hooks": {
    "post_tool_use": {
      "enabled": false,
      "events": ["Write", "Edit"],
      "command": "codebase-index update --quiet"
    }
  }
}
```

### Configuration Options

| Option | Default | Description |
|---|---|---|
| `index.max_file_bytes` | 1048576 (1 MB) | Maximum file size to index |
| `index.chunk_size` | 500 | Target tokens per chunk |
| `index.chunk_overlap` | 50 | Overlap tokens between chunks |
| `embeddings.backend` | "noop" | Embedding backend: "noop", "local", or "external" |
| `embeddings.allow_external` | false | Allow sending code to external embedding APIs |
| `hooks.post_tool_use.enabled` | false | Enable automatic index updates after edits |

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
