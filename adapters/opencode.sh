# shellcheck shell=sh
# adapters/opencode.sh — установка для OpenCode.
#
# OpenCode использует markdown-команды и agent-файлы:
#   global:  ~/.config/opencode/commands/<name>.md
#            ~/.config/opencode/agents/<name>.md
#   project: .opencode/commands/<name>.md
#            .opencode/agents/<name>.md
#
# Запуск команды в OpenCode: /<command-name> (см. README).
# Мы НЕ трогаем opencode.json/opencode.jsonc. Если потребуется правка config —
# делаем backup и патчим только managed section (здесь config не требуется).
#
# Подключается из install.sh. Использует функции lib/common.sh.

opencode_base_dir() {
  if [ -n "${INSTALL_DIR:-}" ]; then
    expand_home "$INSTALL_DIR"
  elif [ "${SCOPE:-global}" = "project" ]; then
    printf '%s\n' "$(pwd)/.opencode"
  else
    printf '%s\n' "$HOME/.config/opencode"
  fi
}

opencode_command_file() { printf '%s\n' "$(opencode_base_dir)/commands/$SKILL_NAME.md"; }
opencode_agent_file()   { printf '%s\n' "$(opencode_base_dir)/agents/$SKILL_NAME.md"; }
opencode_resource_dir() { printf '%s\n' "$(opencode_base_dir)/skills/$SKILL_NAME"; }

# Markdown-команда: что делает /codebase-index.
opencode_command_content() {
  _desc="$(skill_field "$SKILL_SRC_DIR/SKILL.md" description)"
  cat <<EOF
---
description: $_desc
---

Используй локальный индекс кода вместо полного сканирования репозитория.

Выполни поиск по индексу и ответь с цитатами file:line:

\`\`\`bash
codebase-index search "\$ARGUMENTS" --json
\`\`\`

Подкоманды: \`search\`, \`symbol <name>\`, \`refs <name>\`, \`impact <file|symbol>\`.
Если индекс отсутствует — сначала выполни \`codebase-index index\`.
EOF
}

adapter_install() {
  _cmd="$(opencode_command_file)"
  _agent="$(opencode_agent_file)"
  _resdir="$(opencode_resource_dir)"
  assert_no_traversal "$_cmd"; assert_no_traversal "$_resdir"
  log_info "OpenCode команда:  $_cmd"
  log_info "OpenCode agent:    $_agent"
  log_info "OpenCode ресурсы:  $_resdir"

  if [ -e "$_cmd" ] && [ "${FORCE:-0}" != "1" ] && [ "${DRY_RUN:-0}" != "1" ]; then
    die "Команда уже установлена: $_cmd (используйте --force)" 6
  fi

  MANIFEST_FILELIST="$(mktemp 2>/dev/null || echo "/tmp/cbx-opencode.$$")"
  export MANIFEST_FILELIST
  : > "$MANIFEST_FILELIST" 2>/dev/null || true

  # Ресурсы skill.
  if [ -e "$_resdir" ]; then
    backup_path "$_resdir" >/dev/null
    [ "${DRY_RUN:-0}" = "1" ] || rm -rf "$_resdir"
  fi
  copy_tree "$SKILL_SRC_DIR" "$_resdir"

  # Markdown-команда.
  if [ "${DRY_RUN:-0}" = "1" ]; then
    log_info "[dry-run] записал бы команду: $_cmd"
  else
    mkdir -p "$(dirname "$_cmd")"
    [ -e "$_cmd" ] && backup_path "$_cmd" >/dev/null
    opencode_command_content > "$_cmd"
    printf '%s\n' "$_cmd" >> "$MANIFEST_FILELIST"
    log_ok "Команда записана: $_cmd"
  fi

  # Agent-инструкция (тот же текст, что SKILL.md — как справочник).
  if [ "${DRY_RUN:-0}" = "1" ]; then
    log_info "[dry-run] записал бы agent: $_agent"
  else
    mkdir -p "$(dirname "$_agent")"
    [ -e "$_agent" ] && backup_path "$_agent" >/dev/null
    cp "$SKILL_SRC_DIR/SKILL.md" "$_agent"
    printf '%s\n' "$_agent" >> "$MANIFEST_FILELIST"
    log_ok "Agent записан: $_agent"
  fi

  _mf="$_resdir/install_manifest.json"
  _boot_status="$(run_python_bootstrap "$_resdir" "$_mf" "opencode")"
  _pyver="$(_py="$(find_python || true)"; [ -n "$_py" ] && python_version_of "$_py" || echo none)"
  write_manifest "$_mf" "opencode" "$_pyver" "$_boot_status"

  rm -f "$MANIFEST_FILELIST" 2>/dev/null || true
  log_ok "OpenCode: команда установлена. Запуск: /$SKILL_NAME"
}

adapter_uninstall() {
  _resdir="$(opencode_resource_dir)"
  _mf="$_resdir/install_manifest.json"
  [ -f "$_mf" ] && remove_from_manifest "$_mf"

  for _p in "$(opencode_command_file)" "$(opencode_agent_file)"; do
    if [ -f "$_p" ]; then
      if [ "${DRY_RUN:-0}" = "1" ]; then log_info "[dry-run] удалил бы: $_p"
      else rm -f "$_p" && log_ok "Удалён: $_p"; fi
    fi
  done
  if [ -d "$_resdir" ]; then
    if [ "${DRY_RUN:-0}" = "1" ]; then log_info "[dry-run] удалил бы: $_resdir"
    else rm -rf "$_resdir" && log_ok "Удалены ресурсы: $_resdir"; fi
  fi
}
