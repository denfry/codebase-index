"""Evidence identity: line model, hashing, references. Pure functions, so tested exhaustively."""

from __future__ import annotations

import random
import sys

import pytest

from codebase_index.memory import identity as ident
from codebase_index.parsers.line_chunker import chunk_text


def test_crlf_and_lf_checkouts_are_the_same_evidence():
    lf = b"def f():\n    return 1\n"
    crlf = b"def f():\r\n    return 1\r\n"
    assert ident.split_lines(lf) == ident.split_lines(crlf)
    assert ident.span_sha(ident.split_lines(lf), 1, 2) == ident.span_sha(ident.split_lines(crlf), 1, 2)


def test_line_model_matches_the_chunker_including_form_feeds():
    """Chunk content and the hashed span must be the same lines, or verification lies."""
    raw = b"a = 1\n\x0cb = 2\nc = 3\r\nd = 4\n"
    text = raw.decode("utf-8").replace("\r\n", "\n")
    chunk = chunk_text(text, window_lines=80, overlap_lines=0)[0]
    lines = ident.split_lines(raw)
    assert ident.span_text(lines, chunk.line_start, chunk.line_end) == chunk.content


def test_whitespace_and_comments_are_part_of_identity():
    base = ident.split_lines(b"x = 1\n")
    for variant in (b"x  = 1\n", b"x = 1  # note\n", b"X = 1\n"):
        assert ident.span_sha(ident.split_lines(variant), 1, 1) != ident.span_sha(base, 1, 1)


def test_undecodable_bytes_still_change_the_hash():
    a = ident.split_lines(b"blob = '\xff'\n")
    b = ident.split_lines(b"blob = '\xfe'\n")
    assert ident.span_sha(a, 1, 1) != ident.span_sha(b, 1, 1)
    # ...while the indexer-visible text (bytes dropped) is identical for both.
    assert ident.visible_text(a[0]) == ident.visible_text(b[0])


def test_span_identity_is_independent_of_position():
    body = [b"def g(x):", b"    return x * 2"]
    top = ident.split_lines(b"\n".join(body) + b"\n")
    shifted = ident.split_lines(b"import os\n\n" + b"\n".join(body) + b"\n")
    assert ident.span_sha(top, 1, 2) == ident.span_sha(shifted, 3, 4)


@pytest.mark.parametrize("start,end", [(0, 1), (2, 1), (1, 99)])
def test_out_of_range_spans_have_no_identity(start, end):
    assert ident.span_sha(["a", "b"], start, end) is None


def test_reference_round_trip_and_prefix_matching():
    lines = ident.split_lines(b"one\ntwo\nthree\n")
    full = ident.span_sha(lines, 2, 3)
    ref = ident.make_ref("src/mod.py", 2, 3, full)
    printed = str(ref)
    assert printed == f"src/mod.py:2-3@{full[:ident.REF_HASH_CHARS]}"
    parsed = ident.parse_ref(printed)
    assert parsed.path == "src/mod.py" and (parsed.line_start, parsed.line_end) == (2, 3)
    assert parsed.matches(full)
    assert not parsed.matches(ident.span_sha(lines, 1, 2))


def test_reference_parsing_is_right_anchored_for_odd_paths():
    ref = ident.parse_ref("docs/a:b@c.md:10-12@0123456789abcdef")
    assert ref.path == "docs/a:b@c.md" and ref.line_start == 10 and ref.line_end == 12


def test_windows_separators_normalise():
    assert ident.parse_ref("src\\pkg\\m.py:1-2@0123456789ab").path == "src/pkg/m.py"


@pytest.mark.parametrize(
    "text",
    [
        "src/m.py:1-2",                      # no hash
        "src/m.py:3-2@0123456789abcdef",     # inverted range
        "src/m.py:0-2@0123456789abcdef",     # zero line
        "src/m.py:1-2@0123456789",           # hash too short
        "src/m.py:1-2@zzzzzzzzzzzzzzzz",     # not hex
        "/etc/passwd:1-1@0123456789abcdef",  # absolute
        "C:/Windows/win.ini:1-1@0123456789abcdef",
        "../outside.py:1-1@0123456789abcdef",
        "src/../../outside.py:1-1@0123456789abcdef",
        "src/m\x00.py:1-1@0123456789abcdef",
    ],
)
def test_malformed_or_escaping_references_are_rejected(text):
    with pytest.raises(ValueError):
        ident.parse_ref(text)


def test_content_matches_equality_and_excerpts():
    span = "def f(a, b):\n    return a + b"
    assert ident.content_matches(span, span)
    assert ident.is_full_span(span, span)
    assert ident.content_matches("def f(a, b):", span)
    assert not ident.is_full_span("def f(a, b):", span)
    assert not ident.content_matches("def f(a):", span)
    assert not ident.content_matches(None, span)
    assert not ident.content_matches("", span)
    assert ident.content_matches(span.replace("\n", "\r\n"), span)


def test_repo_ids_differ_per_root_and_fold_case_on_windows(tmp_path):
    a, b = tmp_path / "a", tmp_path / "b"
    a.mkdir()
    b.mkdir()
    assert ident.repo_id_for(a) != ident.repo_id_for(b)
    assert ident.repo_id_for(a) == ident.repo_id_for(str(a))
    if sys.platform == "win32":
        assert ident.repo_id_for(str(a).upper()) == ident.repo_id_for(str(a).lower())


def test_session_keys_are_scoped_to_repository_and_hide_the_tag():
    key_a = ident.session_key("repoA", "auth-fix")
    assert key_a != ident.session_key("repoB", "auth-fix")
    assert key_a != ident.session_key("repoA", "auth-fix-2")
    assert "auth" not in key_a


@pytest.mark.parametrize("tag", ["", " ", "-lead", "a b", "x" * 129, "emoji-😀", "a/b"])
def test_invalid_session_tags(tag):
    with pytest.raises(ValueError):
        ident.validate_session_tag(tag)


def test_valid_session_tags():
    assert ident.validate_session_tag(" auth-fix.2026:09_10 ") == "auth-fix.2026:09_10"


def test_randomised_edits_change_identity_iff_span_bytes_change():
    """Property: for any edit, the span hash is unchanged exactly when the span text is."""
    rng = random.Random(20260910)
    vocab = ["x = 1", "return x", "", "    pass", "def f():", "}", "# c", "y = 'é'"]
    for _ in range(400):
        lines = [rng.choice(vocab) for _ in range(rng.randint(3, 25))]
        start = rng.randint(1, len(lines))
        end = rng.randint(start, len(lines))
        before = ident.span_sha(lines, start, end)
        edited = list(lines)
        op = rng.choice(["replace", "insert", "delete", "noop"])
        pos = rng.randrange(len(edited))
        if op == "replace":
            edited[pos] = rng.choice(vocab)
        elif op == "insert":
            edited.insert(pos, rng.choice(vocab))
        elif op == "delete" and len(edited) > 1:
            del edited[pos]
        after = ident.span_sha(edited, start, end)
        same_text = ident.span_text(edited, start, end) == ident.span_text(lines, start, end)
        assert (after == before) == same_text
