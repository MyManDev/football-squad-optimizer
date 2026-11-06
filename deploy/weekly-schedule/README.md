# The weekly schedule on its Contabo host

These files run the weekly schedule of #1243 under systemd on a host of its own: a Contabo Cloud
VPS 4 (4 shared vCPU, 8 GB memory, 100 GB SSD) on Ubuntu 24.04 in an EU region, billed monthly,
which the owner approved on 2026-11-01 (6559768575). Since 2026-11-02 it is the advice
backend's host as well ("The advice backend" below); the weekly units never start, restart or
stop the backend. Nothing here is installed or run by committing it.

| File | What it is |
| --- | --- |
| `provision.sh` | Sets a fresh Ubuntu 24.04 host up as root, and can run again at any time: packages, `gh`, Python 3.13, the user `squadopt`, the checkout and its venv, swap, firewall, security updates, a journald cap, SSH hardening once root has a key, and the units below with the timer on |
| `backend.sh` | Sets the advice backend's side up as root after `provision.sh`, and can run again at any time: Docker and `cloudflared` from their own apt repositories, the release layout under `/root/squadopt`, the tunnel's unit and `squadopt-receive`. It starts no backend and writes no secret |
| `check_host.sh` | A read-only readiness report, run as root: each line OK, WARN or MISSING, the backend included |
| `squadopt-receive` | Takes the data stores from the PC as a tar on stdin and puts them in the checkout as `squadopt`'s (step 6); installed in `/usr/local/sbin` |
| `cloudflared-squadopt.service` | The tunnel from Cloudflare to the api on `127.0.0.1:8000`, started once `/etc/cloudflared/config.yml` exists |
| `cloudflared.example.yml` | That configuration with a placeholder for the tunnel's id: the api and nothing else, `/metrics` and the generated api pages refused |
| `weekly-schedule.service` | One tick: the checkout's venv runs the gate without `--release` (D1), one solver worker per core, the club-news settings from a private `EnvironmentFile`, no start timeout |
| `weekly-schedule.timer` | A tick every 15 minutes (`OnCalendar=*:0/15`), and once after the host was off through one (`Persistent=true`) |
| `dry-run.conf` | A drop-in for the first week: the same tick with `--dry-run`, which writes, starts and posts nothing |
| `squadopt-requested-history` | Optional pre-run copy of completed answers, inside the running backend image with no network; installed explicitly as a root-owned command |
| `requested-history.conf` | Optional weekly drop-in that prepares and consumes the private history receipt before each gate tick |

## Requested history before a weekly run

Enable this only after the backend and weekly checkout both contain this change, including
the snapshot CLI's `--reuse-unchanged` and `--max-snapshot-bytes` options. The API and worker
must run the same immutable image and mount
`/root/squadopt/store`. Do not install or enable it during a weekly run or a merge/deployment
hold. It is independent of the release drop-in; provisioning does not enable it automatically.

The hook reads the active systemd command first and does nothing when it contains `--dry-run`.
For a real tick it runs the already installed backend image, without a pull, network, extra
capabilities or root inside the container. Only the durable store and history output are
mounted. UID 10001 owns the output; the `squadopt` group can read it. The weekly process
continues as `squadopt`, and no backend service is restarted. A failed copy stops the tick
instead of silently consuming an old pointer.

After the current weekly run finishes and the deployment hold is lifted, as root:

```sh
install -o root -g root -m 0755 \
  /srv/squadopt/weekly/deploy/weekly-schedule/squadopt-requested-history \
  /usr/local/sbin/squadopt-requested-history
# Install the updated backup command so snapshots and pinned journals restore together.
install -o root -g root -m 0755 \
  /srv/squadopt/weekly/deploy/weekly-schedule/squadopt-backup \
  /usr/local/sbin/squadopt-backup
install -o root -g root -m 0755 \
  /srv/squadopt/weekly/deploy/weekly-schedule/squadopt-watch \
  /usr/local/sbin/squadopt-watch
/usr/local/sbin/squadopt-requested-history
sudo -u squadopt /srv/squadopt/weekly/.venv/bin/python -c \
  'from pathlib import Path; from squadopt.platform.requested_history_snapshot import read_history_snapshot; read_history_snapshot(Path("/var/lib/squadopt/requested-history/latest.json")); print("history readable and verified")'
install -D -o root -g root -m 0644 \
  /srv/squadopt/weekly/deploy/weekly-schedule/requested-history.conf \
  /etc/systemd/system/weekly-schedule.service.d/requested-history.conf
systemctl daemon-reload
```

The manual preparation requires a real gate configuration, not `dry-run.conf`. Verify the
readable receipt before installing the drop-in. These commands do not start a weekly run;
the next scheduled tick uses the hook. A restored or resumed run continues to use its
original pinned snapshot, even if the latest pointer has advanced.

The hook caps one snapshot at 512 MiB of payload and reserves another copy plus 1 GiB of
free space for staging and metadata. Its private history directory has a conservative
10 GiB budget. Unchanged evidence reuses the exact previous receipt, so quiet timer ticks
do not accumulate copies. Requests still waiting or computing do not advance history.
Failed or timed-out containers are removed by their unique invocation name.
The existing five-minute watch alerts on a failed weekly service even when its pre-run
hook stopped before a run log existed. It suppresses repeats and reports recovery.

The nightly backup includes `/var/lib/squadopt/requested-history` when it exists and holds
the producer's snapshot lock until restic finishes copying it. The weekly journals under
`data/runtime/weekly` are already included. Restore both at their original paths before
resuming a run; copying only `latest.json` is insufficient.

No snapshot is automatically deleted. When the capacity guard refuses, retain the current
receipt's backup and every backup pinned by a resumable run's
`data/runtime/weekly/<run-id>/run.json` (`request.requested_history_receipt`). Verify the
off-host backup before archiving completed runs and retiring only their unreferenced
copies. Read failures or uncertain pins are a reason to retain the copy. The normal host
disk alert remains enabled. A larger budget requires a reviewed change to the installed
hook, rather than disabling the guard.

To disable the hook, remove only
`/etc/systemd/system/weekly-schedule.service.d/requested-history.conf` and reload systemd.
Keep the retained copies and journals. Disabling it stops future collection; existing
published histories remain intact. If the history environment variable was also set in
`weekly-schedule.env`, remove that setting too. Confirm service permissions, lock behavior,
a real requested answer, backup/restore and the next tick on the host before accepting
this deployment; local unit tests alone do not establish those outcomes.

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
6. **The data stores, copied once by the owner.** On the host, as root, `bash
   /srv/squadopt/weekly/deploy/weekly-schedule/backend.sh` installs `squadopt-receive` (and the
   backend's side, below). The owner's key is in root's `authorized_keys`. Then on the PC,
   from the checkout's root, in Git Bash:

   ```sh
   tar -czf - data/snapshots data/entries data/ledger data/handoffs data/advice_records data/raw/vaastav-fpl artifacts/phase_b artifacts/rotation artifacts/football |
     ssh root@<ip> /usr/local/sbin/squadopt-receive
   ```

   It unpacks into a staging directory beside the checkout, refuses an archive that holds
   anything but `data/` and `artifacts/`, copies those into the checkout, gives them to
   `squadopt` with mode `go-rwx`, and prints their sizes. Copy `artifacts/backend-artifact-root.json` as well only if its `artifact_root` is a
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

## The advice backend

Since 2026-11-02 12:57Z `squadopt-api.mymandev.com` is served from this host. It ran on an
Azure for Students VM (2 vCPU) from 2026-10-15 until then. It runs as it ran there:

- the api and one worker under Docker Compose (`deploy/compose.yaml`), the worker limited to
  1 CPU and 2 GB, the api to 0.5 CPU and 1 GB;
- serving one immutable release package at a time, made by `vm_football_release.py`, the
  release tool of draft #1211, under `/root/squadopt`, the `~/squadopt` of the user that
  tool reaches over SSH;
- reachable only through the tunnel. The api listens on `127.0.0.1:8000`, and the firewall
  still lets only SSH in.

The weekly run's data stores (step 6) and the backend's release packages are separate
copies. A release is packed on the PC from the stores there.

### Set it up

Public teams can use the existing API/worker queue with
`SQUADOPT_BACKEND_PUBLIC_ENTRIES=1` in the backend's private Compose environment.
`SQUADOPT_BACKEND_PUBLIC_QUEUE_LIMIT` defaults to 32 open jobs. Apply the tested release
to both API and worker before enabling the flag; rollback disables the flag or restores
the previous release.

`GET /api/v1/public/leagues/{league}/entries/{entry}/advice` only reads an existing result.
`POST` fetches and pins that one team's FPL bundle, then joins or creates a durable job.
League 0 denotes a standalone `/entry/{entry}` page; regular league endpoints still require
a positive league id. Only the plain one-week plan is accepted. Country leagues are never
added to the weekly capture configuration. The browser starts neither server nor device
computation until the visitor chooses it; queued work can resume after a reload.

Inputs live under `store/public-entries`, keyed by capture and entry, and their fingerprint
is part of the advice cache identity. The first valid input for a capture is immutable;
a newer capture gets fresh inputs. API and worker share this store and the normal rate
limits, deadline guard, per-client job limit, job progress and cache. Fetches use only the
deployed FPL forwarder, reject redirects, and are bounded to 15 seconds and 2 MiB.

1. As root: `bash /srv/squadopt/weekly/deploy/weekly-schedule/backend.sh`. It is the same
   script for a first setup and for a check that changes nothing.
2. **The tunnel, by a person, once.** The two commands make the account's certificate and
   the tunnel's credential, so a person runs them:

   ```sh
   cloudflared tunnel login                 # opens Cloudflare's page: approve mymandev.com
   cloudflared tunnel create squadopt-api-contabo
   ```

   Then copy `cloudflared.example.yml` to `/etc/cloudflared/config.yml`, put the printed id
   in its two places, run the three checks at its top, and run `backend.sh` again. That
   starts `cloudflared-squadopt.service`. No hostname routes to the new tunnel yet, so it
   carries nothing.
3. **The first release**, from the PC as for every new gameweek (below), then the cutover.

### A release

Each gameweek the owner moves the backend with `vm_football_release.py`'s five steps, as on
the VM, with `SQUADOPT_VM_HOST=root@<ip>`:

1. `pack`;
2. `push`;
3. `remote prepare`;
4. `remote candidate`;
5. `remote activate`.

`activate` keeps the live `.env` and override as the release's rollback. A release that
changes only the web front end needs nothing here.

A `candidate` after the gameweek's deadline is refused its advice job (`DEADLINE_PASSED`),
since the backend computes nothing new for a closed gameweek. `--no-jobs` is then the only
candidate there is, as for GW9 on 2026-11-02.

### Members' addresses

Behind `cloudflared` and Docker's port proxy, the api's TCP peer is the gateway of the
Compose network `squadopt_default` (172.18.0.1 when it was checked), never 127.0.0.1. With
`FORWARDED_ALLOW_IPS` unset, uvicorn trusts no forwarded address, so the rate limits treat
every member as one client: 30 requests a minute and 4 open jobs. The Azure VM ran so as
well.

Once a release is active:

1. Read the peer in `docker logs squadopt-api-1`.
2. Add `FORWARDED_ALLOW_IPS=<that gateway>` to `/root/squadopt/.env`. Every release keeps the
   line: the tool replaces only the image and the paths.
3. Recreate the api:

   ```sh
   cd /root/squadopt && docker compose -p squadopt --env-file .env -f repo/deploy/compose.yaml -f compose.artifacts.yaml up -d
   ```

`check_host.sh` compares the line with the network's gateway.

### The cutover, and the way back

```sh
cloudflared tunnel route dns --overwrite-dns squadopt-api-contabo squadopt-api.mymandev.com
```

It points the hostname at this host's tunnel; the browser and the site build keep the same
address. The Azure VM's tunnel, `squadopt-api`, stays connected with its backend on GW9 for
a week as the way back:

```sh
cloudflared tunnel route dns --overwrite-dns squadopt-api squadopt-api.mymandev.com
```

After that week, delete `/root/.cloudflared/cert.pem`. It can manage every tunnel of the
account, and only the route commands need it.

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

## Backups and alerts

#1294 asked for both before the host held captures of its own; since 2026-11-04 it does, and
FPL serves only the present, so a lost capture cannot be taken again.

- **The backup** (`squadopt-backup`, nightly at 23:30Z, when no run writes) sends what the
  weekly run and the backend cannot rebuild to a restic repository in Cloudflare R2. That covers
  `data/snapshots`, `data/handoffs`, `data/ledger`, `data/advice_records`, `data/entries`,
  `data/runtime`, `data/logs`, `artifacts/`, and the backend's `releases/` and `store/`.
  Once the multi-league baseline store exists, `data/member_baselines` is included too.
  Keep the runtime journals, started markers and release logs with their captures: they prevent
  a restored host from starting a run or publishing a release twice.
  - restic encrypts each backup, adds only what changed and checksums every block. It keeps
    14 daily, 8 weekly and 12 monthly snapshots, checks the repository's structure each night
    and reads a fifth of the data back on Sundays.
  - A success writes `/var/lib/squadopt/backup/last-success`. A failure sends an alert.
- **The watch** (`squadopt-watch`, every five minutes) sends an ntfy alert when a check turns
  bad, again once a day while it stays bad, and once when it is good again:

  A failed delivery is retried on the next pass, including a recovery notice. Only a successful
  delivery starts the daily repeat interval. A pass with a failed delivery exits non-zero and
  sends no success ping to healthchecks.io.

  | Alert | What it means, and what to do |
  | --- | --- |
  | `backend` | `/ready` has not answered 200 for 5 minutes. Read `docker ps` and `docker logs squadopt-api-1`. |
  | `disk` | The root file system is over 80 % full. Read `du -sh /root/squadopt/* /srv/squadopt/weekly/data/*`. |
  | `backup` | No backup in 36 hours, or none yet. Read `journalctl -u squadopt-backup`. |
  | `run` | The newest weekly run ended with a non-zero exit; the alarm on #1093 names its stage. Read its log. |
  | `timer` | `weekly-schedule.timer` has been off for 3 hours, so no run can start. Start it once no release by hand is running. |
  | `capture` | A deadline is 3 hours away and nothing was captured since the deadline before, or the cached deadlines cannot be read. Check the gate's journal and bootstrap cache now: a missing capture cannot be taken after the deadline. |

- **From outside**, healthchecks.io expects a ping from every watch pass and every backup, and
  alerts through the same ntfy topic when one is late. That is how a host that cannot send
  anything at all is noticed.

### Set them up, once, by a person

The values are secrets: write them on the host yourself, never in chat, an issue or a commit.

1. **ntfy.** Install the ntfy app on both phones. Choose a long, random topic name, subscribe
   to it on `ntfy.sh` in both apps, and share it only in private.
2. **healthchecks.io.** In a free account, add two checks:
   - "squadopt-watch", period 5 minutes, grace 10 minutes;
   - "squadopt-backup", period 1 day, grace 12 hours.

   Add the ntfy integration with the same topic, and copy each check's ping address.
3. **R2.** In Cloudflare, create the bucket `squadopt-backup`, then an R2 API token with
   *Object Read & Write* on that bucket only. Keep its access key id, its secret access key and
   the account's S3 endpoint (`https://<account id>.r2.cloudflarestorage.com`).
4. **On the host, as root:**

   ```sh
   install -m 0600 /srv/squadopt/weekly/deploy/weekly-schedule/alert.example.env /etc/squadopt/alert.env
   install -m 0600 /srv/squadopt/weekly/deploy/weekly-schedule/backup.example.env /etc/squadopt/backup.env
   nano /etc/squadopt/alert.env /etc/squadopt/backup.env      # fill in every <...>
   (umask 077; openssl rand -base64 33 > /etc/squadopt/restic-password)
   ```

   Keep a copy of the restic password in a password manager: without it the backup cannot be
   read.
5. **Initialise the repository and start the timers:**

   ```sh
   set -a; . /etc/squadopt/backup.env; set +a; restic init
   bash /srv/squadopt/weekly/deploy/weekly-schedule/backend.sh
   systemctl start squadopt-backup.service     # the first backup, now
   squadopt-alert default "SquadOpt test" "The alert reaches this phone."
   ```

### Restore

Into an empty directory, never over the live data:

```sh
set -a; . /etc/squadopt/backup.env; set +a
restic snapshots --tag nightly
restic restore latest --tag nightly --target /srv/restore
restic check --read-data
```

Then compare checksums with the live stores (for example `sha256sum` over a capture's files),
and copy back only what was lost, as the squadopt user. `restic find <name>` finds one file.

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
  writes `backend: left to its operator ...` and runs nothing. A backend release, the five
  steps of "A release" above, is run by a person, and so are the cutover and the way back.
- **A release that stopped**, as above, and a final run the gate reports missed (an alarm on
  #1093, exit 3).
