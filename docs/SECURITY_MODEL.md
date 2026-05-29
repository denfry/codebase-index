# Security Model

`codebase-index` is **local-first and offline by default**. Its threat model assumes the indexed repository may contain secrets and that a skill must not exfiltrate code or run dangerous commands.

## Principles

1. **Local-first** — Index, query, and storage all happen on the user's machine.
2. **No network by default** — The base install has no network dependency. The only code path that can leave the machine is an *external embedding API*, which is **opt-in and off by default**.
3. **Never index sensitive material** — Secrets, `.env`, keys, certificates, build artifacts, dependency directories, binary files, and generated files are excluded before parsing.
4. **Redact secrets in output** — Even indexed snippets are scrubbed before being shown to Claude or printed to the terminal.
5. **Respect ignore files** — `.gitignore`, `.claudeignore`, `.codeindexignore`, and `.cursorignore` are all honored.
6. **Minimal, safe tool surface** — The skill's `allowed-tools` only permits read-only CLI subcommands and read-only fallbacks (Grep/Glob). No destructive commands.
7. **Workspace trust** — Indexing executes parsers over repo content; treat indexing an untrusted repo as you would opening it in an editor.

## Exclusion Pipeline

A file must pass **every** gate to be indexed:

| Gate | Rule |
|---|---|
| Ignore files | Not matched by `.gitignore` / `.claudeignore` / `.codeindexignore` / `.cursorignore` |
| Built-in denylist | Not in `node_modules`, `.venv`, `dist`, `build`, `target`, `.git`, `vendor`, `__pycache__`, etc. |
| Secret filenames | Not `.env*`, `*.pem`, `*.key`, `*.p12`, `*.pfx`, `id_rsa*`, `*.crt`, `*.keystore`, `credentials*`, `secrets*` |
| Binary detection | No NUL bytes / not a known binary extension (images, archives, fonts, compiled artifacts) |
| Size limit | `size_bytes <= max_file_bytes` (default 1 MB) |
| Generated files | Not matched by generated-file patterns (`*.min.js`, `*.lock`, `*.pb.go`, `*_pb2.py`, `*.generated.*`) |

`.codeindexignore` is the tool's **own** ignore file (highest specificity) so users can exclude paths from indexing without affecting git or other tools.

## Secret Redaction

Two layers of protection:

### At Index Time
Files that look like secret stores are excluded entirely by the exclusion pipeline above.

### At Output Time
Every snippet is passed through a redactor before emission. Detected patterns:

- High-entropy strings assigned to keys named `*key*`, `*secret*`, `*token*`, `*password*`, `*api*`
- AWS access keys (`AKIA...`)
- Private key headers (`-----BEGIN ... PRIVATE KEY-----`)
- JWTs and bearer tokens
- Connection strings with embedded credentials
- Slack tokens (`xox[baprs]-`)

Matches are replaced with `«redacted:<type>»`, preserving line numbers and snippet structure.

Redaction is conservative: it never widens the snippet, only masks within it.

## Embeddings & Network Policy

| Backend | Network | Default | Notes |
|---|---|---|---|
| `noop` | None | Yes | Pure lexical + symbol + graph search |
| `local` | One-time download | No | On-device model (sentence-transformers) |
| `external` | Per-query | No | Sends chunk text to a configured API |

External embeddings require **all three** conditions:
1. Explicit `embeddings.allow_external = true` in config
2. An environment-provided API key
3. `doctor` and `index` both print a clear warning naming the endpoint

Without all three, external embedding is refused.

## Threat Model

### Trusted Inputs
- The user's own codebase (they control what's in it)
- Configuration files they create

### Untrusted Inputs
- Third-party dependencies (excluded by denylist)
- Generated files (excluded by pattern matching)
- Binary files (excluded by binary detection)

### Attack Vectors Mitigated
| Vector | Mitigation |
|---|---|
| Secret exfiltration | No network by default; external embeddings opt-in |
| Secret exposure in output | Redaction pipeline |
| Indexing sensitive files | Multi-layer exclusion pipeline |
| Malicious file content | Parsers are read-only; no code execution |
| Cache leakage | Cache in `.gitignore`; doctor checks permissions |

## Unsafe Patterns

- **Do not commit the SQLite index** to a shared repository. It contains code snippets.
- **Do not enable external embeddings** on repositories containing proprietary or regulated code without reviewing your organization's data handling policies.
- **Do not run `codebase-index index`** on repositories you do not trust without reviewing the `doctor` output first.

## Hook Risks

Optional hooks (e.g., post-tool-use auto-update) execute CLI commands automatically. Ensure:

- Hook commands are read-only or safe (`codebase-index update --quiet`)
- Hook commands do not contain user-controlled input
- Hook output is not echoed to the user unless necessary

## `doctor` — Safety Self-Check

`codebase-index doctor` reports:

- Whether the cache is inside `.gitignore` (warns if the index could be committed)
- Whether external embeddings are enabled and to which endpoint
- Any indexed file that matches a secret pattern (should be none)
- Ignore-file coverage and any oversized/binary files that slipped through
- The resolved `allowed-tools` vs. the recommended minimal set
- World-writable cache directory permissions

With `--strict` flag, `doctor` exits non-zero if any high-severity finding is present, suitable for CI gating.
