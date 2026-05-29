from __future__ import annotations

from pathlib import Path

import pytest

FIXTURE_ROOT = Path(__file__).parent / "fixtures" / "sample_repo"


@pytest.fixture
def sample_repo() -> Path:
    assert FIXTURE_ROOT.is_dir(), "run the M1 fixture-build steps first"
    return FIXTURE_ROOT