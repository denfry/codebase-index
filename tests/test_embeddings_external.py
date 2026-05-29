# tests/test_embeddings_external.py
from __future__ import annotations

from codebase_index.embeddings.external import ExternalBackend


def test_external_uses_injected_transport_no_network():
    calls: list[dict] = []

    def fake_transport(endpoint: str, api_key: str, model: str, texts: list[str]):
        calls.append({"endpoint": endpoint, "api_key": api_key, "model": model, "texts": texts})
        return [[0.1, 0.2, 0.3] for _ in texts]

    backend = ExternalBackend(
        endpoint="https://example.test/embed",
        api_key="sk-test",
        model_name="text-embedding-3-small",
        transport=fake_transport,
    )
    vecs = backend.embed(["a", "b"])
    assert vecs == [[0.1, 0.2, 0.3], [0.1, 0.2, 0.3]]
    assert backend.dim == 3
    assert calls and calls[0]["endpoint"] == "https://example.test/embed"
    assert calls[0]["api_key"] == "sk-test"
