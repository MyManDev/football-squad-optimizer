"""Opt-in synthetic real-solver capacity measurements; no live member inputs."""

import hashlib
import json
import os
import platform
import subprocess
import sys
import threading
import time
from contextlib import ExitStack, suppress
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

import pytest
import tests.unit.test_advice_worker as fixtures
import tests.unit.test_backend_runtime as deployment
from tests.integration.test_advice_browser import _available_port, _process

from squadopt.data.snapshots import read_snapshot, write_snapshot
from squadopt.platform.advice_load import run_burst

pytestmark = pytest.mark.skipif(
    os.environ.get("SQUADOPT_CAPACITY_PROBE") != "1",
    reason="Opt-in synthetic real-solver capacity probe; results depend on local resources.",
)


@pytest.mark.parametrize("users", [15, 30, 60])
@pytest.mark.parametrize("replicas", [1, 3])
def test_real_worker_capacity(tmp_path: Path, users: int, replicas: int) -> None:
    try:
        import psutil
    except ImportError:
        pytest.fail("Install psutil in the measurement environment to collect process resources.")
    seed_root = tmp_path / "seed"
    seed_id = fixtures._capture_with_entries(seed_root)
    seed = read_snapshot(seed_root, seed_id)
    snapshots = tmp_path / "snapshots"
    identifiers = list(range(101, 101 + users))
    payloads = dict(seed.payloads)
    for identifier in identifiers:
        payloads.update(fixtures._entry_payloads(identifier, 1))
    captured = write_snapshot(
        snapshots,
        source="fpl-live",
        captured_at_utc=seed.metadata.captured_at_utc,
        payloads=payloads,
    )
    handoffs = tmp_path / "handoffs"
    deployment._handoff(handoffs, captured.snapshot_id)
    site = tmp_path / "site"
    deployment._publish_members(site, *identifiers[1:])
    requests = [
        {"league_id": 352490, "entry_id": identifier, "strategy": "saf-puan", "window": 1}
        for identifier in identifiers
    ]
    reports = []
    scenarios = os.environ.get("SQUADOPT_CAPACITY_SCENARIOS", "dedup,distinct,cache-hit").split(",")
    assert scenarios and set(scenarios) <= {"dedup", "distinct", "cache-hit"}
    repository = Path(__file__).resolve().parents[2]
    source_hashes = {
        path.relative_to(repository).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted((repository / "src").rglob("*.py"))
    }
    for scenario in scenarios:
        store = tmp_path / scenario
        store.mkdir()
        api_port = _available_port()
        origin = f"http://127.0.0.1:{api_port}"
        environment = dict(
            os.environ,
            SQUADOPT_REPOSITORY_COMMIT="e" * 40,
            SQUADOPT_BACKEND_STORE_ROOT=str(store),
            SQUADOPT_BACKEND_SITE_DATA_ROOT=str(site),
            SQUADOPT_BACKEND_SNAPSHOT_ROOT=str(snapshots),
            SQUADOPT_BACKEND_HANDOFF_ROOT=str(handoffs),
            SQUADOPT_BACKEND_RATE_LIMIT="5000",
        )
        with ExitStack() as stack:
            api = stack.enter_context(
                _process(
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
                    store / "api.log",
                )
            )
            workers: list[subprocess.Popen] = []
            for index in range(replicas):
                workers.append(
                    stack.enter_context(
                        _process(
                            [
                                sys.executable,
                                "-m",
                                "squadopt.platform.advice_worker",
                                "--idle-seconds",
                                "0.05",
                            ],
                            environment,
                            store / f"worker-{index}.log",
                        )
                    )
                )
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                try:
                    with urlopen(origin + "/ready", timeout=1) as response:
                        if response.status == 200:
                            break
                except (URLError, TimeoutError):
                    time.sleep(0.1)
            else:
                pytest.fail((store / "api.log").read_text(encoding="utf-8"))
            if scenario == "cache-hit":
                warmup = run_burst(origin, requests, scenario="distinct", users=users)
                assert warmup["failed"] == 0
            processes = [psutil.Process(process.pid) for process in [api, *workers]]
            peak_rss: dict[int, int] = {}
            stop = threading.Event()

            def resource_tree(process):
                # Windows venv python.exe is a launcher; actual computation is in its
                # child. Measure each launched role's complete owned process tree.
                return [process, *process.children(recursive=True)]

            def cpu_seconds(process):
                return sum(sum(child.cpu_times()[:2]) for child in resource_tree(process))

            def sample(processes=processes, peak_rss=peak_rss, stop=stop) -> None:
                while not stop.is_set():
                    for process in processes:
                        with suppress(psutil.Error):
                            peak_rss[process.pid] = max(
                                peak_rss.get(process.pid, 0),
                                sum(child.memory_info().rss for child in resource_tree(process)),
                            )
                    stop.wait(0.05)

            before = {process.pid: cpu_seconds(process) for process in processes}
            observer = threading.Thread(target=sample, daemon=True)
            observer.start()
            try:
                report = run_burst(origin, requests, scenario=scenario, users=users)
            finally:
                stop.set()
                observer.join(timeout=3)
            report["replicas"] = replicas
            report["cpu_seconds"] = [
                cpu_seconds(process) - before[process.pid] for process in processes
            ]
            report["peak_sampled_rss_bytes"] = [peak_rss.get(process.pid) for process in processes]
            report["resource_order"] = ["api", *[f"worker-{index}" for index in range(replicas)]]
            report["resource_scope"] = "launched_role_and_descendants"
            report["resource_process_counts"] = [
                len(resource_tree(process)) for process in processes
            ]
            reports.append(report)
            (tmp_path / "capacity.json").write_text(
                json.dumps(
                    {
                        "environment": {
                            "os": platform.platform(),
                            "cpu_count": os.cpu_count(),
                            "python": platform.python_version(),
                            "synthetic": True,
                            "rate_limit": 5000,
                            "worker_idle_seconds": 0.05,
                        },
                        "capture_id": captured.snapshot_id,
                        "source_sha256": source_hashes,
                        "runtime_commit_is_synthetic": True,
                        "results": reports,
                    },
                    indent=2,
                ),
                encoding="utf-8",
            )
            assert report["failed"] == 0, report
            assert report["unique_job_count"] == (
                0 if scenario == "cache-hit" else 1 if scenario == "dedup" else users
            )
