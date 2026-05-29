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
from ..embeddings.backend import resolve_backend
from ..graph.builder import build_graph
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
    skipped: int = 0
    symbols: int = 0
    edges: int = 0
    edges_resolved: int = 0
    vectors: int = 0


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

    graph = build_graph(conn)
    stats.edges_resolved = graph["resolved"]

    if config.embeddings.enabled:
        stats.vectors = _embed_chunks(config, db, conn)

    conn.commit()
    return stats


def _embed_chunks(cfg, db, conn) -> int:
    """Embed every chunk and (re)store its vector. Returns the vector count.

    Fully gated: with embeddings disabled this is never called, so no optional
    dependency is imported and vec_chunks is never created.
    """
    backend = resolve_backend(cfg, warn=lambda m: print(m))
    if not getattr(backend, "enabled", False):
        return 0
    rows = repo.chunks_for_embedding(conn)
    if not rows:
        return 0
    db.enable_vectors()
    texts = [r["content"] for r in rows]
    vectors = backend.embed(texts)
    repo.ensure_vec_tables(conn, dim=backend.dim)
    repo.clear_vectors(conn)
    for row, vec in zip(rows, vectors):
        repo.upsert_chunk_vector(conn, int(row["id"]), vec)
    built_at = datetime.now(timezone.utc).isoformat()
    repo.set_vec_meta(conn, model=backend.name, dim=backend.dim, built_at=built_at)
    return len(rows)


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


def update_index(
    config: Config,
    db: Database,
    root: Optional[Path] = None,
    *,
    since: Optional[str] = None,
    all_files: bool = False,
) -> BuildStats:
    root = Path(root or config.root).resolve()
    conn = db.conn
    now = _utc_now_iso()
    stats = BuildStats()

    indexed_fp = repo.fingerprints(conn)
    scope = _git_changed_since(root, since) if since else None

    seen: set[str] = set()
    for cand in walk(root, config):
        seen.add(cand.rel_path)
        if scope is not None and cand.rel_path not in scope:
            stats.skipped += 1
            continue

        st = cand.path.stat()
        prior = indexed_fp.get(cand.rel_path)
        fast_ok = (
            not all_files
            and prior is not None
            and prior[0] == st.st_mtime_ns
            and prior[1] == cand.size_bytes
        )
        if fast_ok:
            stats.skipped += 1
            continue

        sha = _sha256_file(cand.path)
        if prior is not None and prior[2] == sha:
            conn.execute(
                "UPDATE files SET mtime_ns = ?, size_bytes = ?, indexed_at = ? WHERE path = ?",
                (st.st_mtime_ns, cand.size_bytes, now, cand.rel_path),
            )
            stats.skipped += 1
            continue

        file_id = repo.upsert_file(
            conn,
            path=cand.rel_path,
            lang=cand.lang,
            size_bytes=cand.size_bytes,
            sha256=sha,
            mtime_ns=st.st_mtime_ns,
            git_status=None,
            parser=cand.parser,
            indexed_at=now,
            is_generated=cand.is_generated,
        )
        file_chunks = chunk_text(
            _read_text(cand.path),
            window_lines=config.chunk.window_lines,
            overlap_lines=config.chunk.overlap_lines,
        )
        repo.replace_chunks(conn, file_id, file_chunks)
        stats.chunks += len(file_chunks)
        stats.indexed += 1
        stats.total_bytes += cand.size_bytes

    if scope is None:
        gone = repo.all_paths(conn) - seen
    else:
        gone = {p for p in scope if p not in seen and p in indexed_fp}
    repo.delete_files(conn, gone)
    stats.deleted = len(gone)

    repo.set_meta(conn, "built_at", repo.get_meta(conn, "built_at") or now)
    repo.set_meta(conn, "updated_at", now)
    repo.set_meta(conn, "config_hash", config.config_hash())
    if head := _git_head(root):
        repo.set_meta(conn, "head_commit", head)
    conn.commit()
    return stats


def _git_changed_since(root: Path, ref: str) -> set[str]:
    changed: set[str] = set()
    try:
        diff = subprocess.run(
            ["git", "-C", str(root), "diff", "--name-only", ref],
            capture_output=True, text=True, timeout=15, check=False,
        )
        if diff.returncode == 0:
            changed.update(line for line in diff.stdout.splitlines() if line)
        untracked = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--others", "--exclude-standard"],
            capture_output=True, text=True, timeout=15, check=False,
        )
        if untracked.returncode == 0:
            changed.update(line for line in untracked.stdout.splitlines() if line)
    except (OSError, subprocess.SubprocessError):
        return set()
    return changed
