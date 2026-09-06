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
from squadopt.platform.backend_runtime import BackendConfig, build_backend
from squadopt.platform.store_probe import probe_store

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
    config = BackendConfig(
        store_root=tmp_path / "store",
        site_data_root=site_root,
        snapshot_root=snapshot_root,
        handoff_root=handoff_root,
    )
    return {"config": config, "snapshot_id": snapshot_id}


def test_the_store_passes_the_primitives_the_adapters_were_built_on(tmp_path: Path) -> None:
    """ADR 0006's probe, on a real path. A failure here would keep a service unready."""

    result = probe_store(tmp_path / "store")
    assert result.ok, result.detail
    assert set(result.checks) == {
        "writable_root",
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
    assert "writable_root" in result.failures()
    assert result.detail["writable_root"]


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
