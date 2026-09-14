#!/usr/bin/env bash
# Reproducible demo of codebase-index on a real public repository (Flask).
#
#   bash examples/demo/run_demo.sh                 # clones Flask into ./.tmp-demo
#   bash examples/demo/run_demo.sh /path/to/flask  # use an existing checkout
#
# Every command below is what an agent (or you) would run; the output is what
# examples/demo/EXPECTED_OUTPUT.md was captured from. Nothing leaves the machine.
set -euo pipefail

REPO_URL="https://github.com/pallets/flask.git"
REPO_SHA="d318b683471101618febed18996405ad26462110"   # pinned so the output is stable
WORKDIR="${1:-.tmp-demo/flask}"
export CBX_NO_SKILL_AUTO_UPDATE=1

step() { printf '\n\033[1;34m$ %s\033[0m\n' "$*"; "$@"; }

if ! command -v codebase-index >/dev/null 2>&1; then
  echo "codebase-index is not on PATH. Install it first:  pip install codebase-index" >&2
  exit 1
fi

if [ ! -d "$WORKDIR/.git" ]; then
  echo "Cloning Flask into $WORKDIR ..."
  git clone --quiet "$REPO_URL" "$WORKDIR"
fi
git -C "$WORKDIR" checkout --quiet "$REPO_SHA"
cd "$WORKDIR"

# 1. Build the index (about 230 files; a few seconds).
step codebase-index index

# 2. FIND — where is the session cookie signed and saved?
step codebase-index search "where is the session cookie signed and saved" --limit 5

# 3. TRACE — who calls open_session? (definitions, callers, edge confidence)
step codebase-index refs open_session

# 4. TRACE — how does a WSGI request reach the view function?
step codebase-index path wsgi_app dispatch_request

# 5. PREDICT — what could break if SecureCookieSessionInterface changes?
step codebase-index impact SecureCookieSessionInterface --direction up --depth 2

# 6. PREDICT — what does my current diff affect? (make a throwaway edit, then revert)
sed -i.bak 's/^    def open_session(/    def open_session(  # demo edit/' src/flask/sessions.py
step codebase-index diff-impact
git checkout --quiet -- src/flask/sessions.py && rm -f src/flask/sessions.py.bak

# 7. The same packet as an agent sees it.
step codebase-index --json search "where is the session cookie signed and saved" --limit 3

printf '\nDone. Index lives in %s/.claude/cache/codebase-index/ and nothing was sent anywhere.\n' "$WORKDIR"
