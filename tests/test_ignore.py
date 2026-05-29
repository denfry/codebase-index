from __future__ import annotations

from codebase_index.discovery.ignore import IgnoreMatcher


def test_builtin_denylist_ignores_dependency_and_build_dirs(sample_repo):
    matcher = IgnoreMatcher.from_root(sample_repo)
    assert matcher.is_ignored_dir("node_modules")
    assert matcher.is_ignored_dir(".git")
    assert matcher.is_ignored("dist/bundle.min.js")
    assert not matcher.is_ignored("src/auth/token.py")


def test_root_ignore_files_and_extra_ignore(sample_repo):
    matcher = IgnoreMatcher.from_root(sample_repo, extra_ignore=["web/"])
    assert matcher.is_ignored("debug.log")
    assert matcher.is_ignored("web/app.ts")
    assert not matcher.is_ignored("src/models/user.py")