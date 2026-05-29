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
) -> None:
    """Lexical ranked search; hybrid aliases FTS until fusion lands."""
    from .config import load
    from .models import IndexFreshness, SearchResponse
    from .output import json as json_out
    from .output import markdown as md_out
    from .retrieval.searchers import fts_response
    from .storage.db import Database

    is_json = bool(ctx.obj and ctx.obj.get("json"))

    if mode in ("symbol", "vector"):
        typer.echo(
            f"[codebase-index] --mode {mode} is not available until a later "
            "milestone. Use --mode fts."
        )
        raise typer.Exit(code=0)

    cfg = load(ctx.obj.get("root") if ctx.obj else None)
    db_path = Path(cfg.root) / ".claude" / "cache" / "codebase-index" / "index.sqlite"

    if not db_path.exists():
        resp = SearchResponse(
            query=query,
            intent="keyword",
            index=IndexFreshness(exists=False, stale=False),
            confidence="low",
            results=[],
            recommended_reads=[],
            fallback_suggestions={} if no_fallback else {"ripgrep": [f'rg -n "{query}"']},
        )
        typer.echo(json_out.render(resp) if is_json else md_out.render(resp))
        raise typer.Exit(code=0)

    with Database(db_path) as db:
        resp = fts_response(
            db.conn,
            query,
            limit=limit,
            token_budget=token_budget,
            root=Path(cfg.root),
        )
    if no_fallback:
        resp.fallback_suggestions = {}

    typer.echo(json_out.render(resp) if is_json else md_out.render(resp))


@app.command()
def symbol(
    name: str = typer.Argument(...),
    kind: Optional[str] = typer.Option(None, "--kind", help="Filter by symbol kind."),
    exact: bool = typer.Option(False, "--exact"),
) -> None:
    """Locate a symbol definition by name."""
    _todo("symbol")


@app.command()
def refs(
    symbol_name: str = typer.Argument(...),
    kind: str = typer.Option("all", "--kind", help="callers|all"),
) -> None:
    """Find references / callers of a symbol."""
    _todo("refs")


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
    query: str = typer.Argument(...),
    token_budget: int = typer.Option(1500, "--token-budget"),
) -> None:
    """Intent-aware bundle for 'how does X work' / overview questions."""
    _todo("explain")


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
