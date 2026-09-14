"""Walk the project root and yield indexable candidates."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

from ..config import Config
from . import classify
from .gates import BINARY_SNIFF_BYTES, PathGate


@dataclass
class Candidate:
    path: Path
    rel_path: str
    size_bytes: int
    lang: Optional[str]
    parser: str
    is_generated: bool


def walk(root: Path, config: Config) -> Iterator[Candidate]:
    root = Path(root).resolve()
    gate = PathGate(root, config)

    for dirpath, dirnames, filenames in os.walk(root):
        kept: list[str] = []
        for d in dirnames:
            rel_dir = _rel(root, Path(dirpath) / d)
            if rel_dir is not None and gate.dir_allowed(d, rel_dir):
                kept.append(d)
        dirnames[:] = kept

        for fname in filenames:
            abs_path = Path(dirpath) / fname
            rel = _rel(root, abs_path)
            if rel is None:
                continue

            if gate.name_rejection(rel):
                continue
            try:
                size = abs_path.stat().st_size
            except OSError:
                continue
            if size > gate.max_file_bytes:
                continue
            try:
                with abs_path.open("rb") as fh:
                    head = fh.read(BINARY_SNIFF_BYTES)
            except OSError:
                continue
            if gate.content_rejection(size, head):
                continue

            lang = classify.detect_language(rel)
            yield Candidate(
                path=abs_path,
                rel_path=rel,
                size_bytes=size,
                lang=lang,
                parser=classify.parser_for(lang),
                is_generated=classify.is_generated(rel),
            )


def _rel(root: Path, path: Path) -> Optional[str]:
    """Root-relative POSIX path of ``path``, or ``None`` if it resolves outside ``root``.

    ``os.walk`` lists symlinks lexically under ``root``, but a link may point elsewhere
    (Bazel's ``bazel-out`` convenience symlinks are the common case). Such entries are
    skipped rather than raising, matching the gate's "resolves outside the repository"
    exclusion.
    """
    try:
        return path.resolve().relative_to(root).as_posix()
    except (ValueError, OSError):
        return None
