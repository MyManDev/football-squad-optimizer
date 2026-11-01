"""`squadopt.platform.weekly_schedule` decides on a schedule whether a weekly run starts (#1243).

The decision table, the missed window, the refusals, the markers and the suffixes of the
PowerShell gate's tests (#1244), run on the Python gate with no PowerShell. `main` runs on a
synthetic workspace and bootstrap with a fake runner, a fake club-news entry and a fake release,
so nothing here reads the network, runs git, starts a weekly run or releases one. The systemd
units that tick the gate on a Linux host (`deploy/weekly-schedule/`) are read as text.
"""

from __future__ import annotations

import inspect
import itertools
import json
import subprocess
from collections.abc import Collection, Sequence
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from squadopt.data.errors import DataSourceError
from squadopt.platform import weekly_release
from squadopt.platform import weekly_schedule as gate
from squadopt.platform.weekly_journal import WeeklyRun, WeeklyStageResult
from squadopt.platform.weekly_publish import WEEKLY_RUNS, PublishNames

DEADLINES = {9: "2026-10-31T11:00:00Z", 10: "2026-11-06T18:30:00Z"}
HOST_FILES = Path(__file__).resolve().parents[2] / "deploy" / "weekly-schedule"


def _bootstrap(deadlines: dict[int, str], settled: Collection[int] = ()) -> bytes:
    # The bootstrap's shape, with fields the gate does not read beside the ones it does.
    events = [
        {
            "id": week,
            "deadline_time": deadline,
            "finished": week in settled,
            "data_checked": week in settled,
        }
        for week, deadline in sorted(deadlines.items(), reverse=True)
    ]
    return json.dumps({"events": events, "teams": []}).encode()


def _decide(now: str, markers: list[str], lead: float = 4.0) -> list[str]:
    events = gate.schedule_events(_bootstrap(DEADLINES))
    decision = gate.decide(events, datetime.fromisoformat(now), "2026-27", markers, lead_hours=lead)
    return [decision.action, str(decision.gameweek), decision.marker, decision.reason]


MORNING_30, MORNING_31, FINAL_9 = "morning-2026-10-30", "morning-2026-10-31", "final-2026-27-gw09"


@pytest.mark.parametrize(
    "now,markers,expected,reason",
    [
        ("2026-10-30T01:59Z", [], "none 9", "today's morning run starts at 2026-10-30T02:00Z"),
        ("2026-10-30T02:00Z", [], f"morning 9 {MORNING_30}", "today's morning run for gameweek 9"),
        ("2026-10-30T09:00Z", [MORNING_30], "none 9", "today's morning run has already started"),
        (
            "2026-10-30T09:00Z",
            ["morning-2026-10-29"],
            f"morning 9 {MORNING_30}",
            "today's morning run for gameweek 9",
        ),
        ("2026-10-31T02:00Z", [], f"morning 9 {MORNING_31}", "today's morning run for gameweek 9"),
        (
            "2026-10-31T04:00Z",
            [],
            "none 9",
            "the final run starts at 2026-10-31T07:00Z, before a morning run could finish",
        ),
        ("2026-10-31T07:00Z", [MORNING_31], f"final 9 {FINAL_9}", "the final run for gameweek 9"),
        (
            "2026-10-31T07:15Z",
            [MORNING_31, FINAL_9],
            "none 9",
            "the final run for gameweek 9 has already started",
        ),
        (
            "2026-10-31T11:00:01Z",
            [MORNING_31, FINAL_9],
            "none 10",
            "today's morning run has already started",
        ),
        (
            "2026-11-01T02:00Z",
            [MORNING_31, FINAL_9],
            "morning 10 morning-2026-11-01",
            "today's morning run for gameweek 10",
        ),
    ],
)
def test_the_gate_chooses_one_run_per_morning_and_one_final_run_per_gameweek(
    now: str, markers: list[str], expected: str, reason: str
) -> None:
    action, gameweek, marker, said = _decide(now, markers)
    assert (" ".join((action, gameweek, marker)).strip(), said) == (expected, reason)


#: The real fixture gap of 2026-27: GW5 closed on Friday 18 September, GW6 on Saturday 10
#: October, 22 days later.
GAP = {5: "2026-09-18T17:30:00Z", 6: "2026-10-10T10:00:00Z", 7: "2026-10-17T10:00:00Z"}
SETTLED_5, MORNING_18 = "settled-2026-27-gw05", "morning-2026-09-18"
IN_GAP = "a fixture gap: gameweek 6's deadline is more than 9 days away; gameweek 5's settled view"
RESUME = "morning runs resume at 2026-10-02T02:00Z"


@pytest.mark.parametrize(
    "now,settled,markers,expected,reason",
    [
        (
            "2026-09-18T02:00Z",
            False,
            [],
            f"morning 5 {MORNING_18}",
            "today's morning run for gameweek 5",
        ),
        (
            "2026-09-19T02:00Z",
            False,
            [MORNING_18],
            "none 6",
            f"{IN_GAP} waits for it to settle, and {RESUME}",
        ),
        (
            "2026-09-22T02:00Z",
            False,
            [MORNING_18],
            "none 6",
            f"{IN_GAP} waits for it to settle, and {RESUME}",
        ),
        (
            "2026-09-22T09:00Z",
            True,
            [MORNING_18],
            f"morning 6 {SETTLED_5}",
            "the settled view of gameweek 5, once in the fixture gap before gameweek 6",
        ),
        (
            "2026-09-22T09:15Z",
            True,
            [MORNING_18, SETTLED_5],
            "none 6",
            f"{IN_GAP} has already started, and {RESUME}",
        ),
        # Judged at the morning time: at 23:59 the deadline is 8.4 days away, at 02:00 9.3.
        (
            "2026-10-01T23:59Z",
            True,
            [SETTLED_5],
            "none 6",
            f"{IN_GAP} has already started, and {RESUME}",
        ),
        (
            "2026-10-02T02:00Z",
            True,
            [SETTLED_5],
            "morning 6 morning-2026-10-02",
            "today's morning run for gameweek 6",
        ),
        # Once the window holds the deadline the flags no longer matter.
        (
            "2026-10-03T02:00Z",
            False,
            [],
            "morning 6 morning-2026-10-03",
            "today's morning run for gameweek 6",
        ),
        (
            "2026-10-10T06:00Z",
            True,
            [SETTLED_5],
            "final 6 final-2026-27-gw06",
            "the final run for gameweek 6",
        ),
    ],
)
def test_inside_a_fixture_gap_the_settled_view_is_published_once_and_mornings_wait(
    now: str, settled: bool, markers: list[str], expected: str, reason: str
) -> None:
    events = gate.schedule_events(_bootstrap(GAP))
    decision = gate.decide(
        events, datetime.fromisoformat(now), "2026-27", markers, settled={5} if settled else set()
    )
    assert gate.LEAD_WINDOW_DAYS == 9
    assert (
        " ".join((decision.action, str(decision.gameweek), decision.marker)).strip(),
        decision.reason,
    ) == (expected, reason)


def test_every_tick_across_the_gw5_to_gw6_gap_starts_one_settled_view_and_then_the_week() -> None:
    """Every 15 minutes from GW5's deadline to GW6's, with GW5 settled on 22 September."""

    events = gate.schedule_events(_bootstrap(GAP))
    settled_at = datetime.fromisoformat("2026-09-22T08:00:00Z")
    now, end = datetime.fromisoformat("2026-09-18T17:45:00Z"), datetime.fromisoformat(GAP[6])
    markers: list[str] = []
    started: list[str] = []
    while now < end:
        decision = gate.decide(
            events, now, "2026-27", markers, settled={5} if now >= settled_at else set()
        )
        if decision.action in {"morning", "final"}:
            markers.append(decision.marker)
            started.append(f"{gate.utc_text(now)} {decision.marker}")
        now += timedelta(minutes=15)
    mornings = [f"2026-10-{day:02d}T02:00Z morning-2026-10-{day:02d}" for day in range(2, 11)]
    assert started == [
        f"2026-09-22T08:00Z {SETTLED_5}",
        *mornings,
        "2026-10-10T06:00Z final-2026-27-gw06",
    ]


def test_a_gap_before_the_first_gameweek_waits_and_the_window_is_an_option() -> None:
    events = gate.schedule_events(_bootstrap({1: "2026-08-21T17:30:00Z"}))
    decision = gate.decide(events, datetime.fromisoformat("2026-08-01T02:00:00Z"), "2026-27", [])
    assert (decision.action, decision.reason) == (
        "none",
        "a fixture gap: gameweek 1's deadline is more than 9 days away; morning runs resume at "
        "2026-08-13T02:00Z",
    )
    events = gate.schedule_events(_bootstrap(GAP))
    wide = gate.decide(
        events, datetime.fromisoformat("2026-09-25T02:00:00Z"), "2026-27", [], window_days=22
    )
    assert (wide.action, wide.marker) == ("morning", "morning-2026-09-25")
    assert gate.build_parser().parse_args([]).lead_window_days == gate.LEAD_WINDOW_DAYS
    with pytest.raises(gate.ScheduleError) as refused:
        gate.decide(events, datetime.fromisoformat(GAP[5]), "2026-27", [], window_days=0)
    assert str(refused.value) == "--lead-window-days must be above 0, not 0."


def test_a_final_window_the_gate_missed_is_reported_not_started() -> None:
    assert _decide("2026-10-31T07:31:00Z", []) == [
        "missed",
        "9",
        "",
        "the final run for gameweek 9 did not start: the deadline is 209 min away and a run "
        "takes about 3.5 h",
    ]


def test_a_lead_shorter_than_a_run_and_a_season_with_no_deadline_ahead_refuse() -> None:
    with pytest.raises(gate.ScheduleError) as short:
        _decide("2026-10-30T02:00:00Z", [], lead=3)
    assert str(short.value) == (
        "A final run 3 h before the deadline cannot be live before it: a run takes about 3.5 h."
    )
    events = gate.schedule_events(_bootstrap({38: "2027-05-23T15:00:00Z"}))
    with pytest.raises(gate.ScheduleError) as over:
        gate.decide(events, datetime.fromisoformat("2027-06-01T00:00:00Z"), "2026-27", [])
    assert (
        str(over.value) == "No gameweek deadline lies ahead of 2027-06-01T00:00Z in the bootstrap."
    )


@pytest.mark.parametrize("morning", ["2:00", "24:00", "02:60", "0200"])
def test_the_morning_time_must_be_hh_mm(morning: str) -> None:
    with pytest.raises(gate.ScheduleError) as refused:
        gate.morning_start(datetime.fromisoformat("2026-10-30T00:00:00Z"), morning)
    assert str(refused.value) == f"--morning-utc must be HH:MM in UTC, not '{morning}'."


def test_events_are_read_in_gameweek_order_with_utc_deadlines() -> None:
    events = gate.schedule_events(_bootstrap(DEADLINES))
    assert [(week, gate.utc_text(deadline)) for week, deadline in events] == [
        (9, "2026-10-31T11:00Z"),
        (10, "2026-11-06T18:30Z"),
    ]
    assert all(deadline.utcoffset() is not None for _, deadline in events)


def test_the_markers_are_the_runs_already_started(tmp_path: Path) -> None:
    started = tmp_path / "started"
    assert gate.started_markers(started) == frozenset()
    started.mkdir()
    for name in ("morning-2026-10-30.json", "final-2026-27-gw09.json", "notes.txt"):
        (started / name).write_text("{}", encoding="utf-8")
    assert gate.started_markers(started) == {"final-2026-27-gw09", "morning-2026-10-30"}


def test_each_run_gets_its_own_suffix_that_the_publisher_accepts() -> None:
    assert (gate.run_kind("final", "tuesday"), gate.run_kind("morning", "tuesday")) == (
        "friday",
        "tuesday",
    )
    suffixes = [
        gate.run_suffix("final", datetime.fromisoformat("2026-10-31T07:00:00Z")),
        gate.run_suffix("morning", datetime.fromisoformat("2026-10-31T02:00:00Z")),
    ]
    assert suffixes == ["final-20261031T0700", "morning-20261031T0200"]
    assert {PublishNames("2026-27", 9, "decision", suffix).branch for suffix in suffixes} == {
        "feature/gw09-decision-site-final-20261031T0700",
        "feature/gw09-decision-site-morning-20261031T0200",
    }


def test_the_weekly_arguments_are_weekly_run_s_and_friday_refuses_the_fixture() -> None:
    assert " ".join(gate.weekly_arguments("friday", "2026-27", 7, 15, "rid", "s", "news")) == (
        "-m squadopt.platform.weekly_operations --season 2026-27 --gameweek 7 "
        "--league-list config/leagues.json --workers 15 --projection component-only "
        "--rotation --rotation-capture news --record-advice --publish "
        "--publish-suffix s --run-id rid"
    )
    assert "--rotation-capture" not in gate.weekly_arguments("tuesday", "2026-27", 7, 15, "r", "s")
    with pytest.raises(gate.ScheduleError, match="requires a real club-news capture"):
        gate.weekly_arguments("friday", "2026-27", 7, 15, "rid", "s")


class _Host:
    """The runner, the club-news entry and the #1093 comments, recorded: nothing runs.

    The clock answers 0 when a run starts and `minutes` later when it ends.
    """

    def __init__(
        self,
        news_exit: int = 0,
        weekly_exit: int = 0,
        *,
        pull_exit: int = 0,
        release_exit: int = 7,
        minutes: float = 104,
        journal: bool = False,
    ) -> None:
        self.commands: list[list[str]] = []
        self.news: list[list[str]] = []
        self.released: list[str] = []
        self.posted: list[str] = []
        self.news_exit = news_exit
        self.weekly_exit = weekly_exit
        self.pull_exit = pull_exit
        self.release_exit = release_exit
        self.journal = journal
        self.ticks = itertools.cycle([0.0, minutes * 60])

    def runner(self, arguments: Sequence[str], cwd: Path, log: Path) -> int:
        self.commands.append(list(arguments))
        if "squadopt.platform.weekly_operations" not in arguments:
            return self.pull_exit
        if self.journal:
            _failed_journal(cwd, arguments[arguments.index("--run-id") + 1])
        return self.weekly_exit

    def notify(self, workspace: Path, text: str) -> None:
        self.posted.append(text)

    def clock(self) -> float:
        return next(self.ticks)

    def release(self, workspace: Path, run_id: str) -> int:
        self.released.append(run_id)
        return self.release_exit

    def acquire(self, arguments: list[str]) -> int:
        self.news.append(arguments)
        print("Capture       club-news-held")
        return 0 if "--check-config" in arguments else self.news_exit


def _workspace(tmp_path: Path) -> Path:
    published = tmp_path / "web" / "public" / "data"
    published.mkdir(parents=True)
    (published / "fixtures.json").write_text(
        json.dumps({"contract_version": "fixtures_v1", "payload": {"season": "2026-27"}}),
        encoding="utf-8",
    )
    (tmp_path / "bootstrap.json").write_bytes(_bootstrap(DEADLINES))
    return tmp_path


def _main(workspace: Path, now: str, host: _Host, *extra: str) -> int:
    arguments = ["--workspace", str(workspace), "--bootstrap", str(workspace / "bootstrap.json")]
    return gate.main(
        [*arguments, "--now", now, *extra],
        runner=host.runner,
        acquire=host.acquire,
        read_bootstrap=lambda: pytest.fail("the network was read"),
        release=host.release,
        notify=host.notify,
        clock=host.clock,
    )


def _failed_journal(workspace: Path, run_id: str) -> None:
    """What a weekly command leaves when its league stage fails: a journal that says so."""

    run = WeeklyRun(workspace / WEEKLY_RUNS, run_id, {"request": {}}, ["capture", "league"])
    captured = workspace / "captured.txt"
    captured.write_text("capture", encoding="utf-8")

    def fails() -> WeeklyStageResult:
        raise RuntimeError("the solver stopped")

    with run.hold():
        run.stage("capture", inputs=[], operation=lambda: WeeklyStageResult((captured,)))
        with pytest.raises(RuntimeError):
            run.stage("league", inputs=[], operation=fails)


def test_a_dry_run_prints_the_run_it_would_start_and_writes_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    host = _Host()
    assert _main(_workspace(tmp_path), "2026-10-31T07:05:00Z", host, "--dry-run") == 0
    gate_line, decision, would = capsys.readouterr().out.splitlines()
    assert gate_line == (
        "gate at 2026-10-31T07:05Z: 2026-27 gameweek 9, deadline 2026-10-31T11:00Z, "
        "final run from 2026-10-31T07:00Z"
    )
    assert decision == "decision: final (the final run for gameweek 9)"
    assert would.startswith("would run: ")
    assert would.endswith(
        "--rotation-capture <club-news capture> --record-advice --publish "
        "--publish-suffix final-20261031T0705 --run-id 2026-27-gw09-friday-20261031T0705Z"
    )
    assert (host.commands, host.news) == ([], [])
    assert not (tmp_path / "data").exists()


def test_a_dry_run_exits_three_for_a_missed_window_and_two_for_a_short_lead(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = _workspace(tmp_path)
    assert _main(workspace, "2026-10-31T08:00:00Z", _Host(), "--dry-run") == 3
    assert "decision: missed (the final run for gameweek 9 did not start" in capsys.readouterr().out
    assert not (tmp_path / "data").exists()
    host = _Host()
    assert _main(workspace, "2026-10-30T02:00:00Z", host, "--final-lead-hours", "3") == 2
    assert capsys.readouterr().out.strip() == (
        "Refused: A final run 3 h before the deadline cannot be live before it: "
        "a run takes about 3.5 h."
    )
    # A refusal writes nothing but the marker of its one alarm that day.
    alarms = workspace / gate.SCHEDULE_STATE / "alarms"
    assert [path.name for path in (tmp_path / "data").rglob("*") if path.is_file()] == [
        "refused-2026-10-30.json"
    ]
    assert alarms.is_dir() and len(host.posted) == 1


def test_a_start_leaves_its_marker_acquires_news_and_runs_the_weekly_command_once(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    for capture in ("fpl-live-20261030", "fpl-live-20261031"):
        (workspace / "data" / "snapshots" / capture).mkdir(parents=True)
    host = _Host()
    assert _main(workspace, "2026-10-31T07:05:00Z", host) == 0

    marker = workspace / gate.SCHEDULE_STATE / "started" / "final-2026-27-gw09.json"
    assert json.loads(marker.read_text(encoding="utf-8")) == {
        "action": "final",
        "gameweek": 9,
        "deadline_utc": "2026-10-31T11:00Z",
        "kind": "friday",
        "suffix": "final-20261031T0705",
        "started_at_utc": "2026-10-31T07:05Z",
    }
    assert host.news[0] == ["--check-config"]
    assert host.news[1][:2] == ["--roster-snapshot", "fpl-live-20261031"]
    pull, weekly = host.commands
    assert pull == ["git", "pull", "-q", "--ff-only"]
    assert weekly[1:3] == ["-m", "squadopt.platform.weekly_operations"]
    assert "--rotation-capture club-news-held" in " ".join(weekly)
    news_log = workspace / gate.WEEKLY_LOGS / "2026-27-gw09-friday-20261031T0705Z.club-news.log"
    assert "Capture       club-news-held" in news_log.read_text(encoding="utf-8")

    # The next tick finds the marker and starts nothing.
    assert _main(workspace, "2026-10-31T07:20:00Z", host) == 0
    assert len(host.commands) == 2


def test_a_morning_run_takes_no_club_news_and_only_the_final_run_does(tmp_path: Path) -> None:
    # D3 on #1243: the gate's morning kind is tuesday, so a morning run makes no model call.
    assert (gate.MORNING_KIND, gate.build_parser().parse_args([]).morning_kind) == (
        "tuesday",
        "tuesday",
    )
    workspace = _workspace(tmp_path)
    (workspace / "data" / "snapshots" / "fpl-live-20261030").mkdir(parents=True)
    host = _Host()
    assert _main(workspace, "2026-10-30T02:00:00Z", host) == 0
    assert host.news == []
    _, weekly = host.commands
    assert "--rotation-capture" not in weekly
    assert weekly[-2:] == ["--run-id", "2026-27-gw09-tuesday-20261030T0200Z"]
    assert _main(workspace, "2026-10-31T07:05:00Z", host) == 0
    assert [arguments[0] for arguments in host.news] == ["--check-config", "--roster-snapshot"]


def test_the_gate_reads_the_settled_week_from_the_bootstrap_and_starts_its_view_once(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "bootstrap.json").write_bytes(_bootstrap(GAP, settled={4, 5}))
    host = _Host()
    assert _main(workspace, "2026-09-22T09:00:00Z", host) == 0
    marker = workspace / gate.SCHEDULE_STATE / "started" / f"{SETTLED_5}.json"
    assert json.loads(marker.read_text(encoding="utf-8"))["kind"] == "tuesday"
    (_, weekly), news = host.commands, host.news
    assert (weekly[weekly.index("--gameweek") + 1], news) == ("6", [])
    assert _main(workspace, "2026-09-23T02:00:00Z", host) == 0
    assert len(host.commands) == 2


def test_a_failed_acquisition_refuses_before_the_weekly_command(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "data" / "snapshots" / "fpl-live-20261031").mkdir(parents=True)
    host = _Host(news_exit=1)
    assert _main(workspace, "2026-10-31T07:05:00Z", host) == 2
    assert host.commands == [["git", "pull", "-q", "--ff-only"]]


@pytest.mark.parametrize(
    "switch,run_exit,released,exit_code",
    [(False, 0, False, 0), (False, 1, False, 1), (True, 1, False, 1), (True, 0, True, 7)],
)
def test_the_gate_releases_only_with_the_switch_and_only_a_run_that_exited_0(
    tmp_path: Path, switch: bool, run_exit: int, released: bool, exit_code: int
) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "data" / "snapshots" / "fpl-live-20261031").mkdir(parents=True)
    host = _Host(weekly_exit=run_exit)
    extra = ["--release"] if switch else []
    assert _main(workspace, "2026-10-31T07:05:00Z", host, *extra) == exit_code
    assert len(host.commands) == 2
    assert host.released == (["2026-27-gw09-friday-20261031T0705Z"] if released else [])


def test_the_switch_passes_the_ported_chain_and_is_off_by_default() -> None:
    seam = inspect.signature(gate.main).parameters["release"]
    assert seam.default is weekly_release.release_run
    assert gate.build_parser().parse_args([]).release is False


def test_a_dry_run_names_the_release_only_with_the_switch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    workspace = _workspace(tmp_path)
    assert _main(workspace, "2026-10-31T07:05:00Z", _Host(), "--dry-run") == 0
    plain = capsys.readouterr().out.splitlines()
    host = _Host()
    assert _main(workspace, "2026-10-31T07:05:00Z", host, "--dry-run", "--release") == 0
    switched = capsys.readouterr().out.splitlines()
    assert (switched[:3], len(plain), host.released) == (plain, 3, [])
    assert switched[3:] == [
        "would release 2026-27-gw09-friday-20261031T0705Z once it exits 0, with "
        "squadopt.platform.weekly_release"
    ]
    assert not (tmp_path / "data").exists()


def _directives(path: Path) -> list[tuple[str, str]]:
    lines = path.read_text(encoding="utf-8").splitlines()
    pairs = [line.split("=", 1) for line in lines if "=" in line and not line.startswith("#")]
    return [(key.strip(), value.strip()) for key, value in pairs]


def test_the_host_units_tick_the_gate_by_its_module_on_a_workspace() -> None:
    service = _directives(HOST_FILES / "weekly-schedule.service")
    timer = _directives(HOST_FILES / "weekly-schedule.timer")
    dry_run = _directives(HOST_FILES / "dry-run.conf")
    workspaces = set()
    for unit, dry in ((service, False), (dry_run, True)):
        (command,) = [value for key, value in unit if key == "ExecStart" and value]
        arguments = command.split()
        assert arguments[1:3] == ["-m", "squadopt.platform.weekly_schedule"], command
        workspace = arguments[arguments.index("--workspace") + 1]
        assert arguments[0] == f"{workspace}/.venv/bin/python"
        # D1 on #1243: no tick releases; a run is released by hand after its preview.
        assert ("--release" in arguments, "--dry-run" in arguments) == (False, dry), command
        workspaces.add(workspace)
    (workspace,) = workspaces
    # The drop-in clears the unit's command before it gives its own.
    assert [key for key, _ in dry_run] == ["ExecStart", "ExecStart"]
    assert {("Type", "oneshot"), ("TimeoutStartSec", "infinity")} <= set(service)
    assert ("WorkingDirectory", workspace) in service
    environment = [value for key, value in service if key == "Environment"]
    assert [key for key, _ in service].count("EnvironmentFile") == 1
    # The club-news settings and any key come from the private file, never from the unit.
    assert all(
        value.split("=", 1)[0] in {"PYTHONPATH", "PYTHONUNBUFFERED"} for value in environment
    )
    assert {("OnCalendar", "*:0/15"), ("Persistent", "true")} <= set(timer)
    assert ("Unit", "weekly-schedule.service") in timer


FINAL_RUN = "2026-27-gw09-friday-20261031T0705Z"
HOLD = "Until its end line here, please merge nothing into develop and start no heavy run."
LIFTED = "The hold on develop and heavy runs is lifted."
STAYS = "The last accepted publication stays live."
WAITS = "its site pull request waits for a preview and a yes before its release (D1 on #1243)"


def _started(tmp_path: Path, host: _Host, now: str = "2026-10-31T07:05:00Z", *extra: str) -> int:
    workspace = _workspace(tmp_path)
    (workspace / "data" / "snapshots" / "fpl-live-20261031").mkdir(parents=True, exist_ok=True)
    return _main(workspace, now, host, *extra)


def test_a_run_posts_its_start_and_end_on_the_slot_issue(tmp_path: Path) -> None:
    host = _Host()
    assert _started(tmp_path, host) == 0
    assert host.posted == [
        f"Weekly run `{FINAL_RUN}` started at 2026-10-31T07:05Z on the scheduled host: the final "
        f"run for gameweek 9, with club news, deadline 2026-10-31T11:00Z. {HOLD}",
        f"Weekly run `{FINAL_RUN}` ended at 2026-10-31T08:49Z with exit 0: {WAITS}. It took "
        f"1 h 44 min. {LIFTED}",
    ]


def test_the_settled_view_in_a_gap_says_so_in_its_start_line(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    (workspace / "bootstrap.json").write_bytes(_bootstrap(GAP, settled={5}))
    host = _Host(minutes=50)
    assert _main(workspace, "2026-09-22T09:00:00Z", host) == 0
    assert host.posted[0] == (
        "Weekly run `2026-27-gw06-tuesday-20260922T0900Z` started at 2026-09-22T09:00Z on the "
        "scheduled host: the morning run for gameweek 6 that publishes the settled view of "
        f"gameweek 5 in a fixture gap, deadline 2026-10-10T10:00Z. {HOLD}"
    )
    assert host.posted[1].endswith(f"It took 50 min. {LIFTED}")


@pytest.mark.parametrize(
    "host,stage,verb,log",
    [
        (_Host(pull_exit=1), "checkout", "was refused (exit 2)", f"{FINAL_RUN}.log"),
        (_Host(news_exit=1), "club news", "was refused (exit 2)", f"{FINAL_RUN}.club-news.log"),
        (_Host(weekly_exit=1), "weekly run", "failed (exit 1)", f"{FINAL_RUN}.log"),
        (
            _Host(weekly_exit=1, journal=True),
            "weekly run: league",
            "failed (exit 1)",
            f"{FINAL_RUN}.log",
        ),
    ],
)
def test_a_refused_or_failed_run_posts_an_alarm_naming_its_id_and_stage(
    tmp_path: Path, host: _Host, stage: str, verb: str, log: str
) -> None:
    code = 2 if verb.startswith("was refused") else 1
    assert _started(tmp_path, host) == code
    start, end, alarm = host.posted
    assert start.startswith(f"Weekly run `{FINAL_RUN}` started at 2026-10-31T07:05Z")
    assert end == (
        f"Weekly run `{FINAL_RUN}` ended at 2026-10-31T08:49Z with exit {code}: it stopped at "
        f"stage `{stage}`, and the alarm follows. It took 1 h 44 min. {LIFTED}"
    )
    assert alarm == (
        f"Alarm: weekly run `{FINAL_RUN}` {verb} at stage `{stage}`. Read "
        f"`data/logs/weekly/{log}` on the scheduled host before anything is run again. {STAYS}"
    )


def test_a_release_that_stops_posts_its_alarm_and_one_that_completes_says_live(
    tmp_path: Path,
) -> None:
    host = _Host(release_exit=1)
    assert _started(tmp_path / "stopped", host, "2026-10-31T07:05:00Z", "--release") == 1
    assert host.posted[2] == (
        f"Alarm: weekly run `{FINAL_RUN}` stopped (exit 1) at stage `release`. Read "
        f"`data/logs/weekly/{FINAL_RUN}.release.log` on the scheduled host: a release that "
        f"stopped after the enqueue is reconciled by hand, never run again. {STAYS}"
    )
    live = _Host(release_exit=0, minutes=200)
    assert _started(tmp_path / "live", live, "2026-10-31T07:05:00Z", "--release") == 0
    assert live.posted[1] == (
        f"Weekly run `{FINAL_RUN}` ended at 2026-10-31T10:25Z with exit 0: its release is "
        f"live. It took 3 h 20 min. {LIFTED}"
    )
    assert len(live.posted) == 2


@pytest.mark.parametrize(
    "now,minutes,extra,alarm",
    [
        (
            "2026-10-31T07:05:00Z",
            131,
            (),
            f"Alarm: weekly run `{FINAL_RUN}` is late at stage `weekly run`. It ended at "
            "2026-10-31T09:16Z, after 2026-10-31T09:15Z, the last end that leaves its release "
            f"by hand 1.75 h before the deadline 2026-10-31T11:00Z. {STAYS}",
        ),
        (
            "2026-10-31T07:05:00Z",
            236,
            ("--release",),
            f"Alarm: weekly run `{FINAL_RUN}` is late at stage `release`. It ended at "
            f"2026-10-31T11:01Z, after 2026-10-31T11:00Z, the deadline. {STAYS}",
        ),
        (
            "2026-10-30T02:00:00Z",
            211,
            (),
            "Alarm: weekly run `2026-27-gw09-tuesday-20261030T0200Z` is late at stage `weekly "
            "run`. It ended at 2026-10-30T05:31Z, after 2026-10-30T05:30Z, 3.5 h after its "
            f"start, the time the gate leaves a morning run before a final run. {STAYS}",
        ),
    ],
)
def test_a_run_that_ends_too_late_for_its_budget_posts_an_alarm(
    tmp_path: Path, now: str, minutes: int, extra: tuple[str, ...], alarm: str
) -> None:
    host = _Host(release_exit=0, minutes=minutes)
    assert _started(tmp_path, host, now, *extra) == 0
    assert host.posted[2:] == [alarm]
    # A minute less is in time.
    early = _Host(release_exit=0, minutes=minutes - 1)
    assert _started(tmp_path / "early", early, now, *extra) == 0
    assert len(early.posted) == 2


def test_a_missed_final_run_posts_one_alarm_and_a_dry_run_none(tmp_path: Path) -> None:
    workspace = _workspace(tmp_path)
    host = _Host()
    assert _main(workspace, "2026-10-31T08:00:00Z", host, "--dry-run") == 3
    assert host.posted == []
    assert _main(workspace, "2026-10-31T08:00:00Z", host) == 3
    assert _main(workspace, "2026-10-31T08:15:00Z", host) == 3
    assert host.posted == [
        "Alarm: the final run for gameweek 9 (`final-2026-27-gw09`) was missed at stage `gate`. "
        "At 2026-10-31T08:00Z the deadline 2026-10-31T11:00Z was 180 min away and a run takes "
        f"about 3.5 h, so no run was started. {STAYS}"
    ]
    assert host.commands == []


def test_a_gate_that_cannot_decide_posts_one_alarm_a_day_without_its_paths(
    tmp_path: Path,
) -> None:
    workspace = _workspace(tmp_path)
    (workspace / gate.FIXTURES).write_text("{}", encoding="utf-8")
    host = _Host()
    for now in ("2026-10-30T02:00:00Z", "2026-10-30T02:15:00Z", "2026-10-31T02:00:00Z"):
        assert _main(workspace, now, host) == 2
    assert host.posted == [
        f"Alarm: the weekly schedule gate refused at stage `gate`. At {day}T02:00Z it could not "
        "decide, so no run could start: web/public/data/fixtures.json names no "
        "payload.season. This alarm is posted once a UTC day while the refusal lasts. "
        f"{STAYS}"
        for day in ("2026-10-30", "2026-10-31")
    ]
    assert not any(str(tmp_path) in text for text in host.posted)


def test_every_comment_is_plain_english_with_no_dash_a_secret_or_a_home_path(
    tmp_path: Path,
) -> None:
    posted: list[str] = []
    for index, host in enumerate(
        (_Host(), _Host(news_exit=1), _Host(weekly_exit=1, journal=True), _Host(minutes=300))
    ):
        _started(tmp_path / str(index), host)
        posted += host.posted
    assert len(posted) == 11
    for text in posted:
        assert not {"\u2013", "\u2014"} & set(text), text
        assert str(Path.home()) not in text and str(tmp_path) not in text, text
        assert "KEY" not in text and "token" not in text.lower(), text


def test_the_slot_issue_comment_goes_through_gh_and_a_failure_never_stops_the_gate(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    calls: list[tuple[list[str], dict[str, object]]] = []
    answers = [
        subprocess.CompletedProcess([], 0, "https://github.com/o/r/issues/1093#c1\n"),
        subprocess.CompletedProcess([], 4, "gh: To use GitHub CLI, run gh auth login\n"),
    ]

    def run(arguments: list[str], **options: object) -> subprocess.CompletedProcess[str]:
        calls.append((arguments, options))
        return answers.pop(0)

    monkeypatch.setattr(subprocess, "run", run)
    gate.comment_on_slot_issue(tmp_path, "Weekly run `x` started.")
    gate.comment_on_slot_issue(tmp_path, "Weekly run `x` ended.")
    assert [arguments for arguments, _ in calls] == [
        ["gh", "issue", "comment", "1093", "--body-file", "-"]
    ] * 2
    assert [(options["cwd"], options["input"]) for _, options in calls] == [
        (tmp_path, "Weekly run `x` started."),
        (tmp_path, "Weekly run `x` ended."),
    ]
    assert capsys.readouterr().out.splitlines() == [
        "#1093: https://github.com/o/r/issues/1093#c1",
        "#1093: the comment was not posted (gh exited 4): gh: To use GitHub CLI, run gh auth login",
    ]

    def missing(arguments: list[str], **options: object) -> None:
        raise FileNotFoundError("gh")

    monkeypatch.setattr(subprocess, "run", missing)
    gate.comment_on_slot_issue(tmp_path, "Alarm")
    assert "the comment was not posted (gh exited 127)" in capsys.readouterr().out
    assert inspect.signature(gate.main).parameters["notify"].default is gate.comment_on_slot_issue


def test_a_bootstrap_the_game_does_not_answer_is_decided_on_the_held_copy(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    cache = tmp_path / "bootstrap.json"
    now = datetime.fromisoformat("2030-01-01T00:00:00Z")

    def unavailable() -> bytes:
        raise DataSourceError("bootstrap-static returned HTTP 503 Service Unavailable.")

    with pytest.raises(DataSourceError):
        gate.cached_bootstrap(cache, now, unavailable)
    cache.write_bytes(b"held")
    assert gate.cached_bootstrap(cache, now, unavailable) == b"held"
    said = capsys.readouterr().out
    assert said.startswith("bootstrap: the read failed (bootstrap-static returned HTTP 503")
    assert gate.cached_bootstrap(cache, now, lambda: b"fresh") == b"fresh"
    assert cache.read_bytes() == b"fresh"
