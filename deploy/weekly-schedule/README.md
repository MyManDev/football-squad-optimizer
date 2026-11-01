# The weekly schedule on its Contabo host

These files run the weekly schedule of #1243 under systemd on a host of its own: a Contabo Cloud
VPS 4 (4 shared vCPU, 8 GB memory, 100 GB SSD) on Ubuntu 24.04 in an EU region, billed monthly,
which the owner approved on 2026-11-01 (6559768575). It is not the backend's host, and nothing
here touches the backend. Nothing here is installed or run by committing it.

| File | What it is |
| --- | --- |
| `provision.sh` | Sets a fresh Ubuntu 24.04 host up as root, and can run again at any time: packages, `gh`, Python 3.13, the user `squadopt`, the checkout and its venv, swap, firewall, security updates, a journald cap, SSH hardening once root has a key, and the units below with the timer on |
| `check_host.sh` | A read-only readiness report, run as root: each line OK, WARN or MISSING |
| `weekly-schedule.service` | One tick: the checkout's venv runs the gate without `--release` (D1), one solver worker per core, the club-news settings from a private `EnvironmentFile`, no start timeout |
| `weekly-schedule.timer` | A tick every 15 minutes (`OnCalendar=*:0/15`), and once after the host was off through one (`Persistent=true`) |
| `dry-run.conf` | A drop-in for the first week: the same tick with `--dry-run`, which writes, starts and posts nothing |

## What a tick does

Every 15 minutes the deadline gate, `python -m squadopt.platform.weekly_schedule`, reads the
deadlines from the public bootstrap and starts at most one weekly run
(`src/squadopt/platform/weekly_schedule.py`, the decisions D1 to D6 in 6559389043):

- **A morning run** once a UTC day from 02:00Z for the open gameweek, with no club news, so no
  model call (D3), and no manager's word: it passes no `--rotation`, so its index says
  `no_evidence_this_run` and its pages offer no word. It is skipped when the final run would
  start before it could finish.
- **The final run** once a gameweek, 4 h before the deadline, with club news (D2), which its
  manager's word reads (`--rotation --rotation-capture <its capture>`).
- **A fixture gap** (D4): while the next deadline is more than 9 days away at the morning time
  (`LEAD_WINDOW_DAYS`, `--lead-window-days`), one morning run starts, the first once the
  gameweek before is finished and checked, and publishes its settled view; the other mornings
  start nothing until the deadline is inside those 9 days. The 2026-27 gaps are GW5 to GW6,
  GW10 to GW11, GW20 to GW21, GW25 to GW26, GW28 to GW29 and GW30 to GW31.
- **A run ends at its site pull request.** Its release runs only after İbo has seen the preview
  and said yes, by hand (D1, "Release a run" below).
- **#1093** gets the run's start line, its end line with its duration and peak memory, and an
  alarm naming the run and the stage when a run is refused, fails or ends late, when the final
  run's window was missed, and once a UTC day while the gate cannot decide (D6).
- **Each run's duration and peak memory** go into `data/logs/weekly/measurements.jsonl`, one
  JSON line per run, and into the tick's journal.

A tick that starts a run lasts hours; systemd starts no second tick while one runs, so the
timer's ticks in between do nothing.

## The layout

| What | Where |
| --- | --- |
| Service user | `squadopt`, home `/srv/squadopt` (mode 0750) |
| Checkout | `/srv/squadopt/weekly`, a clone of `develop` (of #1262's branch until it merges, `SQUADOPT_REF`); the gate fast-forwards it before each run, because the weekly command refuses a revision that is not the fresh `origin/develop` |
| venv | `/srv/squadopt/weekly/.venv`, Python 3.13, `pip install -c constraints.txt -e ".[llm]"` |
| Private settings | `/srv/squadopt/private/club-news.settings.toml` (squadopt, 0600) and `/etc/squadopt/weekly-schedule.env` (root, 0600), the file the unit's `EnvironmentFile` names |
| Units | `/etc/systemd/system/weekly-schedule.{service,timer}`, drop-ins in `weekly-schedule.service.d/`: `dry-run.conf` (the first week) and `workers.conf` (`WEEKLY_WORKERS`, the host's cores) |
| Swap | `/swapfile`, 4 GB, only when the host has no swap |
| Journal | capped at 1 GB; the clock in UTC |

Python 3.13 is the version `constraints.txt` pins and CI installs; Ubuntu 24.04 ships 3.12.
`provision.sh` takes 3.13 from the deadsnakes PPA rather than `uv`: it is an apt package, so
unattended-upgrades patches it (the script allows the PPA's origin) and the venv follows each
patch release, and the venv is the plain `python3.13 -m venv` this guide and CI use, with no
second toolchain on the host.

The data stores live inside the checkout, where the weekly run reads and writes them. They are
gitignored, so the clone has none, and they are copied once from the PC (step 6). The gate and
the runs add `data/runtime` (journals, previews, the gate's markers) and `data/logs` (each
run's logs, release logs and measurements); keep both, since the markers and the release logs
keep a run, and a release, from happening twice. Link no store into the checkout: the weekly
journal refuses a path through a symbolic link.

## Set the host up, in this order

1. **Order the VPS.** Contabo Cloud VPS 4, monthly term, an EU region, the image Ubuntu 24.04,
   no paid add-ons. Contabo mails its IP address and root password.
2. **Give root your SSH key** from your own machine, so that step 3 turns password login off:
   `ssh-copy-id root@<ip>`. Without a key the script leaves passwords on and says so; add the
   key later and run it again.
3. **Provision**, as root on the host. Until #1262 is on `develop`, from #1262's branch:
   `SQUADOPT_REF` names the branch the checkout is cloned on (`develop` when it is not set),
   and the script prints the one in use.

   ```sh
   ssh root@<ip>
   curl -fsSLO https://raw.githubusercontent.com/MyManDev/football-squad-optimizer/refs/heads/feature/the-scheduled-run-releases-itself-on-any-host/deploy/weekly-schedule/provision.sh
   SQUADOPT_REF=feature/the-scheduled-run-releases-itself-on-any-host bash provision.sh
   ```

   Once #1262 is merged, run it once more with `develop`. It moves the existing checkout over
   (fetch, check out `develop` tracking `origin/develop`, `pull --ff-only`), refuses a
   checkout with local changes or a tick that is running, and reinstalls the venv and the
   units from `develop`:

   ```sh
   curl -fsSLO https://raw.githubusercontent.com/MyManDev/football-squad-optimizer/develop/deploy/weekly-schedule/provision.sh
   SQUADOPT_REF=develop bash provision.sh
   ```

   The dry-run week can start on the branch, since a dry run only decides; real runs need
   `develop`, because the weekly command refuses a revision that is not the fresh
   `origin/develop`. The script refuses any OS but Ubuntu 24.04, a branch origin does not
   have, and a branch without these units. In order it installs
   `git`, `curl`, `time`, `ufw` and `unattended-upgrades`; `gh` from GitHub's apt repository;
   `python3.13` and `python3.13-venv` from deadsnakes; the user `squadopt`; the clone of
   `develop` and its venv (a compiler only if a pinned package has no wheel); 4 GB of swap; a
   firewall that lets only OpenSSH in; unattended security updates with no automatic reboot;
   the journald cap; SSH with `PasswordAuthentication no` and
   `PermitRootLogin prohibit-password`, only when `/root/.ssh/authorized_keys` holds a key;
   and the units, with the dry-run drop-in on the first provisioning, and the timer enabled.
   It ends by printing steps 4 to 6. Steps 4 to 8 do not wait for the run with `develop`.
4. **GitHub, as `squadopt`.** Log in with the account the release acts as: it pushes branches
   and tags, opens pull requests, enqueues into `develop`'s merge queue, merges the release
   pull request into `main`, dispatches `deploy-pages.yml` and comments on #1093. Then let git
   push through it and give its commits that account's identity:

   ```sh
   sudo -u squadopt -H gh auth login --hostname github.com --git-protocol https
   sudo -u squadopt -H gh auth setup-git
   sudo -u squadopt -H git config --global user.name "<the account's name>"
   sudo -u squadopt -H git config --global user.email "<the account's email>"
   ```

5. **Club news**, which only the final run reads (D3). Copy the private settings
   ([`club-news.settings.example.toml`](../club-news.settings.example.toml) filled in, see
   [club news configuration](../../docs/club_news_configuration.md)) to the host, then:

   ```sh
   install -m 0600 -o squadopt -g squadopt <copy> /srv/squadopt/private/club-news.settings.toml
   ```

   and fill `/etc/squadopt/weekly-schedule.env`, which `provision.sh` created with comments
   only (root, mode 0600):

   ```sh
   SQUADOPT_CLUB_NEWS_SETTINGS=/srv/squadopt/private/club-news.settings.toml
   # The variable the settings' api_key_env names, unless the private copy holds api_key.
   <API_KEY_VARIABLE>=<the key>
   ```

   Without them a morning run still runs, and the final run refuses before it starts.
6. **The data stores, copied once by the owner.** On the PC, from the checkout's root
   (PowerShell or Git Bash):

   ```sh
   tar -czf squadopt-data.tgz data/snapshots data/entries data/ledger data/handoffs data/advice_records data/raw/vaastav-fpl artifacts/phase_b artifacts/rotation artifacts/football
   scp squadopt-data.tgz root@<ip>:/root/
   ```

   then on the host, as root:

   ```sh
   tar -xzf /root/squadopt-data.tgz -C /srv/squadopt/weekly
   chown -R squadopt:squadopt /srv/squadopt/weekly/data /srv/squadopt/weekly/artifacts
   chmod -R go-rwx /srv/squadopt/weekly/data /srv/squadopt/weekly/artifacts
   rm /root/squadopt-data.tgz
   ```

   Copy `artifacts/backend-artifact-root.json` as well only if its `artifact_root` is a
   relative path: a Windows path does not resolve here. `data/runtime` and `data/logs` are the
   host's own and are not copied.
7. **Check the host:** `bash /srv/squadopt/weekly/deploy/weekly-schedule/check_host.sh`. Every
   line should be OK; the dry-run drop-in is a WARN for its week.
8. **A week of dry runs.** Read the ticks with
   `journalctl -u weekly-schedule.service --since today`. A dry run leaves no marker, so from
   the morning time on every tick says it would start that morning's run; check the times and
   the gameweek against the deadlines, and in a fixture gap the reason each tick waits. The
   week's choices are posted on #1243.
9. **Real runs**, once the checkout is on `develop` (step 3's second run). Remove the drop-in;
   the next tick runs for real, up to its site pull request:

   ```sh
   sudo rm /etc/systemd/system/weekly-schedule.service.d/dry-run.conf
   sudo systemctl daemon-reload
   ```

   `provision.sh` run again later leaves it removed.

## Release a run (D1)

Once İbo has seen a run's preview and said yes, release it by its run id, the one on its start
line on #1093. Stop the timer first: the gate does not yet wait for a release started by hand,
and a run started under one would find `develop` moved and refuse to publish. A tick missed
while the timer is stopped runs once when it starts again (`Persistent=true`).

```sh
systemctl is-active weekly-schedule.service   # "inactive": no tick is running
sudo systemctl stop weekly-schedule.timer
sudo -u squadopt -H bash -c 'cd /srv/squadopt/weekly && .venv/bin/python -m squadopt.platform.weekly_release --run-id <run id>'
sudo systemctl start weekly-schedule.timer
```

The release checks the league tree, waits for the pull request's checks, enqueues it pinned to
the commit the run published, runs `scripts/release/ship.sh` with the next unused tag (D5),
which ends in `verify_live`, and seals the football bundle after a club-news run. It writes one
line per step to `data/logs/weekly/<run id>.release.log` and the commands' output to
`<run id>.release-commands.log`. A run is released once: one that stopped after the enqueue
(exit 1) is reconciled by hand from those two logs and never run again.

## Measurements, and the move to a Cloud VPS 8

Each run's line in `data/logs/weekly/measurements.jsonl` holds its id, kind, gameweek,
deadline, workers and cores, start, end, duration, exit code, the stage it stopped at, whether
it was late, the peak memory and swap of the whole unit (its cgroup's `memory.peak`, which
systemd reports as `MemoryPeak`, and `memory.swap.peak`) and the largest single process. The
first week's lines are posted on #1243. The host moves to a Cloud VPS 8 (8 vCPU, 24 GB) when
the final run does not fit its 4 h lead (its line says `"late": true`: it ended less than
1.75 h, GW8's release, before the deadline) or memory runs out (swap in use, or a worker
killed). After the move, run `provision.sh` again: it sets `WEEKLY_WORKERS` to the new count
of cores.

## Stop it

- `sudo systemctl disable --now weekly-schedule.timer` stops the ticks; a tick already running
  goes on to its end.
- `sudo systemctl stop weekly-schedule.service` ends a running tick and the weekly run under
  it, with no end line on #1093. The run's marker stays, so it does not start again by itself;
  reconcile from its log.
- `systemctl list-timers weekly-schedule.timer` shows the next tick.

## What stays a person's

- **The release**, after the preview and a yes (D1); switching the gate's `--release` on is a
  new decision, recorded on #1243 first.
- **The backend.** The release never runs `scripts/vm_push.sh`, and no agent or automation
  starts, restarts or stops the backend: once `ship.sh` reports the site live the release
  writes `backend: left to its operator ...` and runs nothing.
- **A release that stopped**, as above, and a final run the gate reports missed (an alarm on
  #1093, exit 3).
