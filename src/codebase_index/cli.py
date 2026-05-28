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
def index(rebuild: bool = typer.Option(False, "--rebuild", help="Discard and rebuild from scratch.")) -> None:
    """Full index build into .claude/cache/codebase-index/index.sqlite."""
    _todo("index")


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
    query: str = typer.Argument(..., help="Search query."),
    limit: int = typer.Option(10, "--limit"),
    token_budget: int = typer.Option(1500, "--token-budget"),
    mode: str = typer.Option("hybrid", "--mode", help="hybrid|fts|symbol|vector"),
    no_fallback: bool = typer.Option(False, "--no-fallback"),
) -> None:
    """Hybrid ranked search; returns compact results + recommended_reads."""
    _todo("search")


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
def stats() -> None:
    """Index size, coverage %, and freshness."""
    _todo("stats")


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
