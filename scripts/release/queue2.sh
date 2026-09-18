#!/bin/sh
# Merge queue: rebase each PR inside its existing worktree, wait for CLEAN, squash-merge with a cleaned body.
REPO=$(git rev-parse --show-toplevel) || exit 1
S=$(CDPATH='' cd -- "$(dirname -- "$0")" && pwd) || exit 1
GH=$(command -v gh || printf '%s' '/c/Program Files/GitHub CLI/gh.exe')
PY=$(command -v python || command -v python3) || exit 1
cd "$REPO" || exit 1
BODIES=$(mktemp -d) || exit 1
trap 'rm -rf "$BODIES"' EXIT HUP INT TERM
log(){ echo "$(date +%H:%M:%S) $*"; }
for n in "$@"; do
  # A network failure must not read as "not open". Retry, then refuse to guess.
  state=""; br=""
  i=0; while [ $i -lt 5 ]; do
    raw=$("$GH" pr view "$n" --json headRefName,state --jq '.state + " " + .headRefName' 2>/dev/null)
    [ -n "$raw" ] && { state=${raw%% *}; br=${raw#* }; break; }
    sleep 20; i=$((i+1))
  done
  if [ -z "$state" ]; then log "#$n state unreadable after retries, NOT skipping silently; stopping"; exit 1; fi
  [ "$state" = "OPEN" ] || { log "#$n is $state, skip"; continue; }
  # A draft merges to nothing. Say so up front rather than after the whole CI wait.
  if [ "$("$GH" pr view "$n" --json isDraft --jq .isDraft 2>/dev/null)" = "true" ]; then
    log "#$n is a draft, skip (mark it ready first)"; continue
  fi
  d=$(git worktree list --porcelain | awk -v b="refs/heads/$br" '/^worktree/{w=substr($0,10)}/^branch/{if($2==b)print w}')
  if [ -z "$d" ]; then
    d=".codex-tmp/worktrees/q$n"
    git worktree add -q "$d" "origin/$br" || { log "#$n worktree add FAILED"; continue; }
    git -C "$d" checkout -q -B "$br" "origin/$br"
  fi
  git -C "$d" fetch -q origin
  if [ -n "$(git -C "$d" status --porcelain --untracked-files=no)" ]; then log "#$n worktree dirty at $d, skip"; continue; fi
  git -C "$d" reset -q --hard "origin/$br"
  if ! git -C "$d" rebase origin/develop >/dev/null 2>&1; then git -C "$d" rebase --abort; log "#$n rebase CONFLICT, skip"; continue; fi
  if [ "$(git -C "$d" rev-parse HEAD)" != "$(git -C "$d" rev-parse "origin/$br")" ]; then
    if git -C "$d" push -q --force-with-lease origin "$br"; then log "#$n rebased and pushed"; else log "#$n push FAILED"; continue; fi
  else
    log "#$n already on develop tip"
  fi
  "$GH" pr view "$n" --json body --jq .body > "$BODIES/q_body_$n.md"
  "$PY" "$S/clean_body.py" "$BODIES/q_body_$n.md" || { log "#$n body scan FAILED"; continue; }
  # A merge landing under us leaves the branch BEHIND, which never becomes CLEAN on its
  # own. Rebase again and let CI re-run rather than waiting out the poll.
  ok=0; st=""; rebases=0
  i=0; while [ $i -lt 50 ]; do
    st=$("$GH" pr view "$n" --json mergeStateStatus --jq .mergeStateStatus)
    case "$st" in
      CLEAN) ok=1; break;;
      DIRTY) break;;
      BEHIND)
        if [ $rebases -ge 3 ]; then log "#$n behind after $rebases rebases, skip"; break; fi
        rebases=$((rebases+1)); log "#$n behind again, rebasing ($rebases)"
        git -C "$d" fetch -q origin
        if ! git -C "$d" rebase origin/develop >/dev/null 2>&1; then git -C "$d" rebase --abort; log "#$n rebase CONFLICT, skip"; break; fi
        git -C "$d" push -q --force-with-lease origin "$br" || { log "#$n push FAILED"; break; }
        sleep 30
        ;;
    esac
    sleep 45; i=$((i+1))
  done
  [ $ok = 1 ] || { log "#$n not mergeable ($st), skip"; continue; }
  # A network blip must never produce an empty squash subject: retry, then refuse.
  t=""
  i=0; while [ $i -lt 5 ]; do
    t=$("$GH" pr view "$n" --json title --jq .title 2>/dev/null)
    [ -n "$t" ] && break
    sleep 20; i=$((i+1))
  done
  if [ -z "$t" ]; then log "#$n title unreadable after retries, NOT merging"; continue; fi
  if [ ! -s "$BODIES/q_body_$n.md" ]; then log "#$n body file empty, NOT merging"; continue; fi
  if "$GH" pr merge "$n" --squash --subject "$t (#$n)" --body-file "$BODIES/q_body_$n.md"; then log "#$n merged"; else log "#$n merge FAILED"; fi
  sleep 15; git fetch -q origin
done
git log --oneline -1 origin/develop
