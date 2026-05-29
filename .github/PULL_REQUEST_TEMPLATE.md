## Description

Describe your changes and their impact.

Fixes #(issue)

## Type of change

- [ ] Bug fix (non-breaking change that fixes an issue)
- [ ] New feature (non-breaking change that adds functionality)
- [ ] Breaking change (fix or feature that would cause existing functionality to not work as expected)
- [ ] Documentation update
- [ ] Refactoring (no functional change)
- [ ] CI / build / tooling change

## Checklist

- [ ] I have read the [CONTRIBUTING.md](../CONTRIBUTING.md) guide
- [ ] My code follows the project's style conventions (`ruff check`, `ruff format`)
- [ ] I have added tests that prove my fix is effective or that my feature works
- [ ] All tests pass (`pytest`)
- [ ] Type checking passes (`mypy`, if applicable)
- [ ] I have updated the documentation accordingly
- [ ] I have updated `CHANGELOG.md` under `[Unreleased]`
- [ ] My commits follow [Conventional Commits](https://www.conventionalcommits.org/)

## Testing

Describe how you tested your changes:

```bash
# Example:
pytest tests/test_my_new_feature.py
codebase-index index --root tests/fixtures/sample_repo
codebase-index search "test query"
```

## Screenshots (if applicable)
