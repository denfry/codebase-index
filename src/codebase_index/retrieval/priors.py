"""Source-role priors for retrieval ranking.

The helpers in this module inspect only a candidate's path and query metadata. They
never touch the filesystem, and their deliberately small scores are intended to
break near-ties rather than replace lexical or symbol evidence.
"""

from __future__ import annotations

import re
from enum import Enum
from pathlib import PurePosixPath

from ..discovery.classify import detect_language, is_generated, is_test_path
from .types import Intent


class SourceRole(str, Enum):
    """Coarse role used to apply a ranking prior to a source path."""

    IMPLEMENTATION = "implementation"
    TEST = "test"
    DOCUMENTATION = "documentation"
    GENERATED_VENDOR_BUILD = "generated_vendor_build"
    # Extended roles (RetrievalTuning.resource_priors).
    LOCALIZATION = "localization"
    WORKFLOW_ARTIFACT = "workflow_artifact"
    UNKNOWN = "unknown"


# Directory names are compared as complete path components, not substrings. This
# keeps paths such as ``contest`` and ``builder`` from receiving a false penalty.
_GENERATED_DIRS = frozenset(
    {
        "build",
        "coverage",
        "dist",
        "generated",
        "gen",
        "out",
        "target",
        "vendor",
        "vendors",
        "site-packages",
        "dist-packages",
        "thirdparty",
        "external",
        "node_modules",
        "bower_components",
        "__pycache__",
        ".venv",
        "venv",
    }
)
_DOCUMENTATION_DIRS = frozenset({"doc", "docs", "documentation"})
_IMPLEMENTATION_DIRS = frozenset(
    {
        "app",
        "bin",
        "client",
        "cmd",
        "include",
        "lib",
        "module",
        "modules",
        "pkg",
        "server",
        "service",
        "services",
        "src",
    }
)
_DOCUMENTATION_SUFFIXES = frozenset({".adoc", ".md", ".mdx", ".rst", ".textile"})
_DOCUMENTATION_NAMES = frozenset(
    {
        "authors",
        "changelog",
        "codeowners",
        "contributing",
        "copying",
        "license",
        "notice",
        "readme",
        "security",
    }
)
# Source extensions not covered by discovery.classify.detect_language (for
# extensionless special cases, detect_language remains the authoritative check).
_IMPLEMENTATION_SUFFIXES = frozenset(
    {
        ".asm",
        ".dart",
        ".ex",
        ".exs",
        ".fs",
        ".fsx",
        ".groovy",
        ".hs",
        ".jl",
        ".m",
        ".mm",
        ".nim",
        ".pl",
        ".proto",
        ".scala",
        ".sh",
        ".swift",
        ".v",
        ".vue",
        ".zig",
    }
)
# Localisation catalogues repeat every user-facing noun of a feature, so they match
# natural-language questions about it better than the code does.
_LOCALIZATION_DIRS = frozenset({"i18n", "l10n", "lang", "langs", "locale", "locales",
                                "translations"})
_LOCALIZATION_SUFFIXES = frozenset({".po", ".pot", ".xliff", ".xlf", ".strings", ".resx",
                                    ".arb", ".ftl"})
_LOCALE_STEM_RE = re.compile(r"[a-z]{2,3}(?:[_-][a-z]{2,4})?", re.IGNORECASE)
# Suffixes a catalogue under a localisation directory may have.
_DATA_SUFFIXES = frozenset({".json", ".json5", ".yaml", ".yml", ".toml", ".xml", ".csv",
                            ".tsv", ".properties", ".mcmeta", ".nbt", ".snbt", ".ini",
                            ".cfg", ".conf"})
# Review diffs, patches and the scratch directories agents write plans into: they
# quote the code (and the question's words) without being the code.
_WORKFLOW_SUFFIXES = frozenset({".diff", ".patch", ".orig", ".rej"})
_KEPT_DOT_DIRS = frozenset({".github", ".gitlab", ".circleci", ".devcontainer",
                            ".husky", ".config"})
_MINIFIED_NAME_RE = re.compile(r"(?:^|[._-])min(?:ified)?(?:[._-]|$)", re.IGNORECASE)
_TEST_QUERY_RE = re.compile(
    r"\b(?:test|tests|testing|e2e|spec|specs|fixture|fixtures|mock|mocks|pytest|jest)\b",
    re.IGNORECASE,
)

# No single prior may exceed this magnitude. Priors exist to break ties between
# comparably-matching files, never to overrule retrieval evidence: fused scores
# reach ~1.0-1.5 and the largest rerank bonus (exact symbol) is 0.20, so a prior
# capped here can reorder near-neighbours but cannot lift an unrelated file over a
# genuine match. Widening this constant is a deliberate ranking-policy change.
MAX_ABS_PRIOR = 0.25

_ROLE_PRIORS = {
    SourceRole.IMPLEMENTATION: 0.08,
    SourceRole.TEST: -0.06,
    # Prose about a feature matches a natural-language question more literally than
    # the code implementing it, so design notes and plans crowded out the modules
    # they describe. Measured over 305 queries on three repositories, deepening the
    # demotion from -0.05 to -0.20 raised MRR and — because it only reorders docs
    # relative to code, never below other docs — also improved documentation-seeking
    # queries. -0.35 overshoots and collapses them, so the optimum is interior.
    SourceRole.DOCUMENTATION: -0.20,
    # Kept below documentation: a vendored or generated copy is the least useful
    # answer of all. Measured as quality-neutral on the benchmark corpora, so this
    # value preserves the role ordering rather than chasing a score.
    SourceRole.GENERATED_VENDOR_BUILD: -0.25,
    SourceRole.LOCALIZATION: -0.25,
    SourceRole.WORKFLOW_ARTIFACT: -0.25,
    SourceRole.UNKNOWN: 0.0,
}
_TEST_QUERY_PRIOR = 0.05


def _path_parts(path: str) -> tuple[str, ...]:
    """Normalize either separator style without touching the filesystem."""

    normalized = str(path).replace("\\", "/")
    return tuple(part for part in PurePosixPath(normalized).parts if part not in {"", "."})


def classify_source_role(path: str, *, extended: bool = False) -> SourceRole:
    """Classify *path* into a small set of ranking roles.

    Generated/vendor/build markers take precedence over test markers: a vendored
    or generated copy is generally less useful even when it happens to live under
    a test-looking directory. Test detection delegates to the repository's
    word-boundary-aware :func:`is_test_path` helper.
    """

    parts = _path_parts(path)
    lowered = tuple(part.lower() for part in parts)
    name = lowered[-1] if lowered else ""
    stem = name.rsplit(".", 1)[0] if "." in name else name
    suffix = PurePosixPath(name).suffix.lower()

    if (
        is_generated(path)
        or name.endswith(".map")
        or _MINIFIED_NAME_RE.search(name)
        or any(part in _GENERATED_DIRS for part in lowered[:-1])
    ):
        return SourceRole.GENERATED_VENDOR_BUILD
    if extended:
        if suffix in _WORKFLOW_SUFFIXES or any(
            part.startswith(".") and len(part) > 1 and part not in _KEPT_DOT_DIRS
            for part in lowered[:-1]
        ):
            return SourceRole.WORKFLOW_ARTIFACT
        if suffix in _LOCALIZATION_SUFFIXES or (
            any(part in _LOCALIZATION_DIRS for part in lowered[:-1])
            and (suffix in _DATA_SUFFIXES or _LOCALE_STEM_RE.fullmatch(stem))
        ):
            return SourceRole.LOCALIZATION
    if is_test_path(path):
        return SourceRole.TEST
    if (
        any(part in _DOCUMENTATION_DIRS for part in lowered[:-1])
        or suffix in _DOCUMENTATION_SUFFIXES
        or stem in _DOCUMENTATION_NAMES
    ):
        return SourceRole.DOCUMENTATION
    if (
        detect_language(path) is not None
        or suffix in _IMPLEMENTATION_SUFFIXES
        or any(part in _IMPLEMENTATION_DIRS for part in lowered[:-1])
    ):
        return SourceRole.IMPLEMENTATION
    return SourceRole.UNKNOWN


def is_test_intent(query: str = "", intent: Intent | str | None = None) -> bool:
    """Return whether ranking should favor test sources for this request.

    ``intent`` accepts the retrieval ``Intent`` enum, its string value, or another
    enum-like object. Query terms are still checked because the normal intent plan
    intentionally has no dedicated ``TEST`` enum.
    """

    if _TEST_QUERY_RE.search(query):
        return True
    if intent is None:
        return False
    value = getattr(intent, "value", intent)
    return bool(isinstance(value, str) and _TEST_QUERY_RE.search(value))


def source_role_prior(
    path: str,
    *,
    query: str = "",
    intent: Intent | str | None = None,
    extended: bool = False,
) -> float:
    """Return a deterministic, bounded additive score for a source path.

    The test-role penalty is replaced with a small positive bonus for an explicit
    test-oriented query/intent. Other role scores remain unchanged, and generated
    or vendored paths stay penalized even when they contain tests.
    """

    role = classify_source_role(path, extended=extended)
    if role is SourceRole.TEST and is_test_intent(query, intent):
        return _TEST_QUERY_PRIOR
    return _ROLE_PRIORS[role]


# Concise alias for call sites that refer to the signal as a source prior.
def source_prior(path: str, *, query: str = "", intent: Intent | str | None = None) -> float:
    """Alias for :func:`source_role_prior`."""

    return source_role_prior(path, query=query, intent=intent)
