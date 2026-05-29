from __future__ import annotations

import json as _json

from codebase_index.models import (
    IndexFreshness,
    ReadRange,
    RefSite,
    RefsResponse,
    Result,
    SearchResponse,
    SymbolDef,
    SymbolResponse,
)
from codebase_index.output import json as json_out
from codebase_index.output import markdown as md_out


def _resp() -> SearchResponse:
    return SearchResponse(
        query="bootstrap",
        intent="keyword",
        index=IndexFreshness(
            exists=True, stale=False, built_at="2026-05-29T00:00:00Z"
        ),
        confidence="high",
        results=[
            Result(
                rank=1,
                path="web/app.ts",
                line_start=1,
                line_end=3,
                symbols=[],
                score=1.0,
                reason="lexical match (bm25)",
                snippet="export function bootstrap(): void {}",
            )
        ],
        recommended_reads=[ReadRange(path="web/app.ts", line_start=1, line_end=3)],
        fallback_suggestions={},
    )


def test_json_renderer_round_trips():
    text = json_out.render(_resp())
    data = _json.loads(text)
    assert data["query"] == "bootstrap"
    assert data["results"][0]["path"] == "web/app.ts"
    assert data["index"]["exists"] is True


def test_markdown_renderer_contains_key_fields():
    text = md_out.render(_resp())
    assert "web/app.ts" in text
    assert "1-3" in text
    assert "bootstrap" in text
    assert "high" in text.lower()


def test_json_render_accepts_symbol_response():
    resp = SymbolResponse(
        query="User",
        index=IndexFreshness(exists=True, stale=False, built_at="t"),
        symbols=[
            SymbolDef(
                name="User",
                kind="class",
                path="src/models/user.py",
                line_start=4,
                line_end=6,
                signature="class User:",
            )
        ],
    )
    data = _json.loads(json_out.render(resp))
    assert data["symbols"][0]["name"] == "User"


def test_markdown_render_symbols():
    resp = SymbolResponse(
        query="User",
        index=IndexFreshness(exists=True, stale=False, built_at="t"),
        symbols=[
            SymbolDef(
                name="User",
                kind="class",
                path="src/models/user.py",
                line_start=4,
                line_end=6,
                signature="class User:",
            )
        ],
    )
    text = md_out.render_symbols(resp)
    assert "User" in text and "src/models/user.py" in text and "class" in text


def test_markdown_render_refs():
    resp = RefsResponse(
        query="f",
        index=IndexFreshness(exists=True, stale=False, built_at="t"),
        sites=[
            RefSite(path="a.py", line=10, kind="call"),
            RefSite(path="a.py", line=2, kind="definition"),
        ],
    )
    text = md_out.render_refs(resp)
    assert "a.py" in text and "10" in text and "definition" in text
