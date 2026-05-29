"""Drive a build: discovery -> hash -> upsert files -> prune deleted -> meta."""

from __future__ import annotations

import hashlib
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..config import Config
from ..discovery.walker import walk
from ..parsers import languages
from ..parsers.base import ParseResult
from ..parsers.line_chunker import chunk_text
from ..parsers.treesitter import parse_file
from ..storage import repo
from ..storage.db import Database


@dataclass
class BuildStats:
    indexed: int = 0
    deleted: int = 0
    total_bytes: int = 0
    chunks: int = 0
    symbols: int = 0
    edges: int = 0


def build_index(config: Config, db: Database, root: Optional[Path] = None) -> BuildStats:
    root = Path(root or config.root).resolve()
    conn = db.conn
    now = _utc_now_iso()

    stats = BuildStats()
    seen: set[str] = set()

    for cand in walk(root, config):
        file_id = repo.upsert_file(
            conn,
            path=cand.rel_path,
            lang=cand.lang,
            size_bytes=cand.size_bytes,
            sha256=_sha256_file(cand.path),
            mtime_ns=cand.path.stat().st_mtime_ns,
            git_status=None,
            parser=cand.parser,
            indexed_at=now,
            is_generated=cand.is_generated,
        )
        text = _read_text(cand.path)
        parse_result = _parse(cand.lang, text, config)
        symbol_ids = repo.replace_symbols(conn, file_id, parse_result.symbols)
        repo.replace_chunks(conn, file_id, parse_result.chunks, symbol_ids=symbol_ids)
        edge_rows = _resolve_edges(parse_result, symbol_ids, file_id)
        repo.replace_edges(conn, file_id, edge_rows)
        stats.chunks += len(parse_result.chunks)
        stats.symbols += len(parse_result.symbols)
        stats.edges += len(edge_rows)
        seen.add(cand.rel_path)
        stats.indexed += 1
        stats.total_bytes += cand.size_bytes

    stats.deleted = repo.delete_files(conn, repo.all_paths(conn) - seen)
    repo.set_meta(conn, "built_at", now)
    repo.set_meta(conn, "config_hash", config.config_hash())
    if head := _git_head(root):
        repo.set_meta(conn, "head_commit", head)
    conn.commit()
    return stats


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(65536), b""):
            h.update(block)
    return h.hexdigest()


def _read_text(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        return ""


def _parse(lang: Optional[str], text: str, config: Config) -> ParseResult:
    if lang and languages.is_supported(lang):
        try:
            return parse_file(lang, text)
        except Exception:
            pass
    chunks = chunk_text(
        text,
        window_lines=config.chunk.window_lines,
        overlap_lines=config.chunk.overlap_lines,
    )
    return ParseResult(chunks=chunks, symbols=[], edges=[])


def _resolve_edges(
    parse_result: ParseResult, symbol_ids: list[int], file_id: int
) -> list[dict]:
    name_to_id = {
        symbol.name: symbol_ids[idx]
        for idx, symbol in enumerate(parse_result.symbols)
    }
    rows: list[dict] = []
    for edge in parse_result.edges:
        src_id = (
            symbol_ids[edge.src_symbol_index]
            if edge.src_symbol_index is not None
            else file_id
        )
        src_kind = "symbol" if edge.src_symbol_index is not None else "file"
        dst_id = name_to_id.get(edge.callee_name)
        rows.append(
            {
                "edge_type": edge.edge_type,
                "src_kind": src_kind,
                "src_id": src_id,
                "dst_kind": "symbol" if dst_id is not None else None,
                "dst_id": dst_id,
                "dst_name": edge.callee_name,
                "line": edge.line,
                "resolved": 1 if dst_id is not None else 0,
            }
        )
    return rows


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _git_head(root: Path) -> Optional[str]:
    try:
        out = subprocess.run(
            ["git", "-C", str(root), "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() if out.returncode == 0 else None
