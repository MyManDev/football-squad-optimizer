#!/usr/bin/env bash
# Provision the weekly schedule's host (#1243): a fresh Contabo Cloud VPS on Ubuntu 24.04,
# run once as root, and again at any time: every step checks before it changes anything.
#
#   curl -fsSLO https://raw.githubusercontent.com/MyManDev/football-squad-optimizer/develop/deploy/weekly-schedule/provision.sh
#   bash provision.sh
#
# It installs the packages, the GitHub CLI from GitHub's apt repository, Python 3.13 from the
# deadsnakes PPA, the service user squadopt (home /srv/squadopt), the checkout of develop and
# its venv, a 4 GB swap file when the host has no swap, a firewall that lets only SSH in,
# unattended security updates, a journald size cap, SSH without passwords once root has a key,
# and the systemd units of deploy/weekly-schedule/ with the timer on, on the dry-run drop-in
# on a first provisioning. It writes no secret and logs nothing in: it prints the steps left
# for a person at its end (deploy/weekly-schedule/README.md has them in order).
set -euo pipefail

readonly SERVICE_USER=squadopt
readonly SERVICE_HOME=/srv/squadopt
readonly CHECKOUT=/srv/squadopt/weekly
readonly PRIVATE=/srv/squadopt/private
readonly REPOSITORY=https://github.com/MyManDev/football-squad-optimizer.git
readonly BRANCH=develop
readonly SETTINGS_DIR=/etc/squadopt
readonly ENVIRONMENT_FILE=/etc/squadopt/weekly-schedule.env
readonly UNITS=/etc/systemd/system
readonly DROP_INS=/etc/systemd/system/weekly-schedule.service.d
readonly SWAP_FILE=/swapfile
readonly SWAP_SIZE=4G
# The OS check reads this file; the tests point it at a fixture.
readonly OS_RELEASE="${SQUADOPT_OS_RELEASE:-/etc/os-release}"

say() { printf '\n== %s\n' "$*"; }
warn() { printf 'WARNING: %s\n' "$*" >&2; }
refuse() {
  printf 'Refused: %s\n' "$*" >&2
  exit 1
}
as_user() { runuser -u "$SERVICE_USER" -- "$@"; }

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
  # The OS first, then root: neither check changes anything.
  [ -r "$OS_RELEASE" ] || refuse "no $OS_RELEASE to read the OS from"
  local os_id version
  os_id="$(. "$OS_RELEASE" && printf '%s' "${ID:-}")"
  version="$(. "$OS_RELEASE" && printf '%s' "${VERSION_ID:-}")"
  if [ "$os_id" != ubuntu ] || [ "$version" != 24.04 ]; then
    refuse "this provisions Ubuntu 24.04 only, and this host is ${os_id:-unknown} ${version:-unknown}"
  fi
  [ "$(id -u)" -eq 0 ] || refuse "run as root: bash provision.sh"
}

packages() {
  say "Packages"
  export DEBIAN_FRONTEND=noninteractive
  apt-get update -q
  apt-get install -y -q --no-install-recommends \
    git curl ca-certificates gnupg time software-properties-common ufw unattended-upgrades \
    openssh-server
  timedatectl set-timezone Etc/UTC
}

github_cli() {
  say "GitHub CLI, from GitHub's apt repository"
  local keyring=/etc/apt/keyrings/githubcli-archive-keyring.gpg
  install -d -m 0755 /etc/apt/keyrings
  if [ ! -s "$keyring" ]; then
    curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg -o "$keyring"
    chmod go+r "$keyring"
  fi
  if printf 'deb [arch=%s signed-by=%s] https://cli.github.com/packages stable main\n' \
    "$(dpkg --print-architecture)" "$keyring" |
    write_if_changed /etc/apt/sources.list.d/github-cli.list 0644; then
    apt-get update -q
  fi
  apt-get install -y -q gh
}

python313() {
  # Ubuntu 24.04 ships Python 3.12; constraints.txt pins the 3.13 environment. deadsnakes is
  # apt-managed, so unattended-upgrades patches it (its origin is allowed below) and a venv
  # made with it follows each patch release.
  say "Python 3.13, from the deadsnakes PPA"
  if ! compgen -G '/etc/apt/sources.list.d/deadsnakes-ubuntu-ppa-*' >/dev/null; then
    add-apt-repository -y ppa:deadsnakes/ppa
    apt-get update -q
  fi
  apt-get install -y -q python3.13 python3.13-venv
}

service_user() {
  say "User $SERVICE_USER, home $SERVICE_HOME"
  if ! getent passwd "$SERVICE_USER" >/dev/null; then
    useradd --system --create-home --home-dir "$SERVICE_HOME" --shell /bin/bash \
      --user-group "$SERVICE_USER"
  fi
  chmod 0750 "$SERVICE_HOME"
  install -d -m 0700 -o "$SERVICE_USER" -g "$SERVICE_USER" "$PRIVATE"
}

checkout() {
  say "Checkout of $BRANCH at $CHECKOUT"
  if [ ! -d "$CHECKOUT/.git" ]; then
    as_user git clone --branch "$BRANCH" "$REPOSITORY" "$CHECKOUT"
  fi
  local branch
  branch="$(as_user git -C "$CHECKOUT" rev-parse --abbrev-ref HEAD)"
  [ "$branch" = "$BRANCH" ] || warn "the checkout is on $branch, not $BRANCH; the gate needs $BRANCH"
  [ -f "$CHECKOUT/deploy/weekly-schedule/weekly-schedule.service" ] ||
    refuse "the checkout has no deploy/weekly-schedule/ units yet: #1262 is not on $BRANCH"
}

venv() {
  say "venv at $CHECKOUT/.venv, installed as CI installs it, with the club-news extra"
  if [ ! -x "$CHECKOUT/.venv/bin/python" ]; then
    as_user python3.13 -m venv "$CHECKOUT/.venv"
  fi
  local python="$CHECKOUT/.venv/bin/python"
  as_user "$python" -c 'import sys; assert sys.version_info[:2] == (3, 13), sys.version' ||
    refuse "$CHECKOUT/.venv is not a Python 3.13 venv; move it away and run this again"
  as_user "$python" -m pip install -q --upgrade pip
  local install=("$python" -m pip install -q -c "$CHECKOUT/constraints.txt" -e "${CHECKOUT}[llm]")
  if ! as_user "${install[@]}"; then
    # Every pinned package has a manylinux wheel for 3.13 today; a compiler only when one has
    # none.
    warn "pip install failed; installing a compiler and the Python headers, then trying again"
    apt-get install -y -q build-essential python3.13-dev
    as_user "${install[@]}"
  fi
  as_user "$python" -c 'import squadopt.platform.weekly_schedule, squadopt.platform.weekly_release'
}

swap() {
  say "Swap"
  if [ -z "$(swapon --show --noheadings)" ]; then
    if [ ! -f "$SWAP_FILE" ]; then
      fallocate -l "$SWAP_SIZE" "$SWAP_FILE"
      chmod 0600 "$SWAP_FILE"
      mkswap "$SWAP_FILE"
    fi
    swapon "$SWAP_FILE"
  fi
  if [ -f "$SWAP_FILE" ] && ! grep -qE "^$SWAP_FILE[[:space:]]" /etc/fstab; then
    printf '%s none swap sw 0 0\n' "$SWAP_FILE" >>/etc/fstab
  fi
  swapon --show
}

firewall() {
  say "Firewall: SSH in, nothing else"
  ufw allow OpenSSH >/dev/null
  ufw default deny incoming >/dev/null
  ufw default allow outgoing >/dev/null
  ufw --force enable >/dev/null
  ufw status verbose
}

security_updates() {
  say "Unattended security updates"
  write_if_changed /etc/apt/apt.conf.d/20auto-upgrades 0644 <<'CONF' || true
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
CONF
  # Ubuntu's own security origin is allowed by 50unattended-upgrades; Python 3.13 comes from
  # the deadsnakes PPA. No automatic reboot: a reboot would end a running weekly run.
  write_if_changed /etc/apt/apt.conf.d/52squadopt-unattended-upgrades 0644 <<'CONF' || true
Unattended-Upgrade::Allowed-Origins {
        "LP-PPA-deadsnakes:${distro_codename}";
};
CONF
  systemctl enable --now unattended-upgrades.service >/dev/null
}

journal_cap() {
  say "journald size cap"
  install -d -m 0755 /etc/systemd/journald.conf.d
  if write_if_changed /etc/systemd/journald.conf.d/60-squadopt.conf 0644 <<'CONF'; then
[Journal]
SystemMaxUse=1G
CONF
    systemctl restart systemd-journald
  fi
}

ssh_hardening() {
  say "SSH"
  if [ ! -s /root/.ssh/authorized_keys ]; then
    warn "root has no SSH key in /root/.ssh/authorized_keys, so password login stays on." \
      "Add a key (ssh-copy-id root@<host>) and run this again to turn passwords off."
    return 0
  fi
  # Read before Ubuntu's 50-cloud-init.conf: the first value sshd reads wins.
  local hardening=/etc/ssh/sshd_config.d/10-squadopt-hardening.conf
  if write_if_changed "$hardening" 0644 <<'CONF'; then
PasswordAuthentication no
KbdInteractiveAuthentication no
PermitRootLogin prohibit-password
CONF
    if sshd -t; then
      systemctl try-reload-or-restart ssh
    else
      rm -f "$hardening"
      warn "sshd refused the hardening; it was removed and SSH is unchanged"
    fi
  fi
  sshd -T | grep -Ei '^(passwordauthentication|permitrootlogin) ' || true
}

units() {
  say "systemd units"
  local source="$CHECKOUT/deploy/weekly-schedule" first=no
  [ -e "$UNITS/weekly-schedule.service" ] || first=yes
  install -d -m 0750 "$SETTINGS_DIR"
  if [ ! -e "$ENVIRONMENT_FILE" ]; then
    # Comments only: a person fills it in (README, step 5). The unit refuses to start without
    # the file, so it exists from the start.
    write_if_changed "$ENVIRONMENT_FILE" 0600 <<CONF || true
# The weekly schedule's private settings, read by systemd as root before each tick
# (deploy/weekly-schedule/README.md). Mode 0600, owner root. Set by hand:
#   SQUADOPT_CLUB_NEWS_SETTINGS=$PRIVATE/club-news.settings.toml
#   and the variable that file's api_key_env names, set to the model key.
CONF
  fi
  install -d -m 0755 "$DROP_INS"
  # The dry-run week only on a first provisioning: removing the drop-in is the switch to real
  # runs, and a later run of this script must not switch them back.
  if [ "$first" = yes ] || [ -e "$DROP_INS/dry-run.conf" ]; then
    install -m 0644 "$source/dry-run.conf" "$DROP_INS/dry-run.conf"
  fi
  printf '[Service]\nEnvironment=WEEKLY_WORKERS=%s\n' "$(nproc)" |
    write_if_changed "$DROP_INS/workers.conf" 0644 || true
  install -m 0644 "$source/weekly-schedule.service" "$source/weekly-schedule.timer" "$UNITS/"
  systemctl daemon-reload
  systemctl enable --now weekly-schedule.timer
  if [ -e "$DROP_INS/dry-run.conf" ]; then
    echo "The timer ticks on the dry-run drop-in: every tick decides and runs nothing."
  else
    warn "no dry-run drop-in: the timer starts real runs"
  fi
  systemctl list-timers weekly-schedule.timer --no-pager
}

steps_left() {
  cat <<STEPS

== Provisioned. What is left, by hand, in this order (deploy/weekly-schedule/README.md):

1. GitHub, as $SERVICE_USER: log in with the account that pushes, opens and enqueues the site
   pull requests and posts on #1093, then let git use it and give its commits that identity:
     sudo -u $SERVICE_USER -H gh auth login --hostname github.com --git-protocol https
     sudo -u $SERVICE_USER -H gh auth setup-git
     sudo -u $SERVICE_USER -H git config --global user.name "<the account's name>"
     sudo -u $SERVICE_USER -H git config --global user.email "<the account's email>"

2. Club news, the final run's only (D3): copy the private settings file to
   $PRIVATE/club-news.settings.toml, owned by $SERVICE_USER with mode 0600
     install -m 0600 -o $SERVICE_USER -g $SERVICE_USER <copy> $PRIVATE/club-news.settings.toml
   and fill $ENVIRONMENT_FILE (root, 0600), the file the unit's EnvironmentFile names, with
   SQUADOPT_CLUB_NEWS_SETTINGS=$PRIVATE/club-news.settings.toml and the variable the
   settings' api_key_env names.

3. The data stores, copied once from the PC by the owner. From the PC's checkout root:
     tar -czf squadopt-data.tgz data/snapshots data/entries data/ledger data/handoffs data/advice_records data/raw/vaastav-fpl artifacts/phase_b artifacts/rotation artifacts/football
     scp squadopt-data.tgz root@<host>:/root/
   then on this host, as root:
     tar -xzf /root/squadopt-data.tgz -C $CHECKOUT
     chown -R $SERVICE_USER:$SERVICE_USER $CHECKOUT/data $CHECKOUT/artifacts
     chmod -R go-rwx $CHECKOUT/data $CHECKOUT/artifacts
     rm /root/squadopt-data.tgz
   Add artifacts/backend-artifact-root.json only if its artifact_root is a relative path.
   data/runtime and data/logs are this host's own and are not copied.

4. Check the host: bash $CHECKOUT/deploy/weekly-schedule/check_host.sh
5. Read a week of dry-run ticks, then remove the drop-in (README, "Enable it").
STEPS
}

main() {
  preflight
  cd /
  packages
  github_cli
  python313
  service_user
  checkout
  venv
  swap
  firewall
  security_updates
  journal_cap
  ssh_hardening
  units
  steps_left
}

main "$@"
