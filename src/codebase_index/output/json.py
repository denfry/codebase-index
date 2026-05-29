"""Machine-readable JSON renderer for pydantic response models and dict payloads."""

from __future__ import annotations

import json

from pydantic import BaseModel


def render(resp: BaseModel | dict) -> str:
    if isinstance(resp, dict):
        return json.dumps(resp, indent=2, ensure_ascii=False)
    return resp.model_dump_json(indent=2)
