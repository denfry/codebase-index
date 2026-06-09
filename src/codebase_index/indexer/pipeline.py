"""Drive a build: discovery -> parse (parallel) -> write -> prune deleted -> meta."""

from __future__ import annotations

import hashlib
import os
import subprocess
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from ..config import Config
from ..discovery.walker import walk
from ..embeddings.backend import resolve_backend
from ..graph.builder import build_graph
from ..parsers.base import ParseResult
from ..parsers.line_chunker import chunk_text
from ..parsers.treesitter import UnsupportedLanguage, parse_file
from ..storage import repo
from ..storage.db import Database
from .doc_chunks import extract_doc_chunks

# Minimum file count before spawning a process pool (avoids spawn overhead on tiny repos)
_MIN_PARALLEL_FILES = 30

# Set by _pool_init in each worker process; avoids per-task Config serialization
_PARSE_CONFIG: Optional[Config] = None


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
    parse_failed: int = 0
    treesitter_zero_symbols: int = 0


@dataclass
class _ParseOutcome:
    result: ParseResult
    parse_failed: bool = False
    zero_symbols: bool = False


@dataclass
class _ParseResult:
    sha256: str
    outcome: _ParseOutcome
    doc_chunks: list


def _add_stats(target: BuildStats, delta: BuildStats) -> None:
    target.indexed += delta.indexed
    target.deleted += delta.deleted
    target.total_bytes += delta.total_bytes
    target.chunks += delta.chunks
    target.skipped += delta.skipped
    target.symbols += delta.symbols
    target.edges += delta.edges
    target.edges_resolved += delta.edges_resolved
    target.vectors += delta.vectors
    target.parse_failed += delta.parse_failed
    target.treesitter_zero_symbols += delta.treesitter_zero_symbols


# ---------------------------------------------------------------------------
# Parse phase — CPU-bound, can run in parallel
# ---------------------------------------------------------------------------

def _pool_init(config: Config) -> None:
    """Initialiser for each worker process: store config in a module global."""
    global _PARSE_CONFIG
    _PARSE_CONFIG = config


def _parse_one(cand) -> _ParseResult:
    """Parse a single file. Top-level for ProcessPoolExecutor pickling; uses _PARSE_CONFIG."""
    config = _PARSE_CONFIG
    assert config is not None, "_pool_init must set _PARSE_CONFIG before any worker parses"
    try:
        sha256 = _sha256_file(cand.path)
    except OSError:
        sha256 = ""
    text = _read_text(cand.path)
    outcome = _parse(cand.lang, cand.parser, text, config)
    doc_chunks = extract_doc_chunks(text, cand.rel_path, cand.lang)
    return _ParseResult(sha256=sha256, outcome=outcome, doc_chunks=doc_chunks)


def _parse_one_inline(
    cand, config: Config, *, sha256: Optional[str] = None
) -> _ParseResult:
    """Sequential parse — used when pool is unavailable or repo is too small."""
    if sha256 is None:
        try:
            sha256 = _sha256_file(cand.path)
        except OSError:
            sha256 = ""
    text = _read_text(cand.path)
    outcome = _parse(cand.lang, cand.parser, text, config)
    doc_chunks = extract_doc_chunks(text, cand.rel_path, cand.lang)
    return _ParseResult(sha256=sha256, outcome=outcome, doc_chunks=doc_chunks)


def _parse_all(candidates: list, config: Config) -> list[_ParseResult]:
    """Parse all candidates, using a process pool for large repos."""
    if len(candidates) < _MIN_PARALLEL_FILES:
        return [_parse_one_inline(c, config) for c in candidates]
    workers = min(len(candidates), os.cpu_count() or 1)
    try:
        with ProcessPoolExecutor(
            max_workers=workers,
            initializer=_pool_init,
            initargs=(config,),
        ) as pool:
            return list(pool.map(_parse_one, candidates))
    except Exception:
        return [_parse_one_inline(c, config) for c in candidates]


# ---------------------------------------------------------------------------
# Write phase — DB writes, must be serial
# ---------------------------------------------------------------------------

def _write_candidate(conn, cand, pr: _ParseResult, now: str) -> BuildStats:
    """Write a pre-parsed candidate to the database."""
    stats = BuildStats(indexed=1, total_bytes=cand.size_bytes)
    file_id = repo.upsert_file(
        conn,
        path=cand.rel_path,
        lang=cand.lang,
        size_bytes=cand.size_bytes,
        sha256=pr.sha256,
        mtime_ns=cand.path.stat().st_mtime_ns,
        git_status=None,
        parser=cand.parser,
        indexed_at=now,
        is_generated=cand.is_generated,
    )
    outcome = pr.outcome
    parse_result = outcome.result
    stats.parse_failed += int(outcome.parse_failed)
    stats.treesitter_zero_symbols += int(outcome.zero_symbols)
    symbol_ids = repo.replace_symbols(conn, file_id, parse_result.symbols)
    repo.replace_chunks(conn, file_id, parse_result.chunks, symbol_ids=symbol_ids)
    if pr.doc_chunks:
        repo.append_chunks(conn, file_id, pr.doc_chunks)
        stats.chunks += len(pr.doc_chunks)
    edge_rows = _resolve_edges(parse_result, symbol_ids, file_id)
    repo.replace_edges(conn, file_id, edge_rows)
    stats.chunks += len(parse_result.chunks)
    stats.symbols += len(parse_result.symbols)
    stats.edges += len(edge_rows)
    return stats


def build_index(config: Config, db: Database, root: Optional[Path] = None) -> BuildStats:
    root = Path(root or config.root).resolve()
    conn = db.conn
    now = _utc_now_iso()

    candidates = list(walk(root, config))
    parse_results = _parse_all(candidates, config)

    stats = BuildStats()
    seen: set[str] = set()
    for cand, pr in zip(candidates, parse_results):
        _add_stats(stats, _write_candidate(conn, cand, pr, now))
        seen.add(cand.rel_path)

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
    """Embed only new/changed chunks (incremental). Returns count of newly embedded chunks.

    Fully gated: with embeddings disabled this is never called, so no optional
    dependency is imported and vec_chunks is never created.
    """
    backend = resolve_backend(cfg, warn=lambda m: print(m))
    if not getattr(backend, "enabled", False):
        return 0
    import sqlite_vec  # type: ignore[import-untyped]

    db.enable_vectors()
    repo.ensure_vec_tables(conn, dim=backend.dim)
    repo.prune_orphan_vectors(conn)
    existing = repo.embedded_chunk_ids(conn)
    rows = [r for r in repo.chunks_for_embedding(conn) if int(r["id"]) not in existing]
    if not rows:
        return 0

    # Content-addressed reuse: chunk ids churn on every full rebuild (replace_chunks),
    # so a chunk-id keyed skip alone re-embeds the whole repo each time. Hash the content
    # and only call the (potentially slow / paid) backend for text never embedded under
    # this model; everything else is copied straight from the cache.
    shas = [hashlib.sha256(r["content"].encode("utf-8")).hexdigest() for r in rows]
    cached = repo.cached_embeddings(conn, model=backend.name, shas=shas)
    misses = [(r, sha) for r, sha in zip(rows, shas) if sha not in cached]

    fresh: dict[str, bytes] = {}
    if misses:
        vectors = backend.embed([r["content"] for r, _ in misses])
        for (_row, sha), vec in zip(misses, vectors):
            fresh[sha] = sqlite_vec.serialize_float32(vec)
        repo.store_cached_embeddings(conn, model=backend.name, items=list(fresh.items()))

    repo.upsert_chunk_vector_blobs(
        conn,
        [(int(row["id"]), cached.get(sha) or fresh[sha]) for row, sha in zip(rows, shas)],
    )

    built_at = datetime.now(timezone.utc).isoformat()
    repo.set_vec_meta(conn, model=backend.name, dim=backend.dim, built_at=built_at)
    return len(misses)


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


def _parse(lang: Optional[str], parser: str, text: str, config: Config) -> _ParseOutcome:
    """Parse a file to a ParseResult, recording (never swallowing) parse failures.

    Routing is owned by `classify` (Guardrail 1): only files classify labels `treesitter`
    attempt tree-sitter; everything else stays on the line-chunk + FTS floor (Tier C).
    """
    failed = False
    if lang and parser == "treesitter":
        try:
            result = parse_file(lang, text)
            return _ParseOutcome(result=result, zero_symbols=not result.symbols)
        except UnsupportedLanguage:
            # classify routed a tree-sitter lang with no extraction path — a Guardrail 1
            # breach. Count it loudly instead of pretending the file parsed.
            failed = True
        except Exception:
            # Any other parse error: record it (Guardrail 2) and fall back to line chunks,
            # so one bad file never silently looks identical to a clean parse.
            failed = True
    chunks = chunk_text(
        text,
        window_lines=config.chunk.window_lines,
        overlap_lines=config.chunk.overlap_lines,
    )
    return _ParseOutcome(result=ParseResult(chunks=chunks, symbols=[], edges=[]), parse_failed=failed)


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

        pr = _parse_one_inline(cand, config, sha256=sha)
        _add_stats(stats, _write_candidate(conn, cand, pr, now))

    if scope is None:
        gone = repo.all_paths(conn) - seen
    else:
        gone = {p for p in scope if p not in seen and p in indexed_fp}
    repo.delete_files(conn, gone)
    stats.deleted = len(gone)

    if stats.indexed or stats.deleted:
        graph = build_graph(conn)
        stats.edges_resolved = graph["resolved"]
        if config.embeddings.enabled:
            stats.vectors = _embed_chunks(config, db, conn)

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
