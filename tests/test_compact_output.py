"""Agent text output: ranked locations with numbered lines, and build modules.

The point of `--compact` is to hand an agent what `grep -n` would, already ranked
and cut to the matches, so it can cite `file:line` without another Read or Grep.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from typer.testing import CliRunner

from codebase_index.cli import app
from codebase_index.graph.modules import modules_for_paths, owning_module

FILES = {
    "settings.gradle.kts": 'include("polity")\ninclude("api")\n',
    "api/build.gradle.kts": "plugins { java }\n",
    "polity/build.gradle.kts": 'dependencies {\n    implementation(project(":api"))\n}\n',
    "api/src/main/java/api/Ledger.java": """\
package api;

/** Where coins are written down. */
public final class Ledger {
    public Ledger() {}

    public void record(String line) {
        lines.add(line);
    }
}
""",
    "polity/src/main/java/polity/Treasury.java": """\
package polity;

/** The town treasury: its coins are persisted with the world save. */
public final class Treasury {
    public static final String FILE_ID = "polity_treasury";

    public Treasury() {}

    public void deposit(int coins) {
        balance += coins;
        new api.Ledger().record("deposit " + coins);
    }

    public void persist() {
        save(FILE_ID);
    }
}
""",
    "polity/src/main/java/polity/Bank.java": """\
package polity;

public final class Bank {
    void run(Treasury treasury) {
        treasury.deposit(5);
        Treasury t = new Treasury();
    }
}
""",
}


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    for rel, text in FILES.items():
        p = root / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")
    result = CliRunner().invoke(app, ["--root", str(root), "index"])
    assert result.exit_code == 0, result.output
    return root


def _run(root: Path, *args: str) -> list[str]:
    result = CliRunner().invoke(app, ["--root", str(root), *args])
    assert result.exit_code == 0, result.output
    return [ln for ln in result.output.splitlines() if not ln.startswith("[codebase-index]")]


def test_search_compact_gives_numbered_lines_to_cite(repo: Path):
    out = _run(repo, "search", "how is the treasury persisted", "--compact")
    assert out[0].startswith("# ")
    header = next(ln for ln in out if ln.startswith("polity/src/main/java/polity/Treasury.java:"))
    body = out[out.index(header) + 1:]
    numbered = [ln for ln in body if ln.startswith("  ") and "| " in ln]
    assert "  5| public static final String FILE_ID = \"polity_treasury\";" in numbered
    assert "  14| public void persist() {" in numbered      # "persisted" -> persist


def test_class_is_returned_instead_of_its_same_named_constructor(repo: Path):
    out = _run(repo, "search", "Treasury", "--compact")
    header = next(ln for ln in out if "polity/Treasury.java:" in ln)
    assert header.startswith("polity/src/main/java/polity/Treasury.java:4-")


def test_impact_compact_names_the_module_and_its_dependents(repo: Path):
    out = _run(repo, "impact", "Ledger.record", "--compact")
    assert out[1] == (
        "# module api: build files depending on it: polity/build.gradle.kts"
        " · included by settings.gradle.kts:2"
    )
    polity = _run(repo, "impact", "Treasury.deposit", "--compact")
    assert polity[1].startswith("# module polity: build files depending on it: none")


def test_owning_module_is_the_nearest_directory_with_a_build_file(repo: Path):
    assert owning_module(repo, "api/src/main/java/api/Ledger.java") == "api"
    assert owning_module(repo, "settings.gradle.kts") is None
    [api] = modules_for_paths(repo, ["api/src/main/java/api/Ledger.java"])
    assert api["dependents"] == ["polity/build.gradle.kts"]
    assert {r["kind"] for r in api["referenced_by"]} == {"member", "dependency"}
