# tests/golden_utils.py
"""Helpers for golden-snapshot tests of CLI `--json` output.

Golden files live in tests/golden/<name>.json. Volatile fields (timestamps,
commit SHAs, absolute paths, float jitter) are normalized before comparison so
the snapshots stay stable across machines and runs.

Regenerate intentionally with:  UPDATE_GOLDEN=1 pytest tests/test_cli_golden.py
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

GOLDEN_DIR = Path(__file__).parent / "golden"

# Keys whose values are inherently volatile and must be masked, not compared.
_TS_KEYS = {"built_at", "indexed_at", "generated_at"}
_SHA_KEYS = {"head_commit"}


def _scrub(value: Any, root: str) -> Any:
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for k, v in value.items():
            if k in _TS_KEYS and v is not None:
                out[k] = "<TS>"
            elif k in _SHA_KEYS and v is not None:
                out[k] = "<SHA>"
            else:
                out[k] = _scrub(v, root)
        return out
    if isinstance(value, list):
        return [_scrub(v, root) for v in value]
    if isinstance(value, float):
        return round(value, 4)
    if isinstance(value, str):
        # strip the absolute root prefix and normalize to forward slashes
        rel = value.replace(root.replace("\\", "/"), "").replace(root, "")
        rel = rel.replace("\\", "/").lstrip("/")
        return rel if rel != value.replace("\\", "/") else value
    return value


def normalize(payload: dict[str, Any], *, root: str) -> dict[str, Any]:
    """Return a deterministic, machine-independent copy of a `--json` payload."""
    return _scrub(payload, root)


def assert_matches_golden(name: str, payload: dict[str, Any], *, root: str) -> None:
    """Compare `payload` to tests/golden/<name>.json (regenerate if UPDATE_GOLDEN=1)."""
    normalized = normalize(payload, root=root)
    path = GOLDEN_DIR / f"{name}.json"
    serialized = json.dumps(normalized, indent=2, sort_keys=True, ensure_ascii=False) + "\n"

    if os.environ.get("UPDATE_GOLDEN") == "1":
        GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
        path.write_text(serialized, encoding="utf-8")
        return

    assert path.is_file(), (
        f"missing golden {path}. Generate it with: UPDATE_GOLDEN=1 pytest tests/test_cli_golden.py"
    )
    expected = path.read_text(encoding="utf-8")
    assert serialized == expected, (
        f"golden mismatch for {name}.\n"
        f"--- expected ---\n{expected}\n--- actual ---\n{serialized}\n"
        f"If the change is intended, regenerate with UPDATE_GOLDEN=1."
    )
