"""Evidence identity: the line model, span hashing, and verifiable references.

Pure functions only — no filesystem, no database — so every identity property can be
tested exhaustively and cannot depend on I/O timing.

The line model deliberately mirrors the indexer. It reads files with universal newlines
and slices chunks with ``str.splitlines()`` (parsers/line_chunker.py,
parsers/symbol_chunks.py), so a snippet and the span hashed for it are the same lines.
Two things differ on purpose:

* bytes are decoded with ``surrogateescape`` instead of ``ignore``, so editing an
  undecodable byte still changes the hash;
* only line terminators are normalised. Whitespace, comments and case are part of the
  identity: a strict hash can never equate two different programs.
"""

from __future__ import annotations

import hashlib
import re
import sys
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Optional, Sequence

REF_HASH_CHARS = 16
"""Hex characters of the span hash shown in a reference (64 bits)."""

MIN_REF_HASH_CHARS = 12

_REF_RE = re.compile(r"^(?P<path>.+):(?P<start>\d+)-(?P<end>\d+)@(?P<sha>[0-9a-fA-F]+)$")
_DRIVE_RE = re.compile(r"^[A-Za-z]:")


def split_lines(raw: bytes) -> list[str]:
    """Split file bytes into lines exactly as the chunkers number them."""
    text = raw.decode("utf-8", "surrogateescape")
    if "\r" in text:
        text = text.replace("\r\n", "\n").replace("\r", "\n")
    return text.splitlines()


def _encode(text: str) -> bytes:
    return text.encode("utf-8", "surrogateescape")


def sha_hex(text: str) -> str:
    return hashlib.sha256(_encode(text)).hexdigest()


def span_text(lines: Sequence[str], line_start: int, line_end: int) -> Optional[str]:
    """Text of 1-based inclusive lines, or None when the range is not inside the file."""
    if line_start < 1 or line_end < line_start or line_end > len(lines):
        return None
    return "\n".join(lines[line_start - 1 : line_end])


def span_sha(lines: Sequence[str], line_start: int, line_end: int) -> Optional[str]:
    text = span_text(lines, line_start, line_end)
    return None if text is None else sha_hex(text)


def line_sha(line: str) -> str:
    """Short hash of one line; used only to find relocation candidates, never as proof."""
    return sha_hex(line)[:REF_HASH_CHARS]


def visible_text(text: str) -> str:
    """The text the indexer stored for these lines (undecodable bytes dropped)."""
    return _encode(text).decode("utf-8", "ignore")


def content_matches(index_content: Optional[str], span: str) -> bool:
    """Does text taken from the index still describe these working-tree lines?

    Chunk results store the whole span, so the common case is equality. Symbol and doc
    results store an excerpt (a signature, a heading), which must occur inside the span.
    Either way the snippet delivered to the agent is text that exists in the current
    file at that locator, which is all an evidence atom asserts.
    """
    if not index_content:
        return False
    visible = visible_text(span)
    content = index_content.replace("\r\n", "\n")
    return content == visible or content in visible


def is_full_span(index_content: Optional[str], span: str) -> bool:
    """True when the index text is the entire span rather than an excerpt of it."""
    if not index_content:
        return False
    return index_content.replace("\r\n", "\n") == visible_text(span)


def normalize_rel_path(path: str) -> str:
    """Canonical repo-relative POSIX path, or ValueError for anything that could escape.

    References arrive from agents, notes and other tools, so they are untrusted input: an
    absolute path, a drive letter, a ``..`` segment or a NUL byte is rejected before any
    filesystem access is attempted.
    """
    if not path or "\x00" in path:
        raise ValueError("evidence path is empty or contains NUL")
    posix = path.replace("\\", "/")
    if posix.startswith("/") or _DRIVE_RE.match(posix):
        raise ValueError(f"evidence path must be repository-relative: {path!r}")
    parts = [p for p in PurePosixPath(posix).parts if p not in ("", ".")]
    if not parts or any(p == ".." for p in parts):
        raise ValueError(f"evidence path must stay inside the repository: {path!r}")
    return "/".join(parts)


@dataclass(frozen=True)
class EvidenceRef:
    """``<path>:<start>-<end>@<hash>`` — a citable, re-verifiable piece of evidence.

    The line range is the locator at the time the evidence was observed; identity is the
    path plus the span hash. ``sha`` may be a prefix (from a printed reference) or a full
    256-bit digest (from the store).
    """

    path: str
    line_start: int
    line_end: int
    sha: str

    @property
    def line_count(self) -> int:
        return self.line_end - self.line_start + 1

    def matches(self, full_sha: Optional[str]) -> bool:
        return bool(full_sha) and str(full_sha).startswith(self.sha)

    def __str__(self) -> str:
        return f"{self.path}:{self.line_start}-{self.line_end}@{self.sha[:REF_HASH_CHARS]}"


def make_ref(path: str, line_start: int, line_end: int, full_sha: str) -> EvidenceRef:
    return EvidenceRef(normalize_rel_path(path), int(line_start), int(line_end), full_sha.lower())


def parse_ref(text: str) -> EvidenceRef:
    """Parse a printed reference. Paths may contain ``:`` or ``@``; parsing is right-anchored."""
    match = _REF_RE.match(text.strip())
    if match is None:
        raise ValueError(f"not an evidence reference (expected path:start-end@hash): {text!r}")
    start, end = int(match["start"]), int(match["end"])
    if start < 1 or end < start:
        raise ValueError(f"invalid line range in evidence reference: {text!r}")
    sha = match["sha"].lower()
    if not MIN_REF_HASH_CHARS <= len(sha) <= 64:
        raise ValueError(
            f"evidence hash must be {MIN_REF_HASH_CHARS}-64 hex characters: {text!r}"
        )
    return EvidenceRef(normalize_rel_path(match["path"]), start, end, sha)


def repo_id_for(root: Path | str) -> str:
    """Scope key for one checkout. Case-folded on Windows, where paths are case-insensitive."""
    canonical = Path(root).resolve().as_posix()
    if sys.platform == "win32":
        canonical = canonical.casefold()
    return hashlib.sha256(f"repo:{canonical}".encode("utf-8")).hexdigest()


def session_key(repo_id: str, tag: str) -> str:
    """Stored form of a caller's session tag; the tag itself is never persisted."""
    return hashlib.sha256(f"session:{repo_id}:{tag}".encode("utf-8")).hexdigest()


_SESSION_TAG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,127}$")


def validate_session_tag(tag: str) -> str:
    tag = tag.strip()
    if not _SESSION_TAG_RE.match(tag):
        raise ValueError(
            "session tag must be 1-128 characters of letters, digits, '.', '_', ':' or '-', "
            "starting with a letter or digit"
        )
    return tag
