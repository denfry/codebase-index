"""Compact Markdown renderer for SearchResponse."""

from __future__ import annotations

from ..models import RefsResponse, SearchResponse, SymbolResponse


def render(resp: SearchResponse) -> str:
    lines: list[str] = []
    freshness = "fresh" if not resp.index.stale else "STALE"
    if not resp.index.exists:
        freshness = "NO INDEX"
    lines.append(
        f"**query:** {resp.query}  |  **intent:** {resp.intent}  |  "
        f"**confidence:** {resp.confidence}  |  **index:** {freshness}"
    )
    lines.append("")

    if resp.results:
        lines.append("| # | path | lines | reason |")
        lines.append("|---|------|-------|--------|")
        for result in resp.results:
            symbols = f" `{','.join(result.symbols)}`" if result.symbols else ""
            lines.append(
                f"| {result.rank} | `{result.path}`{symbols} | "
                f"{result.line_start}-{result.line_end} | {result.reason} |"
            )
        lines.append("")
        for result in resp.results:
            if result.snippet:
                lines.append(f"`{result.path}:{result.line_start}-{result.line_end}`")
                lines.append("```")
                lines.append(result.snippet)
                lines.append("```")
        lines.append("")
    else:
        lines.append("_No index matches._")
        lines.append("")

    if resp.recommended_reads:
        lines.append("**recommended reads:**")
        for read in resp.recommended_reads:
            lines.append(f"- `{read.path}:{read.line_start}-{read.line_end}`")
        lines.append("")

    if resp.fallback_suggestions:
        lines.append("**fallback:**")
        for commands in resp.fallback_suggestions.values():
            for command in commands:
                lines.append(f"- `{command}`")

    return "\n".join(lines).rstrip() + "\n"


def render_symbols(resp: SymbolResponse) -> str:
    lines = [_header(resp.query, resp.index.exists, resp.index.stale)]
    lines.append("")
    if not resp.symbols:
        lines.append("_No symbol definitions found._")
        return "\n".join(lines).rstrip() + "\n"

    lines.append("| name | kind | path | lines | signature |")
    lines.append("|------|------|------|-------|-----------|")
    for symbol in resp.symbols:
        display = symbol.qualified or symbol.name
        signature = symbol.signature or ""
        lines.append(
            f"| `{display}` | {symbol.kind} | `{symbol.path}` | "
            f"{symbol.line_start}-{symbol.line_end} | `{signature}` |"
        )
    return "\n".join(lines).rstrip() + "\n"


def render_refs(resp: RefsResponse) -> str:
    lines = [_header(resp.query, resp.index.exists, resp.index.stale)]
    lines.append("")
    if not resp.sites:
        lines.append("_No references found._")
        return "\n".join(lines).rstrip() + "\n"

    lines.append("| kind | path | line |")
    lines.append("|------|------|------|")
    for site in resp.sites:
        lines.append(f"| {site.kind} | `{site.path}` | {site.line} |")
    return "\n".join(lines).rstrip() + "\n"


def _header(query: str, exists: bool, stale: bool) -> str:
    freshness = "fresh" if not stale else "STALE"
    if not exists:
        freshness = "NO INDEX"
    return f"**query:** {query}  |  **index:** {freshness}"
