"""Machine-readable JSON renderer for pydantic response models."""

from __future__ import annotations

from pydantic import BaseModel


def render(resp: BaseModel) -> str:
    return resp.model_dump_json(indent=2)
