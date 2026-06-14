# Security Model

`codebase-index` is **local-first and offline by default**. Its threat model assumes the indexed
repository may contain secrets and that a skill must not exfiltrate code or run dangerous commands.

> **Trust model in 60 seconds**
> 1. **Offline by default** — the base install has zero network dependencies; nothing leaves your machine (§1, §4).
> 2. **One opt-in exit, triple-gated** — external embeddings require `allow_external` **and** an env API key **and** a printed endpoint warning, or they are refused (§4).
> 3. **Secrets never get in** — `.env`, keys, certs, and credential files are excluded before parsing (§2).
> 4. **Secrets never get out** — every snippet is redacted before it reaches the agent (§3).
> 5. **No telemetry, ever** — no analytics, no phone-home, no usage data.
> 6. **Verify it yourself** — `codebase-index doctor --strict` audits all of the above and gates CI (§6).
>
> The same callout appears in the README so the trust story is identical wherever a reader lands.

## 1. Principles

1. **Local-first** — index, query, and storage all happen on the user's machine.
2. **No network by default** — the base install has no network dependency. The only code path that
   can leave the machine is an *external embedding API*, which is **opt-in and off by default**.
3. **Never index sensitive material** — secrets, `.env`, keys, certs, build/dependency/binary/
   generated/huge files are excluded before parsing.
4. **Redact secrets in output** — even indexed snippets are scrubbed before being shown to Claude.
5. **Respect ignore files** — `.gitignore`, `.cursorignore`, `.claudeignore`, `.codeindexignore`.
6. **Minimal, safe tool surface** — the skill's `allowed-tools` only permits the read-only CLI
   subcommands and read-only fallbacks (ripgrep/Grep/Glob). No `clean`, no arbitrary shell.
7. **Workspace trust** — indexing executes parsers over repo content; treat indexing an untrusted
   repo as you would opening it in an editor. `doctor` warns before risky operations.

## 2. Exclusion pipeline (`discovery/`)

A file must pass **every** gate to be indexed:

| Gate | Rule |
|---|---|
| Ignore files | Not matched by `.gitignore` / `.cursorignore` / `.claudeignore` / `.codeindexignore` |
| Built-in denylist | Not in `node_modules`, `.venv`, `dist`, `build`, `target`, `.git`, `vendor`, `__pycache__`, etc. |
| Secret filenames | Not `.env*`, `*.pem`, `*.key`, `*.p12`, `*.pfx`, `id_rsa*`, `*.crt`, `*.keystore`, `credentials*`, `secrets*` |
| Binary | No NUL bytes / not a known binary extension (images, archives, fonts, compiled artifacts) |
| Size | `size_bytes <= max_file_bytes` (default 1 MB) |
| Generated | Not matched by generated-file patterns (`*.min.js`, `*.lock`, `*.pb.go`, `*_pb2.py`, `*.generated.*`) — indexed as summary-only at most |

`.codeindexignore` is the tool's **own** ignore file (highest specificity) so users can exclude
paths from indexing without affecting git or other tools.

## 3. Secret redaction (`output/` + parsers)

Two layers:

- **At index time** — files that *look* like secret stores are excluded entirely (above).
- **At output time** — every snippet is passed through a redactor before emission. Patterns:
  - high-entropy strings assigned to keys named `*key*`, `*secret*`, `*token*`, `*password*`, `*api*`
  - common formats: AWS keys (`AKIA...`), private key headers (`-----BEGIN ... PRIVATE KEY-----`),
    JWTs, bearer tokens, connection strings with credentials, `xox[baprs]-` Slack tokens.
  - Matches are replaced with `«redacted:<type>»`, preserving line numbers.

Redaction is conservative: it never widens the snippet, only masks within it.

## 4. Embeddings & network

- Default: `embeddings.backend = "noop"` (disabled) — pure lexical+symbol+graph search.
- `embeddings.backend = "local"` → on-device model (e.g. sentence-transformers). Still no network
  at query time (model downloaded once at setup, which the user initiates explicitly).
- `embeddings.backend = "external"` → sends chunk text to a configured API. This requires:
  - explicit `embeddings.allow_external = true` in config, **and**
  - an env-provided API key, **and**
  - `doctor` and `index` both print a clear warning naming the endpoint.
  Without all three, external embedding is refused.

## 5. Skill tool surface

`SKILL.md` declares a narrow `allowed-tools`:

```yaml
allowed-tools:
  - Bash(codebase-index search:*)
  - Bash(codebase-index explain:*)
  - Bash(codebase-index symbol:*)
  - Bash(codebase-index refs:*)
  - Bash(codebase-index impact:*)
  - Bash(codebase-index stats:*)
  - Bash(codebase-index update:*)
  - Grep
  - Glob
```

Explicitly **not** allowed via the skill: `clean`, `init`, `watch`, or unscoped `Bash`. Destructive
or scaffolding actions remain a human/manual decision. The wrapper scripts (`scripts/cbx`) only
forward to the installed `codebase-index` binary and reject unknown subcommands.

## 6. `doctor` — safety self-check

`codebase-index doctor` (and `--strict` for CI) reports:

- whether the cache is inside `.gitignore` (warns if the index could be committed)
- whether external embeddings are enabled and to which endpoint
- any indexed file that matches a secret pattern (should be none → flags a leak)
- ignore-file coverage and any oversized/binary files that slipped through
- the resolved `allowed-tools` vs. the recommended minimal set
- world-writable cache directory permissions

`doctor` exits non-zero under `--strict` if any high-severity finding is present, so it can gate CI.

## 7. What the skill must NOT do

- Must not run `codebase-index index --rebuild` automatically on huge/untrusted repos without the
  freshness check indicating it's needed.
- Must not echo raw `.env`/secret file contents even if a user pastes a path — the CLI refuses to
  read excluded files for snippet output.
- Must not enable embeddings or any network path on its own.
