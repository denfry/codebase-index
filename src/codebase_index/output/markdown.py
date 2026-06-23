"""Compact Markdown renderer for SearchResponse and dict payloads."""

from __future__ import annotations

from typing import Optional

from ..models import ImpactResponse, RefsResponse, SearchResponse, SymbolResponse


def render(resp: SearchResponse | dict) -> str:
    if isinstance(resp, dict):
        return _render_dict(resp)
    return _render_search_response(resp)


def _render_dict(payload: dict) -> str:
    lines: list[str] = []
    lines.append(f"**Query:** {payload['query']}  ")
    lines.append(
        f"**Intent:** `{payload['intent']}` · **Confidence:** {payload['confidence']}\n"
    )

    if payload["results"]:
        lines.append("| # | Path | Lines | Reason |")
        lines.append("|---|------|-------|--------|")
        for r in payload["results"]:
            lines.append(
                f"| {r['rank']} | `{r['path']}` | {r['line_start']}-{r['line_end']} "
                f"| {r.get('reason', '')} |"
            )
        lines.append("")
        for r in payload["results"]:
            if r.get("snippet"):
                lines.append(f"`{r['path']}:{r['line_start']}-{r['line_end']}`")
                lines.append("```")
                lines.append(r["snippet"])
                lines.append("```")

    if payload["recommended_reads"]:
        lines.append("\n**Recommended reads:**")
        for rr in payload["recommended_reads"]:
            lines.append(f"- `{rr['path']}:{rr['line_start']}-{rr['line_end']}`")

    fb = payload.get("fallback_suggestions", {}).get("ripgrep")
    if fb:
        lines.append("\n**Fallback (low confidence) — try:**")
        for cmd in fb:
            lines.append(f"- `{cmd}`")

    pg = payload.get("pagination")
    if pg:
        shown = f"results {pg['offset'] + 1}–{pg['offset'] + len(payload['results'])}"
        if pg.get("has_more"):
            lines.append(f"\n_Showing {shown}; more available — `--offset {pg['next_offset']}`._")
        else:
            lines.append(f"\n_Showing {shown} (end of results)._")

    return "\n".join(lines)


def _render_search_response(resp: SearchResponse) -> str:
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


def _coverage_line(coverage) -> Optional[str]:
    if coverage is not None and getattr(coverage, "partial", False):
        return f"\n> ⚠️ Partial graph coverage: {coverage.reason}"
    return None


# Audit-trail glyphs: an exact edge needs no annotation; inferred/ambiguous ones
# warn the reader that the link is a heuristic or could not be pinned down.
_CONF_MARK = {"extracted": "", "inferred": "~ inferred", "ambiguous": "? ambiguous"}


def _conf_mark(confidence: Optional[str]) -> str:
    return _CONF_MARK.get(confidence or "extracted", confidence or "")


def render_refs(resp: RefsResponse) -> str:
    lines = [_header(resp.query, resp.index.exists, resp.index.stale)]
    lines.append("")
    note = _coverage_line(resp.coverage)
    if not resp.sites:
        lines.append("_No references found._")
        if note:
            lines.append(note)
        return "\n".join(lines).rstrip() + "\n"

    lines.append("| kind | path | line | confidence |")
    lines.append("|------|------|------|------------|")
    for site in resp.sites:
        lines.append(
            f"| {site.kind} | `{site.path}` | {site.line} | {_conf_mark(site.confidence) or 'exact'} |"
        )
    if note:
        lines.append(note)
    return "\n".join(lines).rstrip() + "\n"


def _header(query: str, exists: bool, stale: bool) -> str:
    freshness = "fresh" if not stale else "STALE"
    if not exists:
        freshness = "NO INDEX"
    return f"**query:** {query}  |  **index:** {freshness}"


def render_impact(resp: ImpactResponse) -> str:
    header = (f"**impact:** `{resp.target}`  ·  **direction:** {resp.direction}  ·  "
              f"**depth:** {resp.depth}  ·  **affected files:** {len(resp.files)}")
    lines = [header, ""]
    note = _coverage_line(resp.coverage)
    if not resp.nodes:
        body = ["_No impact found (target unknown or no edges)._"]
        if note:
            body.append(note)
        return "\n".join(lines + body + [""]).rstrip() + "\n"
    lines.append("| dist | via | kind | node | location |")
    lines.append("|------|-----|------|------|----------|")
    for n in sorted(resp.nodes, key=lambda x: (x.distance, x.path, x.line_start or 0)):
        loc = f"{n.path}:{n.line_start}" if n.line_start else n.path
        node_name = f"`{n.name}`" if n.name else "—"
        mark = _conf_mark(n.via_confidence)
        via = f"{n.via_edge or ''} {mark}".strip()
        lines.append(f"| {n.distance} | {via} | {n.kind} | {node_name} | `{loc}` |")
    if note:
        lines.append(note)
    return "\n".join(lines).rstrip() + "\n"
