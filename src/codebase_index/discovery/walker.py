"""Walk the project root and yield indexable candidates."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator, Optional

from ..config import Config
from . import classify
from .ignore import IgnoreMatcher

_BINARY_SNIFF_BYTES = 4096


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
    matcher = IgnoreMatcher.from_root(
        root,
        ignore_files=config.ignore_files,
        extra_ignore=config.extra_ignore,
    )

    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [
            d
            for d in dirnames
            if not matcher.is_ignored_dir(d)
            and not matcher.is_ignored(_rel(root, Path(dirpath) / d) + "/")
        ]

        for fname in filenames:
            abs_path = Path(dirpath) / fname
            rel = _rel(root, abs_path)

            if matcher.is_ignored(rel) or classify.is_secret_filename(rel):
                continue
            try:
                size = abs_path.stat().st_size
            except OSError:
                continue
            if size > config.max_file_bytes:
                continue
            try:
                with abs_path.open("rb") as fh:
                    head = fh.read(_BINARY_SNIFF_BYTES)
            except OSError:
                continue
            if classify.looks_binary(head):
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


def _rel(root: Path, path: Path) -> str:
    return path.resolve().relative_to(root).as_posix()
