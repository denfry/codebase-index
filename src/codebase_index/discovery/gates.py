"""Discovery gates shared by indexing and by every later read of the working tree.

A path the indexer refuses (ignored, dependency/build directory, secret filename,
oversized, binary) must be refused identically wherever else the tool reads files.
Keeping a single implementation is how that stays true: the walker and evidence
validation both go through `PathGate`.
"""

from __future__ import annotations

import stat as stat_mod
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from ..config import Config
from . import classify
from .ignore import IgnoreMatcher

BINARY_SNIFF_BYTES = 4096


@dataclass(frozen=True)
class GateRead:
    """Outcome of reading one repo-relative file through the gates.

    ``state`` is ``ok`` (``data`` holds the bytes), ``excluded`` (a gate refused it and the
    file was not opened unless the refusal is content-based), ``deleted`` or ``unreadable``.
    """

    state: str
    data: bytes = b""
    reason: str = ""


class PathGate:
    def __init__(self, root: Path | str, config: Config) -> None:
        self.root = Path(root).resolve()
        self.max_file_bytes = config.max_file_bytes
        self.matcher = IgnoreMatcher.from_root(
            self.root,
            ignore_files=config.ignore_files,
            extra_ignore=config.extra_ignore,
        )

    # -- the walker's gates, in the walker's order -----------------------------------
    def dir_allowed(self, name: str, rel_dir: str) -> bool:
        return not self.matcher.is_ignored_dir(name) and not self.matcher.is_ignored(
            rel_dir + "/"
        )

    def name_rejection(self, rel: str) -> Optional[str]:
        if self.matcher.is_ignored(rel):
            return "ignored by an ignore file or the built-in denylist"
        if classify.is_secret_filename(rel):
            return "secret-like filename"
        return None

    def content_rejection(self, size: int, head: bytes) -> Optional[str]:
        if size > self.max_file_bytes:
            return "larger than max_file_bytes"
        if classify.looks_binary(head):
            return "binary content"
        return None

    # -- whole-path checks for reads that did not come from a walk -------------------
    def path_rejection(self, rel: str) -> Optional[str]:
        """Every name-based gate for a repo-relative POSIX path, including its directories."""
        parts = rel.split("/")
        for depth in range(1, len(parts)):
            if not self.dir_allowed(parts[depth - 1], "/".join(parts[:depth])):
                return "inside an ignored directory"
        return self.name_rejection(rel)

    def read(self, rel: str) -> GateRead:
        """Read an admitted file, or explain why it is not admitted.

        Name-based gates run before the file is touched. The resolved on-disk path is gated
        again, so a symlink or (on case-insensitive filesystems) a differently-cased path
        cannot reach a file the walker would never have indexed.
        """
        reason = self.path_rejection(rel)
        if reason:
            return GateRead("excluded", reason=reason)
        path = self.root / rel
        try:
            resolved = path.resolve()
        except OSError as exc:
            return GateRead("unreadable", reason=str(exc))
        try:
            actual_rel = resolved.relative_to(self.root).as_posix()
        except ValueError:
            return GateRead("excluded", reason="resolves outside the repository")
        if actual_rel != rel:
            reason = self.path_rejection(actual_rel)
            if reason:
                return GateRead("excluded", reason=reason)
        try:
            st = path.stat()
        except FileNotFoundError:
            return GateRead("deleted", reason="file no longer exists")
        except OSError as exc:
            return GateRead("unreadable", reason=str(exc))
        if not stat_mod.S_ISREG(st.st_mode):
            return GateRead("deleted", reason="no longer a regular file")
        if st.st_size > self.max_file_bytes:
            return GateRead("excluded", reason="larger than max_file_bytes")
        try:
            data = path.read_bytes()
        except FileNotFoundError:
            return GateRead("deleted", reason="file no longer exists")
        except OSError as exc:
            return GateRead("unreadable", reason=str(exc))
        reason = self.content_rejection(len(data), data[:BINARY_SNIFF_BYTES])
        if reason:
            return GateRead("excluded", reason=reason)
        return GateRead("ok", data=data)
