#!/bin/sh
# Stage two of the release: verify main, wait for its push CI, tag, dispatch the trusted deploy,
# and watch the run to completion. Every step verifies before the next, and refuses loudly.
set -u
ROOT=$(git rev-parse --show-toplevel) || exit 1
cd "$ROOT" || exit 1
GH=$(command -v gh || printf '%s' 'C:/Program Files/GitHub CLI/gh.exe')
[ -x "$GH" ] || command -v "$GH" >/dev/null || { echo 'gh not found' >&2; exit 1; }
REPO="MyManDev/football-squad-optimizer"
TAG="${1:?usage: deploy.sh <site-tag>}"
log(){ echo "$(date -u +%H:%M:%S) $*"; }

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
exit $RC
