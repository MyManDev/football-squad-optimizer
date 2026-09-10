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
from urllib.error import URLError
from urllib.request import urlopen
from uuid import uuid4

import pytest
import tests.unit.test_advice_worker as worker_fixture
import tests.unit.test_backend_runtime as deployment_fixture

from squadopt.application.entries import EntryRegistration
from squadopt.application.league_views import MemberStanding, build_league_views
from squadopt.platform.backend_runtime import BackendConfig, build_backend

pytestmark = pytest.mark.skipif(
    os.environ.get("SQUADOPT_BROWSER_SMOKE") != "1",
    reason="Opt-in: requires web/node_modules and the Playwright Chromium browser.",
)

REPOSITORY = Path(__file__).resolve().parents[2]


def _available_port() -> int:
    with socket.socket() as listener:
        listener.bind(("127.0.0.1", 0))
        return int(listener.getsockname()[1])


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
                    subprocess.run(
                        ["taskkill", "/PID", str(process.pid), "/T", "/F"],
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


def test_browser_computes_a_member_plan_and_reuses_its_cached_answer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    node = shutil.which("node")
    assert node is not None, "Install the web toolchain before running the browser smoke."
    playwright = REPOSITORY / "web/node_modules/@playwright/test/cli.js"
    assert playwright.is_file(), "Run npm ci in web first."

    monkeypatch.setenv("SQUADOPT_REPOSITORY_COMMIT", "e" * 40)
    api_port = _available_port()
    web_port = _available_port()
    api_origin = f"http://127.0.0.1:{api_port}"
    web_origin = f"http://127.0.0.1:{web_port}"
    config = BackendConfig(
        store_root=tmp_path / "store",
        site_data_root=tmp_path / "site",
        snapshot_root=tmp_path / "snapshots",
        handoff_root=tmp_path / "handoffs",
        allowed_origins=(web_origin,),
    )
    config.store_root.mkdir()
    snapshot_id = worker_fixture._capture_with_entries(config.snapshot_root)
    deployment_fixture._handoff(config.handoff_root, snapshot_id)
    deployment_fixture._publish_members(config.site_data_root)
    backend = build_backend(config)
    context = backend.contexts.current()
    assert context is not None
    capture = backend.contexts.capture(context)
    assert capture is not None

    # Generate a complete public fixture through the actual publisher. Remove its
    # static advice only: the browser must request a new answer from the empty
    # backend cache, while the index retains the declared selection capabilities.
    entry_id = deployment_fixture.ENTRY_ID
    league_id = deployment_fixture.LEAGUE_ID
    report = build_league_views(
        capture.provider,
        (EntryRegistration(entry_id, "browser-member", capture.inputs.captured_at_utc),),
        capture.inputs,
        capture.projection,
        capture.rules,
        league_id=league_id,
        league_name="Browser smoke league",
        out_dir=config.site_data_root / "league",
        standings={
            entry_id: MemberStanding(
                entry_id=entry_id,
                team_name="Browser smoke team",
                manager_name="Synthetic member",
                rank=1,
            )
        },
    )
    assert report.rendered_count == 1
    baseline_path = (
        config.site_data_root / "league" / "advice" / str(entry_id) / "saf-puan" / "1.json"
    )
    baseline_path.unlink()
    environment = dict(
        os.environ,
        PYTHONPATH=str(REPOSITORY / "src"),
        PYTHONIOENCODING="utf-8",
        SQUADOPT_BACKEND_STORE_ROOT=str(config.store_root),
        SQUADOPT_BACKEND_SITE_DATA_ROOT=str(config.site_data_root),
        SQUADOPT_BACKEND_SNAPSHOT_ROOT=str(config.snapshot_root),
        SQUADOPT_BACKEND_HANDOFF_ROOT=str(config.handoff_root),
        SQUADOPT_BACKEND_ALLOWED_ORIGINS=web_origin,
        SQUADOPT_BROWSER_CONTEXT=json.dumps(
            {
                "apiOrigin": api_origin,
                "webOrigin": web_origin,
                "webPort": web_port,
                "siteRoot": str(config.site_data_root),
                "entryId": entry_id,
                "leagueId": league_id,
                "season": context.season,
                "gameweek": context.gameweek,
                "snapshotId": snapshot_id,
                "buildName": f"advice-backend-smoke-{uuid4().hex}",
            }
        ),
    )
    api_log = tmp_path / "api.log"
    worker_log = tmp_path / "worker.log"
    browser_log = tmp_path / "browser.log"
    with _process(
        [
            sys.executable,
            "-m",
            "uvicorn",
            "--factory",
            "squadopt.api.runtime:build_app",
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

        with _process(
            [sys.executable, "-m", "squadopt.platform.advice_worker", "--max-jobs", "1"],
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

    # A fresh reader proves persistence outside the API process. Both browser POSTs
    # must have addressed one job and one immutable answer.
    fresh = build_backend(config)
    jobs = fresh.queue.jobs()
    assert len(jobs) == 1
    assert jobs[0].status == "completed"
    assert fresh.cache.get(jobs[0].cache_key) == fresh.reader.read_advice(
        league_id=league_id, entry_id=entry_id, strategy="saf-puan", window=1
    )
