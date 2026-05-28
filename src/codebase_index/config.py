"""Configuration loading, merging, and validation.

Resolution order (later wins): built-in defaults -> .claude/cache/codebase-index/config.json ->
environment overrides (CBX_*) -> CLI flags. A stable `config_hash` is computed over indexing-
relevant fields; when it changes, the indexer knows to rebuild affected rows (see SCHEMA.md).
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Optional, Union

from pydantic import BaseModel


class ChunkConfig(BaseModel):
    window_lines: int = 80
    overlap_lines: int = 10


class RetrievalConfig(BaseModel):
    default_mode: Literal["hybrid", "fts", "symbol", "vector"] = "hybrid"
    rrf_k: int = 60
    token_budget: int = 1500
    limit: int = 10


class EmbeddingsConfig(BaseModel):
    backend: Literal["noop", "local", "external"] = "noop"
    enabled: bool = False
    model: str = "all-MiniLM-L6-v2"
    allow_external: bool = False  # external backend refused unless this is True AND a key is present
    endpoint: Optional[str] = None


class GraphConfig(BaseModel):
    max_depth: int = 2
    node_cap: int = 40


class Config(BaseModel):
    root: str = "."
    languages: Union[Literal["auto"], list[str]] = "auto"
    max_file_bytes: int = 1_048_576
    ignore_files: list[str] = [".gitignore", ".cursorignore", ".claudeignore", ".codeindexignore"]
    extra_ignore: list[str] = []
    chunk: ChunkConfig = ChunkConfig()
    retrieval: RetrievalConfig = RetrievalConfig()
    embeddings: EmbeddingsConfig = EmbeddingsConfig()
    graph: GraphConfig = GraphConfig()
    redaction: dict = {"enabled": True}

    def config_hash(self) -> str:
        """Stable hash over indexing-relevant fields; drives rebuild decisions."""
        raise NotImplementedError


def load(root: Optional[Path] = None) -> Config:
    """Discover the project root and return the resolved, validated Config."""
    raise NotImplementedError
