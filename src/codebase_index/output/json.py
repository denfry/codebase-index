"""Machine-readable JSON renderer for SearchResponse."""

from __future__ import annotations

from ..models import SearchResponse


def render(resp: SearchResponse) -> str:
    return resp.model_dump_json(indent=2)
