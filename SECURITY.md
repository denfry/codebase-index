# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| 1.2.x   | :white_check_mark: |
| < 1.2   | :x:                |

Only the latest minor version receives security updates.

## Reporting a Vulnerability

We take security seriously. If you discover a vulnerability, please report it responsibly:

1. **Do not** open a public issue.
2. Email the maintainers with a description of the vulnerability and steps to reproduce.
3. We will acknowledge receipt within 48 hours and provide a timeline for a fix.
4. Once resolved, we will publish a security advisory and credit the reporter (if desired).

## No Telemetry Promise

`codebase-index` does **not** collect, transmit, or store any telemetry, usage data, or analytics. All indexing, search, and storage operations occur entirely on your local machine. There are no phone-home mechanisms, crash reporters, or usage counters.

## Secret Handling

- **Never indexed**: `.env` files, private keys (`.pem`, `.key`), certificates, tokens, credential files, and binary artifacts are excluded before parsing.
- **Redacted in output**: Any snippets that may contain secret-like patterns (AWS keys, JWTs, bearer tokens, connection strings) are masked before being returned to Claude or printed to the terminal.
- **Respects ignore files**: `.gitignore`, `.claudeignore`, `.codeindexignore`, and `.cursorignore` are all honored during discovery.

## External Embeddings Opt-In

The default configuration disables embeddings entirely (`backend = "noop"`). External embedding APIs (which would send code text to a remote service) require:

1. Explicit `embeddings.allow_external = true` in configuration.
2. A user-provided API key via environment variable.
3. Warnings printed by both `doctor` and `index` commands.

Without all three conditions, external embeddings are refused.

## Threat Model

- **Indexed content**: Treat indexing an untrusted repository the same as opening it in a text editor. Parsers operate over file content but do not execute code.
- **Cache location**: The SQLite index is stored in `.claude/cache/codebase-index/`. Ensure this directory is not committed to version control (it is in the default `.gitignore`).
- **World-writable directories**: `doctor` warns if the cache directory has insecure permissions.

## Unsafe Patterns to Avoid

- Do not commit the SQLite index file to a shared repository.
- Do not enable external embeddings on repositories containing proprietary or regulated code without reviewing your organization's data handling policies.
- Do not run `codebase-index index` on repositories you do not trust without reviewing the `doctor` output first.
