from codebase_index.retrieval.skeleton import render_skeleton


def test_render_collapses_elided_run_with_absolute_lines():
    content = "def f():\n    a = 1\n    b = 2\n    return a + b"
    keep = [True, False, False, False]
    text, elided = render_skeleton(content, keep, line_start=10)
    assert text == "def f():\n... 3 lines elided (read 11-13)"
    assert elided == 3


def test_render_all_keep_is_unchanged():
    content = "a\nb\nc"
    text, elided = render_skeleton(content, [True, True, True], line_start=1)
    assert text == content
    assert elided == 0


def test_render_merges_adjacent_runs_but_keeps_separated_ones():
    content = "h1\nx\nh2\ny\nz"
    keep = [True, False, True, False, False]
    text, elided = render_skeleton(content, keep, line_start=1)
    assert text == "h1\n... 1 lines elided (read 2-2)\nh2\n... 2 lines elided (read 4-5)"
    assert elided == 3


from codebase_index.retrieval.skeleton import Compacted, compact  # noqa: E402


PY_SAMPLE = (
    "import os\n"
    "\n"
    "class Store:\n"
    "    def refresh(self, tok):\n"
    "        decoded = decode(tok)\n"
    "        validate(decoded)\n"
    "        return decoded\n"
    "    def revoke(self, tok):\n"
    "        self.blocklist.add(tok)\n"
    "        log('revoked')\n"
)


def estimate_tokens_helper(text):
    from codebase_index.parsers.line_chunker import estimate_tokens
    return estimate_tokens(text)


def test_code_skeleton_keeps_signatures_and_elides_bodies():
    r = compact(PY_SAMPLE, path="store.py", line_start=1,
                ctx_lines=0, query_terms=[], min_reduction=0.25)
    assert r.skeletonized is True
    assert "def refresh(self, tok):" in r.text
    assert "def revoke(self, tok):" in r.text
    assert "class Store:" in r.text
    assert "import os" in r.text
    assert "decoded = decode(tok)" not in r.text   # body elided
    assert r.elided_lines >= 3
    assert r.token_est < estimate_tokens_helper(PY_SAMPLE)


def test_focus_keeps_matched_body_line_and_context():
    # Low threshold isolates the focus behaviour: on this tiny sample only the
    # unrelated `refresh` body is elided (the matched `revoke` body is kept by
    # focus), a sub-25% win the guard would otherwise reject. The 25% guard
    # itself is covered by test_savings_guard_returns_raw_when_not_enough_win.
    r = compact(PY_SAMPLE, path="store.py", line_start=1,
                ctx_lines=1, query_terms=["blocklist"], min_reduction=0.10)
    assert "self.blocklist.add(tok)" in r.text       # matched line preserved
    assert "decoded = decode(tok)" not in r.text      # unrelated body still elided


def test_unparseable_or_unknown_type_falls_back_to_raw():
    blob = "%%% not code %%%\n@@@@@\n!!!!!"
    r = compact(blob, path="notes.bin", line_start=1,
                ctx_lines=0, query_terms=[], min_reduction=0.25)
    assert r.skeletonized is False
    assert r.text == blob
    assert r.elided_lines == 0


def test_savings_guard_returns_raw_when_not_enough_win():
    tiny = "def f(): pass"     # one line, nothing to elide
    r = compact(tiny, path="f.py", line_start=1,
                ctx_lines=0, query_terms=[], min_reduction=0.25)
    assert r.skeletonized is False
    assert r.text == tiny


def test_compact_is_deterministic():
    a = compact(PY_SAMPLE, path="store.py", line_start=1,
                ctx_lines=0, query_terms=[], min_reduction=0.25)
    b = compact(PY_SAMPLE, path="store.py", line_start=1,
                ctx_lines=0, query_terms=[], min_reduction=0.25)
    assert (a.text, a.token_est, a.elided_lines, a.skeletonized) == \
           (b.text, b.token_est, b.elided_lines, b.skeletonized)
