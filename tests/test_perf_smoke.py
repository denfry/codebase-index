"""Perf budget smoke test. Deselected unless `pytest --runslow` is passed.

Budgets are deliberately loose (CI-machine-safe), meant to catch order-of-magnitude
regressions (e.g. an accidental O(n^2) walk), not to benchmark precisely. Uses
perf_counter, which is allowed in tests (the Date/random ban applies to workflow
scripts, not pytest).
"""

from __future__ import annotations

import time
from pathlib import Path

import pytest
from typer.testing import CliRunner

from codebase_index.cli import app

runner = CliRunner()

INDEX_BUDGET_S = 60.0
SEARCH_BUDGET_S = 2.0


@pytest.mark.slow
def test_medium_repo_index_and_search_within_budget(medium_repo: Path):
    t0 = time.perf_counter()
    res = runner.invoke(app, ["--root", str(medium_repo), "index"])
    assert res.exit_code == 0, res.output
    index_elapsed = time.perf_counter() - t0
    assert index_elapsed < INDEX_BUDGET_S, f"index took {index_elapsed:.1f}s (budget {INDEX_BUDGET_S}s)"

    t1 = time.perf_counter()
    res2 = runner.invoke(app, ["--root", str(medium_repo), "--json", "search", "func_5"])
    assert res2.exit_code == 0, res2.output
    search_elapsed = time.perf_counter() - t1
    assert search_elapsed < SEARCH_BUDGET_S, f"search took {search_elapsed:.2f}s (budget {SEARCH_BUDGET_S}s)"
