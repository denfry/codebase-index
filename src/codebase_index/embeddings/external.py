# src/codebase_index/embeddings/external.py
"""External embedding API backend. Constructed ONLY via resolve_backend after the
SECURITY.md §4 gates pass. The network call is isolated in a transport callable so
it can be tested without hitting the network and swapped per provider.
"""

from __future__ import annotations

import json
from typing import Callable, Optional
from urllib.request import Request, urlopen

from .backend import EmbeddingError

Transport = Callable[[str, str, str, list[str]], list[list[float]]]


def _http_transport(endpoint: str, api_key: str, model: str, texts: list[str]) -> list[list[float]]:
    body = json.dumps({"model": model, "input": texts}).encode("utf-8")
    req = Request(
        endpoint,
        data=body,
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        method="POST",
    )
    with urlopen(req, timeout=30) as resp:
        payload = json.loads(resp.read().decode("utf-8"))
    return [item["embedding"] for item in payload["data"]]


class ExternalBackend:
    enabled = True

    def __init__(
        self,
        *,
        endpoint: str,
        api_key: str,
        model_name: str,
        transport: Optional[Transport] = None,
    ) -> None:
        self.name = f"external:{model_name}"
        self.model_name = model_name
        self._endpoint = endpoint
        self._api_key = api_key
        self._transport = transport or _http_transport
        self._dim: Optional[int] = None

    @property
    def dim(self) -> int:
        if self._dim is None:
            raise EmbeddingError("External backend dim is unknown until the first embed() call.")
        return self._dim

    def embed(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        vecs = self._transport(self._endpoint, self._api_key, self.model_name, list(texts))
        if not vecs or not vecs[0]:
            raise EmbeddingError("External embedding endpoint returned no vectors.")
        self._dim = len(vecs[0])
        return [[float(x) for x in v] for v in vecs]
