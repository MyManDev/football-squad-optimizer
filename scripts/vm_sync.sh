#!/usr/bin/env bash
# Runs ON THE VM, called by scripts/vm_push.sh after the inputs arrived: move the checkout at
# ~/squadopt/repo to the release tag the live site serves, refresh the site data the backend
# reads, rebuild the image for that tag, restart the two containers, and print readiness and
# the capabilities so the caller sees the capture the backend now names.
#   bash ~/vm_sync.sh site-2026-27-gw07-decision
# The VM layout is the one docs/backend_runbook.md describes for Compose: ~/squadopt/{repo,
# store, site, snapshots, handoffs, artifacts}, ~/squadopt/.env (no secret in it) and
# ~/squadopt/compose.artifacts.yaml, the override that mounts the artifact root and the
# club-news fixture the base compose file does not mount yet.
# Before the checkout and again after it, against the target release's Compose file, it runs
# the read-only layout preflight ~/vm_check_layout.py, which vm_push.sh copies there from
# scripts/release/check_vm_layout.py. A refusal, or a missing preflight file, stops the script
# before it copies site data, builds or restarts anything. The preflight resolves Compose with
# the same arguments and directory as the restart below; keep the two in step.
set -euo pipefail
TAG="${1:?release tag}"
BASE="$HOME/squadopt"
python3 "$HOME/vm_check_layout.py"
git -C "$BASE/repo" fetch -q --tags origin
git -C "$BASE/repo" checkout -q "$TAG"
COMMIT="$(git -C "$BASE/repo" rev-parse HEAD)"
# The target release may change Compose. Refuse before copying site data or restarting.
python3 "$HOME/vm_check_layout.py"
rsync -a --delete "$BASE/repo/web/public/data/" "$BASE/site/"
docker build -q --build-arg "SQUADOPT_REPOSITORY_COMMIT=$COMMIT" -t "squadopt-backend:$TAG" "$BASE/repo" >/dev/null
sed -i "s#^SQUADOPT_BACKEND_IMAGE=.*#SQUADOPT_BACKEND_IMAGE=squadopt-backend:$TAG#" "$BASE/.env"
cd "$BASE/repo"
docker compose --env-file "$BASE/.env" -f deploy/compose.yaml -f "$BASE/compose.artifacts.yaml" up -d
for _ in $(seq 1 24); do
  if curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8000/ready | grep -q 200; then break; fi
  sleep 5
done
echo "tag $TAG commit ${COMMIT:0:8}"
curl -s http://127.0.0.1:8000/ready; echo
curl -s http://127.0.0.1:8000/api/v1/leagues/352490/capabilities | python3 -c 'import json,sys; d=json.load(sys.stdin); print("capture", d["capture_snapshot_id"], "| top100", d["top100"], "| managers_word", d["managers_word"])'
