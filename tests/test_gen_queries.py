"""Tests for the git-history ground-truth generator.

The generator is benchmark infrastructure, so its failure mode is silent: a bad
filter produces a plausible-looking query set that measures the wrong thing.
These tests pin the filtering rules that keep the set objective and leak-free.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent))

from eval import gen_queries  # noqa: E402


def _git(repo: Path, *args: str, **kw) -> None:
    subprocess.run(
        ["git", "-C", str(repo), *args],
        check=True,
        capture_output=True,
        text=True,
        **kw,
    )


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    root = tmp_path / "corpus"
    root.mkdir()
    _git(root, "init", "-q")
    _git(root, "config", "user.email", "dev@example.test")
    _git(root, "config", "user.name", "Dev")
    return root


def _commit(repo: Path, subject: str, files: dict[str, str]) -> None:
    for rel, body in files.items():
        target = repo / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(body, encoding="utf-8")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", subject)


def _harvest(repo: Path, **kw):
    params = {"max_commits": 100, "max_files": 4, "min_words": 3}
    params.update(kw)
    return gen_queries.harvest(repo, **params)


def test_conventional_prefix_becomes_category_and_is_stripped(repo):
    _commit(repo, "feat(auth): refresh the access token", {"src/auth.py": "def refresh(): ..."})
    (record,) = _harvest(repo)
    assert record["query"] == "refresh the access token"
    assert record["category"] == "feature"
    assert record["expected_files"] == ["src/auth.py"]
    assert record["commit"]


def test_bookkeeping_commits_are_excluded(repo):
    _commit(repo, "feat: add the parser entry point", {"src/parse.py": "x = 1"})
    _commit(repo, "release: v2.1.0", {"src/parse.py": "x = 2"})
    _commit(repo, "chore(deps): bump pytest", {"src/parse.py": "x = 3"})
    _commit(repo, "Revert \"add the parser entry point\"", {"src/parse.py": "x = 4"})
    assert [r["query"] for r in _harvest(repo)] == ["add the parser entry point"]


def test_sweeping_commits_are_dropped(repo):
    _commit(
        repo,
        "refactor: rename everything everywhere at once",
        {f"src/mod{i}.py": "y = 1" for i in range(9)},
    )
    assert _harvest(repo, max_files=4) == []
    assert len(_harvest(repo, max_files=20)) == 1


def test_changelog_is_never_an_expected_answer(repo):
    """Changelogs paraphrase commit subjects; grading against them measures leakage."""
    _commit(
        repo,
        "fix: guard against an empty token budget",
        {"CHANGELOG.md": "- guard against an empty token budget", "src/budget.py": "b = 0"},
    )
    (record,) = _harvest(repo)
    assert record["expected_files"] == ["src/budget.py"]


def test_commit_touching_only_unanswerable_files_is_dropped(repo):
    _commit(repo, "docs: add the architecture diagram", {"assets/diagram.png": "binary-ish"})
    assert _harvest(repo) == []


def test_benchmark_scaffolding_never_grades_itself(repo):
    _commit(
        repo,
        "test: extend the retrieval evaluation set",
        {"tests/eval/queries/extra.yml": "- query: x", "src/thing.py": "z = 1"},
    )
    assert _harvest(repo) == []


def test_short_subjects_and_duplicates_are_filtered(repo):
    _commit(repo, "fix: typo", {"src/a.py": "a = 1"})
    _commit(repo, "fix: correct the retry backoff", {"src/b.py": "b = 1"})
    _commit(repo, "fix: correct the retry backoff", {"src/c.py": "c = 1"})
    records = _harvest(repo)
    assert [r["query"] for r in records] == ["correct the retry backoff"]
    # First occurrence wins, so provenance stays stable across regeneration.
    assert records[0]["expected_files"] == ["src/c.py"]


def test_deleted_files_are_not_expected_answers(repo):
    _commit(repo, "feat: add a temporary shim layer", {"src/shim.py": "s = 1"})
    (repo / "src/shim.py").unlink()
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "-m", "refactor: drop the shim layer entirely")
    # The add-commit's only answer no longer exists at HEAD, so it must not ship.
    assert all("src/shim.py" not in r["expected_files"] for r in _harvest(repo))


def test_rendered_yaml_round_trips_through_the_harness(repo, tmp_path):
    _commit(
        repo,
        'fix: escape a "quoted" path\\name safely',
        {"src/escape.py": "e = 1"},
    )
    out = tmp_path / "generated.yml"
    assert gen_queries.main(["--repo", str(repo), "--out", str(out)]) == 0

    from eval import harness

    queries = harness.load_queries(out)
    assert len(queries) == 1
    # Quotes are stripped as prose decoration; a backslash is content and must
    # survive YAML escaping intact.
    assert queries[0].query == "escape a quoted path\\name safely"
    assert harness.validate_queries(queries, repo) == []


def test_strip_prefix_handles_unprefixed_and_breaking_subjects():
    assert gen_queries.strip_prefix("just do the thing") == ("change", "just do the thing")
    assert gen_queries.strip_prefix("feat!: drop python 3.9") == ("feature", "drop python 3.9")
    assert gen_queries.strip_prefix("perf(index): speed up walking") == (
        "perf",
        "speed up walking",
    )
