# tests/test_cli_golden.py  (initial version — normalizer unit test only)
from __future__ import annotations

from tests.golden_utils import normalize


def test_normalize_scrubs_volatile_fields():
    raw = {
        "query": "token",
        "index": {
            "exists": True,
            "stale": False,
            "built_at": "2026-05-29T12:00:00Z",
            "head_commit": "deadbeef1234",
            "files_changed_since_build": 0,
        },
        "results": [
            {"path": "/abs/root/src/auth/token.py", "score": 0.873421, "line_start": 1, "line_end": 9}
        ],
    }
    out = normalize(raw, root="/abs/root")
    assert out["index"]["built_at"] == "<TS>"
    assert out["index"]["head_commit"] == "<SHA>"
    # absolute root prefix stripped to a repo-relative path
    assert out["results"][0]["path"] == "src/auth/token.py"
    # floats rounded so trivial ranking jitter doesn't churn goldens
    assert out["results"][0]["score"] == 0.8734
