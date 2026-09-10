"""Two real processes, one store: the api accepts, a separate worker computes.

Everything else about the backend is exercised in-process, which is fast and proves the
composition. It cannot prove the thing the whole design rests on — that a job written by one
process is claimed, computed and cached by *another* one through the shared mount. This test
starts the worker as an actual subprocess and does exactly that.

It is not a measurement, and it says nothing about a cloud filesystem: this is a local disk,
and a green run here is evidence about this machine. What it establishes is that the two
commands compose over one store rather than over shared memory.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

import pytest
import tests.unit.test_advice_worker as worker_module
import tests.unit.test_backend_runtime as deployment_module
from fastapi.testclient import TestClient

from squadopt.api.runtime import app_for_backend
from squadopt.application.advice import COMPUTED_MODE, COMPUTED_WINDOW
from squadopt.platform.backend_runtime import BackendConfig, StoreProbeGate, build_backend
from squadopt.platform.store_probe import StoreProbeResult, probe_store

LEAGUE_ID = deployment_module.LEAGUE_ID
ENTRY_ID = deployment_module.ENTRY_ID
COMMIT = "e" * 40


def _environment(config: BackendConfig) -> dict[str, str]:
    """Exactly what a container would be given, and nothing the client could name."""

    environment = dict(os.environ)
    environment.update(
        {
            "SQUADOPT_BACKEND_STORE_ROOT": str(config.store_root),
            "SQUADOPT_BACKEND_SITE_DATA_ROOT": str(config.site_data_root),
            "SQUADOPT_BACKEND_SNAPSHOT_ROOT": str(config.snapshot_root),
            "SQUADOPT_BACKEND_HANDOFF_ROOT": str(config.handoff_root),
            "SQUADOPT_REPOSITORY_COMMIT": COMMIT,
            "PYTHONIOENCODING": "utf-8",
        }
    )
    return environment


@pytest.fixture(name="deployed")
def _deployed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    monkeypatch.setenv("SQUADOPT_REPOSITORY_COMMIT", COMMIT)
    snapshot_root = tmp_path / "snapshots"
    handoff_root = tmp_path / "handoffs"
    site_root = tmp_path / "site"
    snapshot_id = worker_module._capture_with_entries(snapshot_root)
    deployment_module._handoff(handoff_root, snapshot_id)
    deployment_module._publish_members(site_root)
    store_root = tmp_path / "store"
    store_root.mkdir()  # the mount exists before the process does
    config = BackendConfig(
        store_root=store_root,
        site_data_root=site_root,
        snapshot_root=snapshot_root,
        handoff_root=handoff_root,
    )
    return {"config": config, "snapshot_id": snapshot_id}


def test_the_store_passes_the_primitives_the_adapters_were_built_on(tmp_path: Path) -> None:
    """ADR 0006's probe, on a real path. A failure here would keep a service unready."""

    store = tmp_path / "store"
    store.mkdir()
    result = probe_store(store)
    assert result.ok, result.detail
    assert set(result.checks) == {
        "mounted_root",
        "queue_lock",
        "exclusive_create",
        "hard_link_no_overwrite",
        "heartbeat_mtime",
        "shared_listing",
    }


def test_a_probe_on_an_unwritable_root_reports_rather_than_raises(tmp_path: Path) -> None:
    """The caller wants an unready service and the reason, never a crash loop."""

    blocker = tmp_path / "not-a-directory"
    blocker.write_bytes(b"")
    result = probe_store(blocker)
    assert result.ok is False
    assert "mounted_root" in result.failures()
    assert result.detail["mounted_root"]


def test_a_store_root_that_does_not_exist_is_a_forgotten_volume(tmp_path: Path) -> None:
    """The one check that separates an attached mount from a writable container.

    Creating the root would have made this pass: every other primitive here works
    perfectly well on the ephemeral disk a `docker run` without `--volume` provides, and
    the deployment would look healthy until a restart took the queue with it.
    """

    result = probe_store(tmp_path / "never-mounted")
    assert result.ok is False
    assert result.failures() == (
        "exclusive_create",
        "hard_link_no_overwrite",
        "heartbeat_mtime",
        "mounted_root",
        "queue_lock",
        "shared_listing",
    )
    assert not (tmp_path / "never-mounted").exists(), "the probe created the mount point"


def test_the_worker_exits_when_the_store_is_unavailable(tmp_path: Path) -> None:
    """A worker that cannot reach its store must die loudly, not claim nothing forever.

    Run as a subprocess under a timeout on purpose. The worker's normal life *is* an
    endless loop, so a regression here would not fail this test — it would hang it, and
    take the suite with it. Out of process, the same regression is a timeout with a name.
    """

    config = BackendConfig(
        store_root=tmp_path / "never-mounted",
        site_data_root=tmp_path / "site",
        snapshot_root=tmp_path / "snapshots",
        handoff_root=tmp_path / "handoffs",
    )
    finished = subprocess.run(
        [sys.executable, "-m", "squadopt.platform.advice_worker"],
        env=_environment(config),
        capture_output=True,
        text=True,
        timeout=90,
        check=False,
    )
    assert finished.returncode == 1, finished.stdout


def test_a_failed_store_stops_the_api_accepting_work(
    deployed: dict[str, Any], tmp_path: Path
) -> None:
    """503, not a queue write onto storage nothing will read again."""

    config = deployed["config"]
    # A gate that holds nothing, so the store's failure is observed rather than waited out.
    backend = build_backend(config, probe=StoreProbeGate(config.store_root, recheck_seconds=0.0))
    client = TestClient(app_for_backend(backend))
    route = f"/api/v1/leagues/{LEAGUE_ID}/entries/{ENTRY_ID}/advice"
    body = {"strategy": COMPUTED_MODE, "window": COMPUTED_WINDOW}
    assert client.post(route, json=body).status_code == 202

    # The mount goes away after the probe had already passed.
    shutil.rmtree(config.store_root)
    ready, checks = backend.readiness()
    assert ready is False
    assert checks["cache_store"] is False

    refused = client.post(route, json=body)
    assert refused.status_code == 503, refused.text
    assert refused.json()["error"]["code"] == "NOT_READY"


def test_a_separate_worker_process_computes_what_the_api_accepted(
    deployed: dict[str, Any],
) -> None:
    config = deployed["config"]
    backend = build_backend(config)
    client = TestClient(app_for_backend(backend))
    route = f"/api/v1/leagues/{LEAGUE_ID}/entries/{ENTRY_ID}/advice"
    body = {"strategy": COMPUTED_MODE, "window": COMPUTED_WINDOW}

    ready = client.get("/ready")
    assert ready.status_code == 200, ready.text

    accepted = client.post(route, json=body)
    assert accepted.status_code == 202, accepted.text
    job_id = accepted.json()["job_id"]

    # Nothing is shared but the filesystem: a fresh interpreter, the container's own
    # environment, and the same store root.
    finished = subprocess.run(
        [sys.executable, "-m", "squadopt.platform.advice_worker", "--max-jobs", "1"],
        env=_environment(config),
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert finished.returncode == 0, finished.stderr

    view = client.get(f"/api/v1/advice-jobs/{job_id}").json()
    assert view["status"] == "completed", (view, finished.stderr)

    served = client.get(route, params=body)
    assert served.status_code == 200, served.text
    document = served.json()
    assert document["contract_version"] == "provisional_league_ui_v1"
    assert document["payload"]["entry_id"] == ENTRY_ID
    assert document["payload"]["solver_status"] in {"OPTIMAL", "FEASIBLE"}

    # The answer is on the shared store, not in the api's memory: a backend built fresh over
    # the same mount serves the same bytes.
    cache_key = backend.queue.jobs()[0].cache_key
    assert build_backend(config).cache.get(cache_key) == served.content


@pytest.mark.parametrize("argument", ["--idle-seconds=0", "--idle-seconds=-1", "--max-attempts=0"])
def test_the_worker_refuses_operational_arguments_that_would_hurt(argument: str) -> None:
    """A zero idle is a busy wait against the shared mount, not a tuning choice."""

    finished = subprocess.run(
        [sys.executable, "-m", "squadopt.platform.advice_worker", argument],
        env=dict(os.environ, PYTHONIOENCODING="utf-8"),
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    assert finished.returncode == 2, finished.stdout
    assert "must be" in finished.stderr


def test_repeated_probes_do_not_grow_the_store(tmp_path: Path) -> None:
    """The probe is scaffolding, not a record; the gate runs it for the life of a process.

    Every run takes a fresh identity, so a marker left behind was two files a minute per
    process on the shared mount — and every later probe got slower, because the listing
    check reads the whole directory.
    """

    store = tmp_path / "store"
    store.mkdir()
    now = [0.0]
    gate = StoreProbeGate(store, recheck_seconds=30.0, clock=lambda: now[0])

    counts: list[int] = []
    # The results themselves, not their ids: the gate drops each one when it re-probes, and
    # a freed object's address can be handed straight to the next allocation, so a list of
    # bare ids could collapse to fewer than four entries while the gate behaved correctly.
    seen: list[StoreProbeResult] = []
    for _ in range(4):
        now[0] += 100.0  # past the TTL, so each round is a real probe
        assert gate.passed()
        seen.append(gate.result())
        counts.append(len(list((store / "probe").iterdir())))

    # Four distinct results: the gate re-probed rather than replaying a cached pass, which
    # is what makes the count below mean anything.
    assert len({id(result) for result in seen}) == 4, seen
    assert counts == [0, 0, 0, 0], counts


def test_a_probe_leaves_nothing_behind_even_when_it_fails(tmp_path: Path) -> None:
    store = tmp_path / "store"
    store.mkdir()
    (store / "probe").mkdir()
    # A directory where the marker file needs to go: exclusive create cannot win.
    (store / "probe" / "stuck.marker").mkdir()

    result = probe_store(store, process_id="stuck")
    assert result.ok is False
    assert list((store / "probe").iterdir()) == [store / "probe" / "stuck.marker"]
