Ты — senior software architect, DevOps engineer и разработчик CLI-инструментов. Мне нужно спроектировать и реализовать production-ready GitHub-hosted installer для установки одного AI-agent skill/package сразу в несколько CLI-сред: Claude Code, Codex CLI и OpenCode.

Контекст и целевая архитектура:

Правильная форма решения такая:

1. Один GitHub-hosted installer.
2. Installer сам определяет ОС и доступный CLI.
3. Installer ставит нужные файлы в правильное место для Claude Code / Codex / OpenCode.
4. Installer проверяет наличие Python и, если нужно, докидывает runtime и bootstrap.
5. После установки skill/command/agent-интеграция уже доступна без ручной раскладки по директориям.
6. Это не должен быть “один универсальный файл для всех CLI без структуры”. Нужен один installer entrypoint с адаптерами под каждую среду.

Сделай полноценный проект на GitHub по лучшим практикам.

Нужно реализовать подход:

* GitHub raw installer + автоопределение CLI.
* Одна копируемая команда для macOS/Linux.
* Одна копируемая команда для Windows PowerShell.
* Один источник правды в репозитории.
* Отдельные адаптеры установки под:

  * Claude Code;
  * Codex CLI;
  * OpenCode.
* Общий installer entrypoint, который вызывает нужный adapter.
* Возможность явно указать target CLI через флаг, например:

  * --target claude
  * --target codex
  * --target opencode
  * --target all
* Если target не указан, installer должен сам определить доступные CLI по PATH и/или типичным конфиг-директориям.

Обязательные требования к проекту:

1. Дай структуру репозитория, например:

   repo/
   ├── install.sh
   ├── install.ps1
   ├── README.md
   ├── LICENSE
   ├── skill/
   │   ├── SKILL.md
   │   ├── scripts/
   │   │   └── bootstrap.py
   │   └── resources/
   ├── adapters/
   │   ├── claude.sh
   │   ├── codex.sh
   │   ├── opencode.sh
   │   ├── claude.ps1
   │   ├── codex.ps1
   │   └── opencode.ps1
   ├── lib/
   │   ├── common.sh
   │   └── common.ps1
   └── tests/
   ├── smoke.sh
   └── smoke.ps1

2. Напиши полный код для:

   * install.sh;
   * install.ps1;
   * lib/common.sh;
   * lib/common.ps1;
   * adapters/claude.sh;
   * adapters/codex.sh;
   * adapters/opencode.sh;
   * adapters/claude.ps1;
   * adapters/codex.ps1;
   * adapters/opencode.ps1;
   * skill/SKILL.md;
   * skill/scripts/bootstrap.py;
   * README.md.

3. Installer должен поддерживать ОС:

   * macOS;
   * Linux;
   * Windows через PowerShell.

4. Installer должен иметь флаги:

   Для install.sh:

   * --target claude|codex|opencode|all|auto
   * --install-dir PATH
   * --repo-url URL
   * --branch BRANCH
   * --dry-run
   * --force
   * --no-python-bootstrap
   * --verbose
   * --uninstall
   * --help

   Для install.ps1:

   * -Target claude|codex|opencode|all|auto
   * -InstallDir PATH
   * -RepoUrl URL
   * -Branch BRANCH
   * -DryRun
   * -Force
   * -NoPythonBootstrap
   * -Verbose
   * -Uninstall
   * -Help

5. Installer должен:

   * определять ОС;
   * определять shell;
   * проверять наличие curl или wget на Unix;
   * проверять наличие PowerShell на Windows;
   * проверять наличие git, но не требовать его обязательно;
   * уметь скачивать zip/tarball с GitHub без git;
   * создавать временную директорию;
   * скачивать skill package;
   * проверять, что в пакете есть SKILL.md;
   * проверять YAML frontmatter в SKILL.md;
   * копировать файлы атомарно;
   * делать backup существующей установки перед overwrite;
   * поддерживать --force;
   * поддерживать --dry-run;
   * поддерживать --uninstall;
   * выводить понятные статусы: INFO, WARN, ERROR, OK;
   * завершаться с корректными exit codes;
   * не ломать существующие пользовательские конфиги.

6. Python/runtime требования:

   Installer должен:

   * проверить наличие python3/python на Unix;
   * проверить наличие py/python на Windows;
   * проверить версию Python, минимум 3.9;
   * если Python отсутствует, не пытаться опасно ставить системный Python без подтверждения;
   * вместо этого:

     * вывести понятную инструкцию;
     * установить локальный lightweight bootstrap только если это безопасно;
     * создать .venv внутри директории skill, если Python есть;
     * установить зависимости из requirements.txt, если файл существует;
     * запустить skill/scripts/bootstrap.py после установки, если он существует;
   * иметь флаг --no-python-bootstrap / -NoPythonBootstrap.

7. Claude Code adapter:

   Нужно сделать адаптер, который:

   * устанавливает skill как директорию с SKILL.md;
   * поддерживает global install и project install, если возможно;
   * использует безопасные дефолтные пути;
   * объясняет в комментариях, где лежит skill;
   * после установки проверяет наличие SKILL.md;
   * не перезаписывает другие skills.

   Важно: если точный путь для конкретной версии Claude Code может отличаться, сделай код так, чтобы:

   * путь можно было переопределить через --install-dir;
   * дефолтный путь был вынесен в переменную;
   * README честно объяснял, как поменять путь вручную.

8. Codex CLI adapter:

   Нужно сделать адаптер, который:

   * устанавливает agent/project instructions для Codex через AGENTS.md или совместимый instruction-файл;
   * если в проекте уже есть AGENTS.md, не затирает его, а:

     * делает backup;
     * добавляет managed block с маркерами:
       BEGIN MANAGED SKILL BLOCK
       END MANAGED SKILL BLOCK
   * поддерживает global config, если пользователь указал --install-dir;
   * устанавливает дополнительные scripts/resources в отдельную директорию, например ~/.codex/skills/<skill-name>/;
   * README должен объяснить, что для Codex это не “Claude Skill”, а адаптация в формате instruction package.

9. OpenCode adapter:

   Нужно сделать адаптер, который:

   * устанавливает markdown command в commands/;
   * устанавливает agent config или instruction-файл, если нужно;
   * поддерживает global path:
     ~/.config/opencode/commands/
     ~/.config/opencode/agents/
   * поддерживает project path:
     .opencode/commands/
     .opencode/agents/
   * не ломает opencode.json/opencode.jsonc;
   * если нужно изменить config, делает backup и patch только managed block/managed section;
   * README должен показать, как запускать команду через /command-name.

10. Security requirements:

Installer должен:

* не выполнять удалённый код без явного скачивания и проверки структуры;
* по возможности показывать URL скачивания;
* поддерживать pinning по branch/tag;
* предупреждать о риске pipe-to-shell;
* предлагать альтернативный безопасный способ:
  curl -fsSL URL -o install.sh
  less install.sh
  sh install.sh
* не использовать sudo без явного требования;
* не писать за пределы HOME/project dir без явного --install-dir;
* валидировать пути;
* запрещать path traversal при распаковке архива;
* иметь режим dry-run.

11. README.md должен включать:

* краткое описание проекта;
* что именно устанавливается для Claude Code;
* что именно устанавливается для Codex CLI;
* что именно устанавливается для OpenCode;
* quick install для macOS/Linux:
  curl -fsSL https://raw.githubusercontent.com/OWNER/REPO/main/install.sh | sh
* quick install для Windows PowerShell:
  irm https://raw.githubusercontent.com/OWNER/REPO/main/install.ps1 | iex
* безопасная установка с предварительным просмотром;
* установка конкретного target;
* установка всех target;
* dry-run;
* uninstall;
* override install directory;
* troubleshooting;
* security notes;
* developer notes;
* как добавить новый adapter;
* как тестировать installer локально.

12. Код должен быть качественным:

Для shell:

* set -euo pipefail;
* аккуратный trap cleanup;
* функции log_info/log_warn/log_error/log_ok;
* функции detect_os, detect_cli, download_archive, safe_extract, install_target;
* без bash-специфики там, где можно POSIX, но если нужен bash — указать #!/usr/bin/env bash.

Для PowerShell:

* Set-StrictMode -Version Latest;
* $ErrorActionPreference = "Stop";
* функции Write-Info/Write-Warn/Write-ErrorMessage/Write-Ok;
* try/catch/finally;
* аккуратная работа с Join-Path;
* проверка Windows/macOS/Linux, если PowerShell Core.

Для Python bootstrap:

* pathlib;
* argparse;
* logging;
* type hints;
* проверка версии Python;
* создание runtime metadata;
* запись install_manifest.json;
* без внешних зависимостей, если возможно.

13. Нужно предусмотреть manifest:

После установки создать файл install_manifest.json с:

* skill_name;
* version;
* installed_at;
* target;
* os;
* source_repo;
* branch;
* installed_files;
* python_version;
* bootstrap_status.

14. Нужно добавить uninstall:

Uninstall должен:

* читать install_manifest.json;
* удалять только файлы, которые были установлены этим installer;
* не удалять пользовательские файлы;
* для AGENTS.md удалить только managed block;
* для OpenCode удалить только созданные command/agent files;
* оставить backup.

15. Нужно добавить тестовый smoke сценарий:

* dry-run для auto;
* dry-run для claude;
* dry-run для codex;
* dry-run для opencode;
* установка во временную директорию;
* проверка наличия SKILL.md;
* проверка install_manifest.json;
* uninstall из временной директории.

16. В конце ответа дай:

* дерево файлов;
* полный код каждого файла;
* инструкции публикации на GitHub;
* команды проверки;
* финальную рекомендуемую команду установки;
* пояснение архитектуры.

17. Не сокращай код до псевдокода. Нужен рабочий, аккуратный, расширяемый baseline, который можно сразу положить в GitHub repo и доработать под конкретный skill.

18. Используй placeholders OWNER, REPO, SKILL_NAME, SKILL_VERSION там, где нужно, но сделай так, чтобы их было легко заменить.

19. Все комментарии и README пиши на русском языке, но кодовые имена, функции, переменные и CLI-флаги оставь на английском.

20. Особенно важно: не делай “магический” installer, который непонятно куда всё кладёт. Все пути должны быть явно описаны, логироваться и переопределяться.
