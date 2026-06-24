"""Configuration loading, merging, and validation.

Resolution order (later wins): built-in defaults -> .claude/cache/codebase-index/config.json ->
environment overrides (CBX_*) -> CLI flags. A stable `config_hash` is computed over indexing-
relevant fields; when it changes, the indexer knows to rebuild affected rows (see SCHEMA.md).
"""

from __future__ import annotations

import hashlib
import json
import os
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
    compact_snippets: bool = True
    compact_min_reduction: float = 0.25


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
        relevant = {
            "root": self.root,
            "languages": self.languages,
            "max_file_bytes": self.max_file_bytes,
            "ignore_files": self.ignore_files,
            "extra_ignore": self.extra_ignore,
            "chunk": self.chunk.model_dump(),
            "redaction": self.redaction,
            "embeddings": {
                "enabled": self.embeddings.enabled,
                "backend": self.embeddings.backend,
                "model": self.embeddings.model,
            },
        }
        blob = json.dumps(relevant, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(blob.encode("utf-8")).hexdigest()


_ROOT_MARKERS = (".git", ".claude")


def find_root(start: Optional[Path] = None) -> Path:
    """Find the nearest project root marker, or fall back to the start directory."""
    start = (start or Path.cwd()).resolve()
    home = Path.home().resolve()
    for candidate in (start, *start.parents):
        if (candidate / ".git").exists():
            return candidate
        if candidate != home and (candidate / ".claude").exists():
            return candidate
    return start


def _config_path(root: Path) -> Path:
    return root / ".claude" / "cache" / "codebase-index" / "config.json"


def load(root: Optional[Path] = None) -> Config:
    """Discover the project root and return the resolved, validated Config."""
    resolved_root = Path(root).resolve() if root is not None else find_root()
    data: dict = {}
    cfg_file = _config_path(resolved_root)
    if cfg_file.is_file():
        data = json.loads(cfg_file.read_text(encoding="utf-8"))

    if "CBX_MAX_FILE_BYTES" in os.environ:
        data["max_file_bytes"] = int(os.environ["CBX_MAX_FILE_BYTES"])

    cfg = Config(**data)
    cfg.root = str(resolved_root)
    return cfg
