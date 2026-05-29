# Basic Usage

## Quick Start

```bash
# 1. Initialize the index for your project
codebase-index init

# 2. Build the index
codebase-index index

# 3. Search for something
codebase-index search "where is authentication implemented?"

# 4. Check index stats
codebase-index stats
```

## Common Workflows

### Finding where something is implemented

```bash
codebase-index search "user authentication"
```

Returns ranked results with file paths, line ranges, and snippets.

### Looking up a specific symbol

```bash
codebase-index symbol "AuthService"
```

Returns the definition location, type (class/function/etc.), and all references.

### Finding who calls a function

```bash
codebase-index refs "AuthService.login"
```

Returns all callers and references to the symbol.

### Understanding impact of a change

```bash
codebase-index impact "src/auth/AuthService.ts"
```

Returns files and symbols that depend on the target, ordered by blast radius.

### Getting project overview

```bash
codebase-index search "architecture overview main entry point"
```

Returns key files that define the project structure.

## Output Formats

### Human-readable (default)

```bash
codebase-index search "query"
```

Returns a Markdown table with rank, path, symbols, score, and snippets.

### Machine-readable (JSON)

```bash
codebase-index search "query" --json
```

Returns structured JSON for programmatic use by Claude Code or other tools.

## Using with Claude Code

When the skill is installed in `.claude/skills/codebase-index`, Claude Code will automatically use it for codebase questions. You can also invoke it manually:

```
/codebase-index where is the user model defined?
```

Claude will query the index, read only the recommended line ranges, and answer with citations.
