from __future__ import annotations

from codebase_index.parsers.line_chunker import chunk_text


def _lines(n: int) -> str:
    return "\n".join(f"line{i}" for i in range(1, n + 1))


def test_short_file_is_one_chunk():
    chunks = chunk_text(_lines(10), window_lines=80, overlap_lines=10)
    assert len(chunks) == 1
    c = chunks[0]
    assert c.line_start == 1 and c.line_end == 10
    assert c.kind == "window"
    assert c.token_est >= 1


def test_windows_and_overlap():
    chunks = chunk_text(_lines(200), window_lines=80, overlap_lines=10)
    assert [c.line_start for c in chunks] == [1, 71, 141]
    assert chunks[0].line_end == 80
    assert chunks[1].line_start == 71
    assert chunks[-1].line_end == 200


def test_empty_file_yields_no_chunks():
    assert chunk_text("", window_lines=80, overlap_lines=10) == []
    assert chunk_text("   \n  \n", window_lines=80, overlap_lines=10) == []


def test_token_estimate_scales_with_size():
    small = chunk_text(_lines(5), window_lines=80, overlap_lines=10)[0]
    big = chunk_text(_lines(60), window_lines=80, overlap_lines=10)[0]
    assert big.token_est > small.token_est
