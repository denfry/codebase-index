# Installation & Configuration

## 1. Install the CLI

```bash
pipx install codebase-index          # recommended: isolated
# or
pip install codebase-index           # into current environment

# with the optional local vector backend:
pipx install "codebase-index[embeddings,embeddings-local]"
# with live watch mode:
pipx install "codebase-index[watch]"
```

Requirements: Python ≥ 3.10. Tree-sitter grammars ship via `tree-sitter-language-pack` (no system
compiler needed). `ripgrep` is recommended on PATH for the fallback path (Claude Code bundles it).

## 2. Install the skill into a project

From the repo root:

```bash
codebase-index init
```

This:
- creates `.claude/skills/codebase-index/SKILL.md` and `.claude/skills/codebase-index/scripts/`
- creates `.claude/cache/codebase-index/config.json` (resolved defaults)
- appends cache ignore rules to `.gitignore` (idempotent)
- prints next steps

Flags: `--force` (overwrite existing skill), `--with-hooks` (also write `examples/hooks` into
`.claude/settings.json` after confirmation).

> The **skill** (`.claude/skills/codebase-index/`) is safe to commit so your team shares it.
> The **cache** (`.claude/cache/codebase-index/`) must stay gitignored.

## 3. Build the index

```bash
codebase-index index        # full build
codebase-index stats        # verify coverage + freshness
```

Subsequent builds:

```bash
codebase-index update            # incremental (changed files only)
codebase-index update --since HEAD~5
```

## 4. Configuration (`.claude/cache/codebase-index/config.json`)

```jsonc
{
  "root": ".",
  "languages": "auto",                 // or ["python","typescript","go",...]
  "max_file_bytes": 1048576,           // 1 MB
  "ignore_files": [".gitignore", ".cursorignore", ".claudeignore", ".codeindexignore"],
  "extra_ignore": ["**/snapshots/**"],
  "chunk": { "window_lines": 80, "overlap_lines": 10 },
  "retrieval": {
    "default_mode": "hybrid",
    "rrf_k": 60,
    "token_budget": 1500,
    "limit": 10
  },
  "embeddings": {
    "backend": "noop",                 // "noop" | "local" | "external"
    "enabled": false,
    "model": "all-MiniLM-L6-v2",
    "allow_external": false,           // must be true AND key present for "external"
    "endpoint": null
  },
  "graph": { "max_depth": 2, "node_cap": 40 },
  "redaction": { "enabled": true }
}
```

`init` writes sensible defaults; edit and re-run `update` (config changes that affect indexing
trigger the necessary rebuild automatically via `config_hash`).

## 5. Using it in Claude Code

Just ask a codebase question — Claude auto-invokes the skill because of its description. Or invoke
explicitly:

```
/codebase-index where is the websocket reconnect logic
/codebase-index what files break if I change the User model
/codebase-index explain how request authentication works
```

## 6. Optional: auto-update hook

To keep the index fresh after Claude edits files, enable the optional `PostToolUse` hook. It is
**off by default**. See `examples/hooks/settings.json` and [the hooks section](#hooks-detail).

### Hooks detail

`examples/hooks/settings.json`:

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

- **Asynchronous**: trailing `&` (POSIX) detaches so it never blocks Claude's edit loop. On Windows
  use `start /b codebase-index update --quiet`.
- **Incremental only**: the hook calls `update`, never `index --rebuild`.
- **Safe**: it runs a fixed command with no interpolation of tool arguments, avoiding injection.
- **Security note**: hooks run arbitrary commands on your machine on every matching tool use. Only
  enable in trusted workspaces and review the command. `doctor` will report enabled hooks.

A `FileChanged`-style hook (if your Claude Code version supports it) can replace the `PostToolUse`
matcher to also catch external edits. Prefer `watch` mode (`codebase-index watch`) for heavy editing
sessions instead of a per-edit hook.

## 7. Uninstall / reset

```bash
codebase-index clean --yes     # remove the cache (keeps the skill)
```
