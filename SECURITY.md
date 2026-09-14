# Security Policy

`codebase-index` reads entire repositories, so its security posture matters
more than for a typical CLI. The full trust model, exclusion pipeline and
redaction rules are documented in [docs/SECURITY_MODEL.md](docs/SECURITY_MODEL.md);
this page covers reporting and the guarantees in short form.

## Supported versions

Only the latest minor release line receives security fixes.

| Version | Supported |
|---|---|
| 2.0.x (latest) | Yes |
| < 2.0 | No — upgrade with `pip install -U codebase-index` |

## Reporting a vulnerability

Please do **not** open a public issue for security problems.

1. Use GitHub private vulnerability reporting:
   <https://github.com/denfry/codebase-index/security/advisories/new>
   (the *Report a vulnerability* button under the repository's **Security** tab).
2. Include the version (`pip show codebase-index`),
   platform, a description, and reproduction steps. Redact any real secrets.
3. You will get an acknowledgement within a few days. Fixes are released as a
   patch on the supported line and published as a GitHub security advisory,
   crediting the reporter unless they prefer otherwise.

If private reporting is unavailable for any reason, open a minimal issue that
says only "security report, please contact me" without details, and a
maintainer will reach out.

## What the tool guarantees

- **No telemetry.** No usage data, analytics, crash reports or phone-home of
  any kind.
- **No network by default.** The base install makes no network requests.
  The only code path that can send repository text off the machine is the
  *external* embeddings backend, which is refused unless all three hold:
  `embeddings.allow_external = true` in config, an API key provided via
  environment variable, and the endpoint warning printed by `doctor` / `index`.
- **Secrets are never indexed.** `.env*`, private keys and certificates
  (`*.pem`, `*.key`, `*.p12`, `*.pfx`, `id_rsa*`, `*.crt`, `*.keystore`),
  `credentials*`, `secrets*`, binaries, dependency and build directories,
  generated files and oversized files are excluded before parsing.
- **Secrets are redacted on output.** Snippets pass through
  `output/redact.py` before reaching the agent or the terminal (AWS keys,
  private-key blocks, JWTs and bearer tokens, connection strings with
  credentials, Slack tokens, high-entropy values assigned to key-like names).
- **Ignore files are honoured.** `.gitignore`, `.claudeignore`,
  `.codeindexignore` and `.cursorignore`.
- **Read-only agent surface.** The generated skill's `allowed-tools` and the
  `cbx` wrappers whitelist read-only subcommands; `clean`, `init` and `watch`
  are not callable from the skill.
- **Self-audit.** `codebase-index doctor --strict` exits non-zero if any gate
  is misconfigured; use it in CI.

## Threat model in brief

- Indexing a repository is like opening it in an editor: parsers read file
  content, nothing is executed.
- The derived index lives in `.claude/cache/codebase-index/` and is
  gitignored by `init`. Do not commit it or share it as if it were sanitised —
  redaction happens at output time, and the index stores indexed text.
- Treat `doctor` warnings about world-writable cache directories as real.

## Release integrity

Releases are built in GitHub Actions and published to PyPI with Trusted
Publishing (OIDC, no stored tokens). Signed checksums, SBOMs and build
attestations are on the roadmap and are **not** yet provided; do not assume
them.
