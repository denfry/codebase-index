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


MD_SAMPLE = (
    "# Title\n"
    "Intro line one.\n"
    "More prose that is not structural and should be dropped.\n"
    "Even more prose.\n"
    "## Section\n"
    "Section body line.\n"
    "Trailing prose to elide here too.\n"
)

JSON_SAMPLE = (
    '{\n'
    '  "name": "demo",\n'
    '  "description": "a long value that is mostly prose and can be elided away",\n'
    '  "nested": {\n'
    '    "key": "value"\n'
    '  }\n'
    '}\n'
)


def test_markdown_keeps_headings_and_first_section_line():
    r = compact(MD_SAMPLE, path="README.md", line_start=1,
                ctx_lines=0, query_terms=[], min_reduction=0.25)
    assert r.skeletonized is True
    assert "# Title" in r.text
    assert "## Section" in r.text
    assert "Intro line one." in r.text          # first line after heading kept
    assert "Even more prose." not in r.text


def test_structured_keeps_key_lines():
    r = compact(JSON_SAMPLE, path="pkg.json", line_start=1,
                ctx_lines=0, query_terms=["nested"], min_reduction=0.10)
    assert '"name": "demo"' in r.text
    assert '"nested"' in r.text                 # focus term line kept


from codebase_index.retrieval.skeleton import make_compactor  # noqa: E402
from codebase_index.retrieval.types import Candidate, Intent  # noqa: E402


def _cand(content):
    return Candidate(path="store.py", line_start=1, line_end=10,
                     source="fts", score=1.0, content=content, token_est=99)


def test_make_compactor_disabled_returns_none():
    assert make_compactor(intent=Intent.KEYWORD, query="x",
                           enabled=False, min_reduction=0.25) is None


def test_make_compactor_shape_intent_uses_zero_context():
    # min_reduction=0.0 isolates the ctx policy from the savings guard: a shape
    # intent uses ctx 0, so the matched line is kept but its neighbour is not.
    comp = make_compactor(intent=Intent.ARCHITECTURE, query="blocklist",
                          enabled=True, min_reduction=0.0)
    r = comp(_cand(PY_SAMPLE))
    assert r.skeletonized is True
    assert "self.blocklist.add(tok)" in r.text       # matched line kept
    assert "log('revoked')" not in r.text             # neighbour elided (ctx 0)


def test_make_compactor_locate_intent_keeps_matched_line_and_context():
    # A locate intent uses ctx 2, so the matched line AND its neighbour stay.
    comp = make_compactor(intent=Intent.LOCATE_IMPL, query="blocklist",
                          enabled=True, min_reduction=0.0)
    r = comp(_cand(PY_SAMPLE))
    assert "self.blocklist.add(tok)" in r.text        # matched line kept
    assert "log('revoked')" in r.text                  # neighbour kept (ctx 2)
    assert "decoded = decode(tok)" not in r.text       # unrelated body elided
