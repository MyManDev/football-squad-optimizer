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
  before a morning run could finish.

Deadlines decide, not weekdays, so a midweek deadline needs no exception. A start leaves its
marker (``started/morning-<date>.json`` or ``started/final-<season>-gw<NN>.json``) before
anything runs, so a run that fails is not started again by the next tick, and each run
publishes under its own site suffix (``morning-<stamp>`` or ``final-<stamp>``). A Friday-kind
run, which the final run always is, first acquires the week's club news in this process.

``--release``, off by default, releases a run the gate started once its weekly command exits
0, with ``weekly_release.release_run`` (#1249 in Python): D1 on #1243, decided on 2026-10-28,
lets that release run with no person. Without it a run ends at its site pull request.

``--dry-run`` prints the decision and the command it would run, and writes nothing. The exit
code is 0 for a decision (starting nothing is one), the weekly command's own when one ran
(with ``--release``, the release's after a run that exited 0), 3 when the final run's window
was missed, and 2 for a refusal before the weekly command ran.
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
from collections.abc import Callable, Collection, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Final, Literal

from squadopt.contracts.run_logs import LOG_ROOT_NAME
from squadopt.data.atomic import replace_retrying
from squadopt.data.errors import DataError
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, gameweek_deadlines
from squadopt.data.timestamps import as_instant
from squadopt.platform import club_news_acquire, weekly_release
from squadopt.platform.fpl_capture import ENDPOINTS, fetch

#: The defaults #1243 proposes, its decision D2: a morning run from 02:00 UTC, the final run
#: 4 h before the deadline, and 3.5 h for a run from capture to live (GW8 took 3 h 34 min).
MORNING_UTC: Final = "02:00"
FINAL_LEAD_HOURS: Final = 4.0
RUN_HOURS: Final = 3.5
#: D3 on #1243: club news on every run, so a morning run is a Friday-kind run as well.
MORNING_KIND: Final = "friday"
#: `weekly_run.ps1`'s default.
WORKERS: Final = 15

SCHEDULE_STATE: Final = Path("data/runtime/weekly-schedule")
WEEKLY_LOGS: Final = LOG_ROOT_NAME / "weekly"
FIXTURES: Final = Path("web/public/data/fixtures.json")
BOOTSTRAP_MAX_AGE: Final = timedelta(hours=1)
SETTINGS_VARIABLE: Final = "SQUADOPT_CLUB_NEWS_SETTINGS"

Action = Literal["morning", "final", "missed", "none"]
#: Runs one command (its arguments, working directory and log) and answers its exit code.
Runner = Callable[[Sequence[str], Path, Path], int]
#: The club-news command's `main`: its arguments in, its exit code out, its lines printed.
Acquire = Callable[[list[str]], int]
#: Releases a completed run by its id (#1249), answering the release's exit code.
Release = Callable[[Path, str], int]


class ScheduleError(ValueError):
    """A refusal: the gate starts nothing further and exits 2."""


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


def decide(
    events: Sequence[tuple[int, datetime]],
    now: datetime,
    season: str,
    markers: Collection[str],
    *,
    morning_utc: str = MORNING_UTC,
    lead_hours: float = FINAL_LEAD_HOURS,
    run_hours: float = RUN_HOURS,
) -> Decision:
    """Pure: the action of this tick, from the deadlines, the clock and the runs started."""

    if lead_hours < run_hours:
        raise ScheduleError(
            f"A final run {_hours(lead_hours)} h before the deadline cannot be live before it: "
            f"a run takes about {_hours(run_hours)} h."
        )
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
    if morning in markers:
        return chosen("none", "today's morning run has already started")
    if final_start - now < run:
        return chosen(
            "none",
            f"the final run starts at {utc_text(final_start)}, before a morning run could finish",
        )
    return chosen("morning", f"today's morning run for gameweek {gameweek}", morning)


def run_kind(action: Action, morning_kind: str = MORNING_KIND) -> str:
    """The final run is the decision run with real club news; D3 on #1243 sets the morning's."""

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
    """The bootstrap, read again once the held copy is an hour old: deadlines move rarely."""

    if cache.is_file():
        held = datetime.fromtimestamp(cache.stat().st_mtime, UTC)
        if now - held < BOOTSTRAP_MAX_AGE:
            return cache.read_bytes()
    payload = read()
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
    release: Release | None = None,
) -> int:
    """Start the decided run: its marker, the checkout, the club news, the weekly command.

    `release` is the one place the release chain of #1249 (#1243, step 3) is called, with the
    run id, after a weekly command that exited 0: `main` passes `weekly_release.release_run`
    with ``--release`` and `None`, so no release, without it.
    """

    identity = run_id(kind, season, decision.gameweek, now)
    suffix = run_suffix(decision.action, now)
    log = workspace / WEEKLY_LOGS / f"{identity}.log"
    news_log = log.with_name(f"{identity}.club-news.log")
    write_marker(workspace / SCHEDULE_STATE / "started", decision, kind, suffix, now)
    # The weekly command refuses a revision that is not the fresh origin/develop, so a
    # checkout left behind would never publish: weekly_run.ps1 fast-forwards it first too.
    if runner(["git", "pull", "-q", "--ff-only"], workspace, log) != 0:
        print(f"Refused: the checkout did not fast-forward; read {log}")
        return 2
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
        return 2
    if capture:
        print(f"club news: capture {capture}")
        print(f"club-news log: {news_log}")
    command = [sys.executable, *arguments]
    print(f"starting: {' '.join(command)}")
    print(f"log: {log}")
    code = runner(command, workspace, log)
    if code != 0 or release is None:
        return code
    return release(workspace, identity)


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
        help="release a run that exits 0, with no person (#1243 D1); off by default",
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
) -> int:
    """Decide this tick and start its run, and release the run only with ``--release``.

    `runner`, `acquire`, `read_bootstrap` and `release` are seams.
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
            morning_utc=arguments.morning_utc,
            lead_hours=arguments.final_lead_hours,
            run_hours=arguments.run_hours,
        )
    except (DataError, OSError, ValueError) as error:
        print(f"Refused: {error}")
        return 2

    print(
        f"gate at {utc_text(now)}: {season} gameweek {decision.gameweek}, deadline "
        f"{utc_text(decision.deadline)}, final run from {utc_text(decision.final_start)}"
    )
    print(f"decision: {decision.action} ({decision.reason})")
    if decision.action == "missed":
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
        release=release if arguments.release else None,
    )


if __name__ == "__main__":
    raise SystemExit(main())
