from __future__ import annotations

import pytest

from codebase_index.retrieval.priors import (
    MAX_ABS_PRIOR,
    SourceRole,
    classify_source_role,
    is_test_intent,
    source_role_prior,
)


def test_classifies_roles_across_posix_and_windows_paths():
    assert (
        classify_source_role("src/codebase_index/retrieval/searchers.py")
        is SourceRole.IMPLEMENTATION
    )
    assert classify_source_role(r"C:\work\tests\test_searchers.py") is SourceRole.TEST
    assert classify_source_role("docs/retrieval.md") is SourceRole.DOCUMENTATION
    assert (
        classify_source_role(r"C:\work\node_modules\pkg\index.js")
        is SourceRole.GENERATED_VENDOR_BUILD
    )
    assert classify_source_role("misc/data.bin") is SourceRole.UNKNOWN


def test_prior_preserves_order_and_is_bounded():
    values = {
        role: source_role_prior(
            {
                SourceRole.IMPLEMENTATION: "src/search.py",
                SourceRole.TEST: "tests/test_search.py",
                SourceRole.DOCUMENTATION: "docs/search.md",
                SourceRole.GENERATED_VENDOR_BUILD: "dist/search.min.js",
                SourceRole.UNKNOWN: "misc/data.bin",
                SourceRole.LOCALIZATION: "src/i18n/en.json",
                SourceRole.WORKFLOW_ARTIFACT: ".superpowers/review-1..2.diff",
            }[role],
            query="where is search implemented",
            extended=True,
        )
        for role in SourceRole
    }
    assert values[SourceRole.IMPLEMENTATION] > values[SourceRole.TEST]
    assert values[SourceRole.IMPLEMENTATION] > values[SourceRole.DOCUMENTATION]
    # Prose is demoted below tests but stays above vendored/generated output: a
    # design note can still answer a question, a minified bundle never can.
    assert values[SourceRole.TEST] > values[SourceRole.DOCUMENTATION]
    assert values[SourceRole.DOCUMENTATION] > values[SourceRole.GENERATED_VENDOR_BUILD]
    # Priors must stay tiebreakers. The bound is read from the module so the
    # contract cannot drift by editing one number in isolation, and is asserted
    # small here so widening the constant is itself a visible change.
    assert MAX_ABS_PRIOR <= 0.25
    assert all(abs(value) <= MAX_ABS_PRIOR for value in values.values())
    assert (
        source_role_prior("src/search.py", query="where is search implemented")
        == values[SourceRole.IMPLEMENTATION]
    )


def test_test_intent_does_not_demote_tests():
    assert is_test_intent("find the unit tests for search")
    assert (
        source_role_prior("tests/test_search.py", query="find the unit tests for search")
        > 0
    )
    assert (
        source_role_prior("tests/test_search.py", query="find the unit tests for search")
        > source_role_prior(
            "tests/test_search.py", query="where is search implemented"
        )
    )
    assert (
        source_role_prior("tests/test_search.py", query="anything", intent="find_refs")
        < 0
    )
    assert (
        source_role_prior("tests/test_search.py", query="anything", intent="test")
        > 0
    )


def test_role_classification_is_path_only_and_deterministic():
    path = r"C:\repo\src\contest\latest.py"
    assert classify_source_role(path) is SourceRole.IMPLEMENTATION
    assert classify_source_role(path) == classify_source_role(path)


@pytest.mark.parametrize(
    ("path", "role"),
    [
        ("realism-polity/src/main/resources/assets/realism_polity/lang/en_us.json",
         SourceRole.LOCALIZATION),
        ("launcher/app/src/i18n/en.json", SourceRole.LOCALIZATION),
        ("app/locales/pt-BR/messages.po", SourceRole.LOCALIZATION),
        (".superpowers/sdd/phase-2/review-e870589..e5bb4a0.diff", SourceRole.WORKFLOW_ARTIFACT),
        ("patches/fix.patch", SourceRole.WORKFLOW_ARTIFACT),
        # Kept: CI configuration is sometimes the answer, and data is not demoted.
        (".github/workflows/release.yml", SourceRole.IMPLEMENTATION),
        ("src/main/resources/data/realism/crops/wheat.json", SourceRole.IMPLEMENTATION),
        ("src/lang/Parser.java", SourceRole.IMPLEMENTATION),
    ],
)
def test_extended_roles(path, role):
    assert classify_source_role(path, extended=True) is role


def test_extended_roles_are_opt_in():
    assert classify_source_role("launcher/app/src/i18n/en.json") is not SourceRole.LOCALIZATION
