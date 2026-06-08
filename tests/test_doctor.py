from __future__ import annotations

import json

from typer.testing import CliRunner

from codebase_index import scaffold
from codebase_index.cli import app
from codebase_index.config import Config
from codebase_index.doctor import run_doctor

runner = CliRunner()


def test_doctor_flags_uncovered_cache(tmp_path):
    cfg = Config()
    cfg.root = str(tmp_path)
    findings = run_doctor(tmp_path, cfg)
    ids = {f.id for f in findings}
    assert "cache_gitignored" in ids
    cache = next(f for f in findings if f.id == "cache_gitignored")
    assert cache.ok is False and cache.severity == "high"  # not gitignored yet


def test_doctor_reports_hook_state(tmp_path):
    cfg = Config()
    cfg.root = str(tmp_path)

    off = {f.id: f for f in run_doctor(tmp_path, cfg)}
    assert off["hooks_enabled"].ok is False  # no hook yet (informational)

    scaffold.merge_hook_settings(tmp_path)
    on = {f.id: f for f in run_doctor(tmp_path, cfg)}
    assert on["hooks_enabled"].ok is True
    assert "codebase-index update" in on["hooks_enabled"].detail


def test_doctor_cli_json(tmp_path):
    res = runner.invoke(app, ["--root", str(tmp_path), "--json", "doctor"])
    assert res.exit_code == 0, res.output
    data = json.loads(res.output)
    assert "findings" in data
    assert any(f["id"] == "cache_gitignored" for f in data["findings"])


def test_doctor_flags_tier_b_partial_graph(tmp_path):
    """A Tier-B language (Lua) in the index must surface a partial-graph info finding."""
    (tmp_path / "mod.lua").write_text("local function greet()\n  return 1\nend\n", encoding="utf-8")
    assert runner.invoke(app, ["--root", str(tmp_path), "index"]).exit_code == 0

    cfg = Config()
    cfg.root = str(tmp_path)
    findings = {f.id: f for f in run_doctor(tmp_path, cfg)}
    gc = findings["graph_coverage"]
    assert gc.ok is True and gc.severity == "info"
    assert "lua" in gc.detail


def test_doctor_full_graph_when_only_tier_a(tmp_path):
    (tmp_path / "mod.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    assert runner.invoke(app, ["--root", str(tmp_path), "index"]).exit_code == 0

    cfg = Config()
    cfg.root = str(tmp_path)
    findings = {f.id: f for f in run_doctor(tmp_path, cfg)}
    assert "lua" not in findings["graph_coverage"].detail
    assert "full dependency-graph support" in findings["graph_coverage"].detail


def test_doctor_strict_exits_nonzero_on_high_severity(tmp_path):
    # uncovered cache is a high-severity finding → --strict must fail
    res = runner.invoke(app, ["--root", str(tmp_path), "doctor", "--strict"])
    assert res.exit_code != 0

    # once the cache is gitignored, --strict passes
    scaffold.merge_gitignore(tmp_path)
    res2 = runner.invoke(app, ["--root", str(tmp_path), "doctor", "--strict"])
    assert res2.exit_code == 0, res2.output
