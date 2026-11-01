"""The scheduled gate of the weekly run: a morning run once a UTC day, a final run per deadline.

    python -m squadopt.platform.weekly_schedule --dry-run
    python -m squadopt.platform.weekly_schedule --dry-run --now 2026-10-31T07:05:00Z

A scheduler on the host that runs the week calls this every 15 minutes (#1243). It is
``scripts/weekly_schedule.ps1`` (#1244) in Python, with the decisions of
``scripts/weekly_run.ps1`` a run needs, so the same gate runs on Linux and on Windows. From the
public bootstrap's deadlines (cached under ``data/runtime/weekly-schedule`` for an hour), the
clock and the markers of the runs it has already started, it starts at most one weekly run, for
the first gameweek whose deadline is still ahead:

- the final run, once per gameweek, from the deadline minus the lead;
- a morning run, once per UTC day, from the morning time, unless the final run would start
  before a morning run could finish;
- inside a fixture gap, where that deadline is more than the lead-time window away at the
  morning time, one morning run only, the first once the gameweek before has settled, which
  publishes its settled view; the other mornings start nothing until the window (D4 on #1243).

Deadlines decide, not weekdays, so a midweek deadline needs no exception. A start leaves its
marker (``started/morning-<date>.json``, ``started/settled-<season>-gw<NN>.json`` for the
settled view in a gap, or ``started/final-<season>-gw<NN>.json``) before anything runs, so a
run that fails is not started again by the next tick, and each run publishes under its own
site suffix (``morning-<stamp>`` or ``final-<stamp>``). A Friday-kind run, which the final run
always is, first acquires the week's club news in this process; a morning run is a
Tuesday-kind run with no club news (D3 on #1243).

A run ends at its site pull request. D1 on #1243 (6559389043) releases it only after İbo has
seen its preview and said yes, by ``python -m squadopt.platform.weekly_release --run-id <id>``.
``--release`` would release a run the gate started in the same tick, once its weekly command
exited 0, with ``weekly_release.release_run`` (#1249 in Python); it stays off, and switching it
on is a new decision, recorded on #1243 first.

A run the gate starts posts a start line and an end line on #1093, the heavy-run slot, which a
weekly run outranks (6461334333), so that nobody merges into develop or starts a heavy run
under it. A run that is refused, fails or ends late, a final run the gate missed, and a gate
that cannot decide (once a UTC day) post an alarm there naming the run and the stage (D6 on
#1243). Every comment goes through one seam, `Notify`, and a post that fails is printed and
never stops the gate.

Each run the gate starts records its wall duration and peak memory, the figures of the first
week that decide whether the host moves to a Contabo Cloud VPS 8 (#1243, 6559768575): one JSON
line in ``data/logs/weekly/measurements.jsonl``, the same line in the tick's journal, and both
figures on its end line on #1093. Under systemd the peak is the tick's whole unit, read from
its cgroup (``memory.peak``, the number systemd reports as ``MemoryPeak``, and
``memory.swap.peak``); on any POSIX host the largest single process is read as well.

``--dry-run`` prints the decision and the command it would run, and writes and posts nothing.
The exit code is 0 for a decision (starting nothing is one), the weekly command's own when one
ran (with ``--release``, the release's after a run that exited 0), 3 when the final run's
window was missed, and 2 for a refusal before the weekly command ran.
"""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import math
import os
import re
import subprocess
import sys
import time
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final, Literal

from squadopt.contracts.run_logs import LOG_ROOT_NAME
from squadopt.data.atomic import replace_retrying
from squadopt.data.errors import DataError
from squadopt.data.sources.fpl_live import (
    BOOTSTRAP_PAYLOAD,
    gameweek_deadlines,
    scored_gameweeks,
)
from squadopt.data.timestamps import as_instant
from squadopt.platform import club_news_acquire, weekly_release
from squadopt.platform.fpl_capture import ENDPOINTS, fetch
from squadopt.platform.weekly_journal import WeeklyJournalError, inspect_run
from squadopt.platform.weekly_publish import WEEKLY_RUNS

#: The defaults #1243 proposes, its decision D2: a morning run from 02:00 UTC, the final run
#: 4 h before the deadline, and 3.5 h for a run from capture to live (GW8 took 3 h 34 min).
MORNING_UTC: Final = "02:00"
FINAL_LEAD_HOURS: Final = 4.0
RUN_HOURS: Final = 3.5
#: D3 on #1243 (6559389043): club news on the final run only. A morning run is a Tuesday-kind
#: run, which acquires no club news and so makes no model call.
MORNING_KIND: Final = "tuesday"
#: `weekly_run.ps1`'s default.
WORKERS: Final = 15
#: D4 on #1243: inside a fixture gap the settled view is published once, and morning runs stop
#: until the next deadline is inside the lead-time window (``docs/deployment_runbook.md``, "A
#: run inside a fixture gap is not automatically safe"), which names no number of days. The
#: longest gap between consecutive deadlines of a normal week in 2026-27 is 8 days (GW36
#: 2027-05-15T12:30Z to GW37 2027-05-23T12:30Z), and one day more is the margin, so a normal
#: week keeps every morning run. The six longer gaps, 9.8 to 21.7 days, each hold a weekend
#: with no Premier League round: three international breaks (GW5 to GW6, GW10 to GW11, GW30
#: to GW31) and the weekends after three midweek rounds (GW20, GW25 and GW28).
LEAD_WINDOW_DAYS: Final = 9.0

#: GW8's release from its site pull request to live: four CI rounds and the deploy, 102 min,
#: with a few minutes between them (#1243). A final run that ends later than this before its
#: deadline cannot be live in time once its release waits for a person (D1).
RELEASE_HOURS: Final = 1.75
#: The heavy-run slot, where a weekly run posts its start, its end and its alarms (D6).
SLOT_ISSUE: Final = "1093"
#: Where a Linux host mounts its cgroup v2 tree.
CGROUP_ROOT: Final = Path("/sys/fs/cgroup")
PROC_CGROUP: Final = Path("/proc/self/cgroup")

SCHEDULE_STATE: Final = Path("data/runtime/weekly-schedule")
WEEKLY_LOGS: Final = LOG_ROOT_NAME / "weekly"
FIXTURES: Final = Path("web/public/data/fixtures.json")
#: One JSON line per run the gate started: its duration and its memory peaks.
MEASUREMENTS: Final = WEEKLY_LOGS / "measurements.jsonl"
BOOTSTRAP_MAX_AGE: Final = timedelta(hours=1)
SETTINGS_VARIABLE: Final = "SQUADOPT_CLUB_NEWS_SETTINGS"

Action = Literal["morning", "final", "missed", "none"]
#: Runs one command (its arguments, working directory and log) and answers its exit code.
Runner = Callable[[Sequence[str], Path, Path], int]
#: The club-news command's `main`: its arguments in, its exit code out, its lines printed.
Acquire = Callable[[list[str]], int]
#: Releases a completed run by its id (#1249), answering the release's exit code.
Release = Callable[[Path, str], int]
#: Posts one comment on the slot issue from the checkout (D6); never raises.
Notify = Callable[[Path, str], None]
#: A monotonic clock in seconds, for a run's duration.
Clock = Callable[[], float]


class ScheduleError(ValueError):
    """A refusal: the gate starts nothing further and exits 2."""


@dataclass(frozen=True, slots=True)
class Outcome:
    """What a started run came to: its exit code, where it stopped and what a person reads.

    `stage` and `log` are empty for a run that completed; `log` is relative to the checkout,
    so a comment names no path of the host.
    """

    code: int
    stage: str = ""
    verb: str = ""
    log: str = ""
    released: bool = False


@dataclass(frozen=True, slots=True)
class MemoryPeaks:
    """A run's memory peaks in bytes, `None` where the host exposes none.

    `unit` and `swap` cover every process of the systemd unit the tick runs in, the run's
    workers together; `largest` is the largest single process the gate waited for.
    """

    unit: int | None = None
    swap: int | None = None
    largest: int | None = None


#: Reads the memory peaks of the run that just ended.
Peaks = Callable[[], MemoryPeaks]


@dataclass(frozen=True, slots=True)
class Decision:
    """The action of one tick, the gameweek it is for, the marker it leaves and why."""

    action: Action
    gameweek: int
    deadline: datetime
    final_start: datetime
    marker: str
    reason: str


def utc_text(instant: datetime) -> str:
    return instant.astimezone(UTC).strftime("%Y-%m-%dT%H:%MZ")


def _hours(value: float) -> str:
    # 3, 3.5 and 4, as the PowerShell gate printed them on every culture.
    return f"{value:g}"


def schedule_events(bootstrap: bytes) -> tuple[tuple[int, datetime], ...]:
    """Each gameweek and its deadline as a UTC instant, in gameweek order."""

    return tuple(
        (row.gameweek, as_instant(row.deadline_utc)) for row in gameweek_deadlines(bootstrap)
    )


def started_markers(directory: Path) -> frozenset[str]:
    """The runs already started: the name of each `.json` marker, none before the first."""

    if not directory.is_dir():
        return frozenset()
    return frozenset(path.stem for path in directory.glob("*.json") if path.is_file())


def morning_start(now: datetime, morning_utc: str) -> datetime:
    match = re.fullmatch(r"([01][0-9]|2[0-3]):([0-5][0-9])", morning_utc)
    if match is None:
        raise ScheduleError(f"--morning-utc must be HH:MM in UTC, not {morning_utc!r}.")
    day = now.astimezone(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
    return day + timedelta(hours=int(match[1]), minutes=int(match[2]))


def first_morning(instant: datetime, morning_utc: str) -> datetime:
    """The first morning time at or after `instant`."""

    start = morning_start(instant, morning_utc)
    return start if start >= instant else start + timedelta(days=1)


def decide(
    events: Sequence[tuple[int, datetime]],
    now: datetime,
    season: str,
    markers: Collection[str],
    *,
    settled: Collection[int] = frozenset(),
    morning_utc: str = MORNING_UTC,
    lead_hours: float = FINAL_LEAD_HOURS,
    run_hours: float = RUN_HOURS,
    window_days: float = LEAD_WINDOW_DAYS,
) -> Decision:
    """Pure: the action of this tick, from the deadlines, the clock and the runs started.

    `settled` holds the gameweeks the bootstrap says are finished and checked; only a fixture
    gap reads it.
    """

    if lead_hours < run_hours:
        raise ScheduleError(
            f"A final run {_hours(lead_hours)} h before the deadline cannot be live before it: "
            f"a run takes about {_hours(run_hours)} h."
        )
    if window_days <= 0:
        raise ScheduleError(f"--lead-window-days must be above 0, not {_hours(window_days)}.")
    ahead = [(gameweek, deadline) for gameweek, deadline in events if deadline > now]
    if not ahead:
        raise ScheduleError(f"No gameweek deadline lies ahead of {utc_text(now)} in the bootstrap.")
    gameweek, deadline = min(ahead)
    final_start = deadline - timedelta(hours=lead_hours)
    run = timedelta(hours=run_hours)
    final = f"final-{season}-gw{gameweek:02d}"
    morning = f"morning-{now.astimezone(UTC):%Y-%m-%d}"
    morning_from = morning_start(now, morning_utc)

    def chosen(action: Action, reason: str, marker: str = "") -> Decision:
        return Decision(action, gameweek, deadline, final_start, marker, reason)

    if now >= final_start:
        if final in markers:
            return chosen("none", f"the final run for gameweek {gameweek} has already started")
        if deadline - now < run:
            # Rounded half away from zero, as .NET's "0" format rounds.
            minutes = math.floor((deadline - now).total_seconds() / 60 + 0.5)
            return chosen(
                "missed",
                f"the final run for gameweek {gameweek} did not start: the deadline is "
                f"{minutes} min away and a run takes about {_hours(run_hours)} h",
            )
        return chosen("final", f"the final run for gameweek {gameweek}", final)
    if now < morning_from:
        return chosen("none", f"today's morning run starts at {utc_text(morning_from)}")
    window = timedelta(days=window_days)
    if deadline - morning_from > window:
        # A fixture gap (D4), judged at the morning time so that every tick of a day agrees.
        previous = gameweek - 1
        settled_view = f"settled-{season}-gw{previous:02d}"
        resume = f"morning runs resume at {utc_text(first_morning(deadline - window, morning_utc))}"
        gap = (
            f"a fixture gap: gameweek {gameweek}'s deadline is more than "
            f"{_hours(window_days)} days away"
        )
        if previous < 1:
            return chosen("none", f"{gap}; {resume}")
        if previous not in settled:
            return chosen(
                "none",
                f"{gap}; gameweek {previous}'s settled view waits for it to settle, and {resume}",
            )
        if settled_view in markers:
            return chosen(
                "none",
                f"{gap}; gameweek {previous}'s settled view has already started, and {resume}",
            )
        return chosen(
            "morning",
            f"the settled view of gameweek {previous}, once in the fixture gap before gameweek "
            f"{gameweek}",
            settled_view,
        )
    if morning in markers:
        return chosen("none", "today's morning run has already started")
    if final_start - now < run:
        return chosen(
            "none",
            f"the final run starts at {utc_text(final_start)}, before a morning run could finish",
        )
    return chosen("morning", f"today's morning run for gameweek {gameweek}", morning)


def run_kind(action: Action, morning_kind: str = MORNING_KIND) -> str:
    """The final run is the decision run with real club news; a morning run takes none (D3)."""

    return "friday" if action == "final" else morning_kind


def run_suffix(action: Action, now: datetime) -> str:
    """One site suffix per run: `weekly_run.ps1`'s own is one per kind and day."""

    return f"{action}-{now.astimezone(UTC):%Y%m%dT%H%M}"


def run_id(kind: str, season: str, gameweek: int, now: datetime) -> str:
    return f"{season}-gw{gameweek:02d}-{kind}-{now.astimezone(UTC):%Y%m%dT%H%MZ}"


def weekly_arguments(
    kind: str,
    season: str,
    gameweek: int,
    workers: int,
    identity: str,
    suffix: str,
    rotation_capture: str = "",
) -> list[str]:
    """The weekly command's arguments, as `Build-WeeklyArguments` in `weekly_run.ps1`."""

    if kind == "friday" and not rotation_capture:
        raise ScheduleError(
            "A Friday decision requires a real club-news capture; the example fixture cannot "
            "be published instead."
        )
    arguments = [
        *("-m", "squadopt.platform.weekly_operations", "--season", season),
        *("--gameweek", str(gameweek), "--league-list", "config/leagues.json"),
        *("--workers", str(workers), "--projection", "component-only", "--rotation"),
    ]
    if rotation_capture:
        arguments += ["--rotation-capture", rotation_capture]
    arguments += ["--record-advice", "--publish", "--publish-suffix", suffix, "--run-id", identity]
    return arguments


def published_season(workspace: Path) -> str:
    """The season the published site serves, read where `weekly_run.ps1` reads it."""

    document = json.loads((workspace / FIXTURES).read_text(encoding="utf-8"))
    payload = document.get("payload") if isinstance(document, dict) else None
    season = payload.get("season") if isinstance(payload, dict) else None
    if not isinstance(season, str):
        raise ScheduleError(f"{workspace / FIXTURES} names no payload.season.")
    return season


def fpl_bootstrap() -> bytes:
    return fetch(ENDPOINTS[BOOTSTRAP_PAYLOAD])


def cached_bootstrap(cache: Path, now: datetime, read: Callable[[], bytes]) -> bytes:
    """The bootstrap, read again once the held copy is an hour old: deadlines move rarely.

    A read that fails while a copy is held decides on that copy: the game answers nothing
    while it updates after each deadline, and that is no reason to refuse or raise an alarm.
    """

    held = datetime.fromtimestamp(cache.stat().st_mtime, UTC) if cache.is_file() else None
    if held is not None and now - held < BOOTSTRAP_MAX_AGE:
        return cache.read_bytes()
    try:
        payload = read()
    except DataError as error:
        if held is None:
            raise
        print(f"bootstrap: the read failed ({error}); deciding on the copy of {utc_text(held)}")
        return cache.read_bytes()
    cache.parent.mkdir(parents=True, exist_ok=True)
    partial = cache.with_name(f"{cache.name}.partial")
    partial.write_bytes(payload)
    replace_retrying(partial, cache)
    return payload


def latest_capture(snapshots: Path) -> str:
    """The newest `fpl-live` capture on disk, whose roster the club-news acquisition reads."""

    captures = sorted(path.name for path in snapshots.glob("fpl-live-*") if path.is_dir())
    if not captures:
        raise ScheduleError(f"No fpl-live capture under {snapshots} to read a roster from.")
    return captures[-1]


def acquire_club_news(workspace: Path, settings: Path | None, log: Path, acquire: Acquire) -> str:
    """Acquire the week's club news through the command's own `main`; the capture id it wrote.

    The offline configuration check runs first, so a missing key refuses with no page read.
    Both steps print into `log`, the run's `<run id>.club-news.log`.
    """

    settings_arguments = ["--settings-file", str(settings)] if settings else []
    log.parent.mkdir(parents=True, exist_ok=True)

    def step(arguments: list[str]) -> tuple[int, str]:
        printed = io.StringIO()
        with contextlib.redirect_stdout(printed):
            code = acquire(arguments)
        with log.open("a", encoding="utf-8") as handle:
            handle.write(printed.getvalue())
        return code, printed.getvalue()

    if step(["--check-config", *settings_arguments])[0] != 0:
        raise ScheduleError(
            "Club-news configuration failed its offline check; no news was requested. Read the "
            "club-news log."
        )
    snapshots = workspace / club_news_acquire.DEFAULT_SNAPSHOT_ROOT
    code, printed = step(
        [
            *("--roster-snapshot", latest_capture(snapshots)),
            *("--registry", str(workspace / club_news_acquire.DEFAULT_REGISTRY)),
            *("--snapshot-root", str(snapshots), *settings_arguments),
        ]
    )
    if code != 0:
        raise ScheduleError(
            "Club-news acquisition failed; the weekly decision was not started. Read the "
            "club-news log."
        )
    # The command prints "Capture       club-news-<stamp>-<hash>" once it has written the week.
    capture = re.search(r"^Capture\s+(club-news-\S+)", printed, flags=re.MULTILINE)
    if capture is None:
        raise ScheduleError(
            "Club-news acquisition produced no capture id; the weekly decision was not started."
        )
    return capture[1]


def run_logged(arguments: Sequence[str], cwd: Path, log: Path) -> int:
    """Run one command from `cwd` to its end on the checkout's `src`, appending it to `log`."""

    log.parent.mkdir(parents=True, exist_ok=True)
    environment = {**os.environ, "PYTHONPATH": os.pathsep.join((str(cwd / "src"), str(cwd)))}
    with log.open("ab") as handle:
        completed = subprocess.run(
            list(arguments),
            cwd=cwd,
            env=environment,
            stdout=handle,
            stderr=subprocess.STDOUT,
            check=False,
        )
    return completed.returncode


def write_marker(
    directory: Path, decision: Decision, kind: str, suffix: str, now: datetime
) -> Path:
    path = directory / f"{decision.marker}.json"
    directory.mkdir(parents=True, exist_ok=True)
    document = {
        "action": decision.action,
        "gameweek": decision.gameweek,
        "deadline_utc": utc_text(decision.deadline),
        "kind": kind,
        "suffix": suffix,
        "started_at_utc": utc_text(now),
    }
    path.write_text(json.dumps(document, indent=2) + "\n", encoding="utf-8")
    return path


def _counter(path: Path) -> int | None:
    try:
        return int(path.read_text(encoding="ascii").strip())
    except (OSError, ValueError):
        return None


def unit_peaks(proc: Path = PROC_CGROUP, root: Path = CGROUP_ROOT) -> tuple[int | None, int | None]:
    """The memory and swap peaks of the systemd service this process runs in, if it is one.

    cgroup v2 names one group, ``0::/system.slice/weekly-schedule.service``, and each systemd
    start of a service makes its group anew, so its peak is the tick's. A shell's session
    scope holds more than the run, so only a service's group is read.
    """

    try:
        lines = proc.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None, None
    group = next((line[3:] for line in lines if line.startswith("0::")), "")
    if not group.endswith(".service"):
        return None, None
    directory = root / group.lstrip("/")
    return _counter(directory / "memory.peak"), _counter(directory / "memory.swap.peak")


def largest_process() -> int | None:
    """The peak resident memory of the largest process the gate waited for, on POSIX."""

    if sys.platform == "win32":
        return None
    import resource

    peak = resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss
    # Linux counts kibibytes, macOS bytes.
    return int(peak) * (1 if sys.platform == "darwin" else 1024) if peak else None


def memory_peaks() -> MemoryPeaks:
    unit, swap = unit_peaks()
    return MemoryPeaks(unit, swap, largest_process())


def size_text(size: int) -> str:
    gibibytes = size / 2**30
    return f"{gibibytes:.1f} GiB" if gibibytes >= 1 else f"{round(size / 2**20)} MiB"


def memory_text(peaks: MemoryPeaks) -> str:
    parts = []
    if peaks.unit is not None:
        swap = "" if peaks.swap is None else f" and {size_text(peaks.swap)} of swap"
        parts.append(f"peak memory {size_text(peaks.unit)}{swap} for the whole run")
    if peaks.largest is not None:
        parts.append(f"{size_text(peaks.largest)} in its largest process")
    return ", ".join(parts) if parts else "peak memory not measured on this host"


def record_measurement(workspace: Path, document: dict[str, object]) -> None:
    """Append the run's measurement to `MEASUREMENTS` and print it into the tick's journal."""

    line = json.dumps(document)
    print(f"measured: {line}")
    path = workspace / MEASUREMENTS
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as handle:
            handle.write(f"{line}\n")
    except OSError as error:
        print(f"measured: not written to {MEASUREMENTS.as_posix()} ({error})")


def comment_on_slot_issue(workspace: Path, text: str) -> None:
    """Post `text` as a comment on #1093 with `gh` from the checkout; a failure is printed."""

    try:
        completed = subprocess.run(
            ["gh", "issue", "comment", SLOT_ISSUE, "--body-file", "-"],
            cwd=workspace,
            input=text,
            text=True,
            encoding="utf-8",
            errors="replace",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            check=False,
            timeout=120,
        )
        code, said = completed.returncode, completed.stdout.strip()
    except (OSError, subprocess.SubprocessError) as error:
        code, said = 127, str(error)
    if code == 0:
        print(f"#{SLOT_ISSUE}: {said or 'posted'}")
    else:
        print(f"#{SLOT_ISSUE}: the comment was not posted (gh exited {code}): {said}")


def post_once(workspace: Path, name: str, text: str, notify: Notify) -> None:
    """Post the alarm `name` once: its marker is written first, and a held one posts nothing."""

    directory = workspace / SCHEDULE_STATE / "alarms"
    marker = directory / f"{name}.json"
    if marker.exists() or not workspace.is_dir():
        return
    try:
        directory.mkdir(parents=True, exist_ok=True)
        marker.write_text(json.dumps({"text": text}, indent=2) + "\n", encoding="utf-8")
    except OSError as error:
        print(f"alarm {name}: not posted, its marker could not be written ({error})")
        return
    notify(workspace, text)


def public(text: str, workspace: Path) -> str:
    """`text` with the checkout's path and the home folder's taken out, for a public comment.

    A path in the checkout becomes relative to it, as the logs are named in every comment.
    """

    swaps = (
        (f"{workspace}{os.sep}", ""),
        (str(workspace), "the checkout"),
        (str(Path.home()), "~"),
    )
    for path, name in swaps:
        if len(path) > 1:
            text = text.replace(path, name)
    return text


def run_title(decision: Decision) -> str:
    if decision.action == "final":
        return f"the final run for gameweek {decision.gameweek}, with club news"
    if decision.marker.startswith("settled-"):
        return (
            f"the morning run for gameweek {decision.gameweek} that publishes the settled view "
            f"of gameweek {decision.gameweek - 1} in a fixture gap"
        )
    return f"the morning run for gameweek {decision.gameweek}"


def duration_text(seconds: float) -> str:
    hours, minutes = divmod(round(seconds / 60), 60)
    return f"{hours} h {minutes} min" if hours else f"{minutes} min"


def start_text(identity: str, decision: Decision, now: datetime) -> str:
    return (
        f"Weekly run `{identity}` started at {utc_text(now)} on the scheduled host: "
        f"{run_title(decision)}, deadline {utc_text(decision.deadline)}. Until its end line "
        "here, please merge nothing into develop and start no heavy run."
    )


def end_text(
    identity: str, outcome: Outcome, ended: datetime, seconds: float, peaks: MemoryPeaks
) -> str:
    if outcome.code != 0:
        result = f"it stopped at stage `{outcome.stage}`, and the alarm follows"
    elif outcome.released:
        result = "its release is live"
    else:
        result = (
            "its site pull request waits for a preview and a yes before its release (D1 on #1243)"
        )
    return (
        f"Weekly run `{identity}` ended at {utc_text(ended)} with exit {outcome.code}: "
        f"{result}. It took {duration_text(seconds)}; {memory_text(peaks)}. The hold on "
        "develop and heavy runs is lifted."
    )


def alarm_text(subject: str, verb: str, stage: str, detail: str) -> str:
    return (
        f"Alarm: {subject} {verb} at stage `{stage}`. {detail} The last accepted publication "
        "stays live."
    )


def missed_alarm(decision: Decision, season: str, now: datetime, run_hours: float) -> str:
    minutes = math.floor((decision.deadline - now).total_seconds() / 60 + 0.5)
    return alarm_text(
        f"the final run for gameweek {decision.gameweek} "
        f"(`final-{season}-gw{decision.gameweek:02d}`)",
        "was missed",
        "gate",
        f"At {utc_text(now)} the deadline {utc_text(decision.deadline)} was {minutes} min "
        f"away and a run takes about {_hours(run_hours)} h, so no run was started.",
    )


def refused_alarm(now: datetime, reason: str) -> str:
    return alarm_text(
        "the weekly schedule gate",
        "refused",
        "gate",
        f"At {utc_text(now)} it could not decide, so no run could start: {reason} This alarm "
        "is posted once a UTC day while the refusal lasts.",
    )


def outcome_alarm(identity: str, outcome: Outcome) -> str:
    detail = f"Read `{outcome.log}` on the scheduled host before anything is run again."
    if outcome.stage == "release":
        detail = (
            f"Read `{outcome.log}` on the scheduled host: a release that stopped after the "
            "enqueue is reconciled by hand, never run again."
        )
    return alarm_text(f"weekly run `{identity}`", outcome.verb, outcome.stage, detail)


def late_alarm(
    identity: str,
    decision: Decision,
    outcome: Outcome,
    now: datetime,
    ended: datetime,
    run_hours: float,
) -> str:
    """The alarm of a run that ended too late for its budget, or "" for one in time.

    A final run must leave its release by hand its `RELEASE_HOURS` before the deadline, or,
    released in the same tick, be live by it; a morning run must end within `run_hours`, the
    time the gate leaves it before a final run.
    """

    if decision.action == "final" and outcome.released:
        limit, why = decision.deadline, "the deadline"
    elif decision.action == "final":
        limit = decision.deadline - timedelta(hours=RELEASE_HOURS)
        why = (
            f"the last end that leaves its release by hand {_hours(RELEASE_HOURS)} h before "
            f"the deadline {utc_text(decision.deadline)}"
        )
    else:
        limit = now + timedelta(hours=run_hours)
        why = (
            f"{_hours(run_hours)} h after its start, the time the gate leaves a morning run "
            "before a final run"
        )
    if ended <= limit:
        return ""
    return alarm_text(
        f"weekly run `{identity}`",
        "is late",
        "release" if outcome.released else "weekly run",
        f"It ended at {utc_text(ended)}, after {utc_text(limit)}, {why}.",
    )


def stopped_stage(workspace: Path, identity: str) -> str:
    """The first stage the run's journal did not complete, or `weekly run` without a journal."""

    try:
        stages = inspect_run(workspace / WEEKLY_RUNS, identity).get("stages", ())
    except (OSError, WeeklyJournalError):
        return "weekly run"
    for stage in stages:
        if stage.get("status") not in {"completed", "skipped"}:
            return f"weekly run: {stage.get('name')}"
    return "weekly run"


def start_run(
    workspace: Path,
    decision: Decision,
    season: str,
    now: datetime,
    *,
    kind: str,
    workers: int,
    settings: Path | None,
    runner: Runner,
    acquire: Acquire,
    notify: Notify,
    release: Release | None = None,
    run_hours: float = RUN_HOURS,
    clock: Clock = time.monotonic,
    peaks: Peaks = memory_peaks,
) -> int:
    """Start the decided run, measure it, and post its start line, end line and any alarm.

    The marker is written before anything else, so a tick that dies leaves no run to start
    again; the start line follows, so the slot is held before the checkout moves.
    """

    identity = run_id(kind, season, decision.gameweek, now)
    suffix = run_suffix(decision.action, now)
    write_marker(workspace / SCHEDULE_STATE / "started", decision, kind, suffix, now)
    notify(workspace, start_text(identity, decision, now))
    began = clock()
    outcome = run_and_release(
        workspace,
        decision,
        season,
        identity,
        suffix,
        kind=kind,
        workers=workers,
        settings=settings,
        runner=runner,
        acquire=acquire,
        release=release,
    )
    seconds = clock() - began
    ended = now + timedelta(seconds=seconds)
    measured = peaks()
    late = (
        late_alarm(identity, decision, outcome, now, ended, run_hours) if outcome.code == 0 else ""
    )
    record_measurement(
        workspace,
        {
            "run_id": identity,
            "action": decision.action,
            "kind": kind,
            "gameweek": decision.gameweek,
            "deadline_utc": utc_text(decision.deadline),
            "workers": workers,
            "cores": os.cpu_count(),
            "started_at_utc": utc_text(now),
            "ended_at_utc": utc_text(ended),
            "duration_seconds": round(seconds),
            "exit_code": outcome.code,
            "stage": outcome.stage,
            "late": bool(late),
            "memory_peak_bytes": measured.unit,
            "swap_peak_bytes": measured.swap,
            "largest_process_bytes": measured.largest,
        },
    )
    notify(workspace, end_text(identity, outcome, ended, seconds, measured))
    if outcome.code != 0:
        notify(workspace, outcome_alarm(identity, outcome))
    elif late:
        notify(workspace, late)
    return outcome.code


def run_and_release(
    workspace: Path,
    decision: Decision,
    season: str,
    identity: str,
    suffix: str,
    *,
    kind: str,
    workers: int,
    settings: Path | None,
    runner: Runner,
    acquire: Acquire,
    release: Release | None,
) -> Outcome:
    """The checkout, the club news, the weekly command and, with a `release`, its release.

    `release` is the one place the release chain of #1249 (#1243, step 3) is called, with the
    run id, after a weekly command that exited 0: `main` passes `weekly_release.release_run`
    with ``--release`` and `None`, so no release, without it (D1).
    """

    log = workspace / WEEKLY_LOGS / f"{identity}.log"
    news_log = log.with_name(f"{identity}.club-news.log")
    relative = (WEEKLY_LOGS / log.name).as_posix()
    # The weekly command refuses a revision that is not the fresh origin/develop, so a
    # checkout left behind would never publish: weekly_run.ps1 fast-forwards it first too.
    if runner(["git", "pull", "-q", "--ff-only"], workspace, log) != 0:
        print(f"Refused: the checkout did not fast-forward; read {log}")
        return Outcome(2, "checkout", "was refused (exit 2)", relative)
    try:
        capture = (
            acquire_club_news(workspace, settings, news_log, acquire) if kind == "friday" else ""
        )
        arguments = weekly_arguments(
            kind, season, decision.gameweek, workers, identity, suffix, capture
        )
    except ScheduleError as error:
        print(f"Refused: {error}")
        print(f"club-news log: {news_log}")
        news = (WEEKLY_LOGS / news_log.name).as_posix()
        return Outcome(2, "club news", "was refused (exit 2)", news)
    if capture:
        print(f"club news: capture {capture}")
        print(f"club-news log: {news_log}")
    command = [sys.executable, *arguments]
    print(f"starting: {' '.join(command)}")
    print(f"log: {log}")
    code = runner(command, workspace, log)
    if code != 0:
        return Outcome(code, stopped_stage(workspace, identity), f"failed (exit {code})", relative)
    if release is None:
        return Outcome(0)
    code = release(workspace, identity)
    if code != 0:
        released_log = (WEEKLY_LOGS / f"{identity}.release.log").as_posix()
        return Outcome(code, "release", f"stopped (exit {code})", released_log, released=True)
    return Outcome(0, released=True)


def _instant(text: str) -> datetime:
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise argparse.ArgumentTypeError(f"{text!r} names no UTC offset, as in ...T07:05:00Z")
    return parsed.astimezone(UTC)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--workspace", type=Path, default=Path.cwd())
    parser.add_argument(
        "--bootstrap", type=Path, help="a bootstrap-static document to read instead of the FPL API"
    )
    parser.add_argument("--now", type=_instant, help="the gate's clock, a UTC instant")
    parser.add_argument("--morning-utc", default=MORNING_UTC)
    parser.add_argument("--final-lead-hours", type=float, default=FINAL_LEAD_HOURS)
    parser.add_argument("--run-hours", type=float, default=RUN_HOURS)
    parser.add_argument(
        "--lead-window-days",
        type=float,
        default=LEAD_WINDOW_DAYS,
        help="inside a fixture gap, morning runs wait until the deadline is this close (D4)",
    )
    parser.add_argument("--morning-kind", choices=("tuesday", "friday"), default=MORNING_KIND)
    parser.add_argument("--workers", type=int, default=WORKERS)
    parser.add_argument(
        "--club-news-settings",
        type=Path,
        help=f"private club-news settings (or ${SETTINGS_VARIABLE})",
    )
    parser.add_argument(
        "--release",
        action="store_true",
        help=(
            "release a run that exits 0 in the same tick, with no person; off, as D1 on #1243 "
            "keeps it: a run is released after its preview and a yes, by weekly_release"
        ),
    )
    parser.add_argument("--dry-run", action="store_true", help="print the decision, write nothing")
    return parser


def main(
    argv: list[str] | None = None,
    *,
    runner: Runner = run_logged,
    acquire: Acquire = club_news_acquire.main,
    read_bootstrap: Callable[[], bytes] = fpl_bootstrap,
    release: Release = weekly_release.release_run,
    notify: Notify = comment_on_slot_issue,
    clock: Clock = time.monotonic,
    peaks: Peaks = memory_peaks,
) -> int:
    """Decide this tick and start its run, and release the run only with ``--release``.

    `runner`, `acquire`, `read_bootstrap`, `release`, `notify`, `clock` and `peaks` are seams.
    """

    arguments = build_parser().parse_args(argv)
    workspace = arguments.workspace.resolve()
    now: datetime = arguments.now or datetime.now(UTC)
    state = workspace / SCHEDULE_STATE
    try:
        season = published_season(workspace)
        if arguments.bootstrap is not None:
            bootstrap = arguments.bootstrap.read_bytes()
        elif arguments.dry_run:
            bootstrap = read_bootstrap()  # held in memory: a dry run writes nothing
        else:
            bootstrap = cached_bootstrap(state / "bootstrap.json", now, read_bootstrap)
        decision = decide(
            schedule_events(bootstrap),
            now,
            season,
            started_markers(state / "started"),
            settled=scored_gameweeks(bootstrap),
            morning_utc=arguments.morning_utc,
            lead_hours=arguments.final_lead_hours,
            run_hours=arguments.run_hours,
            window_days=arguments.lead_window_days,
        )
    except (DataError, OSError, ValueError) as error:
        print(f"Refused: {error}")
        if not arguments.dry_run:
            reason = public(str(error), workspace)
            post_once(workspace, f"refused-{now:%Y-%m-%d}", refused_alarm(now, reason), notify)
        return 2

    print(
        f"gate at {utc_text(now)}: {season} gameweek {decision.gameweek}, deadline "
        f"{utc_text(decision.deadline)}, final run from {utc_text(decision.final_start)}"
    )
    print(f"decision: {decision.action} ({decision.reason})")
    if decision.action == "missed":
        if not arguments.dry_run:
            alarm = missed_alarm(decision, season, now, arguments.run_hours)
            post_once(workspace, f"missed-{season}-gw{decision.gameweek:02d}", alarm, notify)
        return 3
    if decision.action == "none":
        return 0
    kind = run_kind(decision.action, arguments.morning_kind)
    if arguments.dry_run:
        identity = run_id(kind, season, decision.gameweek, now)
        preview = weekly_arguments(
            kind,
            season,
            decision.gameweek,
            arguments.workers,
            identity,
            run_suffix(decision.action, now),
            "<club-news capture>" if kind == "friday" else "",
        )
        print(f"would run: {sys.executable} {' '.join(preview)}")
        if arguments.release:
            print(f"would release {identity} once it exits 0, with {weekly_release.__name__}")
        return 0
    settings = arguments.club_news_settings or os.environ.get(SETTINGS_VARIABLE)
    return start_run(
        workspace,
        decision,
        season,
        now,
        kind=kind,
        workers=arguments.workers,
        settings=Path(settings) if settings else None,
        runner=runner,
        acquire=acquire,
        notify=notify,
        release=release if arguments.release else None,
        run_hours=arguments.run_hours,
        clock=clock,
        peaks=peaks,
    )


if __name__ == "__main__":
    raise SystemExit(main())
