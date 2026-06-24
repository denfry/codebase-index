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
