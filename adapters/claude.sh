# shellcheck shell=sh
# adapters/claude.sh — установка skill для Claude Code.
#
# Claude Code ищет skills в директориях skills/<name>/SKILL.md:
#   - global:  ~/.claude/skills/<skill-name>/
#   - project: <project>/.claude/skills/<skill-name>/
#
# ВАЖНО: точный путь может отличаться между версиями Claude Code.
# Поэтому путь вынесен в переменную и переопределяется флагом --install-dir.
# В README описано, как поменять путь вручную.
#
# Подключается из install.sh; рассчитывает на функции lib/common.sh
# и глобальные переменные: SKILL_SRC_DIR, INSTALL_DIR, SCOPE, FORCE, DRY_RUN,
# SKILL_NAME, REPO_URL, BRANCH, NO_PY_BOOTSTRAP.

# Дефолтный путь установки (вынесен в переменную, легко переопределить).
claude_default_dir() {
  if [ "${SCOPE:-global}" = "project" ]; then
    printf '%s\n' "$(pwd)/.claude/skills/$SKILL_NAME"
  else
    printf '%s\n' "$HOME/.claude/skills/$SKILL_NAME"
  fi
}

claude_target_dir() {
  if [ -n "${INSTALL_DIR:-}" ]; then
    expand_home "$INSTALL_DIR"
  else
    claude_default_dir
  fi
}

adapter_install() {
  _dst="$(claude_target_dir)"
  assert_no_traversal "$_dst"
  log_info "Claude Code skill-директория: $_dst"

  # Защита: без --install-dir не пишем за пределы HOME/проекта.
  if [ -z "${INSTALL_DIR:-}" ]; then
    if ! path_within "$HOME" "$_dst" && ! path_within "$(pwd)" "$_dst"; then
      die "Путь вне HOME/проекта без --install-dir: $_dst" 2
    fi
  fi

  if [ -e "$_dst" ] && [ "${FORCE:-0}" != "1" ] && [ "${DRY_RUN:-0}" != "1" ]; then
    die "Уже установлено: $_dst (используйте --force для перезаписи)" 6
  fi
  if [ -e "$_dst" ]; then
    backup_path "$_dst" >/dev/null
    [ "${DRY_RUN:-0}" = "1" ] || rm -rf "$_dst"
  fi

  MANIFEST_FILELIST="$(mktemp 2>/dev/null || echo "/tmp/cbx-claude.$$")"
  export MANIFEST_FILELIST
  : > "$MANIFEST_FILELIST" 2>/dev/null || true

  copy_tree "$SKILL_SRC_DIR" "$_dst"

  # Проверяем, что SKILL.md на месте после копирования.
  if [ "${DRY_RUN:-0}" != "1" ]; then
    validate_skill_md "$_dst/SKILL.md" || die "После копирования SKILL.md невалиден" 2
  fi

  _mf="$_dst/install_manifest.json"
  _boot_status="$(run_python_bootstrap "$_dst" "$_mf" "claude")"
  _pyver="$(_py="$(find_python || true)"; [ -n "$_py" ] && python_version_of "$_py" || echo none)"
  write_manifest "$_mf" "claude" "$_pyver" "$_boot_status"

  rm -f "$MANIFEST_FILELIST" 2>/dev/null || true
  log_ok "Claude Code: skill установлен в $_dst"
  log_info "Активируйте через меню skills в Claude Code (имя: $SKILL_NAME)."
}

adapter_uninstall() {
  _dst="$(claude_target_dir)"
  _mf="$_dst/install_manifest.json"
  if [ -f "$_mf" ]; then
    remove_from_manifest "$_mf"
  fi
  # Удаляем нашу skill-директорию целиком (она создана нами).
  if [ -d "$_dst" ]; then
    if [ "${DRY_RUN:-0}" = "1" ]; then
      log_info "[dry-run] удалил бы директорию: $_dst"
    else
      backup_path "$_dst" >/dev/null
      rm -rf "$_dst"
      log_ok "Claude Code: удалена директория $_dst"
    fi
  else
    log_warn "Claude Code: директория не найдена: $_dst"
  fi
}
