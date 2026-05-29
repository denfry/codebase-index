#!/usr/bin/env sh
# tests/installer/smoke.sh — smoke-сценарий для install.sh (POSIX sh).
#
# Проверяет:
#   1. dry-run для auto/claude/codex/opencode;
#   2. реальную установку во временную директорию (--install-dir);
#   3. наличие SKILL.md и install_manifest.json;
#   4. uninstall из временной директории.
#
# Запуск из корня репозитория:  sh tests/installer/smoke.sh
set -eu

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(cd "$HERE/../.." && pwd)"
INSTALL="$ROOT/install.sh"

PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); printf '  [PASS] %s\n' "$*"; }
bad()  { FAIL=$((FAIL+1)); printf '  [FAIL] %s\n' "$*"; }

run() { sh "$INSTALL" "$@"; }

echo "== 1. dry-run для всех целей (без python bootstrap) =="
for t in auto claude codex opencode; do
  # auto может не найти CLI в CI — это допустимо (exit 4), остальные должны проходить.
  if run --target "$t" --dry-run --no-python-bootstrap >/dev/null 2>&1; then
    ok "dry-run --target $t"
  else
    rc=$?
    if [ "$t" = "auto" ] && [ "$rc" = "4" ]; then
      ok "dry-run --target auto (нет CLI в окружении — ожидаемо)"
    else
      bad "dry-run --target $t (rc=$rc)"
    fi
  fi
done

echo "== 2. установка claude в temp install-dir =="
TMP="$(mktemp -d)"
SKILL_DIR="$TMP/skills/codebase-index"
trap 'rm -rf "$TMP"' EXIT

if run --target claude --install-dir "$SKILL_DIR" --no-python-bootstrap --force >/dev/null 2>&1; then
  ok "установка claude в $SKILL_DIR"
else
  bad "установка claude (rc=$?)"
fi

echo "== 3. проверка артефактов =="
[ -f "$SKILL_DIR/SKILL.md" ] && ok "SKILL.md существует" || bad "SKILL.md отсутствует"
[ -f "$SKILL_DIR/install_manifest.json" ] && ok "install_manifest.json существует" || bad "manifest отсутствует"
if [ -f "$SKILL_DIR/install_manifest.json" ]; then
  grep -q '"skill_name"' "$SKILL_DIR/install_manifest.json" && ok "manifest содержит skill_name" || bad "manifest без skill_name"
  grep -q '"target": "claude"' "$SKILL_DIR/install_manifest.json" && ok "manifest target=claude" || bad "manifest target неверный"
fi

echo "== 4. uninstall =="
if run --target claude --install-dir "$SKILL_DIR" --uninstall >/dev/null 2>&1; then
  ok "uninstall выполнен"
else
  bad "uninstall (rc=$?)"
fi
[ -f "$SKILL_DIR/SKILL.md" ] && bad "SKILL.md не удалён" || ok "SKILL.md удалён"

echo
printf 'ИТОГО: PASS=%s FAIL=%s\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ] || exit 1
