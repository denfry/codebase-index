# CLAUDE.md Example

Place this file in your project's `.claude/CLAUDE.md` to guide Claude Code's behavior with the codebase-index skill.

```markdown
# Project Guidelines

## Codebase Questions

Before answering any question about this project's code, architecture, or implementation:

1. Use the `codebase-index` skill to search the local index first.
2. Read only the recommended line ranges — do not scan entire files.
3. Answer with file:line citations (e.g., `src/auth/token.py:88-134`).
4. If the index returns no results or low confidence, fall back to Grep.

## Indexing

The index is stored in `.claude/cache/codebase-index/index.sqlite`.

If the index is stale, run:
```bash
codebase-index update
```

For a full rebuild:
```bash
codebase-index index
```

## Code Style

- Follow existing patterns in the codebase.
- Use type hints for all function signatures.
- Write tests for new features.
- Keep functions under 50 lines where possible.

## Security

- Never commit secrets, API keys, or credentials.
- Use environment variables for configuration.
- Review `.gitignore` before committing new files.
```

## How It Works

When Claude Code receives a question about the codebase:

1. The `codebase-index` skill is automatically selected based on the question's intent.
2. Claude runs `codebase-index search "query" --json` to get ranked results.
3. Claude reads only the `recommended_reads` line ranges using the Read tool.
4. Claude answers with precise citations.

This approach is significantly more token-efficient than scanning the entire repository.
