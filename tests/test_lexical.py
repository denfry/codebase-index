from codebase_index.retrieval.lexical import (
    build_fts_query,
    build_lexical_query,
    escape_fts_term,
    expansion_weights,
    salient_terms,
    split_identifier,
)


def test_split_identifier_handles_camel_pascal_snake_kebab_and_concatenation():
    assert split_identifier("getUserById") == ("get", "user", "by", "id")
    assert split_identifier("PascalCase") == ("pascal", "case")
    assert split_identifier("refresh_access-token") == ("refresh", "access", "token")
    assert split_identifier("userid") == ("userid",)


def test_salient_terms_excludes_natural_language_filler():
    assert salient_terms("How does the auth config work?") == ("auth", "config")


def test_lexical_query_preserves_originals_and_adds_synonyms_subtokens():
    parsed = build_lexical_query("refresh_access_token auth")

    assert parsed.original_terms == ("refresh_access_token", "auth")
    assert [term.term for term in parsed.expanded_terms] == [
        "refresh",
        "access",
        "token",
        "authentication",
    ]
    assert all(term.weight < 1.0 for term in parsed.expanded_terms)

def test_query_expansion_retains_camel_case_boundaries():
    parsed = build_lexical_query("getUserById")

    assert parsed.original_terms == ("getuserbyid",)
    assert [term.term for term in parsed.expanded_terms] == ["get", "user", "by", "id"]


def test_synonym_weights_are_lower_than_original_terms():
    weights = expansion_weights("delete config")

    assert weights["delete"] == 1.0
    assert weights["remove"] < weights["delete"]
    assert weights["config"] == 1.0
    assert weights["configuration"] < weights["config"]


def test_fts_terms_are_quoted_and_unsafe_syntax_is_literal():
    assert escape_fts_term('name" OR secret') == '"name"" OR secret"'
    query = build_fts_query('delete " OR drop')
    assert ' OR drop' not in query
    assert '"delete"' in query


def test_natural_language_inflections_get_downweighted_bridges():
    parsed = build_lexical_query("secrets were redacted")
    assert parsed.original_terms == ("secrets", "redacted")
    assert [term.term for term in parsed.expanded_terms] == ["secret", "redact"]
    assert all(term.weight < 1.0 for term in parsed.expanded_terms)


def test_morphological_merging_bridge_matches_merging_text():
    parsed = build_lexical_query("configuration get loaded and merged")
    assert "merg" in [term.term for term in parsed.expanded_terms]
