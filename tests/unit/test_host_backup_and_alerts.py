"""The host's backup and alerts (#1294), read as text and run where they can be.

`deploy/weekly-schedule/squadopt-watch` checks the host every five minutes and tells a person
through ntfy when a check breaks; `squadopt-backup` backs the irreplaceable data up to R2 with
restic each night; `squadopt-alert` sends one alert. These tests run the watch's checks and its
decision on scratch inputs with a fixed clock, so nothing here sends an alert, reads the host or
touches a repository: when a check alerts, repeats and resolves, the backend's five-minute grace,
the 36-hour backup limit, the run's exit and the capture before a deadline. The scripts parse and
name every store the issue lists, the units start them as the issue's times say, and no file
holds a secret.
"""

from __future__ import annotations

import importlib.machinery
import importlib.util
import json
import re
import shutil
import subprocess
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[2]
HOST_FILES = ROOT / "deploy" / "weekly-schedule"
WATCH = HOST_FILES / "squadopt-watch"
BACKUP = HOST_FILES / "squadopt-backup"
ALERT = HOST_FILES / "squadopt-alert"
NOW = datetime(2026, 11, 21, 8, 30, tzinfo=UTC)
BASH = shutil.which("bash")
needs_bash = pytest.mark.skipif(
    BASH is None or sys.platform == "win32", reason="the host scripts run under a POSIX bash"
)


def _load() -> ModuleType:
    loader = importlib.machinery.SourceFileLoader("squadopt_watch", str(WATCH))
    spec = importlib.util.spec_from_loader(loader.name, loader)
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    # A dataclass reads its module's globals while it is made, so the module is registered first.
    sys.modules[loader.name] = module
    loader.exec_module(module)
    return module


@pytest.fixture
def watch() -> ModuleType:
    return _load()


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_a_check_alerts_once_repeats_daily_and_says_when_it_is_good_again(
    watch: ModuleType,
) -> None:
    bad = watch.Reading("disk", True, "The host's disk is 91% full.")
    state: dict[str, object] = {}
    assert [a.title for a in watch.decide([bad], state, NOW)] == ["SquadOpt disk"]
    assert watch.decide([bad], state, NOW + timedelta(hours=23)) == []
    repeated = watch.decide([bad], state, NOW + timedelta(hours=24))
    assert [(a.title, a.priority) for a in repeated] == [("SquadOpt disk", "high")]
    good = watch.Reading("disk", False, "")
    resolved = watch.decide([good], state, NOW + timedelta(hours=25))
    assert [(a.title, a.priority) for a in resolved] == [("SquadOpt disk: resolved", "default")]
    assert state["disk"] == {}
    assert watch.decide([good], state, NOW + timedelta(hours=26)) == []


def test_the_backend_alerts_only_after_five_minutes_without_ready(watch: ModuleType) -> None:
    def refused(url: str) -> int:
        raise ConnectionRefusedError

    state: dict[str, object] = {}
    reading = watch.read_backend(refused)
    assert reading.bad and "no answer" in reading.text
    assert watch.decide([reading], state, NOW) == []
    assert watch.decide([reading], state, NOW + timedelta(minutes=4)) == []
    assert len(watch.decide([reading], state, NOW + timedelta(minutes=5))) == 1
    assert not watch.read_backend(lambda url: 200).bad
    assert watch.read_backend(lambda url: 503).bad


def test_failed_notifications_retry_without_repeating_successful_checks(
    watch: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(watch, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(
        watch,
        "readings",
        lambda now: [watch.Reading("disk", True, "full"), watch.Reading("backup", True, "late")],
    )
    attempts: list[str] = []
    pings: list[str] = []

    def send(alert: Any) -> bool:
        key = alert.key
        attempts.append(key)
        return key != "disk" or attempts.count("disk") > 1

    monkeypatch.setattr(watch, "send", send)
    monkeypatch.setattr(watch, "ping", pings.append)
    monkeypatch.setenv("HC_WATCH_URL", "https://health.invalid/watch")
    assert watch.main(lambda: NOW) == 1
    assert attempts == ["disk", "backup"]
    assert pings == []
    assert watch.main(lambda: NOW + timedelta(minutes=5)) == 0
    assert attempts == ["disk", "backup", "disk"]
    assert pings == ["https://health.invalid/watch"]
    assert watch.main(lambda: NOW + timedelta(minutes=10)) == 0
    assert attempts == ["disk", "backup", "disk"]


def test_a_failed_recovery_notice_is_retried_until_delivered(
    watch: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(watch, "STATE", tmp_path / "state.json")
    bad = True
    monkeypatch.setattr(watch, "readings", lambda now: [watch.Reading("disk", bad, "full")])
    attempts: list[str] = []

    def send(alert: Any) -> bool:
        title = alert.title
        attempts.append(title)
        return title != "SquadOpt disk: resolved" or attempts.count(title) > 1

    monkeypatch.setattr(watch, "send", send)
    monkeypatch.setattr(watch, "ping", lambda url: None)
    assert watch.main(lambda: NOW) == 0
    bad = False
    assert watch.main(lambda: NOW + timedelta(minutes=5)) == 1
    assert watch.main(lambda: NOW + timedelta(minutes=10)) == 0
    assert watch.main(lambda: NOW + timedelta(minutes=15)) == 0
    assert attempts == ["SquadOpt disk", "SquadOpt disk: resolved", "SquadOpt disk: resolved"]


def test_notification_failure_does_not_restart_the_backend_grace_period(
    watch: ModuleType, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(watch, "STATE", tmp_path / "state.json")
    monkeypatch.setattr(watch, "readings", lambda now: [watch.read_backend(lambda url: 503)])
    attempts: list[str] = []

    def send(alert: Any) -> bool:
        attempts.append(alert.key)
        return len(attempts) > 1

    monkeypatch.setattr(watch, "send", send)
    monkeypatch.setattr(watch, "ping", lambda url: None)
    assert watch.main(lambda: NOW) == 0
    assert attempts == []
    assert watch.main(lambda: NOW + timedelta(minutes=5)) == 1
    assert watch.main(lambda: NOW + timedelta(minutes=6)) == 0
    assert attempts == ["backend", "backend"]


def test_a_new_failed_run_alerts_at_once_and_the_same_one_only_daily(watch: ModuleType) -> None:
    def line(run_id: str, code: int, stage: str = "") -> str:
        return json.dumps({"run_id": run_id, "exit_code": code, "stage": stage})

    first = watch.read_run([line("2026-27-gw10-friday-20261106T0830Z", 0)])
    assert not first.bad
    failed = watch.read_run(
        [line("a", 0), line("2026-27-gw11-tuesday-20261113T0200Z", 1, "weekly run: publish")]
    )
    assert failed.bad and "at stage weekly run: publish" in failed.text
    state: dict[str, object] = {}
    assert len(watch.decide([failed], state, NOW)) == 1
    assert watch.decide([failed], state, NOW + timedelta(hours=1)) == []
    second = watch.read_run([line("2026-27-gw11-tuesday-20261114T0200Z", 1, "weekly run: league")])
    assert len(watch.decide([second], state, NOW + timedelta(hours=2))) == 1
    assert not watch.read_run([]).bad


def test_the_backup_is_late_after_36_hours_and_missing_until_one_succeeds(
    watch: ModuleType, tmp_path: Path
) -> None:
    stamp = tmp_path / "last-success"
    assert watch.read_backup(stamp, NOW).bad
    stamp.write_text("2026-11-19T23:35:02Z 1a2b3c4d\n", encoding="utf-8")
    assert not watch.read_backup(stamp, NOW).bad
    late = watch.read_backup(stamp, NOW + timedelta(hours=28))
    assert late.bad and "61 hours old" in late.text


def test_no_capture_since_the_last_deadline_alerts_three_hours_before_the_next(
    watch: ModuleType, tmp_path: Path
) -> None:
    bootstrap = {
        "events": [
            {"id": 10, "deadline_time": "2026-11-06T18:30:00Z"},
            {"id": 11, "deadline_time": "2026-11-21T11:00:00Z"},
        ]
    }
    early = datetime(2026, 11, 21, 7, 59, tzinfo=UTC)
    assert not watch.read_capture(bootstrap, None, early).bad
    stale = datetime(2026, 11, 6, 17, 0, tzinfo=UTC)
    missing = watch.read_capture(bootstrap, stale, NOW)
    assert missing.bad and missing.identity == "2026-11-21T11:00:00Z"
    taken = datetime(2026, 11, 21, 3, 0, tzinfo=UTC)
    assert not watch.read_capture(bootstrap, taken, NOW).bad
    assert watch.read_capture(bootstrap, None, NOW).bad
    snapshots = tmp_path / "snapshots"
    for name, moment in (
        ("fpl-live-20261113T020037Z-aaaaaaaaaaaa", "2026-11-13T02:00:37Z"),
        ("fpl-live-20261121T030012Z-bbbbbbbbbbbb", "2026-11-21T03:00:12Z"),
    ):
        (snapshots / name).mkdir(parents=True)
        metadata = {"captured_at_utc": moment}
        (snapshots / name / "metadata.json").write_text(json.dumps(metadata), encoding="utf-8")
    assert watch.newest_capture(snapshots) == datetime(2026, 11, 21, 3, 0, 12, tzinfo=UTC)


def test_the_timer_and_the_disk_use_their_limits(watch: ModuleType) -> None:
    state: dict[str, object] = {}
    off = watch.read_timer(False)
    assert watch.decide([off], state, NOW) == []
    assert watch.decide([off], state, NOW + timedelta(hours=2, minutes=59)) == []
    assert len(watch.decide([off], state, NOW + timedelta(hours=3))) == 1
    assert not watch.read_timer(True).bad
    assert watch.read_disk(lambda path: (100, 80, 20)).bad is False
    assert watch.read_disk(lambda path: (100, 81, 19)).bad is True


@pytest.mark.parametrize(
    "bootstrap",
    [
        {},
        {"events": []},
        {"events": None},
        {"events": [{}]},
        {"events": [{"deadline_time": "bad"}]},
    ],
)
def test_unavailable_deadlines_do_not_report_capture_health(
    watch: ModuleType, bootstrap: dict[str, Any]
) -> None:
    reading = watch.read_capture(bootstrap, NOW, NOW)
    assert reading.bad
    assert reading.identity == "deadline_source_unavailable"
    assert "cannot be checked" in reading.text


def test_a_finished_season_is_distinct_from_unavailable_deadlines(watch: ModuleType) -> None:
    bootstrap = {"events": [{"deadline_time": "2026-11-06T18:30:00Z"}]}
    assert not watch.read_capture(bootstrap, None, NOW).bad


def test_the_watch_reads_every_check_the_issue_lists(watch: ModuleType) -> None:
    keys = {
        "backend": "/ready",
        "disk": "80 %",
        "backup": "36 hours",
        "run": "non-zero exit",
        "timer": "3 hours",
        "capture": "3 hours away",
    }
    doc = watch.__doc__ or ""
    for key, words in keys.items():
        assert f"``{key}``" in doc and words in doc, key
    source = _text(WATCH)
    for key in keys:
        assert f'"{key}"' in source, key


@needs_bash
@pytest.mark.parametrize("script", [BACKUP, ALERT], ids=lambda path: path.name)
def test_both_scripts_parse(script: Path) -> None:
    parsed = subprocess.run([BASH or "bash", "-n", str(script)], capture_output=True, text=True)
    assert parsed.returncode == 0, parsed.stderr
    assert _text(script).splitlines()[0] == "#!/usr/bin/env bash"


def test_the_backup_covers_every_store_the_issue_names_and_keeps_a_stamp() -> None:
    text = _text(BACKUP)
    for store in (
        "data/snapshots",
        "data/handoffs",
        "data/ledger",
        "data/advice_records",
        "data/entries",
        "data/runtime",
        "data/logs",
        "artifacts",
        "/releases",
        "/store",
    ):
        assert store in text, store
    assert "--keep-daily 14 --keep-weekly 8 --keep-monthly 12 --prune" in text
    assert "--read-data-subset=20%" in text
    assert "ping /fail" in text and 'ping ""' in text
    assert "/var/lib/squadopt/backup/last-success" in text
    assert "/var/lib/squadopt/backup/last-success" in _text(WATCH)


@needs_bash
def test_an_alert_with_no_topic_or_a_bad_priority_is_refused(tmp_path: Path) -> None:
    environment = {"PATH": "/usr/bin:/bin", "HOME": str(tmp_path)}
    bad = subprocess.run(
        [BASH or "bash", str(ALERT), "loud", "t", "x"],
        capture_output=True,
        text=True,
        env=environment,
    )
    assert bad.returncode == 2 and "priority loud" in bad.stderr
    none = subprocess.run(
        [BASH or "bash", str(ALERT), "high", "t", "x"],
        capture_output=True,
        text=True,
        env=environment,
    )
    assert none.returncode == 2 and "no NTFY_TOPIC" in none.stderr


def _directives(path: Path) -> list[tuple[str, str]]:
    lines = [line for line in _text(path).splitlines() if "=" in line and not line.startswith("#")]
    return [tuple(part.strip() for part in line.split("=", 1)) for line in lines]  # type: ignore[misc]


def test_the_units_start_the_two_commands_at_their_times() -> None:
    backup = _directives(HOST_FILES / "squadopt-backup.service")
    assert ("ExecStart", "/usr/local/sbin/squadopt-backup") in backup
    assert ("EnvironmentFile", "/etc/squadopt/backup.env") in backup
    assert ("EnvironmentFile", "-/etc/squadopt/alert.env") in backup
    assert ("Environment", "RESTIC_CACHE_DIR=/var/cache/squadopt-restic") in backup
    assert ("OnCalendar", "*-*-* 23:30:00 UTC") in _directives(HOST_FILES / "squadopt-backup.timer")
    watch = _directives(HOST_FILES / "squadopt-watch.service")
    assert ("ExecStart", "/usr/local/sbin/squadopt-watch") in watch
    assert ("EnvironmentFile", "-/etc/squadopt/alert.env") in watch
    assert ("OnCalendar", "*:0/5") in _directives(HOST_FILES / "squadopt-watch.timer")


@pytest.mark.parametrize(
    "path",
    [WATCH, BACKUP, ALERT, HOST_FILES / "alert.example.env", HOST_FILES / "backup.example.env"],
    ids=lambda path: path.name,
)
def test_no_file_holds_a_secret(path: Path) -> None:
    text = _text(path)
    assert "-----BEGIN" not in text
    for name, value in re.findall(r"^([A-Z_]+)=(.*)$", text, flags=re.MULTILINE):
        if any(word in name for word in ("KEY", "TOKEN", "SECRET", "PASSWORD", "TOPIC", "HC_")):
            assert value.startswith("<") or value.startswith("/etc/"), (name, value)
    assert not {chr(0x2013), chr(0x2014)} & set(text), path
