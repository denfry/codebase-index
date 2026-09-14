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

## Skill tool surface

The generated `SKILL.md` frontmatter restricts the agent to read-only subcommands
(`search`, `explain`, `architecture`, `symbol`, `refs`, `impact`, `diff-impact`, `path`,
`describe`, `graph`, `stats`, `doctor`, `update`, `index`, and the `cbx` wrapper) plus `Read`,
`Grep`, `Glob`. `clean`, `init`, `watch`, unscoped `Bash`, and `python -m codebase_index` are not
allowed. The `cbx` wrappers (skill `scripts/cbx` and plugin `bin/cbx`) enforce the same whitelist
and refuse other subcommands.

## Threat Model

(`docs/SECURITY.md` was merged into this page; the reporting policy lives in the root
[SECURITY.md](../SECURITY.md).)

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

## `doctor` — safety self-check

`codebase-index doctor` (`src/codebase_index/doctor.py`) reports exactly these findings today:

| id | severity | what it checks |
|---|---|---|
| `cache_gitignored` | high | the derived index directory is in `.gitignore` (a committed index leaks indexed text) |
| `hooks_enabled` | info | whether the Claude Code PostToolUse auto-update hook is configured |
| `index_fresh` | medium | the index exists and is not stale relative to the tree |
| `symbol_extraction` | medium | Tree-sitter languages actually produce symbols (guards silent parser failure) |
| `graph_coverage` | info | every indexed language has dependency-graph support, or names the partial ones |

`--strict` exits non-zero when a high-severity finding fails, so it can gate CI. The external-
embedding warning (naming the endpoint) is printed by `index` and `search` when the backend is
resolved, not by `doctor`. Secret-pattern scans of the index, `allowed-tools` diffs and
cache-permission checks are **not** implemented; do not rely on `doctor` for them.

## Hook risks

Optional hooks (the PostToolUse auto-update) execute CLI commands automatically. Keep hook
commands read-only (`codebase-index update --quiet`), free of user-controlled input, and quiet.

## Unsafe patterns

- Do not commit the SQLite index to a shared repository: it stores indexed text, and redaction
  happens only at output time.
- Do not enable external embeddings on proprietary or regulated code without reviewing your
  organisation's data-handling policy.
- Review `doctor` output before indexing a repository you do not trust.
