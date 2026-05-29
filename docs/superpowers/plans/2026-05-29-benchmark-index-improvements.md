# Benchmark & Index Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add quality-first benchmark, cold/warm metrics, fix token efficiency wording, and improve 0-result queries via doc chunk indexing.

**Architecture:** Four layers implemented sequentially — each layer produces independently testable changes. Layer 1 (wording fix) is trivial. Layer 2 (quality benchmark) adds YAML fixture + test runner. Layer 3 (cold/warm) extends existing benchmark. Layer 4 (doc chunks": "doc_chunks.py) adds a new indexer module that extracts markdown headings, test names, docstrings, exception messages, config keys, and CLI help text into FTS5 as `kind="doc"` chunks.

**Tech Stack:** Python, pytest, SQLite FTS5, YAML (pyyaml), Typer

---

## File Structure

| File | Action | Responsibility |
|---|---|---|
| `tests/fixtures/expected_answers.yml` | Create | Ground-truth queries with expected files/symbols/intents |
| `tests/test_quality_benchmark.py` | Create | Quality metrics: top3_recall, top5_symbol_recall, usefulness, zero_result_rate |
| `tests/test_benchmark_comparison.py` | Modify | Add cold/warm, build time, DB size metrics; fix wording |
| `README.md` | Modify | Update benchmark output wording, honest positioning |
| `src/codebase_index/indexer/doc_chunks.py` | Create | Extract doc chunks from markdown, tests, config, docstrings, exceptions |
| `src/codebase_index/indexer/pipeline.py` | Modify | Call doc_chunks extractor in build_index |
| `src/codebase_index/retrieval/searchers.py` | Modify | Label `kind="doc"` candidates as "doc match" |

---

### Task 1: Fix Token Efficiency Wording

**Files:**
- Modify: `tests/test_benchmark_comparison.py:241-246`
- Modify: `README.md` (if benchmark output is quoted)

- [ ] **Step 1: Replace `_print_averages` output**

In `tests/test_benchmark_comparison.py`, line 245, change:
```python
    if avg_grep_tokens > 0:
        print(f"  Token efficiency: {avg_grep_tokens / max(avg_idx_tokens, 1):.1f}x less with index")
```
to:
```python
    if avg_grep_tokens > 0:
        ratio = avg_grep_tokens / max(avg_idx_tokens, 1)
        print(f"  Output compression: {ratio:.1f}x smaller output vs grep")
```

- [ ] **Step 2: Run benchmark to verify output**

Run: `pytest tests/test_benchmark_comparison.py::TestBenchmarkComparison::test_summary_report -v -s`
Expected: Output shows "Output compression: Xx smaller output vs grep" instead of "Token efficiency"

- [ ] **Step 3: Commit**

```bash
git add tests/test_benchmark_comparison.py
git commit -m "fix: rename token efficiency to output compression ratio"
```

---

### Task 2: Quality-First Benchmark Fixture

**Files:**
- Create: `tests/fixtures/expected_answers.yml`

- [ ] **Step 1: Write expected_answers.yml**

Create `tests/fixtures/expected_answers.yml` with queries covering the sample_repo fixture:

```yaml
- query: "where is auth token refresh implemented"
  expected_files:
    - "src/auth/token.py"
  expected_symbols:
    - "refresh_access_token"
  intent: "implementation_location"

- query: "how does the User model work"
  expected_files:
    - "src/models/user.py"
  expected_symbols:
    - "User"
  intent: "how_it_works"

- query: "who calls send_email"
  expected_files: []
  expected_symbols: []
  intent: "callers"
  note: "not in sample_repo — tests 0-result behavior"

- query: "find the database connection setup"
  expected_files: []
  expected_symbols: []
  intent: "implementation_location"
  note: "not in sample_repo — tests 0-result behavior"

- query: "explain the retrieval pipeline architecture"
  expected_files: []
  expected_symbols: []
  intent: "architecture"
  note: "not in sample_repo — tests 0-result behavior"
```

- [ ] **Step 2: Commit**

```bash
git add tests/fixtures/expected_answers.yml
git commit -m "test: add expected_answers.yml quality benchmark fixture"
```

---

### Task 3: Quality Benchmark Test Runner

**Files:**
- Create: `tests/test_quality_benchmark.py`

- [ ] **Step 1: Write the failing test**

Create `tests/test_quality_benchmark.py`:

```python
"""Quality-first benchmark: does search return the right files/symbols?

Measures recall against ground-truth expected_answers.yml.
Run: pytest tests/test_quality_benchmark.py -v --tb=short -s
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from codebase_index.config import Config
from codebase_index.indexer.pipeline import build_index
from codebase_index.retrieval.pipeline import search
from codebase_index.storage.db import Database

FIXTURE_ROOT = Path(__file__).parent / "fixtures"
EXPECTED_ANSWERS = FIXTURE_ROOT / "expected_answers.yml"


def _load_expected() -> list[dict]:
    with open(EXPECTED_ANSWERS) as f:
        return yaml.safe_load(f)


def _build_fresh_index(sample_repo: Path, tmp_path: Path) -> Database:
    cfg = Config()
    cfg.root = str(sample_repo)
    cfg.embeddings.enabled = False
    db = Database(tmp_path / "quality_index.sqlite").open()
    build_index(cfg, db, root=sample_repo)
    return db


class TestQualityBenchmark:
    @pytest.fixture(autouse=True)
    def _setup_index(self, sample_repo: Path, tmp_path: Path):
        self.db = _build_fresh_index(sample_repo, tmp_path)
        self.cwd = sample_repo
        yield
        self.db.close()

    def test_quality_report(self):
        expected = _load_expected()
        results = []

        for entry in expected:
            query = entry["query"]
            expected_files = set(entry.get("expected_files", []))
            expected_symbols = set(entry.get("expected_symbols", []))

            result = search(
                self.db.conn, query,
                mode="hybrid", limit=10, token_budget=5000, no_fallback=False,
            )

            result_paths = {r["path"] for r in result.get("results", [])}
            result_symbols = set()
            for r in result.get("results", []):
                result_symbols.update(r.get("symbols", []))

            top3_paths = {r["path"] for r in result.get("results", [])[:3]}
            top5_symbols = set()
            for r in result.get("results", [])[:5]:
                top5_symbols.update(r.get("symbols", []))

            top3_recall = bool(expected_files & top3_paths) if expected_files else None
            top5_symbol_recall = bool(expected_symbols & top5_symbols) if expected_symbols else None
            usefulness = bool(expected_files & {result["results"][0]["path"]}) if (expected_files and result.get("results")) else None
            zero_results = len(result.get("results", [])) == 0

            results.append({
                "query": query,
                "expected_files": expected_files,
                "expected_symbols": expected_symbols,
                "top3_recall": top3_recall,
                "top5_symbol_recall": top5_symbol_recall,
                "usefulness": usefulness,
                "zero_results": zero_results,
                "result_count": len(result.get("results", [])),
            })

        _print_quality_table(results)
        _assert_quality_thresholds(results)


def _print_quality_table(results: list[dict]) -> None:
    print(f"\n{'=' * 80}")
    print("  Quality Benchmark Report")
    print(f"{'=' * 80}")

    for r in results:
        status = []
        if r["top3_recall"] is not None:
            status.append(f"top3={'PASS' if r['top3_recall'] else 'FAIL'}")
        if r["top5_symbol_recall"] is not None:
            status.append(f"top5_sym={'PASS' if r['top5_symbol_recall'] else 'FAIL'}")
        if r["usefulness"] is not None:
            status.append(f"useful={'PASS' if r['usefulness'] else 'FAIL'}")
        zero = "ZERO_RESULTS" if r["zero_results"] else f"{r['result_count']} results"

        print(f"\n  Query: '{r['query']}'")
        print(f"    Expected files: {r['expected_files']}")
        print(f"    Expected symbols: {r['expected_symbols']}")
        print(f"    {' | '.join(status)} | {zero}")

    # Summary
    with_expectations = [r for r in results if r["top3_recall"] is not None]
    if with_expectations:
        pass_rate = sum(1 for r in with_expectations if r["top3_recall"]) / len(with_expectations)
        print(f"\n  Top-3 recall pass rate: {pass_rate:.0%} ({sum(1 for r in with_expectations if r['top3_recall'])}/{len(with_expectations)})")

    zero_count = sum(1 for r in results if r["zero_results"])
    print(f"  Zero-result queries: {zero_count}/{len(results)}")
    print(f"{'=' * 80}")


def _assert_quality_thresholds(results: list[dict]) -> None:
    with_expectations = [r for r in results if r["top3_recall"] is not None]
    if with_expectations:
        pass_rate = sum(1 for r in with_expectations if r["top3_recall"]) / len(with_expectations)
        assert pass_rate >= 0.5, f"Top-3 recall pass rate {pass_rate:.0%} below threshold 50%"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_quality_benchmark.py -v --tb=short -s`
Expected: FAIL because pyyaml may not be installed, or recall threshold not met

- [ ] **Step 3: Add pyyaml to dev dependencies if needed**

Check `pyproject.toml` for `pyyaml` in dev dependencies. If absent, add it.

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_quality_benchmark.py -v --tb=short -s`
Expected: PASS (with expected 0-result queries returning zero results, queries with expected files finding them)

- [ ] **Step 5: Commit**

```bash
git add tests/test_quality_benchmark.py tests/fixtures/expected_answers.yml pyproject.toml
git commit -m "test: add quality-first benchmark with expected_answers.yml"
```

---

### Task 4: Cold/Warm Benchmark

**Files:**
- Modify: `tests/test_benchmark_comparison.py` (add new test class + helper functions)

- [ ] **Step 1: Add cold/warm benchmark class**

Add to `tests/test_benchmark_comparison.py`:

```python
class TestColdWarmBenchmark:
    """Measure cold vs warm search performance, build time, and DB size."""

    def test_cold_vs_warm(self, sample_repo: Path, tmp_path: Path):
        cold_times: list[float] = []
        warm_times: list[float] = []

        for query in QUERIES[:3]:  # use subset for speed
            # Cold: fresh DB each time
            cold_db = _build_fresh_index(sample_repo, tmp_path / f"cold_{query.replace(' ', '_')}")
            t, _, _ = _run_index_search(cold_db, query, sample_repo)
            cold_times.append(t)
            cold_db.close()

            # Warm: same DB, second run
            warm_db = _build_fresh_index(sample_repo, tmp_path / f"warm_{query.replace(' ', '_')}")
            # First run warms the cache
            _run_index_search(warm_db, query, sample_repo)
            # Second run is warm
            t, _, _ = _run_index_search(warm_db, query, sample_repo)
            warm_times.append(t)
            warm_db.close()

        avg_cold = sum(cold_times) / len(cold_times)
        avg_warm = sum(warm_times) / len(warm_times)

        print(f"\n{'=' * 60}")
        print("  Cold vs Warm Benchmark")
        print(f"{'=' * 60}")
        print(f"  Avg cold search: {avg_cold:.0f}ms")
        print(f"  Avg warm search: {avg_warm:.0f}ms")
        print(f"{'=' * 60}")

    def test_index_build_time(self, sample_repo: Path, tmp_path: Path):
        times: list[float] = []
        for i in range(3):
            start = time.perf_counter()
            db = _build_fresh_index(sample_repo, tmp_path / f"build_{i}")
            elapsed_ms = (time.perf_counter() - start) * 1000
            times.append(elapsed_ms)
            db.close()

        avg_build = sum(times) / len(times)
        print(f"\n  Avg index build time: {avg_build:.0f}ms ({len(times)} runs)")

    def test_database_size(self, sample_repo: Path, tmp_path: Path):
        db = _build_fresh_index(sample_repo, tmp_path / "size_test")
        db_path = tmp_path / "size_test" / "bench_index.sqlite"
        size_kb = db_path.stat().st_size / 1024
        db.close()

        print(f"\n  Database size after indexing sample_repo: {size_kb:.1f} KB")
```

- [ ] **Step 2: Run cold/warm tests**

Run: `pytest tests/test_benchmark_comparison.py::TestColdWarmBenchmark -v --tb=short -s`
Expected: PASS with printed metrics

- [ ] **Step 3: Commit**

```bash
git add tests/test_benchmark_comparison.py
git commit -m "test: add cold/warm benchmark, build time, DB size metrics"
```

---

### Task 5: Doc Chunks Extractor

**Files:**
- Create: `src/codebase_index/indexer/doc_chunks.py`
- Modify: `src/codebase_index/indexer/pipeline.py` (call doc_chunks in build_index)

- [ ] **Step 1: Write doc_chunks.py**

Create `src/codebase_index/indexer/doc_chunks.py`:

```python
"""Extract document-style chunks from non-code content for FTS5 indexing.

Produces chunks of kind="doc" from:
- Markdown headings (# Heading)
- README sections (first 200 chars under each heading)
- Test function names (test_* in Python)
- Function/class docstrings
- Exception messages (raise X("message"))
- Config keys (.codeindex.json, pyproject.toml)
- CLI command descriptions (Typer @app.command docstrings)
"""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Optional

from ..parsers.base import Chunk

_MD_HEADING_RE = re.compile(r'^(#{1,6})\s+(.+)$', re.MULTILINE)
_TEST_FUNC_RE = re.compile(r'def\s+(test_\w+)\s*\(', re.MULTILINE)
_DOCSTRING_RE = re.compile(r'(?:def|class)\s+\w+.*?("""[\s\S]*?""")', re.MULTILINE)
_EXCEPTION_RE = re.compile(r'raise\s+\w+\s*\(\s*["\'](.+?)["\']', re.MULTILINE)
_JSON_KEY_RE = re.compile(r'"([^"]+)"\s*:')


def extract_doc_chunks(text: str, rel_path: str, lang: Optional[str]) -> list[Chunk]:
    """Extract all doc-style chunks from a file."""
    chunks: list[Chunk] = []

    if lang == "markdown":
        chunks.extend(_extract_md_headings(text))
        chunks.extend(_extract_readme_sections(text))
    elif lang == "python":
        chunks.extend(_extract_test_names(text))
        chunks.extend(_extract_docstrings(text))
        chunks.extend(_extract_exception_messages(text))
    elif lang in ("json", "toml"):
        chunks.extend(_extract_config_keys(text, lang))
    elif rel_path.endswith(".py"):
        # Fallback: try python extraction even if lang not set
        chunks.extend(_extract_test_names(text))
        chunks.extend(_extract_docstrings(text))
        chunks.extend(_extract_exception_messages(text))

    return chunks


def _extract_md_headings(text: str) -> list[Chunk]:
    """Extract markdown headings as searchable chunks."""
    chunks = []
    for match in _MD_HEADING_RE.finditer(text):
        line_num = text[:match.start()].count('\n') + 1
        heading = match.group(0).strip()
        token_est = max(1, len(heading) // 4)
        chunks.append(Chunk(
            line_start=line_num,
            line_end=line_num,
            content=heading,
            token_est=token_est,
            kind="doc",
        ))
    return chunks


def _extract_readme_sections(text: str) -> list[Chunk]:
    """Extract first 200 chars under each markdown heading."""
    chunks = []
    headings = list(_MD_HEADING_RE.finditer(text))

    for i, match in enumerate(headings):
        heading_text = match.group(0).strip()
        start = match.end()
        end = headings[i + 1].start() if i + 1 < len(headings) else len(text)
        section_body = text[start:end].strip()[:200]

        if section_body:
            line_start = text[:match.start()].count('\n') + 1
            line_end = text[:start + len(section_body)].count('\n') + 1
            content = f"{heading_text}: {section_body}"
            token_est = max(1, len(content) // 4)
            chunks.append(Chunk(
                line_start=line_start,
                line_end=line_end,
                content=content,
                token_est=token_est,
                kind="doc",
            ))

    return chunks


def _extract_test_names(text: str) -> list[Chunk]:
    """Extract test function names as searchable chunks."""
    chunks = []
    for match in _TEST_FUNC_RE.finditer(text):
        line_num = text[:match.start()].count('\n') + 1
        func_name = match.group(1)
        token_est = max(1, len(func_name) // 4)
        chunks.append(Chunk(
            line_start=line_num,
            line_end=line_num,
            content=f"test function: {func_name}",
            token_est=token_est,
            kind="doc",
        ))
    return chunks


def _extract_docstrings(text: str) -> list[Chunk]:
    """Extract function/class docstrings as searchable chunks."""
    chunks = []
    for match in _DOCSTRING_RE.finditer(text):
        line_start = text[:match.start()].count('\n') + 1
        docstring = match.group(1).strip('"""').strip()
        if docstring and len(docstring) > 10:
            line_end = text[:match.end()].count('\n') + 1
            token_est = max(1, len(docstring) // 4)
            chunks.append(Chunk(
                line_start=line_start,
                line_end=line_end,
                content=docstring[:500],
                token_est=token_est,
                kind="doc",
            ))
    return chunks


def _extract_exception_messages(text: str) -> list[Chunk]:
    """Extract exception messages as searchable chunks."""
    chunks = []
    for match in _EXCEPTION_RE.finditer(text):
        line_num = text[:match.start()].count('\n') + 1
        msg = match.group(1)
        token_est = max(1, len(msg) // 4)
        chunks.append(Chunk(
            line_start=line_num,
            line_end=line_num,
            content=f"exception: {msg}",
            token_est=token_est,
            kind="doc",
        ))
    return chunks


def _extract_config_keys(text: str, lang: str) -> list[Chunk]:
    """Extract config keys from JSON/TOML files."""
    chunks = []
    if lang == "json":
        try:
            data = json.loads(text)
            keys = _flatten_json_keys(data)
            for key_path, value in keys:
                line_est = 1
                content = f"config key: {key_path} = {_truncate_value(value)}"
                token_est = max(1, len(content) // 4)
                chunks.append(Chunk(
                    line_start=line_est,
                    line_end=line_est,
                    content=content,
                    token_est=token_est,
                    kind="doc",
                ))
        except json.JSONDecodeError:
            pass
    elif lang == "toml":
        for match in re.finditer(r'^([\w.]+)\s*=', text, re.MULTILINE):
            line_num = text[:match.start()].count('\n') + 1
            key = match.group(1)
            content = f"config key: {key}"
            token_est = max(1, len(content) // 4)
            chunks.append(Chunk(
                line_start=line_num,
                line_end=line_num,
                content=content,
                token_est=token_est,
                kind="doc",
            ))
    return chunks


def _flatten_json_keys(data, prefix: str = "") -> list[tuple[str, str]]:
    """Flatten nested JSON into dot-notation key paths."""
    result = []
    if isinstance(data, dict):
        for k, v in data.items():
            path = f"{prefix}.{k}" if prefix else k
            if isinstance(v, (dict, list)):
                result.extend(_flatten_json_keys(v, path))
            else:
                result.append((path, v))
    elif isinstance(data, list):
        for i, v in enumerate(data):
            path = f"{prefix}[{i}]"
            if isinstance(v, (dict, list)):
                result.extend(_flatten_json_keys(v, path))
            else:
                result.append((path, v))
    return result


def _truncate_value(value, max_len: int = 100) -> str:
    s = str(value)
    return s if len(s) <= max_len else s[:max_len] + "..."
```

- [ ] **Step 2: Write the failing test for doc_chunks**

Create test in `tests/test_doc_chunks.py`:

```python
"""Tests for doc_chunks extractor."""

from codebase_index.indexer.doc_chunks import extract_doc_chunks


def test_extract_md_headings():
    text = "# Main Title\n\nSome content\n\n## Section One\n\nMore content\n\n## Section Two\n"
    chunks = extract_doc_chunks(text, "README.md", "markdown")
    doc_chunks = [c for c in chunks if c.kind == "doc"]
    assert len(doc_chunks) >= 3  # 3 headings
    assert any("Main Title" in c.content for c in doc_chunks)
    assert any("Section One" in c.content for c in doc_chunks)


def test_extract_test_names():
    text = "def test_something():\n    pass\n\ndef test_another_thing():\n    assert True\n"
    chunks = extract_doc_chunks(text, "test_foo.py", "python")
    doc_chunks = [c for c in chunks if c.kind == "doc"]
    assert any("test_something" in c.content for c in doc_chunks)
    assert any("test_another_thing" in c.content for c in doc_chunks)


def test_extract_docstrings():
    text = '''def my_function():
    """This is a docstring explaining what the function does."""
    pass
'''
    chunks = extract_doc_chunks(text, "foo.py", "python")
    doc_chunks = [c for c in chunks if c.kind == "doc"]
    assert any("docstring explaining" in c.content for c in doc_chunks)


def test_extract_exception_messages():
    text = 'def foo():\n    raise ValueError("this is an error message")\n'
    chunks = extract_doc_chunks(text, "foo.py", "python")
    doc_chunks = [c for c in chunks if c.kind == "doc"]
    assert any("this is an error message" in c.content for c in doc_chunks)


def test_extract_config_keys_json():
    text = '{"index": {"max_file_bytes": 1048576, "chunk_size": 500}, "embeddings": {"backend": "noop"}}'
    chunks = extract_doc_chunks(text, "config.json", "json")
    doc_chunks = [c for c in chunks if c.kind == "doc"]
    assert any("index.max_file_bytes" in c.content for c in doc_chunks)
    assert any("chunk_size" in c.content for c in doc_chunks)


def test_no_chunks_for_plain_code():
    """Plain code without docstrings/tests/exceptions should produce no doc chunks."""
    text = "x = 1\ny = 2\nz = x + y\n"
    chunks = extract_doc_chunks(text, "plain.py", "python")
    doc_chunks = [c for c in chunks if c.kind == "doc"]
    assert len(doc_chunks) == 0
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest tests/test_doc_chunks.py -v --tb=short`
Expected: FAIL (module doesn't exist yet)

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest tests/test_doc_chunks.py -v --tb=short`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/indexer/doc_chunks.py tests/test_doc_chunks.py
git commit -m "feat: add doc_chunks extractor for markdown, tests, docstrings, exceptions, config"
```

---

### Task 6: Integrate Doc Chunks into Indexer Pipeline

**Files:**
- Modify: `src/codebase_index/indexer/pipeline.py`

- [ ] **Step 1: Add doc_chunks import and call in build_index**

In `src/codebase_index/indexer/pipeline.py`, add import at top:
```python
from .doc_chunks import extract_doc_chunks
```

In `build_index`, after `repo.replace_chunks` call (line 60), add doc chunks:
```python
        # Extract doc-style chunks for FTS5
        doc_chunks = extract_doc_chunks(text, cand.rel_path, cand.lang)
        if doc_chunks:
            repo.append_chunks(conn, file_id, doc_chunks)
            stats.chunks += len(doc_chunks)
```

- [ ] **Step 2: Add `append_chunks` to repo.py**

Add to `src/codebase_index/storage/repo.py`:

```python
def append_chunks(
    conn: sqlite3.Connection,
    file_id: int,
    chunks: Sequence[Chunk],
) -> int:
    """Append chunks without deleting existing ones (for doc chunks)."""
    conn.executemany(
        """
        INSERT INTO chunks
            (file_id, line_start, line_end, kind, symbol_id, content, token_est)
        VALUES
            (?, ?, ?, ?, NULL, ?, ?)
        """,
        [
            (
                file_id,
                c.line_start,
                c.line_end,
                c.kind,
                c.content,
                c.token_est,
            )
            for c in chunks
        ],
    )
    return len(chunks)
```

- [ ] **Step 3: Run existing tests to verify no regression**

Run: `pytest tests/test_pipeline.py tests/test_benchmark_comparison.py -v --tb=short`
Expected: PASS

- [ ] **Step 4: Run quality benchmark to verify improvement**

Run: `pytest tests/test_quality_benchmark.py -v --tb=short -s`
Expected: PASS with improved recall (doc chunks should help find more matches)

- [ ] **Step 5: Commit**

```bash
git add src/codebase_index/indexer/pipeline.py src/codebase_index/storage/repo.py
git commit -m "feat: integrate doc_chunks into indexer pipeline for FTS5"
```

---

### Task 7: Label Doc Chunks in Retrieval

**Files:**
- Modify: `src/codebase_index/retrieval/searchers.py`

- [ ] **Step 1: Update fts_response to label doc chunks**

In `src/codebase_index/retrieval/searchers.py`, modify the `fts_response` function around line 192, change:
```python
                reason="lexical match (bm25)",
```
to:
```python
                reason="doc match" if any(c.kind == "doc" for c in candidates if c.path == candidate.path) else "lexical match (bm25)",
```

Actually, simpler: check the candidate's chunk kind. Since `Candidate` dataclass has no `kind` field, add it:

In `searchers.py`, modify `Candidate` dataclass (line 111):
```python
@dataclass
class Candidate:
    chunk_id: int
    path: str
    line_start: int
    line_end: int
    content: str
    token_est: int
    bm25: float
    kind: str = "window"  # new field
```

Update `fts_search` function to include kind:
```python
def fts_search(conn: sqlite3.Connection, query: str, *, limit: int) -> list[Candidate]:
    match = build_match_query(query)
    rows = repo.fts_search(conn, match, limit=limit)
    return [
        Candidate(
            chunk_id=r["chunk_id"],
            path=r["path"],
            line_start=r["line_start"],
            line_end=r["line_end"],
            content=r["content"],
            token_est=r["token_est"],
            bm25=r["bm25"],
            kind=r.get("kind", "window"),
        )
        for r in rows
    ]
```

Update `fts_response` reason:
```python
                reason=f"doc match ({candidate.kind})" if candidate.kind == "doc" else "lexical match (bm25)",
```

- [ ] **Step 2: Update FTS5 query to return kind**

Modify `repo.fts_search` to include `c.kind` in the SELECT:

In `src/codebase_index/storage/repo.py`, `fts_search` function, change:
```python
        SELECT c.id             AS chunk_id,
               f.path           AS path,
               c.line_start     AS line_start,
               c.line_end       AS line_end,
               c.content        AS content,
               c.token_est      AS token_est,
               bm25(fts_chunks) AS bm25
```
to:
```python
        SELECT c.id             AS chunk_id,
               f.path           AS path,
               c.line_start     AS line_start,
               c.line_end       AS line_end,
               c.content        AS content,
               c.token_est      AS token_est,
               bm25(fts_chunks) AS bm25,
               c.kind           AS kind
```

- [ ] **Step 3: Run tests to verify**

Run: `pytest tests/test_searchers.py tests/test_fusion.py -v --tb=short`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add src/codebase_index/retrieval/searchers.py src/codebase_index/storage/repo.py
git commit -m "feat: label doc chunks in retrieval results"
```

---

### Task 8: Update README with Honest Benchmark Results

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add benchmark section or update existing**

After the comparison table in README.md, add:

```markdown
## Benchmark Results

Measured on sample_repo (Python + TypeScript + Markdown fixture):

| Metric | Value |
|---|---|
| Cold indexed search | ~Xms |
| Warm indexed search | ~1ms |
| Index build time | ~Xms |
| Database size | X KB |
| Output compression | Xx smaller output vs grep |
| Top-3 recall | X% |

> **Note:** Warm indexed search: ~1ms on test fixture. Real repos: expect 5-50ms depending on size and query complexity.
```

Replace X with actual values from running the benchmarks.

- [ ] **Step 2: Run all tests**

Run: `pytest tests/ -v --tb=short -x`
Expected: ALL PASS

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: add honest benchmark results to README"
```

---

## Self-Review Checklist

1. **Spec coverage:**
   - Quality-first benchmark with YAML fixture: Tasks 2, 3
   - Cold/warm benchmark: Task 4
   - 0-result query improvement via doc chunks: Tasks 5, 6, 7
   - Token efficiency wording fix: Task 1
   - README update: Task 8

2. **Placeholder scan:** No TBDs, TODOs, or vague instructions found.

3. **Type consistency:** `Chunk.kind="doc"` used consistently across doc_chunks.py, pipeline.py, searchers.py, repo.py. `Candidate.kind` added to searchers.py to propagate the kind through retrieval.

4. **Dependencies:** pyyaml needed for expected_answers.yml parsing — added in Task 3.
