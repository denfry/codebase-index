# shellcheck shell=sh
# adapters/codex.sh — установка для Codex CLI.
#
# Для Codex это НЕ «Claude Skill», а адаптация в формате instruction package:
#   - инструкции добавляются в AGENTS.md (project) или ~/.codex/AGENTS.md (global)
#     внутри managed block с маркерами BEGIN/END MANAGED SKILL BLOCK;
#   - существующий AGENTS.md НЕ затирается: делается backup и патчится только блок;
#   - дополнительные scripts/resources ставятся в ~/.codex/skills/<skill-name>/.
#
# Подключается из install.sh. Использует функции lib/common.sh.

# Каталог ресурсов Codex (scripts/SKILL.md и т.п.).
codex_resource_dir() {
  if [ -n "${INSTALL_DIR:-}" ] && [ "${SCOPE:-global}" = "global" ]; then
    printf '%s\n' "$(expand_home "$INSTALL_DIR")/skills/$SKILL_NAME"
  else
    printf '%s\n' "$HOME/.codex/skills/$SKILL_NAME"
  fi
}

# Файл инструкций (AGENTS.md).
codex_agents_file() {
  if [ "${SCOPE:-global}" = "project" ]; then
    printf '%s\n' "$(pwd)/AGENTS.md"
  elif [ -n "${INSTALL_DIR:-}" ]; then
    printf '%s\n' "$(expand_home "$INSTALL_DIR")/AGENTS.md"
  else
    printf '%s\n' "$HOME/.codex/AGENTS.md"
  fi
}

# Текст managed-block: краткая инструкция + ссылка на ресурсы.
codex_block_content() {
  _resdir="$1"
  _desc="$(skill_field "$SKILL_SRC_DIR/SKILL.md" description)"
  cat <<EOF
## Skill: $SKILL_NAME (managed)

$_desc

Ресурсы skill установлены в: \`$_resdir\`
Подробная инструкция: \`$_resdir/SKILL.md\`

Используйте CLI \`codebase-index\` (обёртка \`cbx\`) для поиска по индексу
перед чтением файлов. Команды: \`search\`, \`symbol\`, \`refs\`, \`impact\`.
EOF
}

adapter_install() {
  _resdir="$(codex_resource_dir)"
  _agents="$(codex_agents_file)"
  assert_no_traversal "$_resdir"
  assert_no_traversal "$_agents"
  log_info "Codex CLI ресурсы:   $_resdir"
  log_info "Codex CLI инструкции: $_agents"

  if [ -e "$_resdir" ] && [ "${FORCE:-0}" != "1" ] && [ "${DRY_RUN:-0}" != "1" ]; then
    die "Ресурсы уже установлены: $_resdir (используйте --force)" 6
  fi
  if [ -e "$_resdir" ]; then
    backup_path "$_resdir" >/dev/null
    [ "${DRY_RUN:-0}" = "1" ] || rm -rf "$_resdir"
  fi

  MANIFEST_FILELIST="$(mktemp 2>/dev/null || echo "/tmp/cbx-codex.$$")"
  export MANIFEST_FILELIST
  : > "$MANIFEST_FILELIST" 2>/dev/null || true

  copy_tree "$SKILL_SRC_DIR" "$_resdir"
  if [ "${DRY_RUN:-0}" != "1" ]; then
    validate_skill_md "$_resdir/SKILL.md" || die "SKILL.md невалиден после копирования" 2
  fi

  # Патчим AGENTS.md только в пределах managed block.
  _blk="$(mktemp 2>/dev/null || echo "/tmp/cbx-codex-blk.$$")"
  codex_block_content "$_resdir" > "$_blk"
  managed_block_upsert "$_agents" "$_blk"
  rm -f "$_blk" 2>/dev/null || true
  # AGENTS.md тоже фиксируем в manifest (для информации; удаляем как managed block).
  [ "${DRY_RUN:-0}" = "1" ] || printf '%s\n' "$_agents" >> "$MANIFEST_FILELIST"

  _mf="$_resdir/install_manifest.json"
  _boot_status="$(run_python_bootstrap "$_resdir" "$_mf" "codex")"
  _pyver="$(_py="$(find_python || true)"; [ -n "$_py" ] && python_version_of "$_py" || echo none)"
  write_manifest "$_mf" "codex" "$_pyver" "$_boot_status"

  rm -f "$MANIFEST_FILELIST" 2>/dev/null || true
  log_ok "Codex CLI: instruction package установлен."
}

adapter_uninstall() {
  _resdir="$(codex_resource_dir)"
  _agents="$(codex_agents_file)"

  # Из AGENTS.md удаляем ТОЛЬКО managed block, файл сохраняем.
  managed_block_remove "$_agents"

  if [ -d "$_resdir" ]; then
    if [ "${DRY_RUN:-0}" = "1" ]; then
      log_info "[dry-run] удалил бы ресурсы: $_resdir"
    else
      backup_path "$_resdir" >/dev/null
      rm -rf "$_resdir"
      log_ok "Codex CLI: удалены ресурсы $_resdir"
    fi
  else
    log_warn "Codex CLI: ресурсы не найдены: $_resdir"
  fi
}
