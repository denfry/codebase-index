from __future__ import annotations

from codebase_index.discovery.classify import (
    detect_language,
    is_generated,
    is_secret_filename,
    is_test_path,
    looks_binary,
    parser_for,
)


def test_detect_language_from_extension():
    assert detect_language("src/app.py") == "python"
    assert detect_language("web/app.ts") == "typescript"
    assert detect_language("web/app.tsx") == "typescript"
    assert detect_language("web/app.js") == "javascript"
    assert detect_language("README.md") == "markdown"
    assert detect_language("unknown.xyz") is None


def test_parser_for_tree_sitter_languages():
    assert parser_for("python") == "treesitter"
    assert parser_for("typescript") == "treesitter"
    assert parser_for("markdown") == "line"
    assert parser_for(None) == "line"


def test_detect_config_and_iac_languages():
    assert detect_language("infra/main.tf") == "terraform"
    assert detect_language("infra/prod.tfvars") == "terraform"
    assert detect_language("infra/policy.hcl") == "hcl"
    assert detect_language("setup.cfg") == "ini"
    assert detect_language("app/settings.ini") == "ini"
    assert detect_language("app.conf") == "ini"
    assert detect_language("gradle.properties") == "ini"


def test_detect_language_by_filename():
    # Dockerfile/Makefile carry identity in the name, not the suffix.
    assert detect_language("Dockerfile") == "dockerfile"
    assert detect_language("docker/Dockerfile") == "dockerfile"
    assert detect_language("services/web.Dockerfile") == "dockerfile"
    assert detect_language("Containerfile") == "dockerfile"
    assert detect_language("Makefile") == "make"
    assert detect_language("GNUmakefile") == "make"


def test_config_and_iac_languages_stay_on_line_parser():
    # Tier C: labeled, but FTS-only — never routed to a (missing) tree-sitter spec.
    for lang in ("terraform", "hcl", "ini", "dockerfile", "make"):
        assert parser_for(lang) == "line"


def test_secret_filename_detection():
    for path in [".env", ".env.local", "secrets.pem", "id_rsa", "config/credentials.json"]:
        assert is_secret_filename(path)
    assert not is_secret_filename("src/token.py")


def test_binary_detection():
    assert looks_binary(b"abc\x00def")
    assert not looks_binary(b"plain text\nwith lines")


def test_generated_detection():
    assert is_generated("src/schema.generated.ts")
    assert is_generated("web/app.min.js")
    assert not is_generated("web/app.ts")


def test_is_test_path_matches_test_trees_and_modules():
    for path in [
        "tests/test_auth.py",
        "src/__tests__/user.test.ts",
        "pkg/foo_test.go",
        "app/user.spec.ts",
        "e2e/login.py",
        "project/test/Thing.java",
    ]:
        assert is_test_path(path), path


def test_is_test_path_does_not_match_substring_lookalikes():
    # Word-boundary, not bare substring: these contain "test" but are not tests.
    for path in [
        "src/contest/leaderboard.py",
        "lib/latest.py",
        "util/fastest_path.ts",
        "web/testimonials.tsx",
        "src/attestation.py",
    ]:
        assert not is_test_path(path), path