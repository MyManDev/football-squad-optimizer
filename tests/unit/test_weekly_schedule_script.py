"""`scripts/weekly_schedule.ps1` decides on a schedule whether a weekly run starts (#1243).

A Task Scheduler task calls it every 15 minutes. From the bootstrap's deadlines, the clock and
the markers of the runs it has already started, it chooses the final run (from the deadline
minus the lead), a morning run (once a UTC day, unless the final run would start before it
could finish), a missed final window, or nothing. Each piece is run here by dot-sourcing the
script under Windows PowerShell 5.1 on synthetic inputs, and the whole script only with
`-DryRun` and a synthetic bootstrap; nothing here reads the network or starts a weekly run.
"""

from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest

from squadopt.platform.weekly_publish import PublishNames

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "weekly_schedule.ps1"
WEEKLY_RUN = ROOT / "scripts" / "weekly_run.ps1"
POWERSHELL = shutil.which("powershell.exe")

pytestmark = pytest.mark.skipif(POWERSHELL is None, reason="requires Windows PowerShell 5.1")

DEADLINES = {9: "2026-10-31T11:00:00Z", 10: "2026-11-06T18:30:00Z"}


def _run(command: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [POWERSHELL or "powershell.exe", "-NoProfile", "-NonInteractive", "-Command", command],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def _powershell(*lines: str) -> str:
    """Dot-source the script's functions, then run `lines`; return stdout."""

    completed = _run(
        "\n".join(
            [
                "$ErrorActionPreference = 'Stop'",
                "Set-StrictMode -Version 2.0",
                f". '{SCRIPT}'",
                *lines,
            ]
        )
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    return completed.stdout.strip()


def _bootstrap(path: Path, deadlines: dict[int, str]) -> Path:
    # The bootstrap's shape, with fields the gate does not read beside the two it does.
    events = [
        {"id": week, "deadline_time": deadline, "finished": False, "data_checked": False}
        for week, deadline in sorted(deadlines.items(), reverse=True)
    ]
    path.write_text(json.dumps({"events": events, "teams": []}), encoding="utf-8")
    return path


def _decide(tmp_path: Path, now: str, markers: list[str], lead: float = 4.0) -> list[str]:
    bootstrap = _bootstrap(tmp_path / "bootstrap.json", DEADLINES)
    listed = ", ".join(f"'{marker}'" for marker in markers) or ""
    out = _powershell(
        f"$events = Schedule-Events '{bootstrap}'",
        f"$d = Schedule-Decision $events (Parse-Utc '{now}') '2026-27' @({listed}) "
        f"'02:00' {lead} 3.5",
        "Write-Output ('{0}|{1}|{2}|{3}' -f $d.Action, $d.Gameweek, $d.Marker, $d.Reason)",
    )
    return out.split("|")


@pytest.mark.parametrize(
    "now,markers,expected",
    [
        (
            "2026-10-30T01:59:00Z",
            [],
            ["none", "9", "", "today's morning run starts at 2026-10-30T02:00Z"],
        ),
        (
            "2026-10-30T02:00:00Z",
            [],
            ["morning", "9", "morning-2026-10-30", "today's morning run for gameweek 9"],
        ),
        (
            "2026-10-30T09:00:00Z",
            ["morning-2026-10-30"],
            ["none", "9", "", "today's morning run has already started"],
        ),
        (
            "2026-10-30T09:00:00Z",
            ["morning-2026-10-29"],
            ["morning", "9", "morning-2026-10-30", "today's morning run for gameweek 9"],
        ),
        (
            "2026-10-31T02:00:00Z",
            [],
            ["morning", "9", "morning-2026-10-31", "today's morning run for gameweek 9"],
        ),
        (
            "2026-10-31T04:00:00Z",
            [],
            [
                "none",
                "9",
                "",
                "the final run starts at 2026-10-31T07:00Z, before a morning run could finish",
            ],
        ),
        (
            "2026-10-31T07:00:00Z",
            ["morning-2026-10-31"],
            ["final", "9", "final-2026-27-gw09", "the final run for gameweek 9"],
        ),
        (
            "2026-10-31T07:15:00Z",
            ["morning-2026-10-31", "final-2026-27-gw09"],
            ["none", "9", "", "the final run for gameweek 9 has already started"],
        ),
        (
            "2026-10-31T11:00:01Z",
            ["morning-2026-10-31", "final-2026-27-gw09"],
            ["none", "10", "", "today's morning run has already started"],
        ),
        (
            "2026-11-01T02:00:00Z",
            ["morning-2026-10-31", "final-2026-27-gw09"],
            ["morning", "10", "morning-2026-11-01", "today's morning run for gameweek 10"],
        ),
    ],
)
def test_the_gate_chooses_one_run_per_morning_and_one_final_run_per_gameweek(
    tmp_path: Path, now: str, markers: list[str], expected: list[str]
) -> None:
    assert _decide(tmp_path, now, markers) == expected


def test_a_final_window_the_gate_missed_is_reported_not_started(tmp_path: Path) -> None:
    action, gameweek, marker, reason = _decide(tmp_path, "2026-10-31T07:31:00Z", [])
    assert (action, gameweek, marker) == ("missed", "9", "")
    assert reason == (
        "the final run for gameweek 9 did not start: the deadline is 209 min away and a run "
        "takes about 3.5 h"
    )


def test_a_lead_shorter_than_a_run_refuses(tmp_path: Path) -> None:
    bootstrap = _bootstrap(tmp_path / "bootstrap.json", DEADLINES)
    out = _powershell(
        f"try {{ Schedule-Decision (Schedule-Events '{bootstrap}') "
        "(Parse-Utc '2026-10-30T02:00:00Z') '2026-27' @() '02:00' 3 3.5 }",
        " catch { Write-Output ('refused: ' + $_.Exception.Message) }",
    )
    assert out == (
        "refused: A final run 3 h before the deadline cannot be live before it: "
        "a run takes about 3.5 h."
    )


def test_a_season_with_no_deadline_ahead_refuses(tmp_path: Path) -> None:
    bootstrap = _bootstrap(tmp_path / "bootstrap.json", {38: "2027-05-23T15:00:00Z"})
    out = _powershell(
        f"try {{ Schedule-Decision (Schedule-Events '{bootstrap}') "
        "(Parse-Utc '2027-06-01T00:00:00Z') '2026-27' @() '02:00' 4 3.5 }",
        " catch { Write-Output ('refused: ' + $_.Exception.Message) }",
    )
    assert out == "refused: No gameweek deadline lies ahead of 2027-06-01T00:00Z in the bootstrap."


@pytest.mark.parametrize("morning", ["2:00", "24:00", "02:60", "0200"])
def test_the_morning_time_must_be_hh_mm(morning: str) -> None:
    out = _powershell(
        f"try {{ Morning-Start (Parse-Utc '2026-10-30T00:00:00Z') '{morning}' }}",
        " catch { Write-Output ('refused: ' + $_.Exception.Message) }",
    )
    assert out == f"refused: -MorningUtc must be HH:mm in UTC, not '{morning}'."


def test_events_are_read_in_gameweek_order_with_utc_deadlines(tmp_path: Path) -> None:
    bootstrap = _bootstrap(tmp_path / "bootstrap.json", DEADLINES)
    out = _powershell(
        f"Schedule-Events '{bootstrap}' | ForEach-Object "
        "{ '{0} {1} {2}' -f $_.Gameweek, (Format-Utc $_.Deadline), $_.Deadline.Kind }"
    )
    assert out.splitlines() == ["9 2026-10-31T11:00Z Utc", "10 2026-11-06T18:30Z Utc"]


def test_the_markers_are_the_runs_already_started(tmp_path: Path) -> None:
    started = tmp_path / "started"
    assert _powershell(f"@(Schedule-Markers '{started}').Count") == "0"
    started.mkdir()
    for name in ("morning-2026-10-30.json", "final-2026-27-gw09.json", "notes.txt"):
        (started / name).write_text("{}", encoding="utf-8")
    out = _powershell(f"Schedule-Markers '{started}' | Sort-Object")
    assert out.splitlines() == ["final-2026-27-gw09", "morning-2026-10-30"]


def test_each_run_gets_its_own_suffix_that_the_publisher_accepts() -> None:
    out = _powershell(
        "$now = Parse-Utc '2026-10-31T07:00:00Z'",
        "Run-Kind 'final' 'tuesday'",
        "Run-Kind 'morning' 'tuesday'",
        "Run-Suffix 'final' $now",
        "Run-Suffix 'morning' (Parse-Utc '2026-10-31T02:00:00Z')",
    )
    final_kind, morning_kind, final_suffix, morning_suffix = out.splitlines()
    assert (final_kind, morning_kind) == ("friday", "tuesday")
    assert (final_suffix, morning_suffix) == ("final-20261031T0700", "morning-20261031T0200")
    branches = {PublishNames("2026-27", 9, "decision", s).branch for s in out.splitlines()[2:]}
    assert branches == {
        "feature/gw09-decision-site-final-20261031T0700",
        "feature/gw09-decision-site-morning-20261031T0200",
    }


def _repository(tmp_path: Path) -> Path:
    repository = tmp_path / "repo"
    data = repository / "web" / "public" / "data"
    data.mkdir(parents=True)
    (data / "fixtures.json").write_text(
        json.dumps({"contract_version": "fixtures_v1", "payload": {"season": "2026-27"}}),
        encoding="utf-8",
    )
    return repository


def _dry_run(tmp_path: Path, now: str, *extra: str) -> subprocess.CompletedProcess[str]:
    repository = _repository(tmp_path)
    bootstrap = _bootstrap(tmp_path / "bootstrap.json", DEADLINES)
    return subprocess.run(
        [
            POWERSHELL or "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(SCRIPT),
            "-RepoRoot",
            str(repository),
            "-BootstrapPath",
            str(bootstrap),
            "-Now",
            now,
            "-DryRun",
            *extra,
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )


def test_a_dry_run_prints_the_run_it_would_start_and_writes_nothing(tmp_path: Path) -> None:
    completed = _dry_run(tmp_path, "2026-10-31T07:05:00Z")
    assert completed.returncode == 0, completed.stdout + completed.stderr
    gate, decision, would = completed.stdout.strip().splitlines()
    assert gate == (
        "gate at 2026-10-31T07:05Z: 2026-27 gameweek 9, deadline 2026-10-31T11:00Z, "
        "final run from 2026-10-31T07:00Z"
    )
    assert decision == "decision: final (the final run for gameweek 9)"
    assert would.startswith("would run: powershell.exe -NoProfile -ExecutionPolicy Bypass -File ")
    assert would.endswith("weekly_run.ps1 -Kind friday -Gameweek 9 -Suffix final-20261031T0705")
    assert not (tmp_path / "repo" / "data").exists()


def test_a_dry_run_exits_three_for_a_missed_window_and_two_for_a_short_lead(
    tmp_path: Path,
) -> None:
    missed = _dry_run(tmp_path, "2026-10-31T08:00:00Z")
    assert missed.returncode == 3, missed.stdout + missed.stderr
    assert "decision: missed (the final run for gameweek 9 did not start" in missed.stdout

    short = _dry_run(tmp_path / "short", "2026-10-30T02:00:00Z", "-FinalLeadHours", "3")
    assert short.returncode == 2, short.stdout + short.stderr
    assert short.stdout.strip() == (
        "Refused: A final run 3 h before the deadline cannot be live before it: "
        "a run takes about 3.5 h."
    )


def test_the_weekly_run_refuses_a_suffix_the_publisher_would_refuse() -> None:
    completed = subprocess.run(
        [
            POWERSHELL or "powershell.exe",
            "-NoProfile",
            "-NonInteractive",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(WEEKLY_RUN),
            "-Kind",
            "tuesday",
            "-Suffix",
            "final_20261031",
            "-DryRun",
        ],
        capture_output=True,
        text=True,
        encoding="utf-8",
        check=False,
    )
    assert completed.returncode != 0
    assert "Suffix" in completed.stdout + completed.stderr
