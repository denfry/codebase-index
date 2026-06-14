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

import inspect
import json
import os
import sys
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

# Contract version for every structured tool payload. Bump on a breaking change
# (field removal / type change); additive fields keep the same version. Every tool
# return — including errors — is wrapped by `_emit`, so clients can branch on
# `schema_version` and `tool` without sniffing the shape. See docs/MCP.md.
MCP_SCHEMA_VERSION = 1


def _emit(tool: str, payload: dict) -> str:
    """Serialize a tool payload inside the stable MCP envelope.

    `schema_version` and `tool` lead; the payload follows. A payload key never
    shadows the envelope (payloads do not carry these keys), but the explicit
    order makes the contract self-describing in the raw JSON.
    """
    return json.dumps({"schema_version": MCP_SCHEMA_VERSION, "tool": tool, **payload})


# Tools return JSON *strings* (unstructured text). Newer FastMCP otherwise
# auto-builds a structured-output schema from the `-> str` return annotation,
# which crashes on some mcp/pydantic combinations (mcp>=1.27 + pydantic 2.10).
# Force unstructured output where the kwarg exists; older mcp (>=1.0) lacks it.
_SUPPORTS_STRUCTURED_OUTPUT = "structured_output" in inspect.signature(mcp.tool).parameters


def _tool():
    if _SUPPORTS_STRUCTURED_OUTPUT:
        return mcp.tool(structured_output=False)
    return mcp.tool()


def _resolve_db() -> tuple[Path, "Config"]:
    """Return (db_path, config). Respects CBX_DB_PATH and CBX_ROOT env vars."""
    from ..service import resolve_db

    root_env = os.environ.get("CBX_ROOT")
    return resolve_db(Path(root_env) if root_env else None)


def _search_backend(cfg: "Config"):
    # stdout carries the JSON-RPC stream — warnings must go to stderr.
    from ..service import search_backend

    return search_backend(cfg, warn=lambda m: print(m, file=sys.stderr))


def _no_index_payload() -> dict:
    return {"error": "No index found. Run `codebase-index index` in your project first."}


@_tool()
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
    return _emit("healthcheck", payload)


@_tool()
def search_code(
    query: str,
    mode: str = "hybrid",
    limit: int = 10,
    token_budget: int = 1500,
    offset: int = 0,
) -> str:
    """Hybrid search over the codebase index.

    Returns ranked results with file paths, line ranges, symbol names, and
    recommended_reads — the exact ranges to open next.

    When the response includes a ``pagination`` key, pass ``next_offset`` as
    ``offset`` in the next call to retrieve the following page of results.

    Args:
        query: Natural-language or keyword search query.
        mode: Search mode — "hybrid" (default), "fts" (full-text), or "symbol".
        limit: Maximum number of results to return per page.
        token_budget: Token budget for the response payload.
        offset: Result offset for pagination. Pass ``next_offset`` from a
                previous response to fetch the next page.
    """
    db_path, cfg = _resolve_db()
    if not db_path.exists():
        return _emit("search_code", _no_index_payload())

    from ..service import search_payload

    payload = search_payload(
        db_path, cfg, query, mode=mode, limit=limit, offset=offset,
        token_budget=token_budget, no_fallback=False, backend=_search_backend(cfg),
    )
    return _emit("search_code", payload)


@_tool()
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
        return _emit("find_symbol", _no_index_payload())

    from ..retrieval.searchers import symbol_lookup
    from ..storage.db import Database

    with Database(db_path) as db:
        resp = symbol_lookup(db.conn, name, kind=kind, exact=exact)
    return _emit("find_symbol", resp.model_dump())


@_tool()
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
        return _emit("find_refs", _no_index_payload())

    from ..retrieval.searchers import refs_lookup
    from ..storage.db import Database

    with Database(db_path) as db:
        resp = refs_lookup(db.conn, symbol, kind=kind)
    return _emit("find_refs", resp.model_dump())


@_tool()
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
        return _emit("impact_of", _no_index_payload())

    from ..graph.expand import impact_lookup
    from ..storage.db import Database

    with Database(db_path) as db:
        resp = impact_lookup(db.conn, target, depth=depth, direction=direction)
    return _emit("impact_of", resp.model_dump())


@_tool()
def explain_code(
    query: str,
    token_budget: int = 2200,
    offset: int = 0,
) -> str:
    """Intent-aware retrieval for architecture / how-does-X-work questions.

    Uses a higher token budget and how-it-works intent weights compared to search_code.
    Supports the same pagination protocol as search_code.

    Args:
        query: Question about the codebase (e.g. "how does the retrieval pipeline work").
        token_budget: Token budget for the response payload.
        offset: Result offset for pagination. Pass ``next_offset`` from a
                previous response to fetch the next page.
    """
    db_path, cfg = _resolve_db()
    if not db_path.exists():
        return _emit("explain_code", _no_index_payload())

    from ..service import normalize_explain_query, search_payload

    payload = search_payload(
        db_path, cfg, normalize_explain_query(query), mode="hybrid", limit=10,
        offset=offset, token_budget=token_budget, no_fallback=False,
        backend=_search_backend(cfg),
    )
    return _emit("explain_code", payload)


@_tool()
def index_stats() -> str:
    """Return index freshness, file count, symbol count, and per-language coverage."""
    db_path, _ = _resolve_db()
    if not db_path.exists():
        return _emit("index_stats", {"exists": False, "error": "No index found."})

    from ..service import stats_payload
    from ..storage.db import Database

    with Database(db_path) as db:
        payload = stats_payload(db.conn)
    return _emit("index_stats", payload)


def run() -> None:
    """Entry point for the standalone `codebase-index-mcp` script."""
    mcp.run(transport="stdio")
