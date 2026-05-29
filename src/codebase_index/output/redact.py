"""Conservative output-time secret redaction."""

from __future__ import annotations

import re

_PRIVATE_KEY_RE = re.compile(
    r"-----BEGIN ([A-Z ]*PRIVATE KEY)-----.*?-----END \1-----",
    re.DOTALL,
)
_AWS_ACCESS_KEY_RE = re.compile(r"\bAKIA[0-9A-Z]{16}\b")
_ASSIGNED_SECRET_RE = re.compile(
    r"(?i)\b(api[_-]?key|access[_-]?token|secret|token|password)\b"
    r"(\s*[:=]\s*)"
    r"([\"']?)[A-Za-z0-9_./+=:-]{16,}\3"
)


def redact_snippet(text: str) -> str:
    text = _PRIVATE_KEY_RE.sub(_redact_private_key, text)
    text = _AWS_ACCESS_KEY_RE.sub("<<redacted:aws_access_key>>", text)
    return _ASSIGNED_SECRET_RE.sub(
        lambda m: f"{m.group(1)}{m.group(2)}<<redacted:secret>>", text
    )


def _redact_private_key(match: re.Match[str]) -> str:
    return "\n".join(
        "<<redacted:private_key>>" if line and not line.startswith("-----") else line
        for line in match.group(0).splitlines()
    )
