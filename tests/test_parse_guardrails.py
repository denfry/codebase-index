"""Guardrail 2: parse failures and zero-symbol tree-sitter files must be visible, not silent."""

from __future__ import annotations

from pathlib import Path

from codebase_index.config import Config
from codebase_index.indexer import pipeline
from codebase_index.indexer.pipeline import build_index
from codebase_index.storage import repo
from codebase_index.storage.db import Database


def _write(p: Path, rel: str, body: str) -> None:
    path = p / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def test_multilang_build_extracts_symbols_without_failures(tmp_path):
    cfg = Config()
    cfg.root = str(tmp_path)
    _write(tmp_path, "Town.java", "class Town { Town greet() { return this; } }\n")
    _write(tmp_path, "main.go", "package m\nfunc Run() {}\n")
    _write(tmp_path, "config.yaml", "a: 1\nb: 2\n")  # Tier C: no symbols, not a failure

    db = Database(tmp_path / "index.sqlite").open()
    stats = build_index(cfg, db, root=Path(cfg.root))
    db.close()

    assert stats.symbols >= 3  # Town, greet, Run
    assert stats.parse_failed == 0
    assert stats.treesitter_zero_symbols == 0


def test_parse_failures_are_counted_not_swallowed(tmp_path, monkeypatch):
    cfg = Config()
    cfg.root = str(tmp_path)
    _write(tmp_path, "Town.java", "class Town {}\n")

    def boom(lang, text):
        raise RuntimeError("simulated tree-sitter explosion")

    monkeypatch.setattr(pipeline, "parse_file", boom)

    db = Database(tmp_path / "index.sqlite").open()
    stats = build_index(cfg, db, root=Path(cfg.root))
    db.close()

    assert stats.parse_failed == 1  # recorded, not silently passed
    assert stats.indexed == 1  # line-chunk fallback still indexed the file


def test_zero_symbol_treesitter_file_is_flagged(tmp_path):
    cfg = Config()
    cfg.root = str(tmp_path)
    # A valid Java file that defines no symbols (only a statement-free comment).
    _write(tmp_path, "Empty.java", "// just a comment, no declarations\n")

    db = Database(tmp_path / "index.sqlite").open()
    stats = build_index(cfg, db, root=Path(cfg.root))
    db.close()

    assert stats.treesitter_zero_symbols == 1


def test_doctor_warns_on_treesitter_lang_with_no_symbols(tmp_path):
    from codebase_index import scaffold
    from codebase_index.doctor import run_doctor

    cfg = Config()
    cfg.root = str(tmp_path)
    scaffold.merge_gitignore(tmp_path)

    # Build an index where many Java files exist but extraction is broken (0 symbols).
    db_path = tmp_path / scaffold.CACHE_REL / "index.sqlite"
    db_path.parent.mkdir(parents=True, exist_ok=True)
    db = Database(db_path).open()
    conn = db.conn
    for i in range(5):
        repo.upsert_file(
            conn,
            path=f"F{i}.java",
            lang="java",
            size_bytes=10,
            sha256="0" * 64,
            mtime_ns=0,
            git_status=None,
            parser="treesitter",
            indexed_at="t",
            is_generated=False,
        )
    conn.commit()
    db.close()

    findings = {f.id: f for f in run_doctor(tmp_path, cfg)}
    assert "symbol_extraction" in findings
    assert findings["symbol_extraction"].ok is False
    assert "java" in findings["symbol_extraction"].detail
