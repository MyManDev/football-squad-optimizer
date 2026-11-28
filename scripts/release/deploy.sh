#!/bin/sh
# Stage two of the release: verify main, wait for its push CI, tag, dispatch the trusted deploy,
# and watch the run to completion. Every step verifies before the next, and refuses loudly.
set -u
ROOT=$(git rev-parse --show-toplevel) || exit 1
S=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd) || exit 1
cd "$ROOT" || exit 1
log(){ echo "$(date -u +%H:%M:%S) $*"; }

# The operator can check every local prerequisite before the release mutates anything.
# This mode never installs packages, fetches a repository or contacts a service.
preflight() {
  [ -z "${CI:-}" ] || { log "live browser checks are operator-only, not CI"; return 1; }
  if [ -x "$ROOT/.venv/Scripts/python.exe" ]; then PY="$ROOT/.venv/Scripts/python.exe"
  elif [ -x "$ROOT/.venv/bin/python" ]; then PY="$ROOT/.venv/bin/python"
  else PY=$(command -v python || command -v python3) || { log "python not found"; return 1; }
  fi
  "$PY" -c '' || { log "python could not start"; return 1; }
  BROWSER_READY=0
  CLI="$ROOT/web/node_modules/@playwright/test/cli.js"
  if command -v node >/dev/null 2>&1 && [ -f "$CLI" ] &&
    node "$CLI" --version >/dev/null 2>&1 &&
    node -e 'const { chromium } = require(process.argv[1]); (async () => { const browser = await chromium.launch({ timeout: 10000 }); await browser.close(); })().catch(() => process.exit(1));' "$ROOT/web/node_modules/playwright" >/dev/null 2>&1; then
    BROWSER_READY=1
  fi
  # Missing optional browser tooling never stops the HTTP/content gate.
  return 0
}

verify_live_after_deploy() {
  preflight || return 1
  set -- "$ACCEPTED_STAMP"
  if [ -n "$SETTLED" ]; then set -- "$@" --settled "$SETTLED"; fi
  if [ -n "$DATA_ROOT" ]; then
    [ -d "$DATA_ROOT" ] || { log "expected data root does not exist"; return 1; }
    set -- "$@" --expected-data-root "$DATA_ROOT"
  fi
  log "checking the live publication"
  "$PY" "$S/verify_live.py" "$@" || {
    log "live verification failed; retrying once after 60 seconds"
    sleep 60
    "$PY" "$S/verify_live.py" "$@" || { log "live verification found failures"; return 1; }
  }
  if [ "$BROWSER_READY" -eq 0 ]; then
    log "SKIP browser smoke and tour: local Node, locked web dependencies or Chromium unavailable; HTTP/content gate passed"
    return 0
  fi
  cd "$ROOT/web" || return 1
  log "running read-only live smoke and four-profile page tour"
  BROWSER_STARTED=$(date +%s)
  LIVE_SMOKE_COMPUTE= LIVE_BASE_URL=https://squadopt.mymandev.com node "$CLI" test --config playwright.live.config.ts || {
    log "live browser checks failed; the release is not verified"
    return 1
  }
  log "live browser checks passed in $(( $(date +%s) - BROWSER_STARTED )) seconds"
}

if [ "${1:-}" = --preflight ]; then
  [ "$#" -eq 1 ] || { echo 'usage: deploy.sh --preflight' >&2; exit 2; }
  preflight || exit 1
  exit 0
fi

GH=$(command -v gh || printf '%s' 'C:/Program Files/GitHub CLI/gh.exe')
[ -x "$GH" ] || command -v "$GH" >/dev/null || { echo 'gh not found' >&2; exit 1; }
REPO="MyManDev/football-squad-optimizer"
case "$#" in 2|3|4) ;; *) echo 'usage: deploy.sh <site-tag> <accepted-generated-at-ISO> [settled-gameweek] [expected-data-root]' >&2; exit 2;; esac
TAG="$1"; ACCEPTED_STAMP="$2"; SETTLED="${3:-}"; DATA_ROOT="${4:-}"
case "$SETTLED" in *[!0-9]*) log "settled gameweek must be a number"; exit 2;; esac
if [ "${TAG#*-settled}" != "$TAG" ] && [ -z "$SETTLED" ]; then
  log "a settled tag requires its gameweek"; exit 2
fi
if [ -n "$DATA_ROOT" ] && [ ! -d "$DATA_ROOT" ]; then log "expected data root does not exist"; exit 2; fi
preflight || { log "live verification preflight failed"; exit 1; }

git fetch -q origin || { log "fetch failed"; exit 1; }
MAIN=$(git rev-parse origin/main)
DEV=$(git rev-parse origin/develop)

# main must be a two-parent merge whose tree is exactly develop's.
PARENTS=$(( $(git rev-list --parents -n1 origin/main | wc -w) - 1 ))
[ "$PARENTS" -eq 2 ] || { log "main tip $MAIN has $PARENTS parent(s), not a release merge; refusing"; exit 1; }
[ "$(git rev-parse 'origin/main^{tree}')" = "$(git rev-parse 'origin/develop^{tree}')" ] || { log "main tree != develop tree; refusing"; exit 1; }
log "main $MAIN is a two-parent merge with tree == develop $DEV"

# Wait for a SUCCESSFUL push CI run on exactly that SHA, with one unexpired site artifact.
# A run that ends without success has its failed jobs re-run once, and the wait starts again.
# On 14 and 15 Nov 2026 one flaky browser check on main stopped two scheduled releases after
# their release PRs had merged; a real failure fails the second attempt too, and that refuses.
# Only failed jobs run again, so the site artifact of a web job that passed is the same one.
log "waiting for main-push CI on $MAIN"
deadline=$(( $(date +%s) + 2400 ))
RUN=""
RERUN_FROM=""
while [ "$(date +%s)" -lt "$deadline" ]; do
  RUN=$("$GH" run list --workflow ci.yml --branch main --event push --commit "$MAIN" --limit 1 --json databaseId,attempt,status,conclusion --jq '.[0] | "\(.databaseId) \(.attempt) \(.status) \(.conclusion)"' 2>/dev/null || echo "")
  # shellcheck disable=SC2086 # the four fields are split on purpose; an empty conclusion is last
  set -- $RUN
  CI_ID=${1:-}; CI_ATTEMPT=${2:-0}; CI_STATUS=${3:-}; CI_CONCLUSION=${4:-}
  if [ "$CI_STATUS" = completed ]; then
    [ "$CI_CONCLUSION" = success ] && break
    if [ -z "$RERUN_FROM" ]; then
      log "main CI run $CI_ID attempt $CI_ATTEMPT ended $CI_CONCLUSION; re-running its failed jobs once"
      "$GH" run rerun "$CI_ID" --failed >/dev/null 2>&1 || { log "main CI run $CI_ID could not be re-run; refusing to deploy"; exit 1; }
      RERUN_FROM=$CI_ATTEMPT
      deadline=$(( $(date +%s) + 2400 ))
    elif [ "$CI_ATTEMPT" -gt "$RERUN_FROM" ]; then
      log "main CI run $CI_ID attempt $CI_ATTEMPT ended $CI_CONCLUSION after the re-run; refusing to deploy"; exit 1
    fi
  fi
  sleep 45
done
case "$RUN" in *" completed success") ;; *) log "no successful main CI run within 40 minutes (last: '$RUN'); refusing"; exit 1;; esac
RID=${RUN%% *}
SITES=$("$GH" api "repos/$REPO/actions/runs/$RID/artifacts" --jq '[.artifacts[] | select(.name=="site" and .expired==false)] | length' 2>/dev/null || echo 0)
[ "$SITES" -eq 1 ] || { log "CI run $RID has $SITES unexpired site artifact(s), need exactly 1; refusing"; exit 1; }
log "main CI run $RID succeeded with one site artifact"

# Annotated tag on the main SHA. Immutable: refuse if it exists anywhere.
# The whole ref name is compared, so a tag that is a prefix of an existing one (fix1 beside
# fix10) is not mistaken for it.
if git ls-remote --tags origin | cut -f2 | grep -qxF "refs/tags/$TAG"; then log "tag $TAG exists on origin; refusing"; exit 1; fi
git tag -a "$TAG" "$MAIN" -m "$TAG" || { log "tag failed"; exit 1; }
git push -q origin "refs/tags/$TAG" || { log "tag push failed"; exit 1; }
log "tagged $MAIN as $TAG"

# Dispatch the trusted workflow from the default branch, as the runbook requires. The time is
# taken before dispatching, a minute early for clock skew, so that only a run created after it
# can be picked: the newest dispatch run is otherwise the previous release's, and watching a
# completed run returns its old result at once.
SINCE=$(( $(date -u +%s) - 60 ))
"$GH" workflow run deploy-pages.yml --ref develop -f "release_tag=$TAG" || { log "dispatch failed"; exit 1; }
log "dispatched deploy-pages.yml with release_tag=$TAG"
sleep 20

# Find the dispatch run created since then and watch it to completion.
DRUN=""
for _ in 1 2 3 4 5 6; do
  DRUN=$("$GH" run list --workflow deploy-pages.yml --event workflow_dispatch --limit 20 --json databaseId,createdAt --jq "[.[] | select((.createdAt | fromdateiso8601) >= $SINCE)] | min_by(.databaseId) | .databaseId // empty" 2>/dev/null || echo "")
  [ -n "$DRUN" ] && break
  sleep 10
done
[ -n "$DRUN" ] || { log "could not find a dispatch run created since the dispatch; refusing to report an older run"; exit 1; }
log "deploy run $DRUN, watching"
"$GH" run watch "$DRUN" --exit-status >/dev/null 2>&1
RC=$?
CONC=$("$GH" run view "$DRUN" --json conclusion,jobs --jq '"\(.conclusion) jobs=[\([.jobs[] | "\(.name):\(.conclusion)"] | join(", "))]"' 2>/dev/null)
log "deploy run $DRUN finished: $CONC"
# The production job is named after the tag it deployed, so a successful run that deployed
# another tag (a second dispatch in the same minute) is not reported as this release. A failed
# run is reported as failed whatever it names: a failed source check resolves no tag, so the
# name cannot tell this release's own failure from another run's.
if [ "$RC" -eq 0 ] && ! "$GH" run view "$DRUN" --json jobs --jq '.jobs[].name' 2>/dev/null | grep -qxF "production $TAG"; then
  log "deploy run $DRUN has no job 'production $TAG'; it is not this release's run"; exit 1
fi
[ "$RC" -eq 0 ] || exit "$RC"
sleep 45
verify_live_after_deploy || {
  log "post-deployment verification failed"; exit 1
}
log "LIVE: required publication verification passed"
