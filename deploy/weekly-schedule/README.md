# The weekly schedule on its Contabo host

These files run the weekly schedule of #1243 under systemd on a host of its own: a Contabo Cloud
VPS 4 (4 shared vCPU, 8 GB memory, 100 GB SSD) on Ubuntu 24.04 in an EU region, billed monthly,
which the owner approved on 2026-11-01 (6559768575). Since 2026-11-02 it is the advice
backend's host as well ("The advice backend" below). From GW11 each scheduled release moves
the backend on this host too, through `squadopt-backend-release`; the gate's own units never
start, restart or stop it. Nothing here is installed or run by committing it.

| File | What it is |
| --- | --- |
| `provision.sh` | Sets a fresh Ubuntu 24.04 host up as root, and can run again at any time: packages, `gh`, Python 3.13, the user `squadopt`, the checkout and its venv, swap, firewall, security updates, a journald cap, SSH hardening once root has a key, and the units below with the timer on |
| `backend.sh` | Sets the advice backend's side up as root after `provision.sh`, and can run again at any time: Docker and `cloudflared` from their own apt repositories, the release layout under `/root/squadopt`, the tunnel's unit, `squadopt-receive`, and `squadopt-backend-release` with its two units and its spool. It starts no backend and writes no secret |
| `check_host.sh` | A read-only readiness report, run as root: each line OK, WARN or MISSING, the backend included |
| `squadopt-receive` | Takes the data stores from the PC as a tar on stdin and puts them in the checkout as `squadopt`'s (step 6); installed in `/usr/local/sbin` |
| `squadopt-backend-release` | Root's half of the backend following a release, from GW11: takes the release chain's request from the spool, runs `vm_football_release.py`'s five steps on this host from the run's own data, then prunes old releases; installed in `/usr/local/sbin` |
| `squadopt-backend-release.path`, `.service` | Start that command as root when a request lands in `/srv/squadopt/spool/backend` |
| `cloudflared-squadopt.service` | The tunnel from Cloudflare to the api on `127.0.0.1:8000`, started once `/etc/cloudflared/config.yml` exists |
| `cloudflared.example.yml` | That configuration with a placeholder for the tunnel's id: the api and nothing else, `/metrics` and the generated api pages refused |
| `weekly-schedule.service` | One tick: the checkout's venv runs the gate, without `--release` unless `release.conf` gives it, one solver worker per core, the club-news settings from a private `EnvironmentFile`, no start timeout |
| `weekly-schedule.timer` | A tick every 15 minutes (`OnCalendar=*:0/15`), and once after the host was off through one (`Persistent=true`) |
| `dry-run.conf` | A drop-in for the first week: the same tick with `--dry-run`, which writes, starts and posts nothing |
| `release.conf` | A drop-in from GW11 (#1243, 6605005485): `WEEKLY_RELEASE=--release --backend host`, so a run that exits 0 releases itself and the backend follows on this host. `dry-run.conf`'s command leaves the variable out |

## What a tick does

Every 15 minutes the deadline gate, `python -m squadopt.platform.weekly_schedule`, reads the
deadlines from the public bootstrap and starts at most one weekly run
(`src/squadopt/platform/weekly_schedule.py`, the decisions D1 to D6 in 6559389043):

- **A morning run** once a UTC day from 02:00Z for the open gameweek, with no club news, so no
  model call (D3), and no manager's word: it passes no `--rotation`, so its index says
  `no_evidence_this_run` and its pages offer no word. It is skipped when the final run would
  start before it could finish, and late after 7 h (`--run-hours 7`): the run itself, then,
  from GW11, its release and the backend's move in the same tick.
- **The final run** once a gameweek, with club news, which its manager's word reads
  (`--rotation --rotation-capture <its capture>`). It starts 8 h before the deadline on this
  host (`--final-lead-hours 8`). D2 chose 4 h, but the first run here, on 2026-11-04, took
  4 h 29 min and its release 1 h 40 min; with the backend's move after it, 4 h does not reach
  the deadline (#1243, 2026-11-04).
- **A fixture gap** (D4): while the next deadline is more than 9 days away at the morning time
  (`LEAD_WINDOW_DAYS`, `--lead-window-days`), one morning run starts, the first once the
  gameweek before is finished and checked, and publishes its settled view; the other mornings
  start nothing until the deadline is inside those 9 days. The 2026-27 gaps are GW5 to GW6,
  GW10 to GW11, GW20 to GW21, GW25 to GW26, GW28 to GW29 and GW30 to GW31.
- **A run ends at its site pull request** while `release.conf` is not installed: its release
  runs only after İbo has seen the preview and said yes, by hand (D1, "Release a run" below).
  From GW11's first morning run (2026-11-13), `release.conf` is installed (#1243,
  6605005485): a run that exits 0 releases itself in the same tick, and the backend follows
  the release on this host ("The advice backend").
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
| Units | `/etc/systemd/system/weekly-schedule.{service,timer}`, drop-ins in `weekly-schedule.service.d/`: `dry-run.conf` (the first week), `workers.conf` (`WEEKLY_WORKERS`, the host's cores) and, from GW11, `release.conf`; the backend's `squadopt-backend-release.{path,service}` |
| The backend's spool | `/srv/squadopt/spool/backend` (squadopt, 0700), where the release chain leaves its requests; root's results and logs in `/var/lib/squadopt/backend` (root, 0755) |
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

From GW11 the tick releases instead (#1243, 6605005485). Install the drop-in once:

```sh
sudo install -m 0644 /srv/squadopt/weekly/deploy/weekly-schedule/release.conf /etc/systemd/system/weekly-schedule.service.d/
sudo systemctl daemon-reload
```

The same chain then runs in the tick that ran the weekly command, with `--backend host`: once
`verify_live` passes it hands the release to root's `squadopt-backend-release` and waits up to
55 minutes for the backend's move ("A release" below). On that host the release package
carries the run's club news, so no bundle is sealed. Removing the file is the way back to a
release by hand, which can move the backend the same way with `--backend host`.

## The advice backend

Since 2026-11-02 12:57Z `squadopt-api.mymandev.com` is served from this host. It ran on an
Azure for Students VM (2 vCPU) from 2026-10-15 until then. It runs as it ran there:

- the api and one worker under Docker Compose (`deploy/compose.yaml`), the worker limited to
  1 CPU and 2 GB, the api to 0.5 CPU and 1 GB;
- serving one immutable release package at a time, made by `vm_football_release.py`, the
  release tool of #1211, under `/root/squadopt`, the `~/squadopt` of root, who runs it here;
- reachable only through the tunnel. The api listens on `127.0.0.1:8000`, and the firewall
  still lets only SSH in.

The weekly run's data stores (step 6) and the backend's release packages are separate
copies. Until GW11 a release was packed on the PC from the stores there; from GW11 it is
packed here, from the run's own stores ("A release" below).

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

From GW11 the backend follows every scheduled release, the morning runs' too, so the site and
the backend serve one capture all week: the site refuses a backend that serves another capture
(`capabilitiesForPage`). Once `ship.sh` reports the site live, the release chain writes one
request into `/srv/squadopt/spool/backend`, and `squadopt-backend-release.path` starts the
command as root. It runs the five steps here:

1. `pack`, from the checkout's captures, handoff and manifests, with the release tag's site
   data from root's own clone at `/root/squadopt/repo`;
2. `stage`, in place of `push`;
3. `prepare`;
4. `candidate`, with its advice job while the deadline is more than 20 minutes ahead, and
   with `--no-jobs` after;
5. `activate`, likewise.

Root fetches the tag and the protected `main` history into its own clone without force-moving
an existing tag. The tag must be annotated and its commit must belong to that release history.
The spool is opened without following links in its directory chain. Requests are read and
removed through that same directory descriptor; directories and pipes are quarantined.
The tool is read by that verified commit (`git show <commit>:scripts/release/vm_football_release.py`),
never from the checkout, and root runs no git in the checkout. Before packing, it stages the
named captures, manifest/table pairs and retained handoff in a private temporary directory
under `/var/lib/squadopt/backend/inputs`. Each source is opened through pinned directory
descriptors with links refused, including parent links and hard-linked files. The tool reads
only those root-owned copies; the temporary directory is removed after pack, including a
failed pack. A request names files, never paths, and each is looked for in its one directory.
Then the oldest releases, their images and
their build checkouts are pruned; the live one and the two packed before it stay. The steps'
output is in `journalctl -u squadopt-backend-release.service` and
`/var/lib/squadopt/backend/<run id>.log`, beside the result the chain reads. A `candidate`
that fails leaves the live backend as it was, and an `activate` that fails restores the kept
configuration.

By hand, as before GW11, the owner moves the backend with the same five steps from the PC,
as on the VM, with `SQUADOPT_VM_HOST=root@<ip>`:

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

- **The release, until GW11**, after the preview and a yes (D1). Switching the gate's
  `--release` on was a new decision, recorded on #1243 on 2026-11-03 (6605005485): from GW11
  `release.conf` makes it the tick's.
- **The backend's cutover and its way back.** The release never runs `scripts/vm_push.sh`.
  From GW11 the backend follows a release through `squadopt-backend-release` on this host. The
  rule that no agent or automation starts, restarts or stops the backend no longer applies
  here: it came from a backend started inside an agent application's process tree on Windows
  (2026-10-04), and on this host the containers belong to Docker's own service. Without
  `release.conf` the release writes `backend: left to its operator ...` and runs nothing. The
  cutover, the way back and a release by hand from the PC are a person's.
- **A release that stopped**, as above, a backend move that stopped (its result names the
  step), and a final run the gate reports missed (an alarm on #1093, exit 3).
