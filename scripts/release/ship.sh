#!/bin/sh
# usage: ship.sh [--dry-run] <site PR> <tag> <release branch> <live generated-after ISO> <summary sentence>
# Wait for the site PR, cut the release as a real two-parent merge whose tree is develop's,
# merge it, then deploy.sh (main CI, tag, dispatch, watch) and verify the live site.
set -u
DRY_RUN=0
if [ "${1:-}" = "--dry-run" ]; then DRY_RUN=1; shift; fi
[ "$#" -eq 5 ] || { echo 'usage: ship.sh [--dry-run] <site PR> <tag> <release branch> <live generated-after ISO> <summary>' >&2; exit 2; }
SITE_PR="$1"; TAG="$2"; BR="$3"; LIVE_AFTER="$4"; SUMMARY="$5"
REPO=$(git rev-parse --show-toplevel) || exit 1
S=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd) || exit 1
WT="$REPO/.codex-tmp/worktrees/$(echo "$BR" | tr '/' '-')"
log(){ echo "$(date +%H:%M:%S) $*"; }
cd "$REPO" || exit 1
echo "$TAG" | grep -Eq '^site-[0-9]{4}-[0-9]{2}-gw[0-9]{2}-(decision|settled|fix[0-9]+)$' || { log "tag $TAG does not match the deploy rule"; exit 1; }
if [ "$DRY_RUN" -eq 1 ]; then
  cat <<EOF
Wait up to 60 minutes for site PR #$SITE_PR to be MERGED; refuse CLOSED or timeout.
Fetch origin and read develop plus its commit count since main.
Refuse existing remote tag $TAG.
Remove an existing release worktree $WT and local branch $BR.
Create $BR in $WT from origin/main.
Merge origin/develop with two parents and set its tree to develop.
Commit the release; verify two parents and tree equality.
Push $BR and open a release PR against main, carrying: $SUMMARY
Wait up to 45 minutes for CLEAN; refuse DIRTY, BEHIND or timeout.
Merge the release PR with a merge commit.
Fetch origin; require main to have two parents and develop's tree.
Wait up to 40 minutes for successful main push CI at that exact SHA and one unexpired site artifact.
Refuse an existing tag; create annotated $TAG on main and push it.
Dispatch deploy-pages.yml from develop with release_tag=$TAG; watch its result.
Run ten live smoke checks and content checks generated after $LIVE_AFTER; retry once.
EOF
  exit 0
fi
GH=$(command -v gh || printf '%s' 'C:/Program Files/GitHub CLI/gh.exe')
[ -x "$GH" ] || command -v "$GH" >/dev/null || { echo 'gh not found' >&2; exit 1; }
if [ -x "$REPO/.venv/Scripts/python.exe" ]; then PY="$REPO/.venv/Scripts/python.exe"
elif [ -x "$REPO/.venv/bin/python" ]; then PY="$REPO/.venv/bin/python"
else PY=$(command -v python || command -v python3) || { echo 'python not found' >&2; exit 1; }
fi
"$PY" -c '' || { echo 'python could not start' >&2; exit 1; }
i=0; st=""
while [ $i -lt 120 ]; do
  st=$("$GH" pr view "$SITE_PR" --json state --jq .state 2>/dev/null || echo "")
  case "$st" in MERGED) break;; CLOSED) log "site PR closed without merging; stopping"; exit 1;; esac
  sleep 30; i=$((i+1))
done
[ "$st" = "MERGED" ] || { log "site PR not merged in time; stopping"; exit 1; }
git fetch -q origin || { log "fetch failed"; exit 1; }
DEV=$(git rev-parse origin/develop)
COUNT=$(git rev-list --count origin/main..origin/develop)
log "site PR merged; develop $DEV, $COUNT commits not on main"
if git ls-remote --tags origin | grep -q "refs/tags/$TAG$"; then log "tag $TAG already exists; stopping"; exit 1; fi
git worktree remove --force "$WT" 2>/dev/null
git branch -D "$BR" 2>/dev/null
git worktree add -q "$WT" -b "$BR" origin/main || { log "worktree add failed"; exit 1; }
cd "$WT" || exit 1
git merge --no-ff --no-commit origin/develop >/dev/null 2>&1 || log "merge reported conflicts; tree is forced to develop"
git read-tree -u --reset origin/develop || { log "read-tree failed"; exit 1; }
git commit -q -m "release: bring main to the development tree at $(echo "$DEV" | cut -c1-8)

A real merge, not a squash: the tree is exactly origin/develop at $DEV and the commit has
two parents, so the next release keeps shared ancestry." || { log "commit failed"; exit 1; }
PARENTS=$(git rev-list --parents -n1 HEAD | wc -w)
[ "$PARENTS" -eq 3 ] || { log "not a two-parent merge; stopping"; exit 1; }
[ -z "$(git diff origin/develop HEAD)" ] || { log "release tree differs from develop; stopping"; exit 1; }
git push -q -u origin "$BR" || { log "push failed"; exit 1; }
URL=$("$GH" pr create --base main --head "$BR" --title "release: bring main to the development tree at $(echo "$DEV" | cut -c1-8)" --body "A real merge, not a squash. The tree is exactly \`origin/develop\` at \`$DEV\` and the commit has two parents. Merge with **Create a merge commit**, never squash.

Carries $COUNT commits since the last release. $SUMMARY

Verified before this PR: every merged PR's own gates, and the committed league tree checked member by member (site PR #$SITE_PR).

Tag to follow on the merge commit: \`$TAG\`." 2>&1 | tail -1)
PR=$(echo "$URL" | grep -o '[0-9]*$')
[ -n "$PR" ] || { log "release PR not created: $URL"; exit 1; }
log "release PR #$PR opened"
cd "$REPO" || exit 1
ok=0; i=0
while [ $i -lt 60 ]; do
  st=$("$GH" pr view "$PR" --json mergeStateStatus --jq .mergeStateStatus 2>/dev/null || echo "")
  case "$st" in CLEAN) ok=1; break;; DIRTY|BEHIND) log "release PR $st; stopping"; exit 1;; esac
  sleep 45; i=$((i+1))
done
[ $ok = 1 ] || { log "release PR not mergeable ($st); stopping"; exit 1; }
"$GH" pr merge "$PR" --merge || { log "release merge failed"; exit 1; }
log "release PR #$PR merged"
sleep 20
sh "$S/deploy.sh" "$TAG" || { log "deploy.sh stopped"; exit 1; }
sleep 45
"$PY" "$S/verify_live.py" "$LIVE_AFTER" || { sleep 60; "$PY" "$S/verify_live.py" "$LIVE_AFTER" || { log "live verification found failures"; exit 1; }; }
log "LIVE"
log "Next: cd web && LIVE_BASE_URL=https://squadopt.mymandev.com npx playwright test --config playwright.live.config.ts (read-only browser check after verify_live.py)"
