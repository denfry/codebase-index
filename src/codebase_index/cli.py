"""Typer CLI app — the single entry point for both humans and the Claude Code skill.

Commands map 1:1 to docs/ARCHITECTURE.md §5 (CLI contract) and delegate to the
`indexer`, `retrieval`, and `storage` layers through `service.py` — the same
layer the MCP server uses, so the two surfaces cannot drift. Only `clean` is
still a stub.

Conventions:
  * every command accepts global options via the Typer context: --root, --json, --quiet
  * read-only/search commands accept --limit, --token-budget
  * output goes through `output.json` (when --json) or `output.markdown` (otherwise)
"""

from __future__ import annotations

import os
import subprocess
import sys
import webbrowser
from pathlib import Path
from typing import Any, Optional

# Force UTF-8 output on Windows to avoid cp1251 encoding errors
if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[union-attr]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[union-attr]

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


def _ensure_index(ctx: "typer.Context") -> tuple[Path, Any]:
    from .indexer.pipeline import build_index
    from .service import resolve_db
    from .storage.db import Database

    root_opt = ctx.obj.get("root") if ctx.obj else None
    db_path, cfg = resolve_db(root_opt)
    if db_path.exists():
        return db_path, cfg

    if not (ctx.obj and (ctx.obj.get("quiet") or ctx.obj.get("json"))):
        typer.echo("[codebase-index] no index found; building one now.", err=True)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    with Database(db_path) as db:
        build_index(cfg, db, root=Path(cfg.root))
    return db_path, cfg


def _open_in_browser(path: Path) -> None:
    uri = path.resolve().as_uri()
    try:
        webbrowser.open(uri)
        return
    except Exception:
        pass
    if sys.platform == "win32":
        subprocess.Popen(["cmd", "/c", "start", "", uri], shell=False)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", uri])
    else:
        subprocess.Popen(["xdg-open", uri])


def _resolve_backend_for_search(ctx: "typer.Context"):
    """Embedding backend for query-time vector search (see service.search_backend)."""
    from .config import load
    from .service import search_backend

    cfg = load(ctx.obj.get("root") if ctx.obj else None)
    return search_backend(cfg, warn=lambda m: typer.echo(m, err=True))


def _interactive_target_choice(detected_cli: list[str], detected_mcp: list[str]) -> str:
    from rich.console import Console
    from rich.prompt import Prompt
    from rich.table import Table

    from . import scaffold

    console = Console()
    table = Table(title="Install codebase-index")
    table.add_column("#", justify="right")
    table.add_column("Target")
    table.add_column("Type")
    table.add_column("Status")

    rows: list[str] = [*scaffold.CLI_TARGETS, *scaffold.MCP_TARGETS, "all"]
    for idx, name in enumerate(rows, start=1):
        kind = "skill" if name in scaffold.CLI_TARGETS else ("MCP" if name in scaffold.MCP_TARGETS else "")
        status = "detected" if name in detected_cli or name in detected_mcp else ""
        if name == "all":
            kind = ""
            status = "install everything"
        table.add_row(str(idx), name, kind, status)
    console.print(table)

    all_detected = detected_cli + [t for t in detected_mcp if t not in detected_cli]
    default = all_detected[0] if len(all_detected) == 1 else "all" if all_detected else "claude"
    choices = [*rows, *[str(i) for i in range(1, len(rows) + 1)]]
    selected = Prompt.ask("Choose target", choices=choices, default=default)
    if selected.isdigit():
        return rows[int(selected) - 1]
    return selected


def _resolve_init_targets(root: Path, requested: str | None) -> tuple[list[str], list[str]]:
    """Returns (cli_targets, mcp_targets)."""
    from . import scaffold

    detected_cli = scaffold.detect_cli_targets(root)
    detected_mcp = scaffold.detect_mcp_targets(root)

    if requested is None:
        if sys.stdin.isatty():
            requested = _interactive_target_choice(detected_cli, detected_mcp)
        else:
            requested = "claude"

    if requested == "auto":
        all_detected = detected_cli + [t for t in detected_mcp if t not in detected_cli]
        if not all_detected:
            typer.echo(
                "[codebase-index] no targets detected. "
                f"Use --target with one of: {', '.join(scaffold.ALL_TARGETS)}, all.",
                err=True,
            )
            raise typer.Exit(code=4)
        typer.echo(f"Detected targets: {', '.join(all_detected)}")
        return (
            [t for t in all_detected if t in scaffold.CLI_TARGETS],
            [t for t in all_detected if t in scaffold.MCP_TARGETS],
        )

    if requested == "all":
        return list(scaffold.CLI_TARGETS), list(scaffold.MCP_TARGETS)

    if requested in scaffold.CLI_TARGETS:
        return [requested], []

    if requested in scaffold.MCP_TARGETS:
        return [], [requested]

    typer.echo(
        f"[codebase-index] invalid target '{requested}'. "
        f"Valid: {', '.join(scaffold.ALL_TARGETS)}, auto, all.",
        err=True,
    )
    raise typer.Exit(code=2)


def _try_auto_update_skills(root_opt: Optional[Path]) -> None:
    """Silently update all installed skills when the package version changed."""
    if os.environ.get("CBX_NO_SKILL_AUTO_UPDATE") == "1":
        return
    try:
        from .config import find_root
        from . import scaffold
        from .skill_update import auto_update_if_needed

        root = Path(root_opt).resolve() if root_opt else find_root()
        for target in scaffold.CLI_TARGETS:
            auto_update_if_needed(root, target)
    except Exception:
        pass  # never let an auto-update failure crash the real command


@app.callback()
def main(
    ctx: typer.Context,
    root: Optional[Path] = typer.Option(None, "--root", help="Project root (default: discover from cwd)."),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
    quiet: bool = typer.Option(False, "--quiet", help="Suppress progress output."),
) -> None:
    ctx.obj = {"root": root, "json": json_out, "quiet": quiet}
    _try_auto_update_skills(root)


# --- lifecycle ----------------------------------------------------------------------------------
@app.command()
def init(
    ctx: typer.Context,
    force: bool = typer.Option(False, "--force", help="Overwrite an existing install."),
    with_hooks: bool = typer.Option(
        False,
        "--with-hooks/--no-hooks",
        help="Also write and merge the Claude Code auto-update hook.",
    ),
    target: Optional[str] = typer.Option(
        None,
        "--target",
        help=(
            "Target to install: claude, codex, opencode (skill-based) | "
            "cursor, claude-desktop, zed, vscode, windsurf (MCP config) | "
            "auto (detect) | all. Prompts when interactive."
        ),
    ),
) -> None:
    """Scaffold skill/MCP config, config.json, and .gitignore rules into the current project."""
    from . import scaffold
    from .config import find_root

    root_opt = ctx.obj.get("root") if ctx.obj else None
    root = Path(root_opt).resolve() if root_opt else find_root()
    cli_targets, mcp_targets = _resolve_init_targets(root, target)

    lines: list[str] = []

    # Install skill targets (claude / codex / opencode)
    for name in cli_targets:
        try:
            scaffold.install_target(root, name, force=force)
        except FileExistsError as exc:
            typer.echo(
                f"[codebase-index] '{name}' already installed at {exc.args[0]}. "
                "Re-run with --force to overwrite."
            )
            raise typer.Exit(code=1)
        lines.append(f"Installed {name:<14} (skill) -> {root / scaffold.skill_rel_for_target(name)}")

    # Install MCP config targets
    for name in mcp_targets:
        try:
            cfg_file, written = scaffold.install_mcp_target(root, name, force=force)
        except RuntimeError as exc:
            typer.echo(f"[codebase-index] {name}: {exc}", err=True)
            continue
        state = "written" if written else "already present"
        lines.append(f"Installed {name:<14} (MCP)   -> {cfg_file}  [{state}]")

    cfg_path = scaffold.write_config(root, force=force)
    gitignore_changed = scaffold.merge_gitignore(root)

    lines += [
        f"Wrote config      -> {cfg_path}",
        f".gitignore        -> {'updated' if gitignore_changed else 'already covered'}",
    ]

    if with_hooks:
        if "claude" not in cli_targets:
            lines.append("Auto-update hook  -> skipped (hooks are Claude Code settings)")
        else:
            hook_path = scaffold.write_hooks_example(root)
            merged = scaffold.merge_hook_settings(root)
            state = "enabled in .claude/settings.json" if merged else "already enabled"
            lines.append(f"Auto-update hook  -> {state}")
            lines.append(f"Hook example      -> {hook_path} (reference copy)")

    has_mcp = bool(mcp_targets)
    lines += [
        "",
        "Next steps:",
        "  1. codebase-index index      # build the index",
        "  2. codebase-index stats       # verify coverage",
    ]
    if has_mcp:
        lines.append("  3. Restart your editor — the MCP server will be discovered automatically.")
    else:
        lines.append("  3. Ask a codebase question in your CLI — the installed instructions will invoke it.")
    typer.echo("\n".join(lines))


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
                    "symbols": stats.symbols,
                    "parse_failed": stats.parse_failed,
                    "treesitter_zero_symbols": stats.treesitter_zero_symbols,
                }
            )
        )
    elif not (ctx.obj and ctx.obj.get("quiet")):
        typer.echo(f"Indexed {stats.indexed} files ({stats.deleted} pruned).")
        if stats.parse_failed or stats.treesitter_zero_symbols:
            typer.echo(
                f"  parse failures: {stats.parse_failed}; "
                f"tree-sitter files with 0 symbols: {stats.treesitter_zero_symbols}"
            )


@app.command()
def update(
    ctx: typer.Context,
    since: Optional[str] = typer.Option(None, "--since", help="Re-index files changed since a git ref."),
    all_files: bool = typer.Option(False, "--all", help="Force re-check (hash) of every file."),
) -> None:
    """Incremental re-index (mtime/sha/git aware). Safe to call from a hook or watcher."""
    import json as _json

    from .config import load
    from .indexer.pipeline import update_index
    from .storage.db import Database

    is_json = bool(ctx.obj and ctx.obj.get("json"))
    quiet = bool(ctx.obj and ctx.obj.get("quiet"))

    cfg = load(ctx.obj.get("root") if ctx.obj else None)
    db_path = Path(cfg.root) / ".claude" / "cache" / "codebase-index" / "index.sqlite"
    if not db_path.exists():
        if is_json:
            typer.echo(_json.dumps({"indexed": 0, "deleted": 0, "skipped": 0, "exists": False}))
        elif not quiet:
            typer.echo("No index found. Run `codebase-index index` first.")
        raise typer.Exit(code=0)

    with Database(db_path) as db:
        stats = update_index(cfg, db, root=Path(cfg.root), since=since, all_files=all_files)

    if is_json:
        typer.echo(
            _json.dumps(
                {"indexed": stats.indexed, "deleted": stats.deleted, "skipped": stats.skipped}
            )
        )
    elif not quiet:
        typer.echo(
            f"Updated {stats.indexed} file(s); {stats.deleted} pruned; {stats.skipped} unchanged."
        )


# --- retrieval (read-only; these are what the skill calls) --------------------------------------
@app.command()
def search(
    ctx: typer.Context,
    query: str = typer.Argument(..., help="Search query."),
    limit: int = typer.Option(10, "--limit"),
    offset: int = typer.Option(
        0, "--offset", help="Skip the first N results (use pagination.next_offset to page)."
    ),
    token_budget: int = typer.Option(1500, "--token-budget"),
    mode: str = typer.Option("hybrid", "--mode", help="hybrid|fts|symbol|vector"),
    no_fallback: bool = typer.Option(False, "--no-fallback"),
    json_out: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Hybrid ranked search; returns compact results + recommended_reads."""
    from .output import json as json_renderer
    from .output import markdown as md_renderer
    from .service import search_payload

    if offset < 0:
        typer.echo("[codebase-index] --offset must be >= 0.")
        raise typer.Exit(code=2)

    backend = None
    if mode in ("vector", "hybrid"):
        backend = _resolve_backend_for_search(ctx)
        if mode == "vector" and not getattr(backend, "enabled", False):
            typer.echo(
                "[codebase-index] vector mode needs embeddings.enabled = true and the "
                "[embeddings] extra. Use --mode hybrid or enable embeddings."
            )
            raise typer.Exit(code=2)

    db_path, cfg = _ensure_index(ctx)
    payload = search_payload(
        db_path, cfg, query, mode=mode, limit=limit, offset=offset,
        token_budget=token_budget, no_fallback=no_fallback, backend=backend,
    )

    want_json = json_out or (ctx.obj and ctx.obj.get("json"))
    typer.echo(json_renderer.render(payload) if want_json else md_renderer.render(payload))


@app.command()
def symbol(
    ctx: typer.Context,
    name: str = typer.Argument(...),
    kind: Optional[str] = typer.Option(None, "--kind", help="Filter by symbol kind."),
    exact: bool = typer.Option(False, "--exact"),
    json_flag: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Locate a symbol definition by name."""
    from .output import json as json_out
    from .output import markdown as md_out
    from .retrieval.searchers import symbol_lookup
    from .storage.db import Database

    is_json = json_flag or bool(ctx.obj and ctx.obj.get("json"))
    db_path, _cfg = _ensure_index(ctx)

    with Database(db_path) as db:
        resp = symbol_lookup(db.conn, name, kind=kind, exact=exact)
    typer.echo(json_out.render(resp) if is_json else md_out.render_symbols(resp))


@app.command()
def refs(
    ctx: typer.Context,
    symbol_name: str = typer.Argument(...),
    kind: str = typer.Option("all", "--kind", help="callers|all"),
    json_flag: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Find references / callers of a symbol."""
    from .output import json as json_out
    from .output import markdown as md_out
    from .retrieval.searchers import refs_lookup
    from .storage.db import Database

    is_json = json_flag or bool(ctx.obj and ctx.obj.get("json"))
    db_path, _cfg = _ensure_index(ctx)

    with Database(db_path) as db:
        resp = refs_lookup(db.conn, symbol_name, kind=kind)
    typer.echo(json_out.render(resp) if is_json else md_out.render_refs(resp))


@app.command()
def impact(
    ctx: typer.Context,
    target: str = typer.Argument(..., help="File path or symbol name."),
    depth: int = typer.Option(2, "--depth"),
    direction: str = typer.Option("up", "--direction", help="up|down|both"),
    json_flag: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Blast radius: what is affected if `target` changes (graph walk)."""
    from .graph.expand import impact_lookup
    from .output import json as json_out
    from .output import markdown as md_out
    from .storage.db import Database

    is_json = json_flag or bool(ctx.obj and ctx.obj.get("json"))
    db_path, _cfg = _ensure_index(ctx)

    with Database(db_path) as db:
        resp = impact_lookup(db.conn, target, depth=depth, direction=direction)
    typer.echo(json_out.render(resp) if is_json else md_out.render_impact(resp))


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
    from .service import normalize_explain_query, search_payload

    backend = _resolve_backend_for_search(ctx)
    db_path, cfg = _ensure_index(ctx)

    payload = search_payload(
        db_path, cfg, normalize_explain_query(query), mode="hybrid", limit=10,
        token_budget=token_budget, no_fallback=False, backend=backend,
    )

    want_json = json_out or (ctx.obj and ctx.obj.get("json"))
    typer.echo(json_renderer.render(payload) if want_json else md_renderer.render(payload))


@app.command("graph")
def graph_view(
    ctx: typer.Context,
    target: Optional[str] = typer.Argument(None, help="Optional file path or symbol to center."),
    depth: int = typer.Option(2, "--depth"),
    direction: str = typer.Option("both", "--direction", help="up|down|both"),
    output: Optional[Path] = typer.Option(None, "--output", "-o", help="HTML file path."),
    open_browser: bool = typer.Option(False, "--open", help="Open the HTML graph in a browser."),
    json_flag: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Export an interactive HTML graph of indexed files, symbols, and edges."""
    import json as _json

    from .graph.export import export_graph_html
    from .service import cache_dir_for
    from .storage.db import Database

    is_json = json_flag or bool(ctx.obj and ctx.obj.get("json"))
    db_path, cfg = _ensure_index(ctx)
    out = output or cache_dir_for(cfg) / "graph.html"

    with Database(db_path) as db:
        stats = export_graph_html(
            db.conn,
            out,
            target=target,
            depth=depth,
            direction=direction,
        )

    if open_browser:
        _open_in_browser(out)

    payload = {
        "path": str(out),
        "target": target,
        "depth": depth,
        "direction": direction,
        **stats,
    }
    if is_json:
        typer.echo(_json.dumps(payload))
    else:
        typer.echo(f"Graph written to {out}")
        typer.echo(f"nodes={stats['nodes']} edges={stats['edges']}")


# --- diagnostics / maintenance ------------------------------------------------------------------
@app.command()
def stats(
    ctx: typer.Context,
    json_flag: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Index size, coverage %, and freshness."""
    import json as _json

    from .service import resolve_db, stats_payload
    from .storage.db import Database

    root_opt = ctx.obj.get("root") if ctx.obj else None
    db_path, _cfg = resolve_db(root_opt)

    is_json = json_flag or bool(ctx.obj and ctx.obj.get("json"))

    if not db_path.exists():
        if is_json:
            typer.echo(_json.dumps({"files": 0, "built_at": None, "exists": False}))
        else:
            typer.echo("No index found. Run `codebase-index index`.")
        raise typer.Exit(code=0)

    with Database(db_path) as db:
        payload = stats_payload(db.conn)

    if is_json:
        typer.echo(_json.dumps(payload))
    else:
        typer.echo(
            f"files={payload['files']}  symbols={payload['symbols']}  "
            f"built_at={payload['built_at']}  head={payload['head_commit']}"
        )
        for r in payload["treesitter_coverage"]:
            flag = "  ⚠ 0 symbols" if (r["symbols"] or 0) == 0 and r["files"] >= 3 else ""
            tier = "  · partial graph (Tier-B)" if r["graph"] == "partial" else ""
            typer.echo(f"  {r['lang']}: {r['files']} files, {r['symbols']} symbols{flag}{tier}")


@app.command()
def doctor(
    ctx: typer.Context,
    strict: bool = typer.Option(False, "--strict", help="Exit non-zero on high-severity findings."),
    json_flag: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Diagnose configuration and security issues (see docs/SECURITY.md)."""
    import json as _json

    from .config import load
    from .doctor import has_high_severity_failure, run_doctor

    cfg = load(ctx.obj.get("root") if ctx.obj else None)
    findings = run_doctor(Path(cfg.root), cfg)

    is_json = json_flag or bool(ctx.obj and ctx.obj.get("json"))
    if is_json:
        typer.echo(
            _json.dumps(
                {
                    "findings": [
                        {"id": f.id, "ok": f.ok, "severity": f.severity, "detail": f.detail}
                        for f in findings
                    ]
                }
            )
        )
    else:
        for f in findings:
            mark = "OK " if f.ok else ("!! " if f.severity == "high" else "-- ")
            typer.echo(f"{mark}[{f.severity}] {f.id}: {f.detail}")

    if strict and has_high_severity_failure(findings):
        raise typer.Exit(code=1)


@app.command()
def mcp(
    ctx: typer.Context,
    transport: str = typer.Option("stdio", "--transport", help="Transport: stdio (default)."),
) -> None:
    """Start the MCP server — exposes codebase-index tools to any MCP client (e.g. Claude Code).

    Add to .claude/settings.json:

    \\b
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
    try:
        from .mcp.server import mcp as _mcp
    except ImportError:
        typer.echo(
            "[codebase-index] MCP server needs the optional extra:\n"
            "  pip install codebase-index[mcp]",
            err=True,
        )
        raise typer.Exit(code=1)

    root_opt = ctx.obj.get("root") if ctx.obj else None
    if root_opt:
        import os
        os.environ.setdefault("CBX_ROOT", str(root_opt))

    _mcp.run(transport=transport)  # type: ignore[arg-type]


@app.command()
def clean(yes: bool = typer.Option(False, "--yes", help="Skip confirmation.")) -> None:
    """Remove the per-project cache (keeps the skill)."""
    _todo("clean")


@app.command()
def watch(
    ctx: typer.Context,
    debounce: int = typer.Option(500, "--debounce", help="Debounce window in ms."),
) -> None:
    """Live incremental indexing via filesystem events (requires the 'watch' extra)."""
    from .service import resolve_db
    from .watch.watcher import run_watch

    db_path, cfg = resolve_db(ctx.obj.get("root") if ctx.obj else None)
    if not db_path.exists():
        typer.echo("No index found. Run `codebase-index index` before `watch`.")
        raise typer.Exit(code=1)

    try:
        run_watch(config=cfg, db_path=db_path, debounce_ms=debounce)
    except RuntimeError as exc:
        typer.echo(str(exc))
        raise typer.Exit(code=1)


@app.command("skill-update")
def skill_update(
    ctx: typer.Context,
    target: Optional[str] = typer.Option(
        None,
        "--target",
        help="Skill target to update: claude, codex, opencode (default: all installed).",
    ),
    no_backup: bool = typer.Option(False, "--no-backup", help="Skip backup before updating."),
    force: bool = typer.Option(False, "--force", help="Update even if already on the latest version."),
    json_flag: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Update installed skill(s) to match the current package version."""
    import json as _json

    from .config import find_root
    from . import scaffold
    from .skill_update import needs_update, update_skill

    is_json = json_flag or bool(ctx.obj and ctx.obj.get("json"))
    root_opt = ctx.obj.get("root") if ctx.obj else None
    root = Path(root_opt).resolve() if root_opt else find_root()

    targets = [target] if target else list(scaffold.CLI_TARGETS)
    results = []

    for t in targets:
        skill_dir = root / scaffold.skill_rel_for_target(t)
        if not skill_dir.exists():
            results.append({"target": t, "updated": False, "reason": "not installed"})
            continue

        if not force and not needs_update(skill_dir):
            results.append({"target": t, "updated": False, "reason": "already up to date"})
            if not is_json:
                typer.echo(f"[skill-update] {t}: already up to date")
            continue

        res = update_skill(root, t, backup=not no_backup)
        results.append(res)
        if not is_json:
            backed = " (backup saved)" if res["backed_up"] else ""
            typer.echo(
                f"[skill-update] {t}: {res['old_version'] or 'unknown'} -> {res['new_version']}{backed}"
            )

    if is_json:
        typer.echo(_json.dumps(results))


@app.command("skill-rollback")
def skill_rollback(
    ctx: typer.Context,
    target: Optional[str] = typer.Option(
        None,
        "--target",
        help="Skill target to roll back: claude, codex, opencode (default: all with a backup).",
    ),
    json_flag: bool = typer.Option(False, "--json", help="Emit machine-readable JSON."),
) -> None:
    """Restore the last backed-up version of the installed skill(s)."""
    import json as _json

    from .config import find_root
    from . import scaffold
    from .skill_update import rollback_skill

    is_json = json_flag or bool(ctx.obj and ctx.obj.get("json"))
    root_opt = ctx.obj.get("root") if ctx.obj else None
    root = Path(root_opt).resolve() if root_opt else find_root()

    targets = [target] if target else list(scaffold.CLI_TARGETS)
    results = []

    for t in targets:
        res = rollback_skill(root, t)
        results.append(res)
        if not is_json:
            if res["rolled_back"]:
                typer.echo(f"[skill-rollback] {t}: restored from backup")
            else:
                typer.echo(f"[skill-rollback] {t}: {res.get('reason', 'failed')}")

    if is_json:
        typer.echo(_json.dumps(results))


if __name__ == "__main__":
    app()
