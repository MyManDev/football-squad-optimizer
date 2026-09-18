#!/bin/sh
# Stage two of the release: verify main, wait for its push CI, tag, dispatch the trusted deploy,
# and watch the run to completion. Every step verifies before the next, and refuses loudly.
set -u
cd "C:/Users/ertug/Desktop/football-squad-optimizer" || exit 1
GH="C:/Program Files/GitHub CLI/gh.exe"
REPO="MyManDev/football-squad-optimizer"
TAG="${1:?usage: deploy.sh <site-tag>}"
log(){ echo "$(date -u +%H:%M:%S) $*"; }

git fetch -q origin || { log "fetch failed"; exit 1; }
MAIN=$(git rev-parse origin/main)
DEV=$(git rev-parse origin/develop)

# main must be a two-parent merge whose tree is exactly develop's.
PARENTS=$(( $(git rev-list --parents -n1 origin/main | wc -w) - 1 ))
[ "$PARENTS" -eq 2 ] || { log "main tip $MAIN has $PARENTS parent(s), not a release merge; refusing"; exit 1; }
[ "$(git rev-parse origin/main^{tree})" = "$(git rev-parse origin/develop^{tree})" ] || { log "main tree != develop tree; refusing"; exit 1; }
log "main $MAIN is a two-parent merge with tree == develop $DEV"

# Wait for a SUCCESSFUL push CI run on exactly that SHA, with one unexpired site artifact.
log "waiting for main-push CI on $MAIN"
deadline=$(( $(date +%s) + 2400 ))
RUN=""
while [ "$(date +%s)" -lt "$deadline" ]; do
  RUN=$("$GH" run list --workflow ci.yml --branch main --event push --commit "$MAIN" --limit 1 --json databaseId,status,conclusion --jq '.[0] | "\(.databaseId) \(.status) \(.conclusion)"' 2>/dev/null || echo "")
  case "$RUN" in
    *" completed success") break;;
    *" completed "*) log "main CI run $RUN did not succeed; refusing to deploy"; exit 1;;
  esac
  sleep 45
done
case "$RUN" in *" completed success") ;; *) log "no successful main CI run within 40 minutes (last: '$RUN'); refusing"; exit 1;; esac
RID=${RUN%% *}
SITES=$("$GH" api "repos/$REPO/actions/runs/$RID/artifacts" --jq '[.artifacts[] | select(.name=="site" and .expired==false)] | length' 2>/dev/null || echo 0)
[ "$SITES" -eq 1 ] || { log "CI run $RID has $SITES unexpired site artifact(s), need exactly 1; refusing"; exit 1; }
log "main CI run $RID succeeded with one site artifact"

# Annotated tag on the main SHA. Immutable: refuse if it exists anywhere.
if git ls-remote --tags origin | grep -q "refs/tags/$TAG"; then log "tag $TAG exists on origin; refusing"; exit 1; fi
git tag -a "$TAG" "$MAIN" -m "$TAG" || { log "tag failed"; exit 1; }
git push -q origin "refs/tags/$TAG" || { log "tag push failed"; exit 1; }
log "tagged $MAIN as $TAG"

# Dispatch the trusted workflow from the default branch, as the runbook requires.
"$GH" workflow run deploy-pages.yml --ref develop -f "release_tag=$TAG" || { log "dispatch failed"; exit 1; }
log "dispatched deploy-pages.yml with release_tag=$TAG"
sleep 20

# Find the dispatch run and watch it to completion.
DRUN=""
for _ in 1 2 3 4 5 6; do
  DRUN=$("$GH" run list --workflow deploy-pages.yml --event workflow_dispatch --limit 1 --json databaseId,status,createdAt --jq '.[0].databaseId' 2>/dev/null || echo "")
  [ -n "$DRUN" ] && break
  sleep 10
done
[ -n "$DRUN" ] || { log "could not find the dispatched run"; exit 1; }
log "deploy run $DRUN, watching"
"$GH" run watch "$DRUN" --exit-status >/dev/null 2>&1
RC=$?
CONC=$("$GH" run view "$DRUN" --json conclusion,jobs --jq '"\(.conclusion) jobs=[\([.jobs[] | "\(.name):\(.conclusion)"] | join(", "))]"' 2>/dev/null)
log "deploy run $DRUN finished: $CONC"
exit $RC
