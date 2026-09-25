"""Opt-in browser -> HTTP API -> worker -> disk cache, using synthetic inputs only."""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from urllib.error import URLError
from urllib.request import urlopen
from uuid import uuid4

import pytest
import tests.unit.test_advice_worker as worker_fixture
import tests.unit.test_backend_runtime as deployment_fixture
import tests.unit.test_player_evidence as evidence_fixture
from tests.unit.test_projection_horizon_builder import _calendar

from squadopt.application.entries import EntryRegistration
from squadopt.application.league_views import MemberStanding, build_league_views
from squadopt.application.player_evidence import write_evidence_artifact
from squadopt.application.weekly_plan import evidence_artifact
from squadopt.data.snapshots import write_snapshot
from squadopt.platform.backend_runtime import BackendConfig, build_backend

REPOSITORY = Path(__file__).resolve().parents[2]


def _available_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


def _windows_process_ids(pid: int) -> list[int]:
    """Exclude orphaned processes whose parent PID was reused by this fixture."""
    rows = json.loads(
        subprocess.check_output(
            [
                "powershell.exe",
                "-NoProfile",
                "-Command",
                "ConvertTo-Json -InputObject @(Get-CimInstance Win32_Process | "
                "Select-Object ProcessId,ParentProcessId,@{Name='Created';"
                "Expression={$_.CreationDate.ToUniversalTime().Ticks.ToString()}})",
            ],
            encoding="utf-8",
            timeout=10,
            creationflags=subprocess.CREATE_NO_WINDOW,
        )
    )
    root = next(row for row in rows if row["ProcessId"] == pid)
    selected = [root]
    for parent in selected:
        selected.extend(
            row
            for row in rows
            if row["ParentProcessId"] == parent["ProcessId"]
            and row not in selected
            and int(row["Created"]) >= int(parent["Created"])
        )
    return [row["ProcessId"] for row in reversed(selected)]


def test_windows_process_ids_excludes_older_orphan_branches(monkeypatch):
    rows = [
        {"ProcessId": 10, "ParentProcessId": 1, "Created": "100"},
        {"ProcessId": 11, "ParentProcessId": 10, "Created": "101"},
        {"ProcessId": 12, "ParentProcessId": 11, "Created": "102"},
        {"ProcessId": 20, "ParentProcessId": 10, "Created": "99"},
        {"ProcessId": 21, "ParentProcessId": 20, "Created": "103"},
        {"ProcessId": 30, "ParentProcessId": 1, "Created": "104"},
    ]
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0, raising=False)
    monkeypatch.setattr(subprocess, "check_output", lambda *args, **kwargs: json.dumps(rows))
    assert _windows_process_ids(10) == [12, 11, 10]


def test_windows_process_ids_refuses_a_missing_target(monkeypatch):
    monkeypatch.setattr(subprocess, "CREATE_NO_WINDOW", 0, raising=False)
    monkeypatch.setattr(subprocess, "check_output", lambda *args, **kwargs: "[]")
    with pytest.raises(StopIteration):
        _windows_process_ids(10)


@contextmanager
def _process(
    arguments: list[str], environment: dict[str, str], log: Path, *, cwd: Path = REPOSITORY
):
    with log.open("w", encoding="utf-8") as output:
        process = subprocess.Popen(
            arguments,
            cwd=cwd,
            env=environment,
            stdout=output,
            stderr=output,
            start_new_session=os.name != "nt",
        )
        try:
            yield process
        finally:
            if process.poll() is None:
                # Playwright starts preview/Chromium children; a timeout must close
                # this test's entire process tree, not just its parent Node process.
                if os.name == "nt":
                    try:
                        pids = _windows_process_ids(process.pid)
                    except (OSError, subprocess.SubprocessError, ValueError, StopIteration):
                        # The held handle still identifies our root if listing fails.
                        process.kill()
                    else:
                        subprocess.run(
                            [
                                "taskkill",
                                *[arg for pid in pids for arg in ("/PID", str(pid))],
                                "/F",
                            ],
                            stdout=subprocess.DEVNULL,
                            stderr=subprocess.DEVNULL,
                            timeout=10,
                            check=False,
                        )
                else:
                    # Playwright handles SIGINT by tearing down its detached preview
                    # server; uvicorn and the worker also handle this shutdown signal.
                    os.killpg(process.pid, signal.SIGINT)
                try:
                    process.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    if os.name == "nt":
                        process.kill()
                    else:
                        os.killpg(process.pid, signal.SIGKILL)
                    process.wait(timeout=5)


@pytest.mark.parametrize(
    "failure",
    [
        subprocess.TimeoutExpired("powershell.exe", 10),
        json.JSONDecodeError("invalid listing", "", 0),
        StopIteration(),
    ],
    ids=["listing-timeout", "invalid-json", "root-exited"],
)
def test_windows_cleanup_uses_held_handle_without_hiding_test_failure(
    tmp_path, monkeypatch, failure
):
    process = Mock(pid=10)
    process.poll.return_value = None
    monkeypatch.setattr(subprocess, "Popen", Mock(return_value=process))
    tree_kill = Mock()
    monkeypatch.setattr(subprocess, "run", tree_kill)
    monkeypatch.setattr(sys.modules[__name__], "os", SimpleNamespace(name="nt"))
    monkeypatch.setattr(sys.modules[__name__], "_windows_process_ids", Mock(side_effect=failure))
    with (
        pytest.raises(RuntimeError, match="original browser failure"),
        _process(["unused"], {}, tmp_path / "process.log"),
    ):
        raise RuntimeError("original browser failure")
    process.kill.assert_called_once_with()
    process.wait.assert_called_once_with(timeout=5)
    tree_kill.assert_not_called()


def _top100_export(capture, bootstrap: bytes, directory: Path) -> None:
    """A real export of 100 synthetic members, read unpatched by both processes."""
    document = json.loads(bootstrap)
    for player in document["elements"]:
        player.update(selected_by_percent="1.0", transfers_in_event=0, transfers_out_event=0)
    payloads = {"bootstrap-static.json": json.dumps(document).encode()}
    for page in (1, 2):
        document = json.loads(evidence_fixture._standings_page())
        document["standings"]["page"] = page
        document["standings"]["has_next"] = page == 1
        for member in document["standings"]["results"]:
            for key in ("entry", "rank", "rank_sort"):
                member[key] += (page - 1) * 50
        payloads[evidence_fixture.league_standings_page_payload(314, page)] = json.dumps(
            document
        ).encode()
    cohort = evidence_fixture._snapshot("fpl-top100", capture.inputs.captured_at_utc, payloads)
    picks = evidence_fixture._snapshot(
        "fpl-elite-picks",
        capture.inputs.captured_at_utc,
        {
            evidence_fixture.entry_picks_payload(
                evidence_fixture.FIRST_ENTRY + member, 1
            ): evidence_fixture._picks(
                elements=[code - 1000 for code in worker_fixture.SQUAD_CODES], captain=1, vice=4
            )
            for member in range(1, 101)
        },
    )
    table = evidence_fixture._build(
        cohort_snapshot=cohort,
        snapshots=[cohort, picks],
        cohort_size=100,
        target_gameweek=capture.inputs.deadline.gameweek,
        deadline_timestamp_utc=capture.inputs.deadline.deadline_utc,
    )
    name = evidence_artifact(
        directory,
        capture.inputs.season,
        capture.inputs.deadline.gameweek,
        picks.metadata.snapshot_id,
    )[0].stem
    write_evidence_artifact(
        table,
        directory,
        name,
        repository_commit="e" * 40,
        generated_at_utc=capture.inputs.captured_at_utc,
    )


@pytest.mark.skipif(
    os.environ.get("SQUADOPT_BROWSER_SMOKE") != "1",
    reason="Opt-in: requires web/node_modules and the Playwright Chromium browser.",
)
def test_browser_computes_a_member_plan_and_reuses_its_cached_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    node = shutil.which("node")
    assert node is not None, "Install the web toolchain before running the browser smoke."
    playwright = REPOSITORY / "web/node_modules/@playwright/test/cli.js"
    assert playwright.is_file(), "Run npm ci in web first."

    monkeypatch.setenv("SQUADOPT_REPOSITORY_COMMIT", "e" * 40)
    api_port = _available_port()
    assert api_port != 8000
    web_port = _available_port()
    api_origin = f"http://127.0.0.1:{api_port}"
    web_origin = f"http://127.0.0.1:{web_port}"
    config = BackendConfig(
        store_root=tmp_path / "store",
        site_data_root=tmp_path / "site",
        snapshot_root=tmp_path / "snapshots",
        handoff_root=tmp_path / "handoffs",
        allowed_origins=(web_origin,),
        artifact_root=tmp_path / "artifacts",
    )
    config.store_root.mkdir()
    entry_id = deployment_fixture.ENTRY_ID
    entries = (entry_id, entry_id + 1, entry_id + 2)
    world = worker_fixture.world_module
    snapshot_id = write_snapshot(
        config.snapshot_root,
        source="fpl-live",
        captured_at_utc=world.GW2_CAPTURED_AT,
        payloads={
            world.BOOTSTRAP_PAYLOAD: world._bootstrap(
                events=[dict(world.EVENTS[0], finished=True), *world.EVENTS[1:]],
                elements=world._elements(event_points=2),
            ),
            world.FIXTURES_PAYLOAD: _calendar(gameweeks=(1, 2, 3)),
            **{
                name: value
                for entry in entries
                for name, value in worker_fixture._entry_payloads(entry, 1).items()
            },
        },
    ).snapshot_id
    deployment_fixture._handoff(config.handoff_root, snapshot_id)
    deployment_fixture._publish_members(config.site_data_root)
    backend = build_backend(config)
    context = backend.contexts.current()
    assert context is not None
    capture = backend.contexts.capture(context)
    assert capture is not None
    identity = backend.contexts.identity()
    assert identity is not None
    _top100_export(
        capture,
        identity.snapshot.payloads[world.BOOTSTRAP_PAYLOAD],
        config.artifact_root / "phase_b",
    )

    # Generate a complete public fixture through the actual publisher. Remove its
    # static advice only: the browser must request a new answer from the empty
    # backend cache, while the index retains the declared selection capabilities.
    entry_id = deployment_fixture.ENTRY_ID
    league_id = deployment_fixture.LEAGUE_ID
    report = build_league_views(
        capture.provider,
        tuple(
            EntryRegistration(entry, f"browser-member-{entry}", capture.inputs.captured_at_utc)
            for entry in entries
        ),
        capture.inputs,
        capture.projection,
        capture.rules,
        league_id=league_id,
        league_name="Browser smoke league",
        out_dir=config.site_data_root / "league",
        standings={
            entry: MemberStanding(
                entry_id=entry,
                team_name="Browser smoke team" if entry == entry_id else f"Browser rival {entry}",
                manager_name=f"Synthetic member {entry}",
                rank=rank,
            )
            for rank, entry in enumerate(entries, 1)
        },
    )
    assert report.rendered_count == 3
    # The member page reads the published calendar and withholds Compute once the advised
    # gameweek's deadline has passed. This world's gameweek closed long ago by the wall
    # clock, and the build would otherwise serve the real season's calendar, so the fixture
    # publishes its own, with the week still open. It is site data like the rest: nothing is
    # intercepted in the browser.
    (config.site_data_root / "fixtures.json").write_text(
        json.dumps(
            {
                "contract_version": "fixtures_v1",
                "generated_at_utc": world.GW2_CAPTURED_AT,
                "source_kind": "example",
                "payload": {
                    "season": capture.inputs.season,
                    "source_snapshot_id": snapshot_id,
                    "captured_at_utc": world.GW2_CAPTURED_AT,
                    "current_gameweek": int(capture.inputs.deadline.gameweek),
                    "unscheduled_count": 0,
                    "gameweeks": [
                        {
                            "gameweek": int(capture.inputs.deadline.gameweek),
                            "deadline_utc": "2999-01-01T00:00:00Z",
                            "fixtures": [],
                        }
                    ],
                },
            }
        ),
        encoding="utf-8",
    )
    baseline_path = (
        config.site_data_root / "league" / "advice" / str(entry_id) / "saf-puan" / "1.json"
    )
    baseline_copy = tmp_path / "published-baseline.json"
    shutil.copyfile(baseline_path, baseline_copy)
    baseline_path.unlink()
    index = json.loads((baseline_path.parent.parent / "index.json").read_text(encoding="utf-8"))[
        "payload"
    ]
    rival_id = next(entry for entry in entries[1:] if entry != index["default_rival_entry_id"])
    rival_path = baseline_path.parent.parent / "ortak-koru" / "1" / f"vs-{rival_id}.json"
    assert rival_path.is_file()
    rival_path.unlink()
    chip_path = baseline_path.parent / "1" / "chip-bboost.json"
    assert chip_path.is_file()
    chip_path.unlink()
    environment = dict(
        os.environ,
        PYTHONPATH=str(REPOSITORY / "src"),
        PYTHONIOENCODING="utf-8",
        SQUADOPT_BACKEND_STORE_ROOT=str(config.store_root),
        SQUADOPT_BACKEND_SITE_DATA_ROOT=str(config.site_data_root),
        SQUADOPT_BACKEND_SNAPSHOT_ROOT=str(config.snapshot_root),
        SQUADOPT_BACKEND_HANDOFF_ROOT=str(config.handoff_root),
        SQUADOPT_BACKEND_ALLOWED_ORIGINS=web_origin,
        SQUADOPT_BACKEND_ARTIFACT_ROOT=str(config.artifact_root),
        SQUADOPT_BROWSER_CONTEXT=json.dumps(
            {
                "apiOrigin": api_origin,
                "webOrigin": web_origin,
                "webPort": web_port,
                "siteRoot": str(config.site_data_root),
                "entryId": entry_id,
                "rivalId": rival_id,
                "defaultRivalId": index["default_rival_entry_id"],
                "baselineCopy": str(baseline_copy),
                "fixturePid": os.getpid(),
                "leagueId": league_id,
                "season": context.season,
                "gameweek": context.gameweek,
                "snapshotId": snapshot_id,
                "buildName": f"advice-backend-smoke-{uuid4().hex}",
            }
        ),
    )
    for name in (
        "SQUADOPT_BACKEND_CLUB_NEWS_SOURCE",
        "SQUADOPT_BACKEND_SEASON",
        "SQUADOPT_BACKEND_RATE_LIMIT",
        "SQUADOPT_BACKEND_RATE_WINDOW_SECONDS",
    ):
        environment.pop(name, None)
    api_log = tmp_path / "api.log"
    worker_log = tmp_path / "worker.log"
    browser_log = tmp_path / "browser.log"
    with _process(
        [
            sys.executable,
            "-m",
            "tests.fixtures.backend_app",
            capture.inputs.captured_at_utc,
            "--host",
            "127.0.0.1",
            "--port",
            str(api_port),
        ],
        environment,
        api_log,
    ) as api:
        deadline = time.monotonic() + 30
        while time.monotonic() < deadline and api.poll() is None:
            try:
                with urlopen(f"{api_origin}/ready", timeout=1) as response:
                    if response.status == 200:
                        break
            except (URLError, TimeoutError):
                time.sleep(0.1)
        else:
            pytest.fail(f"API did not become ready:\n{api_log.read_text(encoding='utf-8')}")

        browser_context = json.loads(environment["SQUADOPT_BROWSER_CONTEXT"])
        browser_context["apiPid"] = api.pid
        environment["SQUADOPT_BROWSER_CONTEXT"] = json.dumps(browser_context)
        with _process(
            [sys.executable, "-m", "squadopt.platform.advice_worker", "--max-jobs", "4"],
            environment,
            worker_log,
        ) as worker:
            with _process(
                [node, str(playwright), "test", "--config", "playwright.backend.config.ts"],
                environment,
                browser_log,
                cwd=REPOSITORY / "web",
            ) as browser:
                try:
                    browser.wait(timeout=180)
                except subprocess.TimeoutExpired:
                    pytest.fail(f"Browser timed out; logs: {tmp_path}")
            assert browser.returncode == 0, (
                f"{browser_log.read_text(encoding='utf-8')}\nAPI:\n"
                f"{api_log.read_text(encoding='utf-8')}\nWorker:\n"
                f"{worker_log.read_text(encoding='utf-8')}"
            )
            assert worker.wait(timeout=5) == 0, worker_log.read_text(encoding="utf-8")

    # A fresh reader proves four distinct jobs persisted, and reload queued nothing extra.
    fresh = build_backend(config)
    jobs = fresh.queue.jobs()
    assert len(jobs) == 4
    assert all(job.status == "completed" for job in jobs)
    # The browser's automatic chip request was refused before a job existed (audit H3).
    specs = [fresh.job_specs.get(job.cache_key) for job in jobs]
    chips = [spec.switch("chip").get("chip") for spec in specs if spec is not None]
    assert len(chips) == 4 and "auto" not in chips and "bboost" in chips
    answer = fresh.reader.read_advice(
        league_id=league_id, entry_id=entry_id, strategy="saf-puan", window=1
    )
    assert answer is not None
    assert sum(fresh.cache.get(job.cache_key) == answer for job in jobs) == 1
