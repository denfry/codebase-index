#!/usr/bin/env sh
# install.sh — единый GitHub-hosted installer для skill `codebase-index`.
#
# Раскладывает skill сразу в несколько CLI-сред:
#   - Claude Code  (skill-директория с SKILL.md)
#   - Codex CLI    (managed block в AGENTS.md + ресурсы)
#   - OpenCode     (markdown-команда + ресурсы)
#
# Архитектура: один entrypoint (этот файл) + адаптеры adapters/<target>.sh.
# Источник правды — каталог skill/ в репозитории.
#
# Запуск (см. README): `curl -fsSL .../install.sh | sh` или локально `sh install.sh`.
# POSIX sh: запускается через sh, без bash-специфики.

set -eu

# --------------------------------------------------------------------------
# Значения по умолчанию (легко заменить под свой репозиторий / skill)
# --------------------------------------------------------------------------
SKILL_NAME="codebase-index"          # имя skill (placeholder: SKILL_NAME)
SKILL_VERSION="0.1.0"                # версия (placeholder: SKILL_VERSION)
DEFAULT_REPO_URL="https://github.com/denfry/codebase-index"   # OWNER/REPO
DEFAULT_BRANCH="main"

# Флаги/параметры (заполняются в parse_args).
TARGET="auto"
INSTALL_DIR=""
REPO_URL="$DEFAULT_REPO_URL"
BRANCH="$DEFAULT_BRANCH"
SCOPE="global"            # global | project (для claude/opencode)
DRY_RUN=0
FORCE=0
NO_PY_BOOTSTRAP=0
VERBOSE=0
DO_UNINSTALL=0

export SKILL_NAME SKILL_VERSION REPO_URL BRANCH DRY_RUN FORCE NO_PY_BOOTSTRAP VERBOSE INSTALL_DIR SCOPE

# --------------------------------------------------------------------------
# Минимальный prelude для логирования ДО подключения lib/common.sh
# (нужен, когда скрипт запущен через `curl | sh` и common.sh ещё не скачан).
# --------------------------------------------------------------------------
_boot() { printf '[INFO]  %s\n' "$*" >&2; }
_bootdie() { printf '[ERROR] %s\n' "$*" >&2; exit 1; }

usage() {
  cat >&2 <<'EOF'
install.sh — установка skill codebase-index в Claude Code / Codex CLI / OpenCode.

ИСПОЛЬЗОВАНИЕ:
  sh install.sh [ФЛАГИ]

ФЛАГИ:
  --target  claude|codex|opencode|all|auto   Куда ставить (по умолчанию: auto)
  --install-dir PATH        Переопределить директорию установки
  --repo-url URL            URL репозитория-источника
  --branch BRANCH           Ветка/тег для скачивания
  --scope global|project    Глобально или в текущий проект (claude/opencode)
  --dry-run                 Ничего не менять, только показать действия
  --force                   Перезаписывать существующую установку
  --no-python-bootstrap     Не создавать venv и не запускать bootstrap.py
  --verbose                 Подробный вывод
  --uninstall               Удалить ранее установленный skill (по manifest)
  --help                    Показать эту справку

AUTO-режим определяет доступные CLI по PATH и типичным конфиг-директориям.

БЕЗОПАСНОСТЬ (pipe-to-shell): предпочтительно скачать и просмотреть скрипт:
  curl -fsSL <URL>/install.sh -o install.sh
  less install.sh
  sh install.sh
EOF
}

# --------------------------------------------------------------------------
# Разбор аргументов
# --------------------------------------------------------------------------
parse_args() {
  while [ $# -gt 0 ]; do
    case "$1" in
      --target)            TARGET="${2:?--target требует значение}"; shift 2 ;;
      --target=*)          TARGET="${1#*=}"; shift ;;
      --install-dir)       INSTALL_DIR="${2:?--install-dir требует значение}"; shift 2 ;;
      --install-dir=*)     INSTALL_DIR="${1#*=}"; shift ;;
      --repo-url)          REPO_URL="${2:?--repo-url требует значение}"; shift 2 ;;
      --repo-url=*)        REPO_URL="${1#*=}"; shift ;;
      --branch)            BRANCH="${2:?--branch требует значение}"; shift 2 ;;
      --branch=*)          BRANCH="${1#*=}"; shift ;;
      --scope)             SCOPE="${2:?--scope требует значение}"; shift 2 ;;
      --scope=*)           SCOPE="${1#*=}"; shift ;;
      --dry-run)           DRY_RUN=1; shift ;;
      --force)             FORCE=1; shift ;;
      --no-python-bootstrap) NO_PY_BOOTSTRAP=1; shift ;;
      --verbose)           VERBOSE=1; shift ;;
      --uninstall)         DO_UNINSTALL=1; shift ;;
      -h|--help)           usage; exit 0 ;;
      *)                   _bootdie "Неизвестный аргумент: $1 (см. --help)" ;;
    esac
  done

  case "$TARGET" in
    claude|codex|opencode|all|auto) : ;;
    *) _bootdie "Недопустимый --target: $TARGET" ;;
  esac
  case "$SCOPE" in
    global|project) : ;;
    *) _bootdie "Недопустимый --scope: $SCOPE (global|project)" ;;
  esac
  export TARGET INSTALL_DIR REPO_URL BRANCH SCOPE DRY_RUN FORCE NO_PY_BOOTSTRAP VERBOSE DO_UNINSTALL
}

# --------------------------------------------------------------------------
# Определение корня исходников: локальный clone или скачивание архива
# --------------------------------------------------------------------------
SRC_ROOT=""
TMP_ROOT=""

cleanup() {
  [ -n "$TMP_ROOT" ] && [ -d "$TMP_ROOT" ] && rm -rf "$TMP_ROOT" 2>/dev/null || true
}
trap cleanup EXIT INT TERM HUP

resolve_source_root() {
  # Каталог самого install.sh (если запущен из файла, а не из пайпа).
  _self="${0:-}"
  case "$_self" in
    */*) _selfdir="$(cd "$(dirname "$_self")" 2>/dev/null && pwd)" ;;
    *)   _selfdir="" ;;
  esac

  if [ -n "$_selfdir" ] && [ -f "$_selfdir/lib/common.sh" ] && [ -d "$_selfdir/skill" ]; then
    SRC_ROOT="$_selfdir"
    _boot "Локальный источник: $SRC_ROOT"
    return 0
  fi

  # Fallback: запуск как `sh install.sh` ($0 без пути) из корня репозитория.
  if [ -f "$PWD/lib/common.sh" ] && [ -d "$PWD/skill" ]; then
    SRC_ROOT="$PWD"
    _boot "Локальный источник (cwd): $SRC_ROOT"
    return 0
  fi

  # Иначе скачиваем архив репозитория.
  _boot "Локальный источник не найден — скачиваю репозиторий."
  TMP_ROOT="$(mktemp -d 2>/dev/null || mktemp -d -t cbx-installer)" \
    || _bootdie "Не удалось создать временную директорию"
  _arc="$TMP_ROOT/repo.tar.gz"
  _repo="${REPO_URL%.git}"; _repo="${_repo%/}"
  _url="$_repo/archive/refs/heads/$BRANCH.tar.gz"
  _boot "Источник (скачиваем архив): $_url"
  if command -v curl >/dev/null 2>&1; then
    curl -fsSL "$_url" -o "$_arc" || _bootdie "Скачивание не удалось: $_url"
  elif command -v wget >/dev/null 2>&1; then
    wget -qO "$_arc" "$_url" || _bootdie "Скачивание не удалось: $_url"
  else
    _bootdie "Не найдены ни curl, ни wget."
  fi
  [ -s "$_arc" ] || _bootdie "Скачанный архив пуст."

  command -v tar >/dev/null 2>&1 || _bootdie "Не найден tar."
  if tar -tzf "$_arc" 2>/dev/null | grep -Eq '(^/|(^|/)\.\.(/|$))'; then
    _bootdie "Архив содержит небезопасные пути. Отказ."
  fi
  mkdir -p "$TMP_ROOT/extracted"
  tar -xzf "$_arc" -C "$TMP_ROOT/extracted" || _bootdie "Распаковка не удалась."
  for _d in "$TMP_ROOT/extracted"/*/; do
    if [ -d "${_d}skill" ]; then SRC_ROOT="${_d%/}"; break; fi
  done
  [ -n "$SRC_ROOT" ] || _bootdie "В архиве не найден каталог skill/."
  _boot "Распаковано в: $SRC_ROOT"
}

# --------------------------------------------------------------------------
# Определение доступных CLI (для target=auto)
# --------------------------------------------------------------------------
detect_targets() {
  _found=""
  # Claude Code: бинарь claude или каталог ~/.claude.
  if have_cmd claude || [ -d "$HOME/.claude" ]; then _found="$_found claude"; fi
  # Codex CLI: бинарь codex или каталог ~/.codex.
  if have_cmd codex || [ -d "$HOME/.codex" ]; then _found="$_found codex"; fi
  # OpenCode: бинарь opencode или каталог ~/.config/opencode.
  if have_cmd opencode || [ -d "$HOME/.config/opencode" ]; then _found="$_found opencode"; fi
  printf '%s\n' "$_found" | sed 's/^ *//'
}

# --------------------------------------------------------------------------
# Запуск одного адаптера в subshell (изоляция функций adapter_*)
# --------------------------------------------------------------------------
run_one_target() {
  _t="$1"
  _adapter="$SRC_ROOT/adapters/$_t.sh"
  [ -f "$_adapter" ] || { log_error "Адаптер не найден: $_adapter"; return 1; }
  log_info "=== Target: $_t ==="
  (
    SKILL_SRC_DIR="$SRC_ROOT/skill"
    export SKILL_SRC_DIR
    . "$_adapter"
    if [ "$DO_UNINSTALL" = "1" ]; then
      adapter_uninstall
    else
      adapter_install
    fi
  )
}

# --------------------------------------------------------------------------
# main
# --------------------------------------------------------------------------
main() {
  parse_args "$@"

  if [ "$DRY_RUN" = "1" ]; then
    _boot "Режим dry-run: изменения НЕ применяются."
  fi

  resolve_source_root

  # Подключаем полную библиотеку функций.
  # shellcheck disable=SC1091
  . "$SRC_ROOT/lib/common.sh"

  # Проверяем источник правды.
  validate_skill_md "$SRC_ROOT/skill/SKILL.md" \
    || die "SKILL.md в источнике невалиден — установка прервана." 2

  # Определяем список целей.
  if [ "$TARGET" = "auto" ]; then
    _targets="$(detect_targets)"
    if [ -z "$_targets" ]; then
      log_warn "Авто-определение: не найдено ни одного CLI (claude/codex/opencode)."
      log_warn "Укажите цель явно: --target claude|codex|opencode|all"
      exit 4
    fi
    log_info "Авто-определены цели: $_targets"
  elif [ "$TARGET" = "all" ]; then
    _targets="claude codex opencode"
  else
    _targets="$TARGET"
  fi

  _rc=0
  for _t in $_targets; do
    run_one_target "$_t" || _rc=5
  done

  if [ "$_rc" = "0" ]; then
    if [ "$DO_UNINSTALL" = "1" ]; then
      log_ok "Удаление завершено."
    else
      log_ok "Установка завершена. Skill: $SKILL_NAME v$SKILL_VERSION"
    fi
  else
    log_error "Некоторые цели завершились с ошибкой."
  fi
  return "$_rc"
}

main "$@"
