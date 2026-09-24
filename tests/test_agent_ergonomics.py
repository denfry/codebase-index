"""What an agent needs from refs/symbol/describe without falling back to Grep.

Each case comes from a benchmark run in which an agent using the skill had to leave
the index: enum variants handled in a Rust `match`, a class card with no members,
twenty prefix matches around the one symbol it asked for, test sites mixed into a
"production callers" question, Kotlin files with no call edges at all.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from codebase_index.cli import app
from codebase_index.config import Config
from codebase_index.graph.navigate import describe_payload
from codebase_index.indexer.pipeline import build_index, update_index
from codebase_index.parsers.treesitter import parse_file
from codebase_index.retrieval.searchers import refs_lookup, symbol_lookup
from codebase_index.storage.db import Database

FILES = {
    "launcher/src/error.rs": """\
pub enum CoreError {
    ObjectDamaged(String),
    Gone,
}
""",
    "launcher/src/engine.rs": """\
use crate::error::CoreError;

pub fn prepare(r: Result<(), CoreError>) -> u8 {
    match r {
        Err(CoreError::ObjectDamaged(_)) => 1,
        Err(CoreError::Gone) => 2,
        _ => 0,
    }
}
""",
    "launcher/src/activation.rs": """\
use crate::error::CoreError;

pub fn place(ok: bool) -> Result<(), CoreError> {
    if ok { Ok(()) } else { Err(CoreError::ObjectDamaged(String::new())) }
}
""",
    "polity/treasury/Treasury.java": """\
package treasury;

public final class Treasury {
    public void touched() {
        save();
    }

    private void save() {
    }
}
""",
    "polity/treasury/TreasuryService.java": """\
package treasury;

public final class TreasuryService {
    static void deposit(Treasury treasury) {
        Treasury.touched();
    }
}
""",
    "polity/treasury/TreasuryRules.java": """\
package treasury;

public final class TreasuryRules {
    static boolean mayDeposit() {
        return true;
    }
}
""",
    "polity/src/test/java/treasury/TreasuryTest.java": """\
package treasury;

class TreasuryTest {
    void deposits() {
        TreasuryService.deposit(null);
    }
}
""",
    "polity/src/main/kotlin/Hooks.kt": """\
object Hooks {
    fun run() {
        TreasuryService.deposit(null)
    }
}
""",
}


@pytest.fixture
def repo_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    for rel, text in FILES.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return root


@pytest.fixture
def db(repo_root: Path, tmp_path: Path):
    cfg = Config()
    cfg.root = str(repo_root)
    database = Database(tmp_path / "index.sqlite").open()
    build_index(cfg, database, root=repo_root)
    yield database
    database.close()


def _sites(resp, kind=None):
    return [(s.path, s.line) for s in resp.sites if kind is None or s.kind == kind]


def test_kotlin_calls_are_extracted_with_their_receiver():
    edges = parse_file("kotlin", FILES["polity/src/main/kotlin/Hooks.kt"]).edges
    assert [(e.callee_name, e.receiver) for e in edges if e.edge_type == "call"] == [
        ("deposit", "TreasuryService")
    ]


def test_rust_enum_variants_are_symbols(db):
    resp = symbol_lookup(db.conn, "CoreError.ObjectDamaged", kind=None, exact=True)
    assert [(s.kind, s.path, s.line_start) for s in resp.symbols] == [
        ("variant", "launcher/src/error.rs", 2)
    ]


def test_refs_finds_where_a_rust_variant_is_matched(db):
    resp = refs_lookup(db.conn, "CoreError::ObjectDamaged", kind="all")
    assert ("launcher/src/engine.rs", 5) in _sites(resp, "reference")
    assert ("launcher/src/activation.rs", 4) in _sites(resp, "call")
    assert ("launcher/src/error.rs", 2) in _sites(resp, "definition")
    matched = next(s for s in resp.sites if s.kind == "reference")
    assert matched.caller == "prepare" and matched.target == "CoreError.ObjectDamaged"


def test_refs_callers_leaves_out_non_call_references(db):
    resp = refs_lookup(db.conn, "CoreError::ObjectDamaged", kind="callers")
    assert {s.kind for s in resp.sites} == {"call"}


def test_refs_filters_tests_and_paths(db):
    every = _sites(refs_lookup(db.conn, "TreasuryService.deposit", kind="callers"))
    assert ("polity/src/test/java/treasury/TreasuryTest.java", 5) in every
    prod = refs_lookup(db.conn, "TreasuryService.deposit", kind="callers", exclude_tests=True)
    assert _sites(prod) == [("polity/src/main/kotlin/Hooks.kt", 3)]
    only = refs_lookup(db.conn, "TreasuryService.deposit", kind="callers",
                       paths=["polity/src/test"])
    assert _sites(only) == [("polity/src/test/java/treasury/TreasuryTest.java", 5)]


def test_symbol_returns_exact_matches_alone_and_counts_the_rest(db):
    resp = symbol_lookup(db.conn, "Treasury", kind=None, exact=False)
    assert [s.qualified for s in resp.symbols] == ["Treasury"]
    assert resp.more_prefix_matches == 3        # TreasuryService, TreasuryRules, TreasuryTest
    prefix = symbol_lookup(db.conn, "TreasuryR", kind=None, exact=False)
    assert [s.name for s in prefix.symbols] == ["TreasuryRules"]


def test_describe_a_class_lists_members_and_who_uses_them(db):
    card = describe_payload(db.conn, "Treasury")
    assert [m["name"] for m in card["members"]] == ["touched", "save"]
    assert card["used_by"] == [{
        "member": "touched", "caller": "deposit",
        "path": "polity/treasury/TreasuryService.java", "line": 5,
        "confidence": "extracted",
    }]
    assert card["used_by_total"] == 1


def test_describe_accepts_owner_member_and_names_callers(db):
    card = describe_payload(db.conn, "Treasury.touched")
    assert card["found"] is True
    assert [(c["path"], c["caller"]) for c in card["callers"]] == [
        ("polity/treasury/TreasuryService.java", "TreasuryService.deposit")
    ]


def test_refs_cli_compact_and_session(repo_root: Path, db):
    runner = CliRunner()
    db.close()  # the CLI builds its own index under the repo
    result = runner.invoke(app, [
        "--root", str(repo_root), "refs", "TreasuryService.deposit", "--kind", "callers",
        "--exclude-tests", "--compact", "--session", "bench",
    ])
    assert result.exit_code == 0, result.output
    lines = [ln for ln in result.output.splitlines() if not ln.startswith("[codebase-index]")]
    assert lines == [
        "# TreasuryService.deposit: 1 call",
        "polity/src/main/kotlin/Hooks.kt:3 call Hooks.run -> TreasuryService.deposit",
    ]
    for cmd in (["symbol", "Treasury"], ["impact", "Treasury"], ["refs", "Treasury"]):
        res = runner.invoke(app, ["--root", str(repo_root), *cmd, "--session", "bench",
                                  "--json"])
        assert res.exit_code == 0, res.output
        json.loads(res.output)


def test_update_parses_a_large_change_set_like_a_full_build(repo_root: Path, tmp_path: Path):
    cfg = Config()
    cfg.root = str(repo_root)
    for i in range(60):  # past the parallel-parse threshold
        (repo_root / "gen").mkdir(exist_ok=True)
        (repo_root / "gen" / f"M{i}.java").write_text(
            f"class M{i} {{ void f() {{ TreasuryService.deposit(null); }} }}\n", encoding="utf-8"
        )
    with Database(tmp_path / "a.sqlite") as full:
        build_index(cfg, full, root=repo_root)
        want = full.conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
    with Database(tmp_path / "b.sqlite") as inc:
        for i in range(60):
            (repo_root / "gen" / f"M{i}.java").rename(repo_root / "gen" / f"M{i}.java.bak")
        build_index(cfg, inc, root=repo_root)
        for i in range(60):
            (repo_root / "gen" / f"M{i}.java.bak").rename(repo_root / "gen" / f"M{i}.java")
        stats = update_index(cfg, inc, root=repo_root)
        assert stats.indexed == 60
        assert inc.conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0] == want
