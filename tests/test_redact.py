from __future__ import annotations

from codebase_index.output.redact import redact_snippet


def test_masks_assigned_secrets():
    out = redact_snippet('API_KEY = "sk-livesecret1234567890abcd"')
    assert "sk-livesecret" not in out
    assert "<<redacted" in out


def test_masks_known_formats():
    assert "AKIA" not in redact_snippet("aws = AKIAIOSFODNN7EXAMPLE")
    assert "BEGIN" in redact_snippet("-----BEGIN PRIVATE KEY-----")
    assert "<<redacted:private_key>>" in redact_snippet(
        "-----BEGIN PRIVATE KEY-----\nMIIBVgIBADANBg\n-----END PRIVATE KEY-----"
    )


def test_benign_code_untouched():
    src = "def add(a, b):\n    return a + b"
    assert redact_snippet(src) == src


def test_line_count_preserved():
    src = 'token = "abcd1234efgh5678ijkl"\nx = 1\ny = 2'
    out = redact_snippet(src)
    assert out.count("\n") == src.count("\n")
