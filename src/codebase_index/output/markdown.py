"""Compact Markdown renderer for SearchResponse."""

from __future__ import annotations

from ..models import SearchResponse


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
