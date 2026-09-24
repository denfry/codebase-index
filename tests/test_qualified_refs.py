"""`Owner.member` targets: refs/impact/symbol on a method name several types share.

Mirrors the case that made refs/impact useless on a large Java repo: three types
define `refresh`, callers in other files write `TownService.refresh(server)`, and
both `refs "TownService.refresh"` and `impact "TownService.refresh"` came back empty
with `partial: false`.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from codebase_index.config import Config
from codebase_index.graph.expand import impact_lookup
from codebase_index.indexer.pipeline import build_index
from codebase_index.parsers.treesitter import parse_file
from codebase_index.retrieval.searchers import refs_lookup, symbol_lookup
from codebase_index.storage import repo
from codebase_index.storage.db import Database

FILES = {
    "town/TownService.java": """\
package town;

public final class TownService {
    static void found(Server server) {
        refresh(server);
    }

    public static void refresh(Server server) {
        server.send();
    }

    public static void refresh(Server server, boolean quiet) {
        server.send();
    }
}
""",
    "treasury/TreasuryService.java": """\
package treasury;

public final class TreasuryService {
    static void sweep(Server server) {
        TownService.refresh(server);
    }
}
""",
    "command/PolityCommand.java": """\
package command;

public final class PolityCommand {
    static void rename(Server server) {
        TownService.refresh(server);
        PolityTuning.refresh();
    }

    static void refresh() {
    }
}
""",
    "treasury/Holdings.java": """\
package treasury;

public final class Holdings {
    public List<Item> take(Item kind, int count) {
        return null;
    }
}
""",
    "treasury/Withdraw.java": """\
package treasury;

public final class Withdraw {
    static void run(Chest chest, Item kind) {
        chest.holdings().take(kind, 1);
        ApprenticeService.take(kind);
    }
}
""",
    "apprentice/ApprenticeService.java": """\
package apprentice;

public final class ApprenticeService {
    public static Refusal take(Item kind) {
        return null;
    }
}
""",
    "tools/take.py": """\
def drain(queue, server):
    queue.take()
    server.found()
""",
    "config/PolityTuning.java": """\
package config;

public final class PolityTuning {
    public static void refresh() {
    }
}
""",
}


@pytest.fixture
def db(tmp_path: Path):
    root = tmp_path / "repo"
    for rel, text in FILES.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    cfg = Config()
    cfg.root = str(root)
    database = Database(tmp_path / "index.sqlite").open()
    build_index(cfg, database, root=root)
    yield database
    database.close()


def _calls(resp) -> list[tuple[str, int]]:
    return [(s.path, s.line) for s in resp.sites if s.kind == "call"]


def test_parser_records_the_call_receiver():
    edges = parse_file("java", FILES["command/PolityCommand.java"]).edges
    calls = [(e.callee_name, e.receiver) for e in edges if e.edge_type == "call"]
    assert calls == [("refresh", "TownService"), ("refresh", "PolityTuning")]


@pytest.mark.parametrize(
    ("query", "expected"),
    [
        ("TownService.refresh", ("TownService", "refresh")),
        ("town.TownService.refresh", ("TownService", "refresh")),
        ("Foo::new", ("Foo", "new")),
        ("Foo#bar", ("Foo", "bar")),
        ("refresh", None),
        ("src/town/TownService.java", None),
    ],
)
def test_split_member(query, expected):
    assert repo.split_member(query) == expected


def test_refs_by_owner_finds_cross_file_and_same_file_calls(db):
    resp = refs_lookup(db.conn, "TownService.refresh", kind="callers")
    assert _calls(resp) == [
        ("command/PolityCommand.java", 5),
        ("town/TownService.java", 5),
        ("treasury/TreasuryService.java", 5),
    ]
    assert {s.target for s in resp.sites} == {"TownService.refresh"}
    assert resp.coverage.partial is False


def test_refs_by_owner_excludes_same_named_methods_of_other_types(db):
    tuning = refs_lookup(db.conn, "PolityTuning.refresh", kind="callers")
    assert _calls(tuning) == [("command/PolityCommand.java", 6)]


def test_foreign_receiver_does_not_bind_to_a_local_method_of_that_name(db):
    # PolityCommand defines its own `refresh`; `TownService.refresh(...)` there must
    # not resolve to it.
    own = refs_lookup(db.conn, "PolityCommand.refresh", kind="callers")
    assert _calls(own) == []


def test_refs_sites_name_their_calling_method(db):
    resp = refs_lookup(db.conn, "TownService.refresh", kind="callers")
    callers = {(s.path, s.caller) for s in resp.sites}
    assert ("treasury/TreasuryService.java", "TreasuryService.sweep") in callers
    assert ("town/TownService.java", "TownService.found") in callers


def test_untyped_receiver_calls_are_listed_as_possible_and_mark_coverage_partial(db):
    resp = refs_lookup(db.conn, "Holdings.take", kind="callers")
    possible = [(s.path, s.line, s.caller) for s in resp.sites if s.kind == "possible_call"]
    # The chained call may hit Holdings.take; ApprenticeService.take names another
    # type and the Python `queue.take()` cannot call a Java method.
    assert possible == [("treasury/Withdraw.java", 5, "Withdraw.run")]
    assert resp.coverage.partial is True
    assert "1 call(s) to `take`" in resp.coverage.reason


def test_calls_do_not_bind_across_languages_or_to_another_types_unique_member(db):
    # `found` is defined once (TownService.found); the Python `server.found()` is not
    # a call to it. Nor is `ApprenticeService.take` a call to Holdings.take.
    assert _calls(refs_lookup(db.conn, "TownService.found", kind="callers")) == []
    take = refs_lookup(db.conn, "ApprenticeService.take", kind="callers")
    assert _calls(take) == [("treasury/Withdraw.java", 6)]


def test_bare_name_refs_label_each_site_with_its_target(db):
    resp = refs_lookup(db.conn, "refresh", kind="callers")
    targets = {(s.path, s.line): s.target for s in resp.sites}
    assert targets[("command/PolityCommand.java", 6)] == "PolityTuning.refresh"
    assert targets[("treasury/TreasuryService.java", 5)] == "TownService.refresh"


def test_impact_accepts_owner_member(db):
    resp = impact_lookup(db.conn, "TownService.refresh", depth=1, direction="up")
    callers = {(n.path, n.name) for n in resp.nodes}
    assert ("treasury/TreasuryService.java", "sweep") in callers
    assert ("command/PolityCommand.java", "rename") in callers
    assert ("town/TownService.java", "found") in callers
    assert resp.coverage.partial is False


def test_symbol_accepts_owner_member(db):
    resp = symbol_lookup(db.conn, "TownService.refresh", kind=None, exact=True)
    assert [s.line_start for s in resp.symbols] == [8, 12]


def test_unknown_target_is_reported_as_inconclusive(db):
    for resp in (
        refs_lookup(db.conn, "Nowhere.refresh", kind="all"),
        impact_lookup(db.conn, "Nowhere.refresh", depth=2, direction="up"),
    ):
        assert resp.coverage.partial is True
        assert "Nowhere.refresh" in resp.coverage.reason


RUST_AND_JAVA = {
    "launcher/src/activation.rs": """\
pub fn place(store: &Store, target: &Path) -> Result<()> {
    Ok(())
}

pub fn activate(store: &Store, target: &Path) -> Result<()> {
    place(store, target)?;
    Ok(())
}
""",
    "launcher/src/presets.rs": """\
use crate::activation::place;

pub fn apply(store: &Store, target: &Path) -> Result<()> {
    place(store, target)?;
    crate::activation::place(store, target)
}

struct Cache;

impl Cache {
    fn new() -> Self {
        Cache
    }
    fn fresh() -> Self {
        Self::new()
    }
}
""",
    "mod/Varieties.java": """\
public final class Varieties {
    static void place(Block block) {
    }

    static String describe() {
        return "";
    }

    static void harvest(Block block) {
        Kind.WOOD.describe();
    }
}
""",
}


@pytest.fixture
def mixed_db(tmp_path: Path):
    root = tmp_path / "mixed"
    for rel, text in RUST_AND_JAVA.items():
        path = root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    cfg = Config()
    cfg.root = str(root)
    database = Database(tmp_path / "mixed.sqlite").open()
    build_index(cfg, database, root=root)
    yield database
    database.close()


def test_a_name_unique_within_its_language_resolves_despite_other_languages(mixed_db):
    # Java also defines `place`; the Rust calls still resolve to the Rust one.
    resp = refs_lookup(mixed_db.conn, "activation::place", kind="callers")
    assert _calls(resp) == [
        ("launcher/src/activation.rs", 6),
        ("launcher/src/presets.rs", 4),
        ("launcher/src/presets.rs", 5),
    ]
    assert {s.confidence for s in resp.sites} <= {"extracted", "inferred"}


def test_module_qualified_symbol_lookup(mixed_db):
    resp = symbol_lookup(mixed_db.conn, "activation::place", kind=None, exact=True)
    assert [(s.path, s.line_start) for s in resp.symbols] == [("launcher/src/activation.rs", 1)]


def test_self_and_constant_receivers_keep_resolving(mixed_db):
    assert _calls(refs_lookup(mixed_db.conn, "Cache.new", kind="callers")) == [
        ("launcher/src/presets.rs", 15)
    ]
    assert _calls(refs_lookup(mixed_db.conn, "Varieties.describe", kind="callers")) == [
        ("mod/Varieties.java", 10)
    ]


@pytest.mark.parametrize(
    ("path", "module"),
    [("src/activation.rs", "activation"), ("auth/__init__.py", "auth"),
     ("auth/mod.rs", "auth"), ("web/index.ts", "web"), ("token.py", "token")],
)
def test_module_name(path, module):
    from codebase_index.parsers.base import module_name

    assert module_name(path) == module
