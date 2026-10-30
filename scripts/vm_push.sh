#!/usr/bin/env bash
# After every release: move the backend VM to the release tag. Run on the PC from Git Bash.
#   bash scripts/vm_push.sh site-2026-27-gw07-decision
# First it runs the read-only layout preflight scripts/release/check_vm_layout.py on the VM
# over SSH. A refusal stops the script there, before any remote write; see "VM data root
# selection" in docs/backend_runbook.md. It then copies the preflight to ~/vm_check_layout.py,
# which vm_sync.sh runs before and after its checkout.
# Then it streams the captures, handoffs and the per-capture artifacts the backend reads (the
# Top 100 evidence and the rotation tables) to the VM in one tar over SSH, and runs
# scripts/vm_sync.sh there, which checks the tag out, refreshes the site data the backend
# reads, rebuilds the image for the tag and restarts the two containers. Nothing here holds a
# secret: the host and the key path come from the environment, with the defaults of the first
# VM.
set -euo pipefail
TAG="${1:?release tag, for example site-2026-27-gw07-decision}"
HOST="${SQUADOPT_VM_HOST:-squadopt@74.248.153.181}"
KEY="${SQUADOPT_VM_KEY:-$HOME/.ssh/squadopt_azure}"
REPO="$(cd "$(dirname "$0")/.." && pwd)"
SSH=(ssh -i "$KEY" -o BatchMode=yes -o ServerAliveInterval=10 -o ServerAliveCountMax=12 -o ConnectTimeout=20)
cd "$REPO"
# A retained release can bind all four roots elsewhere. Copying the ordinary folders in
# that layout would leave the served capture unchanged. Check before any remote write.
"${SSH[@]}" "$HOST" 'python3 -' < scripts/release/check_vm_layout.py
scp -q -i "$KEY" -o BatchMode=yes scripts/release/check_vm_layout.py "$HOST:vm_check_layout.py"
scp -q -i "$KEY" -o BatchMode=yes scripts/vm_sync.sh "$HOST:vm_sync.sh"
tar -czf - data/snapshots data/handoffs artifacts/phase_b artifacts/rotation | "${SSH[@]}" "$HOST" '
  set -e
  mkdir -p ~/squadopt/incoming
  tar -xzf - -C ~/squadopt/incoming
  rsync -a ~/squadopt/incoming/data/snapshots/   ~/squadopt/snapshots/
  rsync -a ~/squadopt/incoming/data/handoffs/    ~/squadopt/handoffs/
  rsync -a ~/squadopt/incoming/artifacts/phase_b/  ~/squadopt/artifacts/phase_b/
  rsync -a ~/squadopt/incoming/artifacts/rotation/ ~/squadopt/artifacts/rotation/
  rm -rf ~/squadopt/incoming
  echo "inputs synced $(date -u +%T): $(ls ~/squadopt/snapshots | wc -l) captures"
'
printf -v REMOTE_TAG '%q' "$TAG"
"${SSH[@]}" "$HOST" "bash ~/vm_sync.sh $REMOTE_TAG"
