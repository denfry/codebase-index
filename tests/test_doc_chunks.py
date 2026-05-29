"""Tests for doc_chunks extractor."""

from codebase_index.indexer.doc_chunks import extract_doc_chunks


def test_extract_md_headings():
    text = "# Main Title\n\nSome content\n\n## Section One\n\nMore content\n\n## Section Two\n"
    chunks = extract_doc_chunks(text, "README.md", "markdown")
    doc_chunks = [c for c in chunks if c.kind == "doc"]
    assert len(doc_chunks) >= 3
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
    text = "x = 1\ny = 2\nz = x + y\n"
    chunks = extract_doc_chunks(text, "plain.py", "python")
    doc_chunks = [c for c in chunks if c.kind == "doc"]
    assert len(doc_chunks) == 0
