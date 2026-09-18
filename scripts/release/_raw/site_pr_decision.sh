#!/bin/sh
# Publish the decision run's preview on a new site branch: web/public/data becomes the
# run's preview/data, which holds every file develop has plus the gw05 system documents.
set -u
REPO="C:/Users/ertug/Desktop/football-squad-optimizer"
GH="C:/Program Files/GitHub CLI/gh.exe"
BUILT="$REPO/data/runtime/weekly/gw05-decision-20260918/preview/data"
BR="feature/gw05-decision-site-7"
WT="$REPO/.codex-tmp/publications/gw05-decision-7"
log(){ echo "$(date +%H:%M:%S) $*"; }
cd "$REPO" || exit 1
[ -f "$BUILT/league/members.json" ] || { log "no built tree at $BUILT"; exit 1; }
git fetch -q origin || exit 1
if git ls-remote --heads origin "$BR" | grep -q .; then log "$BR already on origin; stopping"; exit 1; fi
[ -e "$WT" ] && { log "$WT exists; stopping"; exit 1; }
SOURCE=$(git rev-parse origin/develop)
git worktree add -q -b "$BR" "$WT" origin/develop || exit 1
MISSING=$( (cd "$WT/web/public/data" && find . -type f | sort) | while read -r f; do [ -f "$BUILT/$f" ] || echo "$f"; done | grep -v "/league/advice/" | head -5)
[ -z "$MISSING" ] || { log "the preview lacks files develop has: $MISSING"; exit 1; }
rm -rf "$WT/web/public/data"
cp -r "$BUILT" "$WT/web/public/data" || exit 1
cd "$WT" || exit 1
git add -A web/public/data
COUNT=$(git diff --cached --name-only | wc -l)
ADDED=$(git diff --cached --name-only --diff-filter=A | wc -l)
DELETED=$(git diff --cached --name-only --diff-filter=D | wc -l)
log "staged $COUNT files ($ADDED added, $DELETED deleted)"
git diff --cached --name-only --diff-filter=D | head -20
git commit -q -m "site: publish the gw05 decision

Weekly run gw05-decision-20260918 from capture fpl-live-20260918T122516Z-cd5c04029774, taken
five hours before the deadline, with origin/develop at $SOURCE: the rotation table, the
component-only projection, the system squad decided, and every member's whole menu." || exit 1
git push -q -u origin "$BR" || exit 1
URL=$("$GH" pr create --base develop --head "$BR" \
  --title "site: publish the gw05 decision" \
  --body "The preview of weekly run \`gw05-decision-20260918\`, copied as it was built.

- Capture \`fpl-live-20260918T122516Z-cd5c04029774\`, taken at 12:25 UTC, five hours before the 17:30 UTC deadline. Run with \`--rotation --projection component-only --decide\`.
- The system squad for gameweek 5 is decided and in the ledger: OPTIMAL, one free transfer (Enzo Le Fee out, Pascal Gross in), no hit, no chip. On a component-only week it is chosen without the Top 100 uplift, which the owner approved for this week.
- Every member has the whole menu: pure points at 1, 3 and 5 weeks, both rival strategies at 1, 3 and 5 weeks against the default rival, the Top 100 settings, the manager's word (synthetic fixture, labelled as example data), and a chip document for every chip the member still holds (43).
- Checked before this PR: the three tree checkers (all good; 180 one-week documents OPTIMAL, window documents FEASIBLE with stated limits), every document from this capture, and \`shippedTree.test.ts\` over this tree, which holds each index and document to the page's own validators.
- $COUNT files changed: $ADDED added, $DELETED deleted.

Not in this PR: the advice record for this capture. The run was started without \`--publish\` (the runner's publish stage refuses because \`feature/gw05-decision-site\` exists on origin), and the league stage records only on a publishing run. The record is written by a rebuild of the same capture after this publish." 2>&1 | tail -1)
log "site PR: $URL"
cd "$REPO" && git worktree remove "$WT" && log "publication worktree removed"
