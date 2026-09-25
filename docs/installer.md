# Multi-CLI installer for codebase-index

A single GitHub-hosted installer that lays out the **codebase-index** skill into several
AI-CLI environments at once: **Claude Code**, **Codex CLI** and **OpenCode**.

Architecture: one entrypoint (`install.sh` / `install.ps1`) plus one adapter per environment
(`adapters/<target>.{sh,ps1}`). The source of truth is the `skill/` directory in the
repository. No magic: every path is logged and can be overridden.

> Most users should prefer `pip install codebase-index` followed by `codebase-index init`
> (see [INSTALLATION.md](INSTALLATION.md)). The shell installer exists for environments where
> the skill files need to be placed globally without a Python package install first.

---

## What gets installed

| CLI | What | Where (global scope, the default) |
|-----|------|-----------------------------------|
| **Claude Code** | skill directory with `SKILL.md` + scripts | `~/.claude/skills/codebase-index/` |
| **Codex CLI** | managed block in `AGENTS.md` + resources (an instruction package, **not** a Claude Skill) | block in `~/.codex/AGENTS.md`, resources in `~/.codex/skills/codebase-index/` |
| **OpenCode** | markdown command `/codebase-index` + agent file + resources | `~/.config/opencode/commands/`, `.../agents/`, `.../skills/codebase-index/` |

With a project install (`--scope project`) the paths become `./.claude/...`, `./AGENTS.md`,
`./.opencode/...`.

---

## Quick install

**macOS / Linux:**

```sh
curl -fsSL https://raw.githubusercontent.com/denfry/codebase-index/main/install.sh | sh
```

**Windows PowerShell:**

```powershell
irm https://raw.githubusercontent.com/denfry/codebase-index/main/install.ps1 | iex
```

### Safer install (download, read, then run — recommended)

Pipe-to-shell executes remote code blindly. Download, read, then run:

```sh
curl -fsSL https://raw.githubusercontent.com/denfry/codebase-index/main/install.sh -o install.sh
less install.sh
sh install.sh
```

```powershell
irm https://raw.githubusercontent.com/denfry/codebase-index/main/install.ps1 -OutFile install.ps1
Get-Content install.ps1 | more
pwsh ./install.ps1
```

---

## Usage scenarios

**A specific target:**

```sh
sh install.sh --target claude
sh install.sh --target codex
sh install.sh --target opencode
```

```powershell
pwsh ./install.ps1 -Target claude
```

**Everything at once:**

```sh
sh install.sh --target all
```

**Auto-detect (default)** — the installer looks for CLIs on `PATH` and in the usual config
directories (`~/.claude`, `~/.codex`, `~/.config/opencode`):

```sh
sh install.sh            # = --target auto
```

**Dry run** (changes nothing, prints the plan):

```sh
sh install.sh --target all --dry-run
```

**Uninstall** (removes only what this installer wrote, per its manifest):

```sh
sh install.sh --target all --uninstall
```

**Override the install directory:**

```sh
sh install.sh --target claude --install-dir "$HOME/my-skills/codebase-index"
```

```powershell
pwsh ./install.ps1 -Target claude -InstallDir "D:\skills\codebase-index"
```

**Pin to a branch or tag** (reproducibility and safety):

```sh
sh install.sh --branch v2.1.1
```

---

## Flags

| install.sh | install.ps1 | Meaning |
|------------|-------------|---------|
| `--target` | `-Target` | `claude\|codex\|opencode\|all\|auto` |
| `--install-dir` | `-InstallDir` | override the install path |
| `--repo-url` | `-RepoUrl` | source repository URL |
| `--branch` | `-Branch` | branch or tag to download |
| `--scope` | `-Scope` | `global\|project` |
| `--dry-run` | `-DryRun` | make no changes |
| `--force` | `-Force` | overwrite an existing install (a backup is taken first) |
| `--no-python-bootstrap` | `-NoPythonBootstrap` | do not create a venv / run `bootstrap.py` |
| `--verbose` | `-Verbose` | verbose log |
| `--uninstall` | `-Uninstall` | remove per manifest |
| `--help` | `-Help` | show help |

---

## Python / runtime

After laying out the files, unless `--no-python-bootstrap` was given, the installer:

1. looks for `python3` / `python` (Unix) or `py` / `python` (Windows), **3.9 minimum** for the
   bootstrap itself (the `codebase-index` package requires 3.11+);
2. if no Python is found, does **not** install one, but prints a clear instruction;
3. otherwise creates a `.venv` inside the skill directory;
4. installs dependencies from `requirements.txt` if that file exists;
5. runs `skill/scripts/bootstrap.py` (creates `runtime.json`, extends the manifest).

---

## Manifest

After installation the skill directory contains `install_manifest.json`:

```json
{
  "skill_name": "codebase-index",
  "version": "1.9.0",
  "target": "claude",
  "os": "linux",
  "source_repo": "https://github.com/denfry/codebase-index",
  "branch": "main",
  "installed_files": ["..."],
  "python_version": "3.11.6",
  "bootstrap_status": "ok"
}
```

Uninstall reads this file and removes **only** the files listed in it. For `AGENTS.md` only the
managed block is removed; the file itself is kept.

---

## Running in OpenCode

After installation the command is available as:

```
/codebase-index <query>
```

---

## Troubleshooting

- **"Python 3.9+ not found"** — install Python and re-run without `--no-python-bootstrap`, or
  ignore it if you do not need the venv.
- **"Already installed … (use --force)"** — add `--force` (a backup is taken before overwriting).
- **Wrong path for your Claude Code version** — pass `--install-dir`. Default paths live in the
  `*_default_dir` / `Get-*TargetDir` functions.
- **No curl/wget (Unix)** — install one of them; Windows uses `Invoke-WebRequest`.
- **Auto mode found nothing (exit 4)** — pass `--target` explicitly.

---

## Security notes

- Remote code is not executed on the fly: the archive is downloaded first, its structure is
  checked (`SKILL.md` + frontmatter) and its paths are checked (no traversal).
- The source URL is always printed before downloading.
- Pinning with `--branch` is supported.
- Without `--install-dir` the installer never writes outside `HOME` / the project.
- `sudo` is never used.
- `--dry-run` is available.

---

## Developer notes

### Layout

```
install.sh / install.ps1        entrypoints
lib/common.sh / common.ps1      shared functions (logging, download, manifest, bootstrap)
adapters/<target>.{sh,ps1}      per-CLI logic
skill/                          source of truth (SKILL.md, scripts/bootstrap.py)
tests/installer/smoke.{sh,ps1}  smoke tests
```

### Adding an adapter

1. Create `adapters/<new>.sh` defining `adapter_install` and `adapter_uninstall` (use the
   helpers from `lib/common.sh`).
2. Create `adapters/<new>.ps1` with `Invoke-AdapterInstall` / `Invoke-AdapterUninstall`.
3. Add `<new>` to `--target` / `-Target` and to auto-detection (`detect_targets` /
   `Get-AutoTargets`).
4. Add a line to the smoke tests.

### Testing locally

```sh
sh tests/installer/smoke.sh
```

```powershell
pwsh tests/installer/smoke.ps1
```

The smoke test dry-runs every target, installs the skill into a temp directory, checks
`SKILL.md` + the manifest, and uninstalls.
