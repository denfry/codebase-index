"""A miniature of the sequential memory benchmark on a synthetic git history.

The invariants asserted here must hold on any corpus: memory never withholds text the
session does not hold, withheld packets restore to the no-memory packet exactly, every
invalidation notice matches an independent oracle, and a one-task session reuses nothing.
The scenario is built so the unsafe arm demonstrably goes stale where memory does not.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import yaml

from tests.eval import memory_eval

INVOICE = '''def compute_invoice_total(lines, tax_rate):
    """Sum invoice line amounts and apply the tax rate."""
    subtotal = sum(line.amount for line in lines)
    return round(subtotal * (1 + tax_rate), 2)
'''

REFUND = '''def issue_refund(invoice, amount):
    """Refund part of an invoice total."""
    if amount > invoice.total:
        raise ValueError("refund exceeds invoice total")
    return invoice.total - amount
'''

TAX = '''def tax_rate_for(region):
    """Look up the sales tax rate for a region."""
    return {"eu": 0.2, "us": 0.07}.get(region, 0.0)
'''


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=bench", "-c", "user.email=bench@example.com",
         "-c", "core.autocrlf=false", "-C", str(repo), *args],
        check=True, capture_output=True, text=True,
    ).stdout.strip()


def _commit(repo: Path, message: str, files: dict[str, str]) -> str:
    for rel, text in files.items():
        path = repo / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8", newline="\n")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", message)
    return _git(repo, "rev-parse", "HEAD")


def _history(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "origin"
    repo.mkdir()
    _git(repo, "init", "-q")
    _commit(repo, "initial billing", {"billing/invoice.py": INVOICE,
                                      "billing/refund.py": REFUND, "billing/tax.py": TAX})
    queries = []
    # Task 1 sees the original refund; its own commit then changes the signature and the
    # check without moving any line, so the same (path, lines) now holds different text.
    c1 = _commit(repo, "tighten refund check", {"billing/refund.py": REFUND.replace(
        "def issue_refund(invoice, amount):", "def issue_refund(invoice, amount, reason=None):"
    ).replace(">", ">=")})
    queries.append({"query": "refund exceeds invoice total", "commit": c1,
                    "expected_files": ["billing/refund.py"]})
    # Unrelated change: evidence from task 1 about invoices stays valid.
    c2 = _commit(repo, "add region", {"billing/tax.py": TAX.replace('"us": 0.07', '"us": 0.07, "ca": 0.05')})
    queries.append({"query": "refund exceeds invoice total amount", "commit": c2,
                    "expected_files": ["billing/tax.py"]})
    c3 = _commit(repo, "round tax", {"billing/tax.py": TAX.replace("0.0)", "0.0) or 0.0")})
    queries.append({"query": "invoice total refund tax rate", "commit": c3,
                    "expected_files": ["billing/tax.py"]})
    path = tmp_path / "queries.yml"
    path.write_text(yaml.safe_dump(queries), encoding="utf-8")
    return repo, path


def test_replay_is_sound_and_reuses_only_unchanged_evidence(tmp_path):
    repo, queries = _history(tmp_path)
    head_before = _git(repo, "rev-parse", "HEAD")
    result = memory_eval.replay_corpus(repo, queries, [None, 1])
    assert result.tasks == 3
    assert _git(repo, "rev-parse", "HEAD") == head_before  # source repository untouched
    assert _git(repo, "status", "--porcelain") == ""

    one_session = result.totals[None]
    assert one_session.c_stale_withheld == 0
    assert one_session.page_mismatches == 0
    assert one_session.notice_fp == 0 and one_session.notice_fn == 0
    assert one_session.c_reused > 0
    assert one_session.c_tokens < one_session.b_tokens
    assert one_session.s_stale_withheld > 0          # trusting old reads goes stale here
    assert one_session.notices >= 1                   # ...and memory said so instead

    per_task = result.totals[1]
    assert per_task.c_reused == 0 and per_task.c_tokens == per_task.b_tokens
    assert per_task.s_reused == 0

    summary = memory_eval.summarise("all", one_session)
    assert summary["C_validated_reuse_rate"] == 1.0
    assert memory_eval.format_report([summary]).count("|") > 20


def test_oracle_helpers():
    assert memory_eval.span_present(["a", "b", "c"], ["b", "c"], 2)
    assert memory_eval.span_present(["x", "b", "c"], ["b", "c"], 1)   # moved, unique
    assert not memory_eval.span_present(["b", "c", "b", "c"], ["b", "c"], 9)  # ambiguous
    assert not memory_eval.span_present(None, ["b"], 1)
    truth = memory_eval.SessionTruth()
    span = "export default function App() {\n  return 1\n}"
    truth.full_spans["a.tsx"] = {span}
    truth.held["b.py"] = {"def g(x):"}
    assert memory_eval.session_holds(truth, "a.tsx", "function App()", span)   # derived excerpt
    assert not memory_eval.session_holds(truth, "a.tsx", "function App()", span + " ")
    assert memory_eval.session_holds(truth, "b.py", "def g(x):", "def g(x):\n    return 2")
    assert not memory_eval.session_holds(truth, "b.py", "def g(y):", "def g(y):")
