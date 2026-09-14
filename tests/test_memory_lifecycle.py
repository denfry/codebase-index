"""Evidence validity across real repository lifecycles, driven through real git.

Validity is byte identity with the working tree, so every git operation is just another
way of changing (or restoring) bytes. These tests pin that down for the operations agents
actually perform, plus the security property that excluded content never reaches memory.
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path

import pytest

from codebase_index.config import Config
from codebase_index.indexer.pipeline import build_index, update_index
from codebase_index.service import search_payload, verify_payload
from codebase_index.storage.db import Database

REFUND = '''def issue_refund(invoice, amount):
    """Refund part of an invoice total."""
    if amount > invoice.total:
        raise ValueError("refund exceeds invoice total")
    return invoice.total - amount
'''
INVOICE = '''def compute_invoice_total(lines, tax_rate):
    """Sum invoice line amounts and apply the tax rate."""
    subtotal = sum(line.amount for line in lines)
    return round(subtotal * (1 + tax_rate), 2)
'''
TAX = '''def tax_rate_for(region):
    """Look up the sales tax rate for a region."""
    return {"eu": 0.2, "us": 0.07}.get(region, 0.0)
'''
QUERY = "refund exceeds invoice total"


def _git(root: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com",
         "-c", "core.autocrlf=false", "-C", str(root), *args],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


@dataclass
class Repo:
    root: Path
    cfg: Config
    db: Path

    def write(self, rel: str, text: str) -> None:
        path = self.root / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(text.encode("utf-8"))

    def commit(self, message: str) -> None:
        _git(self.root, "add", "-A")
        _git(self.root, "commit", "-q", "-m", message)

    def update(self) -> None:
        with Database(self.db) as db:
            update_index(self.cfg, db, root=self.root)

    def search(self, query: str = QUERY, session: str = "s1") -> dict:
        return search_payload(self.db, self.cfg, query, mode="hybrid", limit=10,
                              token_budget=1500, no_fallback=False, session=session)

    def states(self, session: str = "s1") -> dict[str, str]:
        payload = verify_payload(self.cfg, [], session)
        return {v["ref"].rsplit("@", 1)[0].rsplit(":", 1)[0]: v["state"]
                for v in payload["evidence"]}


def _make_repo(tmp_path: Path, monkeypatch, name: str = "repo") -> Repo:
    for var in ("CBX_DB_PATH", "CBX_MEMORY", "CBX_ROOT"):
        monkeypatch.delenv(var, raising=False)
    monkeypatch.setenv("CBX_MEMORY_PATH", str(tmp_path / "memory.sqlite"))
    root = tmp_path / name
    root.mkdir()
    _git(root, "init", "-q", "-b", "main")
    repo = Repo(root, Config(root=str(root)), tmp_path / f"{name}.sqlite")
    repo.cfg.root = str(root)
    repo.write("billing/refund.py", REFUND)
    repo.write("billing/invoice.py", INVOICE)
    repo.write("billing/tax.py", TAX)
    repo.commit("initial")
    with Database(repo.db) as db:
        build_index(repo.cfg, db, root=root)
    return repo


@pytest.fixture
def repo(tmp_path, monkeypatch) -> Repo:
    return _make_repo(tmp_path, monkeypatch)


def _delivered_paths(payload: dict) -> set[str]:
    return {r["path"] for r in payload["results"] if r["snippet"]}


def test_unrelated_commit_keeps_evidence_valid_and_reused(repo):
    delivered = _delivered_paths(repo.search())
    assert "billing/refund.py" in delivered
    repo.write("billing/tax.py", TAX.replace("0.07", "0.08"))
    repo.commit("adjust us tax")
    repo.update()
    assert set(repo.states().values()) == {"valid"}
    again = repo.search()
    assert again["memory"]["invalidated"] == []
    assert any(r.get("reused") for r in again["results"] if r["path"] == "billing/refund.py")


def test_branch_switch_invalidates_what_differs_and_restores_on_return(repo):
    repo.search()
    _git(repo.root, "checkout", "-q", "-b", "feature")
    repo.write("billing/refund.py", REFUND.replace(">", ">="))
    repo.commit("tighten refund")
    assert repo.states()["billing/refund.py"] == "changed"
    _git(repo.root, "checkout", "-q", "main")
    assert repo.states()["billing/refund.py"] == "valid"  # identical bytes are identical evidence


def test_detached_head_is_validated_against_its_own_tree(repo):
    first = _git(repo.root, "rev-parse", "HEAD")
    repo.write("billing/refund.py", REFUND.replace("amount):", "amount, note=None):"))
    repo.commit("add note")
    repo.update()
    repo.search()                                   # evidence from the new commit
    _git(repo.root, "checkout", "-q", "--detach", first)
    assert repo.states()["billing/refund.py"] == "changed"


def test_worktree_is_a_separate_memory_scope(repo, tmp_path):
    payload = repo.search()
    ref = next(v["ref"] for v in verify_payload(repo.cfg, [], "s1")["evidence"])
    other = tmp_path / "wt"
    _git(repo.root, "worktree", "add", "-q", "--detach", str(other), "HEAD")
    cfg = Config()
    cfg.root = str(other)
    scoped = verify_payload(cfg, [ref], "s1")
    assert scoped["session"]["found"] is False       # sessions never leak across checkouts
    assert scoped["evidence"][0]["state"] == "valid"  # but the bytes there are the same
    assert payload["memory"]["reused"] == 0


def test_dirty_staged_and_unstaged_changes_are_what_is_validated(repo):
    repo.search()
    changed = REFUND.replace("refund exceeds", "refund is larger than")
    repo.write("billing/refund.py", changed)
    assert repo.states()["billing/refund.py"] == "changed"         # unstaged edit
    _git(repo.root, "add", "billing/refund.py")
    assert repo.states()["billing/refund.py"] == "changed"         # staged, same bytes
    repo.write("billing/refund.py", REFUND)
    assert repo.states()["billing/refund.py"] == "valid"           # worktree wins over index
    _git(repo.root, "reset", "-q", "billing/refund.py")
    assert repo.states()["billing/refund.py"] == "valid"


def test_rename_and_delete_invalidate_the_old_paths(repo):
    repo.search("refund invoice total tax rate region")
    held = repo.states()
    assert {"billing/refund.py", "billing/tax.py"} <= set(held)
    _git(repo.root, "mv", "billing/refund.py", "billing/refunds.py")
    (repo.root / "billing" / "tax.py").unlink()
    states = repo.states()
    assert states["billing/refund.py"] == "deleted"
    assert states["billing/tax.py"] == "deleted"


def test_new_file_evidence_is_delivered_before_it_can_be_reused(repo):
    repo.write("billing/credit.py", REFUND.replace("issue_refund", "issue_store_credit"))
    repo.update()
    first = repo.search("issue store credit refund exceeds invoice total")
    hit = next(r for r in first["results"] if r["path"] == "billing/credit.py")
    assert hit["snippet"] and not hit.get("reused")


def test_rebase_evidence_follows_bytes_not_history(repo):
    repo.search("refund invoice total tax rate region")
    _git(repo.root, "checkout", "-q", "-b", "topic")
    repo.write("billing/invoice.py", INVOICE.replace("round(", "abs(round("). replace(", 2)", ", 2))"))
    repo.commit("topic change to invoice")
    _git(repo.root, "checkout", "-q", "main")
    repo.write("billing/tax.py", TAX.replace("0.2", "0.21"))
    repo.commit("main change to tax")
    _git(repo.root, "checkout", "-q", "topic")
    _git(repo.root, "rebase", "-q", "main")
    states = repo.states()
    assert states["billing/refund.py"] == "valid"
    assert states["billing/invoice.py"] == "changed"
    assert states.get("billing/tax.py", "changed") == "changed"


def test_crlf_checkout_is_not_a_change(repo):
    repo.search()
    (repo.root / "billing" / "refund.py").write_bytes(REFUND.replace("\n", "\r\n").encode())
    assert repo.states()["billing/refund.py"] == "valid"


CANARY = "CANARY_7f3a9e_do_not_persist"


def test_excluded_content_never_reaches_memory_or_verification(tmp_path, monkeypatch):
    repo = _make_repo(tmp_path, monkeypatch)
    repo.write(".env", f"API_KEY={CANARY}\n")
    repo.write("config/secrets.json", f'{{"token": "{CANARY}"}}\n')
    repo.write("node_modules/pkg/index.js", f"module.exports = '{CANARY}';\n")
    repo.write("private/notes.py", f"NOTE = '{CANARY}'\n")
    repo.write(".gitignore", "private/\n")
    repo.write("billing/audit.py", f"def audit_refund():\n    return '{CANARY} refund exceeds'\n")
    repo.update()

    payload = repo.search(f"{CANARY} refund exceeds invoice total")
    assert all(not r["path"].startswith((".env", "config/", "node_modules/", "private/"))
               for r in payload["results"])
    # The file is indexed today; ignoring it afterwards must stop memory from using it.
    assert any(r["path"] == "billing/audit.py" for r in payload["results"])
    repo.write(".gitignore", "private/\nbilling/audit.py\n")
    later = repo.search(f"{CANARY} refund exceeds invoice total")
    audit = [r for r in later["results"] if r["path"] == "billing/audit.py"]
    assert audit and all(r.get("stale") for r in audit)

    refs = [f"{p}:1-1@0123456789abcdef" for p in
            (".env", "config/secrets.json", "node_modules/pkg/index.js", "private/notes.py",
             "billing/audit.py")]
    verdicts = verify_payload(repo.cfg, refs)["evidence"]
    assert [v["state"] for v in verdicts] == ["excluded"] * 5

    blob = b"".join(p.read_bytes() for p in tmp_path.glob("memory.sqlite*"))
    assert CANARY.encode() not in blob
