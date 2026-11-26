#!/bin/sh
# Read-only post-deployment gate, also used after an operator re-dispatches a tag.
set -u
ROOT=$(git rev-parse --show-toplevel) || exit 1
S=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd) || exit 1
log(){ echo "$(date -u +%H:%M:%S) $*"; }

# Refuse missing local dependencies before the release can mutate anything. Never install
# packages or browsers as part of a production operation.
[ -z "${CI:-}" ] || { log "live browser checks are operator-only, not CI"; exit 1; }
if [ -x "$ROOT/.venv/Scripts/python.exe" ]; then PY="$ROOT/.venv/Scripts/python.exe"
elif [ -x "$ROOT/.venv/bin/python" ]; then PY="$ROOT/.venv/bin/python"
else PY=$(command -v python || command -v python3) || { log "python not found"; exit 1; }
fi
"$PY" -c '' || { log "python could not start"; exit 1; }
command -v node >/dev/null || { log "node not found"; exit 1; }
CLI="$ROOT/web/node_modules/@playwright/test/cli.js"
[ -f "$CLI" ] || { log "install the locked web dependencies before releasing"; exit 1; }
node "$CLI" --version >/dev/null || { log "browser test runner could not start"; exit 1; }
node -e 'const { chromium } = require(process.argv[1]); (async () => { const browser = await chromium.launch({ timeout: 10000 }); await browser.close(); })().catch(() => { console.error("Chromium could not start; install its browser before releasing"); process.exit(1); });' "$ROOT/web/node_modules/playwright" || exit 1
if [ "${1:-}" = --preflight ]; then
  [ "$#" -eq 1 ] || exit 2
  exit 0
fi
case "$#" in 1|2|3) ;; *) log "usage: verify_release.sh <accepted-generated-at-ISO> [settled-gameweek] [expected-data-root]"; exit 2;; esac
STAMP="$1"; SETTLED="${2:-}"; DATA_ROOT="${3:-}"
case "$SETTLED" in *[!0-9]*) log "settled gameweek must be a number"; exit 2;; esac
set -- "$STAMP"
if [ -n "$SETTLED" ]; then set -- "$@" --settled "$SETTLED"; fi
if [ -n "$DATA_ROOT" ]; then
  [ -d "$DATA_ROOT" ] || { log "expected data root does not exist"; exit 2; }
  set -- "$@" --expected-data-root "$DATA_ROOT"
fi
log "checking the live publication"
"$PY" "$S/verify_live.py" "$@" || {
  log "live verification failed; retrying once after 60 seconds"
  sleep 60
  "$PY" "$S/verify_live.py" "$@" || { log "live verification found failures"; exit 1; }
}
cd "$ROOT/web" || exit 1
log "running read-only live smoke and four-profile page tour"
STARTED=$(date +%s)
LIVE_BASE_URL=https://squadopt.mymandev.com node "$CLI" test --config playwright.live.config.ts || {
  log "live browser checks failed; the release is not verified"
  exit 1
}
log "live browser checks passed in $(( $(date +%s) - STARTED )) seconds"
