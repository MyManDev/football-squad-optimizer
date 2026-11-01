# The weekly schedule on a Linux host

These files run the weekly schedule of #1243 under systemd on a Linux host: an Azure VM of its
own, not the one that runs the advice backend: on that VM's 2 vCPUs a GW7 run was still in the
league stage after 2.5 hours, against 77 minutes on the PC (#1010). Every 15 minutes the
deadline gate,
`python -m squadopt.platform.weekly_schedule`, decides whether a weekly run starts (a morning
run once a UTC day, the final run a lead before each deadline) and starts at most one, which
ends at its site pull request. D1 on #1243 releases a run only after İbo has seen its preview
and said yes, by `python -m squadopt.platform.weekly_release --run-id <id>`
(`src/squadopt/platform/weekly_release.py`); the gate's `--release` stays off. Nothing here is
installed or run by committing it.

| File | What it is |
| --- | --- |
| `weekly-schedule.service` | One tick: the checkout's venv runs the gate, without `--release` (D1), the club-news settings come from a private `EnvironmentFile`, and the tick has no start timeout |
| `weekly-schedule.timer` | A tick every 15 minutes (`OnCalendar=*:0/15`), and once after the host was off through one (`Persistent=true`) |
| `dry-run.conf` | A drop-in for the first week: the same tick with `--dry-run` |

The paths follow the backend VM's layout of [`scripts/vm_sync.sh`](../../scripts/vm_sync.sh):
user `squadopt`, everything under `/home/squadopt/squadopt`. Set the new host up the same way,
or replace them in all three files where it differs. A tick that starts a run lasts hours;
systemd starts no second tick while one runs, so the timer's ticks in between do nothing.

## What the host needs

- **A checkout of its own on `develop`**, clean, at `/home/squadopt/squadopt/weekly`, with
  `origin` the GitHub repository. Not the backend's `~/squadopt/repo`: `vm_sync.sh` keeps that
  one on a release tag, and the gate fast-forwards its checkout before each run, because the
  weekly command refuses a revision that is not the fresh `origin/develop`.
- **A Python 3.12 or newer venv at `<checkout>/.venv`** (3.13 is the version `constraints.txt`
  pins): `python3 -m venv .venv`, then
  `.venv/bin/python -m pip install -c constraints.txt -e ".[llm]"`. `ship.sh` runs its live
  check with `.venv/bin/python` as well.
- **The private data stores, copied once from the PC, on a persistent disk.** They are
  gitignored, so a clone has none of them, and the weekly run reads and writes them inside
  the checkout: `data/snapshots`, `data/entries`, `data/ledger`, `data/handoffs`,
  `data/advice_records`, `data/raw/vaastav-fpl`, `artifacts/phase_b`, `artifacts/rotation`
  and `artifacts/football`, with `artifacts/backend-artifact-root.json` where the PC has one.
  The gate and the run add `data/runtime` (the journals, the previews and the gate's markers)
  and `data/logs` (each run's log and release log). Keep both: the markers and the release
  logs are what keep a run, and a release, from happening twice. Keep the whole checkout on
  the OS disk or an attached managed data disk, never on the temporary disk Azure mounts at
  `/mnt`, which is wiped when the VM is redeployed or resized, and link no store into it: the
  weekly journal refuses a path through a symbolic link.
- **`gh` logged in** as an account that may push branches and tags, open pull requests,
  enqueue into the merge queue of `develop`, merge the release pull request into `main` and
  dispatch `deploy-pages.yml`; the release does all of these, most through
  `scripts/release/ship.sh`. Log in with `gh auth login`, then `gh auth setup-git`, so that
  `git push` uses the same account.
- **The club-news settings.** A private copy of
  [`club-news.settings.example.toml`](../club-news.settings.example.toml)
  ([club news configuration](../../docs/club_news_configuration.md)) that only `squadopt`
  can read, and the environment file the unit names, `/etc/squadopt/weekly-schedule.env`,
  owned by root with mode 0600 (systemd reads it before it starts the tick as `squadopt`):

  ```sh
  SQUADOPT_CLUB_NEWS_SETTINGS=/home/squadopt/squadopt/private/club-news.settings.toml
  # The variable the settings' api_key_env names, unless the private copy holds api_key.
  OPENAI_API_KEY=<the key>
  ```

  The unit files hold no secret. Only the final run reads club news (D3 on #1243), so
  without the settings a morning run still runs and the final run refuses before it starts.
- **A machine the run fits.** A worker is one CP-SAT solve on one core, and `--workers`
  defaults to 15, the owner's PC. Pass the number of cores the backend's own processes leave
  (`--workers N` on `ExecStart`) and time one run there. The defaults allow 3.5 h from
  capture to live (`--run-hours`) and start the final run 4 h before the deadline
  (`--final-lead-hours`); a smaller machine needs both raised to the time a run takes on it.

## Enable it, in this order

1. As `squadopt`, once by hand, from the checkout:
   `.venv/bin/python -m squadopt.platform.weekly_schedule --workspace /home/squadopt/squadopt/weekly --dry-run`.
   It prints the gameweek, the decision and the command it would run, and writes nothing.
2. Install the units with the dry-run drop-in, and start the timer:

   ```sh
   sudo cp deploy/weekly-schedule/weekly-schedule.service deploy/weekly-schedule/weekly-schedule.timer /etc/systemd/system/
   sudo mkdir -p /etc/systemd/system/weekly-schedule.service.d
   sudo cp deploy/weekly-schedule/dry-run.conf /etc/systemd/system/weekly-schedule.service.d/
   sudo systemctl daemon-reload
   sudo systemctl enable --now weekly-schedule.timer
   ```

3. For a week that holds a deadline, read the ticks with
   `journalctl -u weekly-schedule.service --since today`. A dry run leaves no marker, so from
   the morning time on every tick says it would start that morning's run; check the times and
   the gameweek against the deadlines.
4. Then remove the drop-in; the next tick runs for real, up to its site pull request:

   ```sh
   sudo rm /etc/systemd/system/weekly-schedule.service.d/dry-run.conf
   sudo systemctl daemon-reload
   ```

Each release writes one line per step to `data/logs/weekly/<run id>.release.log`, and the
commands' output to `<run id>.release-commands.log`. A release that stopped after the enqueue
(exit 1) is reconciled by hand from those two logs and never run again.

## Stop it

- `sudo systemctl disable --now weekly-schedule.timer` stops the ticks; a tick already running
  goes on to its end.
- `sudo systemctl stop weekly-schedule.service` ends a running tick, and the weekly run or the
  release under it. The run's marker and its release log stay, so neither starts again by
  itself; reconcile from the logs.
- `systemctl list-timers weekly-schedule.timer` shows the next tick.

## What stays a person's

- **The backend.** On this host the release does not run `scripts/vm_push.sh`, which streams
  a PC's data to the VM and restarts the backend's containers there: the data is already here.
  No agent or automation starts, restarts or stops the backend, so once `ship.sh` reports the
  site live the release writes `backend: left to its operator ...` and runs nothing. The
  backend's operator moves it to the release tag, as `vm_sync.sh` does, and gives it this
  checkout's new captures, handoffs and artifacts.
- **A release that stopped**, as above, and a final run the gate reports missed (exit 3).
