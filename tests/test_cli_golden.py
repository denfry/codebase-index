# tests/test_cli_golden.py
from __future__ import annotations

import json as _json
import subprocess

import pytest
from typer.testing import CliRunner

from codebase_index.cli import app
from tests.golden_utils import assert_matches_golden, normalize

runner = CliRunner()


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
    assert out["results"][0]["path"] == "src/auth/token.py"
    assert out["results"][0]["score"] == 0.8734


@pytest.fixture(scope="module")
def indexed_repo(tmp_path_factory):
    """A copy of sample_repo with a freshly built index, isolated from the source tree."""
    import shutil

    from tests.conftest import FIXTURE_ROOT

    dest = tmp_path_factory.mktemp("indexed") / "repo"
    shutil.copytree(FIXTURE_ROOT, dest)

    # Explicit identity: CI runners have no global git config, and on Windows
    # git's identity auto-detection fails, so the commit silently never happens
    # and head_commit becomes null instead of "<SHA>".
    identity = ["-c", "user.name=golden", "-c", "user.email=golden@test"]
    subprocess.run(["git", "init"], cwd=dest, capture_output=True)
    subprocess.run(["git", "add", "."], cwd=dest, capture_output=True)
    commit = subprocess.run(
        ["git", *identity, "commit", "-m", "initial"], cwd=dest, capture_output=True, text=True
    )
    assert commit.returncode == 0, commit.stderr
    assert runner.invoke(app, ["--root", str(dest), "index"]).exit_code == 0
    return dest


CASES = [
    ("search_token", ["search", "token"]),
    ("symbol_user", ["symbol", "User"]),
    ("refs_refresh_access_token", ["refs", "refresh_access_token"]),
    ("impact_user_model", ["impact", "src/models/user.py", "--direction", "up"]),
    ("explain_auth", ["explain", "how does authentication work"]),
    ("stats", ["stats"]),
]


@pytest.mark.parametrize("name,argv", CASES, ids=[c[0] for c in CASES])
def test_command_json_matches_golden(indexed_repo, name, argv):
    res = runner.invoke(app, ["--root", str(indexed_repo), "--json", *argv])
    assert res.exit_code == 0, res.output
    payload = _json.loads(res.output)
    assert_matches_golden(name, payload, root=str(indexed_repo))
