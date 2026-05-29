# shellcheck shell=sh
# lib/common.sh — общие функции для POSIX-инсталлятора codebase-index.
#
# Этот файл НЕ исполняется напрямую: он подключается (`. lib/common.sh`)
# из install.sh и из адаптеров adapters/*.sh.
#
# Все функции написаны на переносимом POSIX sh (без bash-специфики),
# чтобы install.sh можно было запускать через `sh` (в т.ч. `curl ... | sh`).
#
# Соглашение по именам:
#   log_info / log_warn / log_error / log_ok — единый формат вывода.
#   Идентификаторы и флаги — на английском; комментарии — на русском.

# --------------------------------------------------------------------------
# Логирование (INFO / WARN / ERROR / OK)
# --------------------------------------------------------------------------
# Цвета включаются только если stdout/stderr — терминал и не выставлен NO_COLOR.
if [ -t 2 ] && [ -z "${NO_COLOR:-}" ]; then
  _C_RESET="$(printf '\033[0m')"
  _C_INFO="$(printf '\033[36m')"   # cyan
  _C_WARN="$(printf '\033[33m')"   # yellow
  _C_ERR="$(printf '\033[31m')"    # red
  _C_OK="$(printf '\033[32m')"     # green
else
  _C_RESET='' ; _C_INFO='' ; _C_WARN='' ; _C_ERR='' ; _C_OK=''
fi

log_info()  { printf '%s[INFO]%s  %s\n'  "$_C_INFO" "$_C_RESET" "$*" >&2; }
log_warn()  { printf '%s[WARN]%s  %s\n'  "$_C_WARN" "$_C_RESET" "$*" >&2; }
log_error() { printf '%s[ERROR]%s %s\n'  "$_C_ERR"  "$_C_RESET" "$*" >&2; }
log_ok()    { printf '%s[OK]%s    %s\n'  "$_C_OK"   "$_C_RESET" "$*" >&2; }

# Подробный вывод только при VERBOSE=1.
log_debug() { [ "${VERBOSE:-0}" = "1" ] && printf '[DEBUG] %s\n' "$*" >&2 || true; }

# Завершение с ошибкой и осмысленным кодом возврата.
die() { log_error "$*"; exit "${2:-1}"; }

# --------------------------------------------------------------------------
# Проверка наличия команд
# --------------------------------------------------------------------------
have_cmd() { command -v "$1" >/dev/null 2>&1; }

# --------------------------------------------------------------------------
# Определение ОС и shell
# --------------------------------------------------------------------------
# Возвращает: macos | linux | windows | unknown
detect_os() {
  _uname="$(uname -s 2>/dev/null || echo unknown)"
  case "$_uname" in
    Darwin*)                 echo "macos" ;;
    Linux*)                  echo "linux" ;;
    CYGWIN*|MINGW*|MSYS*)    echo "windows" ;;
    *)                       echo "unknown" ;;
  esac
}

# Возвращает имя текущего shell (информативно).
detect_shell() {
  if [ -n "${BASH_VERSION:-}" ]; then echo "bash"
  elif [ -n "${ZSH_VERSION:-}" ]; then echo "zsh"
  else basename "${SHELL:-sh}"; fi
}

# --------------------------------------------------------------------------
# Безопасность путей
# --------------------------------------------------------------------------
# Раскрытие ведущего "~" в $HOME (POSIX sh не делает это в переменных).
expand_home() {
  case "$1" in
    "~")    printf '%s\n' "$HOME" ;;
    "~/"*)  printf '%s\n' "$HOME/${1#~/}" ;;
    *)      printf '%s\n' "$1" ;;
  esac
}

# Запрет path traversal: путь не должен содержать сегмент "..".
# Используется при распаковке архива и при выборе install-dir.
assert_no_traversal() {
  case "/$1/" in
    */../*) die "Небезопасный путь (path traversal запрещён): $1" 2 ;;
  esac
}

# Проверка, что target лежит внутри base (после нормализации).
# Возвращает 0 если внутри, 1 если снаружи. Используется для валидации
# install-dir: не писать за пределы HOME/проекта без явного --install-dir.
path_within() {
  _base="$1"; _target="$2"
  case "$_target/" in
    "$_base"/*|"$_base"/) return 0 ;;
    *) return 1 ;;
  esac
}

# --------------------------------------------------------------------------
# Временная директория с гарантированной очисткой
# --------------------------------------------------------------------------
make_tempdir() {
  _td="$(mktemp -d 2>/dev/null || mktemp -d -t cbx-installer)" \
    || die "Не удалось создать временную директорию"
  printf '%s\n' "$_td"
}

# --------------------------------------------------------------------------
# Скачивание архива репозитория (zip/tarball) без git
# --------------------------------------------------------------------------
# download_archive <repo_url> <branch> <out_file>
# Печатает URL, который будет скачан (security: всегда показываем источник).
download_archive() {
  _repo="$1"; _branch="$2"; _out="$3"
  # Нормализуем repo_url: убираем хвостовой ".git" и "/".
  _repo="${_repo%.git}"; _repo="${_repo%/}"
  _url="$_repo/archive/refs/heads/$_branch.tar.gz"

  log_info "Источник (скачиваем архив): $_url"
  if have_cmd curl; then
    curl -fsSL "$_url" -o "$_out" \
      || die "Скачивание не удалось (curl): $_url" 3
  elif have_cmd wget; then
    wget -qO "$_out" "$_url" \
      || die "Скачивание не удалось (wget): $_url" 3
  else
    die "Не найдены ни curl, ни wget. Установите один из них." 3
  fi
  [ -s "$_out" ] || die "Скачанный архив пуст: $_url" 3
}

# --------------------------------------------------------------------------
# Безопасная распаковка tar.gz в изолированную директорию
# --------------------------------------------------------------------------
# safe_extract <archive> <dest_dir>
# Защищает от path traversal: проверяем список записей до распаковки.
safe_extract() {
  _arc="$1"; _dest="$2"
  have_cmd tar || die "Не найден tar для распаковки архива" 3
  mkdir -p "$_dest"

  # Проверяем содержимое архива на абсолютные пути и "..".
  if tar -tzf "$_arc" 2>/dev/null | grep -Eq '(^/|(^|/)\.\.(/|$))'; then
    die "Архив содержит небезопасные пути (traversal). Отказ в распаковке." 2
  fi
  tar -xzf "$_arc" -C "$_dest" \
    || die "Распаковка архива не удалась" 3
}

# Находит каталог верхнего уровня внутри распакованного архива
# (GitHub архивы оборачивают всё в REPO-BRANCH/).
find_extracted_root() {
  _dest="$1"
  for _d in "$_dest"/*/; do
    if [ -d "$_d" ] && [ -d "${_d}skill" ]; then
      printf '%s\n' "${_d%/}"; return 0
    fi
  done
  # Fallback: единственный подкаталог.
  for _d in "$_dest"/*/; do
    [ -d "$_d" ] && { printf '%s\n' "${_d%/}"; return 0; }
  done
  printf '%s\n' "$_dest"
}

# --------------------------------------------------------------------------
# Валидация SKILL.md и YAML frontmatter
# --------------------------------------------------------------------------
# validate_skill_md <path>
# Проверяет: файл существует; первая строка "---"; есть закрывающий "---";
# в frontmatter есть ключи name и description.
validate_skill_md() {
  _f="$1"
  [ -f "$_f" ] || { log_error "SKILL.md не найден: $_f"; return 1; }

  _first="$(head -n1 "$_f")"
  [ "$_first" = "---" ] || { log_error "SKILL.md: нет открывающего YAML frontmatter (---)"; return 1; }

  # Берём блок между первым и вторым "---".
  _fm="$(awk 'NR>1 && /^---[[:space:]]*$/{exit} NR>1{print}' "$_f")"
  printf '%s\n' "$_fm" | grep -Eq '^name:[[:space:]]*[^[:space:]]' \
    || { log_error "SKILL.md: в frontmatter отсутствует поле name"; return 1; }
  printf '%s\n' "$_fm" | grep -Eq '^description:[[:space:]]*[^[:space:]]' \
    || { log_error "SKILL.md: в frontmatter отсутствует поле description"; return 1; }

  # Проверяем, что закрывающий "---" вообще есть.
  if ! awk 'NR>1 && /^---[[:space:]]*$/{found=1; exit} END{exit !found}' "$_f"; then
    log_error "SKILL.md: не найден закрывающий YAML frontmatter (---)"; return 1
  fi
  return 0
}

# Достаёт значение поля из frontmatter (name/description/version).
skill_field() {
  _f="$1"; _key="$2"
  awk -v k="$_key" '
    NR==1 && $0=="---"{infm=1; next}
    infm && /^---[[:space:]]*$/{exit}
    infm {
      if ($0 ~ "^"k":[[:space:]]*") {
        sub("^"k":[[:space:]]*", ""); gsub(/^"|"$/, ""); print; exit
      }
    }' "$_f"
}

# --------------------------------------------------------------------------
# Резервные копии
# --------------------------------------------------------------------------
# backup_path <path> — делает <path>.bak-TIMESTAMP, печатает путь бэкапа.
# Метку времени берём из mtime файла (не используем переменные времени,
# чтобы поведение было детерминированным в тестах).
backup_path() {
  _p="$1"
  [ -e "$_p" ] || return 0
  if [ "${DRY_RUN:-0}" = "1" ]; then
    log_info "[dry-run] создал бы backup: $_p"
    return 0
  fi
  _ts="$(date +%Y%m%d-%H%M%S 2>/dev/null || echo backup)"
  _bak="$_p.bak-$_ts"
  # Если такой бэкап уже есть — добавим суффикс с pid.
  [ -e "$_bak" ] && _bak="$_bak.$$"
  cp -a "$_p" "$_bak" 2>/dev/null || cp -R "$_p" "$_bak"
  log_info "Создан backup: $_bak"
  printf '%s\n' "$_bak"
}

# --------------------------------------------------------------------------
# Managed block (для AGENTS.md и подобных instruction-файлов)
# --------------------------------------------------------------------------
MANAGED_BEGIN="<!-- BEGIN MANAGED SKILL BLOCK: codebase-index -->"
MANAGED_END="<!-- END MANAGED SKILL BLOCK: codebase-index -->"

# managed_block_upsert <file> <content_file>
# Вставляет/обновляет блок между маркерами, не трогая остальной файл.
managed_block_upsert() {
  _file="$1"; _content="$2"
  if [ "${DRY_RUN:-0}" = "1" ]; then
    log_info "[dry-run] обновил бы managed block в: $_file"
    return 0
  fi
  mkdir -p "$(dirname "$_file")"
  if [ -f "$_file" ]; then
    backup_path "$_file" >/dev/null
    if grep -qF "$MANAGED_BEGIN" "$_file"; then
      # Удаляем старый блок, затем дописываем новый в конец.
      _tmp="$_file.tmp.$$"
      awk -v b="$MANAGED_BEGIN" -v e="$MANAGED_END" '
        $0==b{skip=1} skip && $0==e{skip=0; next} !skip{print}
      ' "$_file" > "$_tmp"
      mv "$_tmp" "$_file"
    fi
  else
    : > "$_file"
  fi
  {
    printf '\n%s\n' "$MANAGED_BEGIN"
    cat "$_content"
    printf '%s\n' "$MANAGED_END"
  } >> "$_file"
  log_ok "Managed block записан в: $_file"
}

# managed_block_remove <file> — удаляет только наш блок, файл сохраняется.
managed_block_remove() {
  _file="$1"
  [ -f "$_file" ] || return 0
  if [ "${DRY_RUN:-0}" = "1" ]; then
    log_info "[dry-run] удалил бы managed block из: $_file"
    return 0
  fi
  grep -qF "$MANAGED_BEGIN" "$_file" || return 0
  backup_path "$_file" >/dev/null
  _tmp="$_file.tmp.$$"
  awk -v b="$MANAGED_BEGIN" -v e="$MANAGED_END" '
    $0==b{skip=1} skip && $0==e{skip=0; next} !skip{print}
  ' "$_file" > "$_tmp"
  mv "$_tmp" "$_file"
  log_ok "Managed block удалён из: $_file"
}

# --------------------------------------------------------------------------
# Копирование файлов с учётом dry-run и записью списка установленных файлов
# --------------------------------------------------------------------------
# INSTALLED_FILES — глобальный накопитель (по одному пути на строку).
INSTALLED_FILES=""

record_installed() { INSTALLED_FILES="$INSTALLED_FILES$1
"; }

# copy_tree <src_dir> <dst_dir> — копирует дерево, наполняет INSTALLED_FILES.
copy_tree() {
  _src="$1"; _dst="$2"
  if [ "${DRY_RUN:-0}" = "1" ]; then
    log_info "[dry-run] скопировал бы: $_src -> $_dst"
    return 0
  fi
  mkdir -p "$_dst"
  # Копируем содержимое src внутрь dst.
  ( cd "$_src" && find . -type f -print ) | while IFS= read -r _rel; do
    _rel="${_rel#./}"
    _to="$_dst/$_rel"
    mkdir -p "$(dirname "$_to")"
    cp "$_src/$_rel" "$_to"
  done
  # Список файлов фиксируем отдельно (find в subshell не делится переменной).
  ( cd "$_src" && find . -type f -print ) | while IFS= read -r _rel; do
    printf '%s\n' "$_dst/${_rel#./}"
  done >> "${MANIFEST_FILELIST:-/dev/null}"
  log_ok "Скопировано: $_src -> $_dst"
}

# --------------------------------------------------------------------------
# Манифест установки
# --------------------------------------------------------------------------
# Минимальный JSON-экранировщик строк.
json_escape() {
  printf '%s' "$1" | sed -e 's/\\/\\\\/g' -e 's/"/\\"/g' -e 's/\t/\\t/g'
}

# write_manifest <manifest_path> <target> <python_version> <bootstrap_status>
# installed_files читаются из файла $MANIFEST_FILELIST (по одному пути на строку).
write_manifest() {
  _mf="$1"; _target="$2"; _py="$3"; _boot="$4"
  if [ "${DRY_RUN:-0}" = "1" ]; then
    log_info "[dry-run] записал бы manifest: $_mf"
    return 0
  fi
  _installed_at="$(date -u +%Y-%m-%dT%H:%M:%SZ 2>/dev/null || echo unknown)"
  mkdir -p "$(dirname "$_mf")"

  # Собираем installed_files как JSON-массив.
  _files_json=""
  if [ -f "${MANIFEST_FILELIST:-}" ]; then
    while IFS= read -r _line; do
      [ -n "$_line" ] || continue
      _esc="$(json_escape "$_line")"
      if [ -z "$_files_json" ]; then _files_json="\"$_esc\""
      else _files_json="$_files_json, \"$_esc\""; fi
    done < "$MANIFEST_FILELIST"
  fi

  cat > "$_mf" <<EOF
{
  "skill_name": "$(json_escape "${SKILL_NAME}")",
  "version": "$(json_escape "${SKILL_VERSION}")",
  "installed_at": "$_installed_at",
  "target": "$(json_escape "$_target")",
  "os": "$(json_escape "$(detect_os)")",
  "source_repo": "$(json_escape "${REPO_URL}")",
  "branch": "$(json_escape "${BRANCH}")",
  "installed_files": [$_files_json],
  "python_version": "$(json_escape "$_py")",
  "bootstrap_status": "$(json_escape "$_boot")"
}
EOF
  log_ok "Manifest записан: $_mf"
}

# --------------------------------------------------------------------------
# Python runtime / bootstrap
# --------------------------------------------------------------------------
# find_python — печатает путь к python3/python >= 3.9 или пусто.
find_python() {
  for _cand in python3 python; do
    if have_cmd "$_cand"; then
      if "$_cand" -c 'import sys; raise SystemExit(0 if sys.version_info[:2] >= (3,9) else 1)' 2>/dev/null; then
        command -v "$_cand"; return 0
      fi
    fi
  done
  return 1
}

python_version_of() { "$1" -c 'import sys;print("%d.%d.%d"%sys.version_info[:3])' 2>/dev/null || echo unknown; }

# run_python_bootstrap <skill_resource_dir> <manifest_path> <target>
# Создаёт .venv (если есть Python), ставит requirements.txt (если есть),
# запускает skill/scripts/bootstrap.py (если есть). Управляется NO_PY_BOOTSTRAP.
# Возвращает строку статуса через эхо: ok | skipped | no-python | failed.
run_python_bootstrap() {
  _resdir="$1"; _mf="$2"; _target="$3"
  if [ "${NO_PY_BOOTSTRAP:-0}" = "1" ]; then
    log_info "Python bootstrap пропущен (--no-python-bootstrap)"
    echo "skipped"; return 0
  fi

  _py="$(find_python || true)"
  if [ -z "$_py" ]; then
    log_warn "Python 3.9+ не найден на PATH."
    log_warn "Установите Python вручную (https://www.python.org/downloads/),"
    log_warn "затем перезапустите установку без --no-python-bootstrap."
    echo "no-python"; return 0
  fi
  log_info "Python найден: $_py ($(python_version_of "$_py"))"

  if [ "${DRY_RUN:-0}" = "1" ]; then
    log_info "[dry-run] создал бы venv и запустил bootstrap.py в: $_resdir"
    echo "skipped"; return 0
  fi

  _boot_script="$_resdir/scripts/bootstrap.py"
  if [ -f "$_boot_script" ]; then
    log_info "Запуск bootstrap.py …"
    if "$_py" "$_boot_script" \
        --skill-dir "$_resdir" \
        --manifest "$_mf" \
        --target "$_target"; then
      echo "ok"; return 0
    else
      log_warn "bootstrap.py завершился с ошибкой (установка не прервана)."
      echo "failed"; return 0
    fi
  fi
  log_debug "bootstrap.py не найден в $_resdir/scripts — пропуск."
  echo "skipped"
}

# --------------------------------------------------------------------------
# Удаление файлов из manifest при uninstall
# --------------------------------------------------------------------------
# remove_from_manifest <manifest_path>
remove_from_manifest() {
  _mf="$1"
  [ -f "$_mf" ] || { log_warn "Manifest не найден: $_mf"; return 1; }
  log_info "Читаю manifest: $_mf"
  # Извлекаем installed_files (простой парсер: строки в массиве).
  _files="$(awk '
    /"installed_files"[[:space:]]*:[[:space:]]*\[/{infiles=1}
    infiles{
      line=$0
      while (match(line, /"[^"]*"/)) {
        s=substr(line, RSTART+1, RLENGTH-2)
        if (s != "installed_files") print s
        line=substr(line, RSTART+RLENGTH)
      }
    }
    infiles && /\]/{exit}
  ' "$_mf")"

  printf '%s\n' "$_files" | while IFS= read -r _f; do
    [ -n "$_f" ] || continue
    if [ "${DRY_RUN:-0}" = "1" ]; then
      log_info "[dry-run] удалил бы: $_f"
    elif [ -e "$_f" ]; then
      rm -f "$_f" && log_ok "Удалён: $_f"
    fi
  done

  if [ "${DRY_RUN:-0}" != "1" ]; then
    rm -f "$_mf" && log_ok "Удалён manifest: $_mf"
  fi
}
