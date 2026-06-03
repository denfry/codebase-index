"""MCP server exposing codebase-index retrieval as tools for Claude.

Wraps the same retrieval/ layer the CLI uses — no subprocess overhead.
Launch via: codebase-index mcp  (or codebase-index-mcp as a standalone entry point)

MCP client config example (.claude/settings.json):
  {
    "mcpServers": {
      "codebase-index": {
        "command": "codebase-index",
        "args": ["mcp"],
        "cwd": "/path/to/your/project"
      }
    }
  }
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from .. import __version__

if TYPE_CHECKING:
    from ..config import Config

try:
    from mcp.server.fastmcp import FastMCP
except ImportError as exc:  # pragma: no cover
    raise ImportError(
        "MCP server needs the optional extra: pip install codebase-index[mcp]"
    ) from exc

mcp = FastMCP(
    "codebase-index",
    instructions=(
        "Local codebase index. Use search_code for general queries, find_symbol for exact "
        "symbol lookups, find_refs to find callers/usages, impact_of for blast-radius analysis, "
        "and explain_code for architecture/how-it-works questions."
    ),
)


def _resolve_db() -> tuple[Path, Config]:
    """Return (db_path, config). Respects CBX_DB_PATH and CBX_ROOT env vars."""
    from ..config import load

    override = os.environ.get("CBX_DB_PATH")
    if override:
        db_path = Path(override)
        cfg: Config = load(Path(db_path.parent))
        return db_path, cfg

    root_env = os.environ.get("CBX_ROOT")
    cfg = load(Path(root_env) if root_env else None)
    db_path = Path(cfg.root) / ".claude" / "cache" / "codebase-index" / "index.sqlite"
    return db_path, cfg


def _no_index_error() -> str:
    return json.dumps({"error": "No index found. Run `codebase-index index` in your project first."})


@mcp.tool()
def healthcheck() -> str:
    """Report package, root, and index health for MCP clients."""
    db_path, cfg = _resolve_db()
    payload: dict[str, object] = {
        "package_version": __version__,
        "root": str(cfg.root),
        "index": {"exists": db_path.exists(), "path": str(db_path)},
    }
    if db_path.exists():
        from ..indexer.freshness import compute_freshness
        from ..storage.db import Database

        with Database(db_path) as db:
            payload["index"] = {
                "exists": True,
                "path": str(db_path),
                **compute_freshness(db.conn, Path(cfg.root), cfg).model_dump(),
            }
    return json.dumps(payload)


@mcp.tool()
def search_code(
    query: str,
    mode: str = "hybrid",
    limit: int = 10,
    token_budget: int = 1500,
) -> str:
    """Hybrid search over the codebase index.

    Returns ranked results with file paths, line ranges, symbol names, and
    recommended_reads — the exact ranges to open next.

    Args:
        query: Natural-language or keyword search query.
        mode: Search mode — "hybrid" (default), "fts" (full-text), or "symbol".
        limit: Maximum number of results to return.
        token_budget: Token budget for the response payload.
    """
    db_path, cfg = _resolve_db()
    if not db_path.exists():
        return _no_index_error()

    from ..retrieval.pipeline import search as run_search
    from ..storage.db import Database

    with Database(db_path) as db:
        payload = run_search(
            db.conn,
            query,
            mode=mode,
            limit=limit,
            token_budget=token_budget,
            no_fallback=False,
            root=Path(cfg.root),
            config=cfg,
        )
    return json.dumps(payload)


@mcp.tool()
def find_symbol(
    name: str,
    kind: Optional[str] = None,
    exact: bool = False,
) -> str:
    """Locate a symbol definition by name (function, class, method, etc.).

    Returns file path, line range, and signature for each match.

    Args:
        name: Symbol name to look up (e.g. "parse_file", "Database", "MyClass.method").
        kind: Optional filter — "function", "class", "method", "struct", etc.
        exact: If True, only exact name matches are returned (no prefix/fuzzy).
    """
    db_path, _ = _resolve_db()
    if not db_path.exists():
        return _no_index_error()

    from ..retrieval.searchers import symbol_lookup
    from ..storage.db import Database

    with Database(db_path) as db:
        resp = symbol_lookup(db.conn, name, kind=kind, exact=exact)
    return json.dumps(resp.model_dump())


@mcp.tool()
def find_refs(
    symbol: str,
    kind: str = "all",
) -> str:
    """Find all references and callers of a symbol.

    Returns call sites with file path and line number.

    Args:
        symbol: Symbol name whose references to find.
        kind: "callers" for call edges only, "all" for any reference type.
    """
    db_path, _ = _resolve_db()
    if not db_path.exists():
        return _no_index_error()

    from ..retrieval.searchers import refs_lookup
    from ..storage.db import Database

    with Database(db_path) as db:
        resp = refs_lookup(db.conn, symbol, kind=kind)
    return json.dumps(resp.model_dump())


@mcp.tool()
def impact_of(
    target: str,
    depth: int = 2,
    direction: str = "up",
) -> str:
    """Blast-radius analysis: what is affected if `target` changes.

    Walks the dependency/call graph and returns affected files and symbols.

    Args:
        target: File path (relative) or symbol name to analyse.
        depth: How many graph hops to follow (default 2).
        direction: "up" (what depends on target), "down" (what target depends on), or "both".
    """
    db_path, _ = _resolve_db()
    if not db_path.exists():
        return _no_index_error()

    from ..graph.expand import impact_lookup
    from ..storage.db import Database

    with Database(db_path) as db:
        resp = impact_lookup(db.conn, target, depth=depth, direction=direction)
    return json.dumps(resp.model_dump())


@mcp.tool()
def explain_code(
    query: str,
    token_budget: int = 2200,
) -> str:
    """Intent-aware retrieval for architecture / how-does-X-work questions.

    Uses a higher token budget and how-it-works intent weights compared to search_code.

    Args:
        query: Question about the codebase (e.g. "how does the retrieval pipeline work").
        token_budget: Token budget for the response payload.
    """
    db_path, cfg = _resolve_db()
    if not db_path.exists():
        return _no_index_error()

    from ..retrieval.pipeline import search as run_search
    from ..storage.db import Database

    q = query if any(w in query.lower() for w in ("how", "architecture", "overview")) else f"how does {query} work"
    with Database(db_path) as db:
        payload = run_search(
            db.conn,
            q,
            mode="hybrid",
            limit=10,
            token_budget=token_budget,
            no_fallback=False,
            root=Path(cfg.root),
            config=cfg,
        )
    return json.dumps(payload)


@mcp.tool()
def index_stats() -> str:
    """Return index freshness, file count, symbol count, and per-language coverage."""
    db_path, _ = _resolve_db()
    if not db_path.exists():
        return json.dumps({"exists": False, "error": "No index found."})

    from ..storage import repo
    from ..storage.db import Database

    with Database(db_path) as db:
        files = repo.count_files(db.conn)
        symbols = repo.count_symbols(db.conn)
        built_at = repo.get_meta(db.conn, "built_at")
        head = repo.get_meta(db.conn, "head_commit")
        coverage = [
            {"lang": r["lang"], "files": r["files"], "symbols": r["symbols"]}
            for r in repo.treesitter_coverage(db.conn)
        ]

    return json.dumps({
        "exists": True,
        "files": files,
        "symbols": symbols,
        "built_at": built_at,
        "head_commit": head,
        "treesitter_coverage": coverage,
    })


def run() -> None:
    """Entry point for the standalone `codebase-index-mcp` script."""
    mcp.run(transport="stdio")
