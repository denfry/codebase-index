#!/usr/bin/env bash
# SessionStart bootstrap for the codebase-index plugin.
# Provisions a Python venv with the codebase-index CLI into ${CLAUDE_PLUGIN_DATA},
# reinstalling only when the bundled requirements.lock changes (official diff-pattern).
# Writes ${CLAUDE_PLUGIN_ROOT}/.venv-path so the bin/ wrappers can locate the venv.
set -euo pipefail

ROOT="${CLAUDE_PLUGIN_ROOT:?CLAUDE_PLUGIN_ROOT not set}"
DATA="${CLAUDE_PLUGIN_DATA:?CLAUDE_PLUGIN_DATA not set}"

VENV="$DATA/venv"
LOCK_SRC="$ROOT/requirements.lock"
LOCK_DST="$DATA/requirements.lock"

mkdir -p "$DATA"
# Pointer the wrappers read. ROOT is per-version/ephemeral, so rewrite it every session.
printf '%s\n' "$VENV" > "$ROOT/.venv-path"

# Warm path: venv present and the lock unchanged -> nothing to do.
if [ -x "$VENV/bin/codebase-index" ] && diff -q "$LOCK_SRC" "$LOCK_DST" >/dev/null 2>&1; then
  exit 0
fi

PY="$(command -v python3 || command -v python || true)"
if [ -z "$PY" ]; then
  echo "codebase-index: Python 3.10+ was not found on PATH. Install Python, then restart Claude Code." >&2
  exit 0
fi

install() {
  if [ "${CBX_NO_UV:-0}" != "1" ] && command -v uv >/dev/null 2>&1; then
    uv venv "$VENV" >&2
    if [ -n "${CBX_INSTALL_SPEC:-}" ]; then
      uv pip install --python "$VENV/bin/python" "$CBX_INSTALL_SPEC" >&2
    else
      uv pip install --python "$VENV/bin/python" -r "$LOCK_SRC" >&2
    fi
  else
    "$PY" -m venv "$VENV" >&2
    "$VENV/bin/python" -m pip install --upgrade pip >&2
    if [ -n "${CBX_INSTALL_SPEC:-}" ]; then
      "$VENV/bin/python" -m pip install "$CBX_INSTALL_SPEC" >&2
    else
      "$VENV/bin/python" -m pip install -r "$LOCK_SRC" >&2
    fi
  fi
}

# `install` is called in an `if`, which disables set -e inside it, so a failed
# step returns non-zero here instead of aborting the script.
if install; then
  cp "$LOCK_SRC" "$LOCK_DST"
else
  rm -f "$LOCK_DST"
  echo "codebase-index: bootstrap install failed; will retry next session." >&2
  exit 0
fi
