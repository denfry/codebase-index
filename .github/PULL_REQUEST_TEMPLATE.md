## What and why

<!-- Problem, then the change. Link the issue: Fixes #123 -->

## How I verified it

```bash
# commands you ran, e.g.
pytest tests/test_xxx.py -q --no-cov
python tests/eval/run_eval.py --ablate   # required for any ranking change; paste the table below
```

<!-- For retrieval changes: pooled table + significance row for your flag. -->

## Checklist

- [ ] `pytest`, `ruff check src tests`, `mypy src/codebase_index` pass
- [ ] `python scripts/sync_skill_copies.py --check` passes (if `skill_template/` changed)
- [ ] Goldens regenerated intentionally and the diff explained (if `--json` / MCP output changed)
- [ ] `CHANGELOG.md` updated under `[Unreleased]` (user-visible changes only; no version bump)
- [ ] No secrets, generated indexes, or local config committed
