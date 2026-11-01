#!/usr/bin/env bash
# A read-only readiness report of the weekly schedule's host (#1243), run as root after
# provision.sh and after each step a person takes by hand:
#
#   bash /srv/squadopt/weekly/deploy/weekly-schedule/check_host.sh
#
# It reads and prints; it installs, starts, stops and writes nothing, and it prints no token
# and no setting's value. Each line is OK, WARN or MISSING; the exit code is 1 when a line is
# MISSING, and 0 otherwise.
set -uo pipefail

readonly SERVICE_USER=squadopt
readonly CHECKOUT=/srv/squadopt/weekly
readonly SETTINGS=/srv/squadopt/private/club-news.settings.toml
readonly ENVIRONMENT_FILE=/etc/squadopt/weekly-schedule.env
readonly DROP_INS=/etc/systemd/system/weekly-schedule.service.d
readonly STORES=(
  data/snapshots data/entries data/ledger data/handoffs data/advice_records data/raw/vaastav-fpl
  artifacts/phase_b artifacts/rotation artifacts/football
)
missing=0

ok() { printf 'OK       %s\n' "$*"; }
note() { printf 'WARN     %s\n' "$*"; }
absent() {
  printf 'MISSING  %s\n' "$*"
  missing=1
}
section() { printf '\n== %s\n' "$*"; }
as_user() { runuser -u "$SERVICE_USER" -- "$@"; }

[ "$(id -u)" -eq 0 ] || {
  echo "Run as root: the checks read as $SERVICE_USER and read the SSH and firewall settings." >&2
  exit 2
}
cd /

section "Machine"
os="$(. /etc/os-release && printf '%s %s' "${ID:-}" "${VERSION_ID:-}")"
if [ "$os" = "ubuntu 24.04" ]; then ok "OS $os, kernel $(uname -r)"; else note "OS $os"; fi
cores="$(nproc)"
memory="$(awk '/^MemTotal:/ { printf "%.1f GiB", $2 / 1048576 }' /proc/meminfo)"
ok "$cores cores, $memory memory"
if [ -n "$(swapon --show --noheadings)" ]; then
  ok "swap $(swapon --show --noheadings --bytes | awk '{ s += $3 } END { printf "%.1f GiB", s / 1073741824 }')"
else
  absent "swap"
fi
ok "disk $(df -h --output=avail /srv | tail -1 | tr -d ' ') free under /srv"
if [ "$(timedatectl show -p NTPSynchronized --value 2>/dev/null)" = yes ]; then
  ok "clock synchronized, zone $(timedatectl show -p Timezone --value)"
else
  note "clock not reported synchronized (timedatectl)"
fi
if [ -r /sys/fs/cgroup/cgroup.controllers ] && grep -qw memory /sys/fs/cgroup/cgroup.controllers; then
  ok "cgroup v2 with the memory controller: a run's peak memory is measured"
else
  note "no cgroup v2 memory controller: a run's peak memory is the largest process only"
fi

section "Python and the checkout"
if command -v python3.13 >/dev/null; then ok "$(python3.13 --version)"; else absent "python3.13"; fi
if [ -d "$CHECKOUT/.git" ]; then
  branch="$(as_user git -C "$CHECKOUT" rev-parse --abbrev-ref HEAD 2>/dev/null)"
  head="$(as_user git -C "$CHECKOUT" log -1 --format='%h %cs %s' 2>/dev/null)"
  if [ "$branch" = develop ]; then ok "checkout on develop at $head"; else note "checkout on $branch"; fi
  if [ -z "$(as_user git -C "$CHECKOUT" status --porcelain 2>/dev/null)" ]; then
    ok "checkout clean"
  else
    note "checkout has changes: the weekly command refuses a dirty checkout"
  fi
else
  absent "checkout at $CHECKOUT"
fi
probe='import sys, squadopt.platform.weekly_schedule as gate
print(sys.version.split()[0], gate.MORNING_KIND, gate.LEAD_WINDOW_DAYS)'
if imported="$(as_user "$CHECKOUT/.venv/bin/python" -c "$probe" 2>/dev/null)"; then
  read -r version kind window <<<"$imported"
  ok "venv Python $version imports squadopt (morning kind $kind, lead window $window days)"
else
  absent "venv at $CHECKOUT/.venv importing squadopt"
fi

section "GitHub, as $SERVICE_USER"
if command -v gh >/dev/null; then
  ok "$(gh --version | head -1)"
  # gh masks its token; the token lines are dropped as well.
  if status="$(as_user gh auth status --hostname github.com 2>&1)"; then
    account="$(printf '%s\n' "$status" | grep -i 'logged in' | grep -vi token | head -1)"
    ok "gh logged in${account#*Logged in}"
  else
    absent "gh login for $SERVICE_USER (sudo -u $SERVICE_USER -H gh auth login)"
  fi
else
  absent "gh"
fi
if as_user git config --global credential.https://github.com.helper >/dev/null 2>&1; then
  ok "git pushes through gh (gh auth setup-git)"
else
  absent "git credential helper (sudo -u $SERVICE_USER -H gh auth setup-git)"
fi
if [ -n "$(as_user git config --global user.email 2>/dev/null)" ]; then
  ok "git commits as $(as_user git config --global user.name 2>/dev/null)"
else
  absent "git identity of $SERVICE_USER (git config --global user.name and user.email)"
fi

section "Club news (the final run only)"
if [ -f "$ENVIRONMENT_FILE" ] && [ "$(stat -c '%a %U' "$ENVIRONMENT_FILE")" = "600 root" ]; then
  if grep -q '^SQUADOPT_CLUB_NEWS_SETTINGS=' "$ENVIRONMENT_FILE"; then
    ok "$ENVIRONMENT_FILE names the settings (mode 600, root)"
  else
    absent "SQUADOPT_CLUB_NEWS_SETTINGS in $ENVIRONMENT_FILE"
  fi
else
  absent "$ENVIRONMENT_FILE with mode 600, owner root"
fi
if [ -f "$SETTINGS" ] && [ "$(stat -c '%a %U' "$SETTINGS")" = "600 $SERVICE_USER" ]; then
  ok "$SETTINGS (mode 600, $SERVICE_USER)"
else
  absent "$SETTINGS with mode 600, owner $SERVICE_USER"
fi

section "Data stores, copied once from the PC"
for store in "${STORES[@]}"; do
  if [ -d "$CHECKOUT/$store" ] && [ -n "$(ls -A "$CHECKOUT/$store" 2>/dev/null)" ]; then
    owner="$(stat -c '%U' "$CHECKOUT/$store")"
    if [ "$owner" = "$SERVICE_USER" ]; then ok "$store"; else note "$store is owned by $owner"; fi
  else
    absent "$store"
  fi
done

section "Timer"
if systemctl is-enabled --quiet weekly-schedule.timer 2>/dev/null &&
  systemctl is-active --quiet weekly-schedule.timer; then
  ok "weekly-schedule.timer enabled and active"
else
  absent "weekly-schedule.timer enabled and active"
fi
if [ -e "$DROP_INS/dry-run.conf" ]; then
  note "dry-run drop-in installed: ticks decide and run nothing (the first week)"
else
  ok "no dry-run drop-in: ticks start real runs"
fi
# The last WEEKLY_WORKERS wins: the unit's, then workers.conf's.
workers="$(systemctl show weekly-schedule.service -p Environment --value | tr ' ' '\n' |
  sed -n 's/^WEEKLY_WORKERS=//p' | tail -1)"
ok "workers ${workers:-unset}, cores $cores"
systemctl list-timers weekly-schedule.timer --no-pager | sed -n '1,2p'
last="$(systemctl show weekly-schedule.service -p Result -p ExecMainStatus -p ExecMainExitTimestamp)"
printf 'last tick: %s\n' "$(printf '%s' "$last" | tr '\n' ' ')"

section "Access"
if ufw status 2>/dev/null | grep -q '^Status: active'; then
  ok "ufw active: $(ufw status | awk 'NR > 4 && $0 != "" { print $1 }' | sort -u | tr '\n' ' ')"
else
  absent "ufw active"
fi
password="$(sshd -T 2>/dev/null | awk '$1 == "passwordauthentication" { print $2 }')"
if [ "$password" = no ]; then
  ok "SSH password login off"
else
  note "SSH password login on: add a key for root and run provision.sh again"
fi
if systemctl is-active --quiet unattended-upgrades.service; then
  ok "unattended upgrades active"
else
  absent "unattended upgrades"
fi

exit "$missing"
