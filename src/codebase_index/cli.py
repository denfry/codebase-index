"""Typer CLI app — the single entry point for both humans and the Claude Code skill.

Commands map 1:1 to docs/ARCHITECTURE.md §5 (CLI contract). At M0 these are stubs that parse the
documented flags and emit `not implemented`; later milestones fill in the bodies by delegating to
the `indexer`, `retrieval`, and `storage` layers.

Conventions:
  * every command accepts global options via the Typer context: --root, --json, --quiet
  * read-only/search commands accept --limit, --token-budget
  * output goes through `output.json` (when --json) or `output.markdown` (otherwise)
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Optional

import typer

app = typer.Typer(
    name="codebase-index",
    help="Local-first hybrid codebase index for Claude Code (Skill + CLI).",
    no_args_is_help=True,
    add_completion=False,
)


# --- global state resolved from common options --------------------------------------------------
def _todo(name: str) -> None:
    typer.echo(f"[codebase-index] '{name}' is not implemented yet (M0 scaffold). See docs/ROADMAP.md")
    raise typer.Exit(code=0)


def _resolve_db_path(ctx: "typer.Context") -> Path:
    from .config import load

    override = os.environ.get("CBX_DB_PATH")
    if override:
        return Path(override)
    root_opt = ctx.obj.get("root") if ctx.obj else None
    cfg = load(root_opt)
    return Path(cfg.root) / ".claude" / "cache" / "codebase-index" / "index.sqlite"


@app.callback()
def main(
    ctx: typer.Context,
    root: Optional[Path] = typer.Option(None, "--root", help="Project root (default: discover from cwd)."),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress progress output."),
) -> None:
    ctx.obj = {"root": root, "json": json_out, "quiet": quiet}


# --- lifecycle ----------------------------------------------------------------------------------
@app.command()
def init(
    force: bool = typer.Option(False, "--force", help="Overwrite an existing skill install."),
    with_hooks: bool = typer.Option(False, "--with-hooks", help="Also offer to install the update hook."),
) -> None:
    """Scaffold the skill, config.json, and .gitignore rules into the current project."""
    _todo("init")


@app.command()
def index(
    ctx: typer.Context,
    rebuild: bool = typer.Option(False, "--rebuild", help="Discard and rebuild from scratch."),
) -> None:
    """Full index build into .claude/cache/codebase-index/index.sqlite."""
    import json as _json

    from .config import load
    from .indexer.pipeline import build_index
    from .storage.db import Database

    root_opt = ctx.obj.get("root") if ctx.obj else None
    cfg = load(root_opt)
    db_path = Path(cfg.root) / ".claude" / "cache" / "codebase-index" / "index.sqlite"
    if rebuild and db_path.exists():
        db_path.unlink()

    with Database(db_path) as db:
        stats = build_index(cfg, db, root=Path(cfg.root))

    if ctx.obj and ctx.obj.get("json"):
        typer.echo(
            _json.dumps(
                {
                    "indexed": stats.indexed,
                    "deleted": stats.deleted,
                    "total_bytes": stats.total_bytes,
                }
            )
        )
    elif not (ctx.obj and ctx.obj.get("quiet")):
        typer.echo(f"Indexed {stats.indexed} files ({stats.deleted} pruned).")


@app.command()
def update(
    since: Optional[str] = typer.Option(None, "--since", help="Re-index files changed since a git ref."),
    all_files: bool = typer.Option(False, "--all", help="Force re-check of every file."),
) -> None:
    """Incremental re-index (hash/mtime/git aware)."""
    _todo("update")


# --- retrieval (read-only; these are what the skill calls) --------------------------------------
@app.command()
def search(
    ctx: typer.Context,
    query: str = typer.Argument(..., help="Search query."),
    limit: int = typer.Option(10, "--limit"),
    token_budget: int = typer.Option(1500, "--token-budget"),
    mode: str = typer.Option("hybrid", "--mode", help="hybrid|fts|symbol|vector"),
    no_fallback: bool = typer.Option(False, "--no-fallback"),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Hybrid ranked search; returns compact results + recommended_reads."""
    from .output import json as json_renderer
    from .output import markdown as md_renderer
    from .retrieval.pipeline import search as run_search
    from .storage.db import Database

    if mode == "vector":
        typer.echo("[codebase-index] vector mode requires embeddings (M6); use --mode hybrid.")
        raise typer.Exit(code=2)

    db_path = _resolve_db_path(ctx)
    if not db_path.exists():
        typer.echo("No index found. Run `codebase-index index`.")
        raise typer.Exit(code=1)

    with Database(db_path) as db:
        payload = run_search(
            db.conn, query, mode=mode, limit=limit,
            token_budget=token_budget, no_fallback=no_fallback,
        )

    want_json = json_out or (ctx.obj and ctx.obj.get("json"))
    typer.echo(json_renderer.render(payload) if want_json else md_renderer.render(payload))


@app.command()
def symbol(
    ctx: typer.Context,
    name: str = typer.Argument(...),
    kind: Optional[str] = typer.Option(None, "--kind", help="Filter by symbol kind."),
    exact: bool = typer.Option(False, "--exact"),
) -> None:
    """Locate a symbol definition by name."""
    from .config import load
    from .models import IndexFreshness, SymbolResponse
    from .output import json as json_out
    from .output import markdown as md_out
    from .retrieval.searchers import symbol_lookup
    from .storage.db import Database

    is_json = bool(ctx.obj and ctx.obj.get("json"))
    cfg = load(ctx.obj.get("root") if ctx.obj else None)
    db_path = Path(cfg.root) / ".claude" / "cache" / "codebase-index" / "index.sqlite"

    if not db_path.exists():
        resp = SymbolResponse(
            query=name, index=IndexFreshness(exists=False, stale=False), symbols=[]
        )
        typer.echo(json_out.render(resp) if is_json else md_out.render_symbols(resp))
        raise typer.Exit(code=0)

    with Database(db_path) as db:
        resp = symbol_lookup(db.conn, name, kind=kind, exact=exact)
    typer.echo(json_out.render(resp) if is_json else md_out.render_symbols(resp))


@app.command()
def refs(
    ctx: typer.Context,
    symbol_name: str = typer.Argument(...),
    kind: str = typer.Option("all", "--kind", help="callers|all"),
) -> None:
    """Find references / callers of a symbol."""
    from .config import load
    from .models import IndexFreshness, RefsResponse
    from .output import json as json_out
    from .output import markdown as md_out
    from .retrieval.searchers import refs_lookup
    from .storage.db import Database

    is_json = bool(ctx.obj and ctx.obj.get("json"))
    cfg = load(ctx.obj.get("root") if ctx.obj else None)
    db_path = Path(cfg.root) / ".claude" / "cache" / "codebase-index" / "index.sqlite"

    if not db_path.exists():
        resp = RefsResponse(
            query=symbol_name, index=IndexFreshness(exists=False, stale=False), sites=[]
        )
        typer.echo(json_out.render(resp) if is_json else md_out.render_refs(resp))
        raise typer.Exit(code=0)

    with Database(db_path) as db:
        resp = refs_lookup(db.conn, symbol_name, kind=kind)
    typer.echo(json_out.render(resp) if is_json else md_out.render_refs(resp))


@app.command()
def impact(
    target: str = typer.Argument(..., help="File path or symbol name."),
    depth: int = typer.Option(2, "--depth"),
    direction: str = typer.Option("up", "--direction", help="up|down|both"),
) -> None:
    """Blast radius: what is affected if `target` changes (graph walk)."""
    _todo("impact")


@app.command()
def explain(
    ctx: typer.Context,
    query: str = typer.Argument(...),
    token_budget: int = typer.Option(2200, "--token-budget"),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Intent-aware bundle for 'how does X work' / overview questions."""
    from .output import json as json_renderer
    from .output import markdown as md_renderer
    from .retrieval.pipeline import search as run_search
    from .storage.db import Database

    db_path = _resolve_db_path(ctx)
    if not db_path.exists():
        typer.echo("No index found. Run `codebase-index index`.")
        raise typer.Exit(code=1)

    q = query if any(w in query.lower() for w in ("how", "architecture", "overview")) else f"how does {query} work"
    with Database(db_path) as db:
        payload = run_search(db.conn, q, mode="hybrid", limit=10,
                             token_budget=token_budget, no_fallback=False)

    want_json = json_out or (ctx.obj and ctx.obj.get("json"))
    typer.echo(json_renderer.render(payload) if want_json else md_renderer.render(payload))


# --- diagnostics / maintenance ------------------------------------------------------------------
@app.command()
def stats(ctx: typer.Context) -> None:
    """Index size, coverage %, and freshness."""
    import json as _json

    from .config import load
    from .storage import repo
    from .storage.db import Database

    root_opt = ctx.obj.get("root") if ctx.obj else None
    cfg = load(root_opt)
    db_path = Path(cfg.root) / ".claude" / "cache" / "codebase-index" / "index.sqlite"

    if not db_path.exists():
        if ctx.obj and ctx.obj.get("json"):
            typer.echo(_json.dumps({"files": 0, "built_at": None, "exists": False}))
        else:
            typer.echo("No index found. Run `codebase-index index`.")
        raise typer.Exit(code=0)

    with Database(db_path) as db:
        files = repo.count_files(db.conn)
        built_at = repo.get_meta(db.conn, "built_at")
        head = repo.get_meta(db.conn, "head_commit")

    if ctx.obj and ctx.obj.get("json"):
        typer.echo(
            _json.dumps(
                {
                    "files": files,
                    "built_at": built_at,
                    "head_commit": head,
                    "exists": True,
                }
            )
        )
    else:
        typer.echo(f"files={files}  built_at={built_at}  head={head}")


@app.command()
def doctor(strict: bool = typer.Option(False, "--strict", help="Exit non-zero on high-severity findings.")) -> None:
    """Diagnose configuration and security issues (see docs/SECURITY.md)."""
    _todo("doctor")


@app.command()
def clean(yes: bool = typer.Option(False, "--yes", help="Skip confirmation.")) -> None:
    """Remove the per-project cache (keeps the skill)."""
    _todo("clean")


@app.command()
def watch(debounce: int = typer.Option(500, "--debounce", help="Debounce window in ms.")) -> None:
    """(Optional) Live incremental indexing via filesystem events."""
    _todo("watch")


if __name__ == "__main__":
    app()
