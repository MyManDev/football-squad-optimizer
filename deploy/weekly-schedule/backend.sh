#!/usr/bin/env bash
# Set the advice backend up on the weekly schedule's host (#1243), beside the weekly run, as
# root after provision.sh. It can run again at any time: every step checks before it changes
# anything.
#
#   bash /srv/squadopt/weekly/deploy/weekly-schedule/backend.sh
#
# The backend runs here as it ran on the Azure VM this host replaced: the api and one worker
# under Docker Compose, serving the release packages of scripts/release/vm_football_release.py,
# which keeps its layout under ~/squadopt of the user it reaches over SSH, here root. This
# script installs Docker and cloudflared from their own apt repositories, makes that layout
# (the checkout, a store owned by the containers' user, the environment file and an empty
# override), installs the tunnel's unit, the squadopt-receive command and
# squadopt-backend-release with its two units, which move the backend after each release from
# GW11 (#1243, 6605005485). It starts no backend and writes no secret: a release's activate
# starts the backend, and a person makes the tunnel's credential (README, "The advice backend").
set -euo pipefail

readonly BASE=/root/squadopt
readonly REPOSITORY=https://github.com/MyManDev/football-squad-optimizer.git
readonly SOURCE="${SQUADOPT_HOST_FILES:-/srv/squadopt/weekly/deploy/weekly-schedule}"
readonly KEYRINGS=/etc/apt/keyrings
# The image's own user (Dockerfile); the store must be writable by it.
readonly CONTAINER_UID=10001
readonly ORIGINS=https://squadopt.mymandev.com,https://squadopt.pages.dev
readonly TUNNEL_CONFIG=/etc/cloudflared/config.yml
readonly TUNNEL_UNIT=cloudflared-squadopt.service
readonly RECEIVE=/usr/local/sbin/squadopt-receive
readonly FOLLOW=/usr/local/sbin/squadopt-backend-release
readonly FOLLOW_UNIT=squadopt-backend-release
readonly SERVICE_USER="${SQUADOPT_SERVICE_USER:-squadopt}"
# The release chain writes its requests here as the service user; root writes its results
# where that user can read them and change nothing.
readonly SPOOL=/srv/squadopt/spool/backend
readonly STATE=/var/lib/squadopt/backend

say() { printf '\n== %s\n' "$*"; }
refuse() {
  printf 'Refused: %s\n' "$*" >&2
  exit 1
}

# Write stdin to $1 with mode $2 when its content differs; exit 0 when it changed the file.
write_if_changed() {
  local target="$1" mode="$2" staged
  staged="$(mktemp)"
  cat >"$staged"
  if [ -f "$target" ] && cmp -s "$staged" "$target"; then
    rm -f "$staged"
    return 1
  fi
  install -m "$mode" "$staged" "$target"
  rm -f "$staged"
  return 0
}

preflight() {
  [ "$(id -u)" -eq 0 ] || refuse "run as root: bash backend.sh"
  local file
  for file in squadopt-receive "$TUNNEL_UNIT" cloudflared.example.yml "$FOLLOW_UNIT" \
    "$FOLLOW_UNIT.path" "$FOLLOW_UNIT.service"; do
    [ -f "$SOURCE/$file" ] || refuse "no $SOURCE/$file: run provision.sh first"
  done
}

docker_engine() {
  say "Docker, from Docker's apt repository"
  install -d -m 0755 "$KEYRINGS"
  if [ ! -s "$KEYRINGS/docker.asc" ]; then
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o "$KEYRINGS/docker.asc"
    chmod a+r "$KEYRINGS/docker.asc"
  fi
  if printf 'deb [arch=%s signed-by=%s/docker.asc] https://download.docker.com/linux/ubuntu %s stable\n' \
    "$(dpkg --print-architecture)" "$KEYRINGS" "$(. /etc/os-release && printf '%s' "$VERSION_CODENAME")" |
    write_if_changed /etc/apt/sources.list.d/docker.list 0644; then
    apt-get update -q
  fi
  apt-get install -y -q docker-ce docker-ce-cli containerd.io docker-buildx-plugin \
    docker-compose-plugin rsync
  # Container logs rotate: the journald cap of provision.sh does not reach json-file logs.
  install -d -m 0755 /etc/docker
  if [ ! -e /etc/docker/daemon.json ]; then
    printf '{\n  "log-driver": "json-file",\n  "log-opts": {"max-size": "20m", "max-file": "5"}\n}\n' |
      write_if_changed /etc/docker/daemon.json 0644 || true
    systemctl restart docker
  fi
  systemctl enable --now docker >/dev/null
  docker --version
  docker compose version
}

cloudflared_package() {
  say "cloudflared, from Cloudflare's apt repository"
  if [ ! -s "$KEYRINGS/cloudflare-main.gpg" ]; then
    curl -fsSL https://pkg.cloudflare.com/cloudflare-main.gpg -o "$KEYRINGS/cloudflare-main.gpg"
    chmod a+r "$KEYRINGS/cloudflare-main.gpg"
  fi
  if printf 'deb [signed-by=%s/cloudflare-main.gpg] https://pkg.cloudflare.com/cloudflared any main\n' \
    "$KEYRINGS" | write_if_changed /etc/apt/sources.list.d/cloudflared.list 0644; then
    apt-get update -q
  fi
  apt-get install -y -q cloudflared
  cloudflared --version
}

release_layout() {
  say "The release tool's layout at $BASE"
  install -d -m 0750 "$BASE"
  if [ ! -d "$BASE/repo/.git" ]; then
    git clone -q "$REPOSITORY" "$BASE/repo"
  fi
  install -d -m 0750 -o "$CONTAINER_UID" -g "$CONTAINER_UID" "$BASE/store"
  # The lines every release keeps: vm_football_release.py replaces the image and the paths and
  # leaves the others as they are. FORWARDED_ALLOW_IPS is added once the peer is verified
  # (README, "The advice backend").
  if [ ! -e "$BASE/.env" ]; then
    write_if_changed "$BASE/.env" 0600 <<ENV || true
SQUADOPT_BACKEND_IMAGE=unset
SQUADOPT_BACKEND_ALLOWED_ORIGINS=$ORIGINS
SQUADOPT_STORE_PATH=$BASE/store
SQUADOPT_SITE_PATH=unset
SQUADOPT_SNAPSHOT_PATH=unset
SQUADOPT_HANDOFF_PATH=unset
SQUADOPT_API_PORT=8000
SQUADOPT_WORKER_METRICS_PORT=9091
ENV
  fi
  # activate keeps the live override as the rollback, so one exists from the start.
  if [ ! -e "$BASE/compose.artifacts.yaml" ]; then
    printf '# No release has been activated on this host yet.\nservices: {}\n' |
      write_if_changed "$BASE/compose.artifacts.yaml" 0644 || true
  fi
  ls -ld "$BASE" "$BASE/repo" "$BASE/store"
}

tunnel_unit() {
  say "The tunnel's unit, $TUNNEL_UNIT"
  if write_if_changed "/etc/systemd/system/$TUNNEL_UNIT" 0644 <"$SOURCE/$TUNNEL_UNIT"; then
    systemctl daemon-reload
  fi
  if [ -s "$TUNNEL_CONFIG" ]; then
    systemctl enable --now "$TUNNEL_UNIT" >/dev/null
    systemctl is-active "$TUNNEL_UNIT"
  else
    echo "No $TUNNEL_CONFIG yet: the unit is installed and stays off (README, \"The tunnel\")."
  fi
}

receive_command() {
  say "squadopt-receive, the data stores' way in from the PC"
  write_if_changed "$RECEIVE" 0755 <"$SOURCE/squadopt-receive" || true
  ls -l "$RECEIVE"
}

follow_releases() {
  say "$FOLLOW_UNIT, the backend following each release on this host"
  write_if_changed "$FOLLOW" 0755 <"$SOURCE/$FOLLOW_UNIT" || true
  local group unit changed=no
  group="$(id -gn "$SERVICE_USER")"
  install -d -m 0700 -o "$SERVICE_USER" -g "$group" "$(dirname "$SPOOL")" "$SPOOL"
  install -d -m 0755 "$(dirname "$STATE")" "$STATE"
  for unit in "$FOLLOW_UNIT.path" "$FOLLOW_UNIT.service"; do
    if write_if_changed "/etc/systemd/system/$unit" 0644 <"$SOURCE/$unit"; then
      changed=yes
    fi
  done
  if [ "$changed" = yes ]; then
    systemctl daemon-reload
  fi
  # The path unit only watches the spool; the service runs when a release leaves a request.
  systemctl enable --now "$FOLLOW_UNIT.path" >/dev/null
  systemctl is-active "$FOLLOW_UNIT.path"
  ls -l "$FOLLOW"
}

steps_left() {
  cat <<STEPS

== The backend's layout is in place. What is left, in this order (README, "The advice backend"):

1. The tunnel, by a person, once: cloudflared tunnel login (approve mymandev.com in the browser),
   cloudflared tunnel create <name>, then $TUNNEL_CONFIG from cloudflared.example.yml with the
   tunnel's id, and bash backend.sh again to start $TUNNEL_UNIT.
2. A release from the PC: vm_football_release.py pack and push with
   SQUADOPT_VM_HOST=root@<this host>, then prepare, candidate and activate.
3. FORWARDED_ALLOW_IPS in $BASE/.env, once the api's peer is verified.
4. The cutover: cloudflared tunnel route dns --overwrite-dns <name> squadopt-api.mymandev.com
5. From GW11, release.conf in weekly-schedule.service.d (README, "Release a run"): each run then
   releases itself, and $FOLLOW_UNIT moves the backend after it.
STEPS
}

main() {
  preflight
  cd /
  docker_engine
  cloudflared_package
  release_layout
  tunnel_unit
  receive_command
  follow_releases
  steps_left
}

# Sourced, as the tests source it, it defines its functions and runs nothing.
if [ "${BASH_SOURCE[0]}" = "$0" ]; then
  main "$@"
fi
