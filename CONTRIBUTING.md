# Contributing

Thank you for your interest in contributing to `codebase-index`. This project is a local-first Claude Code Skill for codebase indexing, and we welcome contributions of all kinds.

## Development Setup

### Prerequisites

- Python 3.10 or later
- `pipx` or `uv` for package management (optional but recommended)
- Git

### Clone and Install

```bash
git clone https://github.com/<OWNER>/claude-code-codebase-index-skill.git
cd claude-code-codebase-index-skill

# Using uv (recommended)
uv sync --all-extras

# Or using pip
pip install -e ".[dev,embeddings-local,watch]"
```

### Run Tests

```bash
pytest
pytest --cov=src/codebase_index --cov-report=term-missing
```

### Run Linting

```bash
ruff check src/ tests/
ruff format --check src/ tests/
```

### Run Type Checking

```bash
mypy src/codebase_index
```

## Commit Style

We follow [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/):

```
<type>(<scope>): <description>

[optional body]

[optional footer(s)]
```

Types: `feat`, `fix`, `docs`, `style`, `refactor`, `test`, `chore`, `ci`

Examples:
```
feat(retrieval): add RRF fusion for hybrid search
fix(storage): handle FTS5 trigger recreation on schema change
docs(readme): add comparison table and FAQ
test(parsers): add tree-sitter symbol extraction tests for Go
```

## Branch Naming

Use the pattern `<type>/<short-description>`:

- `feat/hybrid-search`
- `fix/fts5-trigger-recreate`
- `docs/readme-comparison`
- `test/treesitter-go`

## Test Requirements

- All new features must include tests.
- All bug fixes must include a regression test.
- Aim for >80% line coverage on new code.
- Tests must pass on Python 3.10+.
- Use the fixture repository under `tests/fixtures/sample_repo/` for integration tests.

## Documentation Requirements

- New commands or flags must be documented in the README and relevant docs files.
- New configuration options must be documented in `docs/INSTALLATION.md` and `examples/config.example.json`.
- API changes must be noted in `CHANGELOG.md` under `[Unreleased]`.

## Pull Request Checklist

Before submitting a PR, ensure:

- [ ] Tests pass: `pytest`
- [ ] Linting passes: `ruff check src/ tests/`
- [ ] Formatting is correct: `ruff format src/ tests/`
- [ ] Type checking passes: `mypy src/codebase_index` (if applicable)
- [ ] CHANGELOG.md is updated under `[Unreleased]`
- [ ] Documentation is updated (README, docs/, examples/)
- [ ] Commit messages follow Conventional Commits
- [ ] No secrets or credentials are committed
- [ ] The PR description explains the change and links to any related issues

## Code Review

- All PRs require at least one approving review before merging.
- Reviewers will check for correctness, test coverage, documentation, and adherence to project conventions.
- Be respectful and constructive in code review comments.

## Reporting Issues

- Use the [bug report template](.github/ISSUE_TEMPLATE/bug_report.yml) for bugs.
- Use the [feature request template](.github/ISSUE_TEMPLATE/feature_request.yml) for new features.
- Use the [skill listing request template](.github/ISSUE_TEMPLATE/skill_listing_request.yml) to request skill directory inclusion.

## Code of Conduct

This project follows the [Contributor Covenant Code of Conduct](CODE_OF_CONDUCT.md). Please read it before participating.

## License

By contributing, you agree that your contributions will be licensed under the [MIT License](LICENSE).
