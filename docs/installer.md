# Multi-CLI Installer для codebase-index

Единый GitHub-hosted installer, который раскладывает skill **codebase-index**
сразу в несколько AI-CLI сред: **Claude Code**, **Codex CLI** и **OpenCode**.

Архитектура: один entrypoint (`install.sh` / `install.ps1`) + отдельные
адаптеры под каждую среду (`adapters/<target>.{sh,ps1}`). Источник правды —
каталог `skill/` в репозитории. Никакой «магии»: все пути логируются и
переопределяются.

---

## Что устанавливается

| CLI | Что именно | Куда (global по умолчанию) |
|-----|------------|----------------------------|
| **Claude Code** | skill-директория с `SKILL.md` + scripts | `~/.claude/skills/codebase-index/` |
| **Codex CLI** | managed block в `AGENTS.md` + ресурсы (instruction package, **не** Claude Skill) | блок в `~/.codex/AGENTS.md`, ресурсы в `~/.codex/skills/codebase-index/` |
| **OpenCode** | markdown-команда `/codebase-index` + agent-файл + ресурсы | `~/.config/opencode/commands/`, `.../agents/`, `.../skills/codebase-index/` |

Для project-установки (`--scope project`) пути меняются на
`./.claude/...`, `./AGENTS.md`, `./.opencode/...`.

---

## Быстрая установка

**macOS / Linux:**

```sh
curl -fsSL https://raw.githubusercontent.com/denfry/codebase-index/main/install.sh | sh
```

**Windows PowerShell:**

```powershell
irm https://raw.githubusercontent.com/denfry/codebase-index/main/install.ps1 | iex
```

### Безопасная установка (с предпросмотром — рекомендуется)

Pipe-to-shell исполняет удалённый код «вслепую». Безопаснее скачать, прочитать
и только потом запустить:

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

## Сценарии использования

**Конкретный target:**

```sh
sh install.sh --target claude
sh install.sh --target codex
sh install.sh --target opencode
```

```powershell
pwsh ./install.ps1 -Target claude
```

**Все сразу:**

```sh
sh install.sh --target all
```

**Авто-определение (по умолчанию)** — installer сам находит CLI по PATH и
типичным конфиг-директориям (`~/.claude`, `~/.codex`, `~/.config/opencode`):

```sh
sh install.sh            # = --target auto
```

**Dry-run** (ничего не меняет, показывает план):

```sh
sh install.sh --target all --dry-run
```

**Uninstall** (удаляет только установленное этим installer — по manifest):

```sh
sh install.sh --target all --uninstall
```

**Переопределение директории установки:**

```sh
sh install.sh --target claude --install-dir "$HOME/my-skills/codebase-index"
```

```powershell
pwsh ./install.ps1 -Target claude -InstallDir "D:\skills\codebase-index"
```

**Pinning по ветке/тегу** (воспроизводимость и безопасность):

```sh
sh install.sh --branch v1.1.0
```

---

## Флаги

| install.sh | install.ps1 | Значение |
|------------|-------------|----------|
| `--target` | `-Target` | `claude\|codex\|opencode\|all\|auto` |
| `--install-dir` | `-InstallDir` | переопределить путь установки |
| `--repo-url` | `-RepoUrl` | URL репозитория-источника |
| `--branch` | `-Branch` | ветка/тег для скачивания |
| `--scope` | `-Scope` | `global\|project` |
| `--dry-run` | `-DryRun` | не вносить изменений |
| `--force` | `-Force` | перезаписать существующую установку (с backup) |
| `--no-python-bootstrap` | `-NoPythonBootstrap` | не создавать venv / не запускать bootstrap.py |
| `--verbose` | `-Verbose` | подробный лог |
| `--uninstall` | `-Uninstall` | удалить по manifest |
| `--help` | `-Help` | справка |

---

## Python / runtime

После раскладки файлов installer (если не указан `--no-python-bootstrap`):

1. ищет `python3`/`python` (Unix) или `py`/`python` (Windows), **минимум 3.9**;
2. если Python не найден — **не** ставит системный Python сам, а печатает
   понятную инструкцию;
3. при наличии Python создаёт `.venv` внутри директории skill;
4. ставит зависимости из `requirements.txt`, если файл есть;
5. запускает `skill/scripts/bootstrap.py` (создаёт `runtime.json`, дополняет manifest).

---

## Manifest

После установки в директории skill создаётся `install_manifest.json`:

```json
{
  "skill_name": "codebase-index",
  "version": "1.1.0",
  "installed_at": "2026-05-29T12:00:00Z",
  "target": "claude",
  "os": "linux",
  "source_repo": "https://github.com/denfry/codebase-index",
  "branch": "main",
  "installed_files": ["..."],
  "python_version": "3.11.6",
  "bootstrap_status": "ok"
}
```

Uninstall читает этот файл и удаляет **только** перечисленные в нём файлы.
Для `AGENTS.md` удаляется только managed block, сам файл сохраняется.

---

## Как запускать в OpenCode

После установки команда доступна как:

```
/codebase-index <запрос>
```

---

## Troubleshooting

- **«Python 3.9+ не найден»** — установите Python и повторите без
  `--no-python-bootstrap`, либо игнорируйте, если venv не нужен.
- **«Уже установлено … (используйте --force)»** — добавьте `--force`
  (создаётся backup перед перезаписью).
- **Неверный путь для вашей версии Claude Code** — задайте `--install-dir`.
  Дефолтные пути вынесены в функции `*_default_dir` / `Get-*TargetDir`.
- **Нет curl/wget (Unix)** — установите один из них; на Windows используется
  `Invoke-WebRequest`.
- **Авто-режим ничего не нашёл (exit 4)** — укажите `--target` явно.

---

## Security notes

- Удалённый код не исполняется «на лету»: архив сначала скачивается,
  проверяется структура (`SKILL.md` + frontmatter) и пути (запрет traversal).
- URL источника всегда печатается перед скачиванием.
- Поддерживается pinning по `--branch`.
- Без `--install-dir` installer не пишет за пределы `HOME`/проекта.
- `sudo` не используется.
- Есть `--dry-run`.

---

## Developer notes

### Структура

```
install.sh / install.ps1     entrypoints
lib/common.sh / common.ps1   общие функции (лог, скачивание, manifest, bootstrap)
adapters/<target>.{sh,ps1}   логика конкретного CLI
skill/                       источник правды (SKILL.md, scripts/bootstrap.py)
tests/installer/smoke.{sh,ps1}  smoke-тесты
```

### Как добавить новый adapter

1. Создайте `adapters/<new>.sh`, определив функции `adapter_install` и
   `adapter_uninstall` (используйте функции из `lib/common.sh`).
2. Создайте `adapters/<new>.ps1` с `Invoke-AdapterInstall` /
   `Invoke-AdapterUninstall`.
3. Добавьте `<new>` в `--target`/`-Target` и в авто-определение
   (`detect_targets` / `Get-AutoTargets`).
4. Допишите строку в smoke-тесты.

### Как тестировать локально

```sh
sh tests/installer/smoke.sh
```

```powershell
pwsh tests/installer/smoke.ps1
```

Smoke-тест прогоняет dry-run для всех целей, ставит skill в temp-директорию,
проверяет `SKILL.md` + manifest и выполняет uninstall.
