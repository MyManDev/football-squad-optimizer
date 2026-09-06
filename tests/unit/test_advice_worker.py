"""The worker: a claimed job becomes a real answer, or a stated refusal.

The end-to-end test here runs the actual ``advise_entry`` against a real capture and a real
projection handoff, through the real queue and the real cache. It is not a measurement and
it fits no scientific claim; it is the check that the parts compose into the thing a member
presses a button for.
"""

import json
import time
from collections.abc import Callable
from dataclasses import replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest
import tests.unit.test_backend_runtime as deployment_module
import tests.unit.test_live_transfers as world_module
import tests.unit.test_source_fpl_live as payload_module
from fastapi.testclient import TestClient

from squadopt.api.runtime import app_for_backend
from squadopt.application.advice import COMPUTED_MODE, COMPUTED_WINDOW, EntryError
from squadopt.data.snapshots import write_snapshot
from squadopt.platform.advice_job_spec import (
    AdviceJobSpec,
    AdviceJobSpecConflictError,
    FileAdviceJobSpecStore,
)
from squadopt.platform.advice_queue import AdviceComputeRefused, run_advice_worker_once
from squadopt.platform.advice_read import AdviceRequestContext
from squadopt.platform.advice_worker import build_advice_compute, run_advice_worker
from squadopt.platform.backend_runtime import BackendConfig, build_backend
from squadopt.platform.jobs_contract import AdviceJob

SEASON = deployment_module.SEASON
LEAGUE_ID = deployment_module.LEAGUE_ID
ENTRY_ID = deployment_module.ENTRY_ID
RIVAL_ID = ENTRY_ID + 1
BOOTSTRAP_PAYLOAD = world_module.BOOTSTRAP_PAYLOAD
FIXTURES_PAYLOAD = world_module.FIXTURES_PAYLOAD

# A legal fifteen out of the world's roster: 2/5/5/3, at most three per club, inside the
# budget. Element ids are code - 1000, which is the translation the capture provider owns.
STARTING_ELEVEN = (1001, 1004, 1006, 1008, 1009, 1013, 1014, 1016, 1017, 1020, 1023)
BENCH = (1003, 1011, 1019, 1024)  # in the substitution order the platform walks
SQUAD_CODES = STARTING_ELEVEN + BENCH


def _entry_payloads(entry_id: int, gameweek: int) -> dict[str, bytes]:
    elements = [code - 1000 for code in SQUAD_CODES]
    return {
        f"entry-{entry_id}-picks-gw{gameweek:02d}.json": payload_module._picks_payload(
            squad=elements
        ),
        f"entry-{entry_id}-history.json": payload_module._history_payload(),
    }


def _capture_with_entries(snapshot_root: Path) -> str:
    gw1_finished = [dict(world_module.EVENTS[0], finished=True), *world_module.EVENTS[1:]]
    written = write_snapshot(
        snapshot_root,
        source="fpl-live",
        captured_at_utc=world_module.GW2_CAPTURED_AT,
        payloads={
            BOOTSTRAP_PAYLOAD: world_module._bootstrap(
                events=gw1_finished, elements=world_module._elements(event_points=2)
            ),
            FIXTURES_PAYLOAD: b"[]",
            **_entry_payloads(ENTRY_ID, 1),
        },
    )
    return written.snapshot_id


@pytest.fixture(name="running")
def _running(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """A deployment whose capture actually holds the member's squad."""

    monkeypatch.setenv("SQUADOPT_REPOSITORY_COMMIT", "c" * 40)
    snapshot_root = tmp_path / "snapshots"
    handoff_root = tmp_path / "handoffs"
    site_root = tmp_path / "site"
    snapshot_id = _capture_with_entries(snapshot_root)
    deployment_module._handoff(handoff_root, snapshot_id)
    deployment_module._publish_members(site_root, RIVAL_ID)
    backend = build_backend(
        BackendConfig(
            store_root=tmp_path / "store",
            site_data_root=site_root,
            snapshot_root=snapshot_root,
            handoff_root=handoff_root,
        )
    )
    return {
        "backend": backend,
        "snapshot_id": snapshot_id,
        "snapshot_root": snapshot_root,
        "handoff_root": handoff_root,
    }


def _context(snapshot_id: str = "fpl-live-20260826T083133Z-d45f1bea8b68") -> AdviceRequestContext:
    return AdviceRequestContext(
        advice_contract_version="provisional_league_ui_v1",
        capture_snapshot_id=snapshot_id,
        season=SEASON,
        gameweek=2,
        projection_handoff_fingerprint="f" * 64,
        repository_commit="a" * 40,
        configuration_fingerprint="d" * 64,
    )


def _spec(**overrides: Any) -> AdviceJobSpec:
    fields: dict[str, Any] = {
        "league_id": LEAGUE_ID,
        "entry_id": ENTRY_ID,
        "strategy": COMPUTED_MODE,
        "window": COMPUTED_WINDOW,
        "context": _context(),
    }
    fields.update(overrides)
    return AdviceJobSpec(**fields)


def _now_stamp() -> str:
    """The contract's timestamp shape at the current instant.

    A fixed literal would sit before the job the api just created, and the record
    refuses a transition that moves time backwards.
    """

    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _job(cache_key: str, *, attempt: int = 1) -> AdviceJob:
    return AdviceJob(
        job_id="advice-0123456789abcdef-1",
        status="running",
        request_fingerprint="1" * 64,
        cache_key=cache_key,
        created_at_utc="2026-09-01T10:00:00Z",
        updated_at_utc="2026-09-01T10:00:00Z",
        attempt=attempt,
    )


def _stop_after(rounds: int) -> Callable[[], bool]:
    """A stop predicate that always terminates.

    A predicate that never stops, paired with ``max_jobs``, looks equivalent and is not: if a
    claim ever comes back empty the loop waits and asks again forever, which turns a flake
    into a hung CI job rather than a failing one.
    """

    remaining = [rounds]

    def stop() -> bool:
        remaining[0] -= 1
        return remaining[0] < 0

    return stop


def test_a_spec_survives_the_round_trip_with_its_context(tmp_path: Path) -> None:
    store = FileAdviceJobSpecStore(tmp_path / "specs")
    key = "a" * 64
    store.put(key, _spec(rival_entry_id=777, strategy="fark-yarat"))
    read = store.get(key)
    assert read == _spec(rival_entry_id=777, strategy="fark-yarat")
    assert read is not None
    assert read.context.capture_snapshot_id == _context().capture_snapshot_id


def test_one_address_may_only_ever_mean_one_question(tmp_path: Path) -> None:
    """Many requests share a key by design; they must therefore agree about it."""

    store = FileAdviceJobSpecStore(tmp_path / "specs")
    key = "b" * 64
    store.put(key, _spec())
    store.put(key, _spec())  # the same meaning again is a no-op
    with pytest.raises(AdviceJobSpecConflictError):
        store.put(key, _spec(entry_id=ENTRY_ID + 1))


def test_a_missing_spec_is_a_named_refusal_not_a_crash(tmp_path: Path) -> None:
    backend = build_backend(
        BackendConfig(
            store_root=tmp_path / "store",
            site_data_root=tmp_path / "site",
            snapshot_root=tmp_path / "snapshots",
            handoff_root=tmp_path / "handoffs",
        )
    )
    compute = build_advice_compute(backend.contexts, backend.job_specs)
    with pytest.raises(AdviceComputeRefused) as refusal:
        compute(_job("c" * 64))
    assert refusal.value.code == "REQUEST_UNREADABLE"


def test_a_job_retried_past_the_limit_is_failed_rather_than_repeated(tmp_path: Path) -> None:
    backend = build_backend(
        BackendConfig(
            store_root=tmp_path / "store",
            site_data_root=tmp_path / "site",
            snapshot_root=tmp_path / "snapshots",
            handoff_root=tmp_path / "handoffs",
        )
    )
    compute = build_advice_compute(backend.contexts, backend.job_specs, max_attempts=2)
    with pytest.raises(AdviceComputeRefused) as refusal:
        compute(_job("d" * 64, attempt=3))
    assert refusal.value.code == "TOO_MANY_ATTEMPTS"


def test_a_job_from_a_replaced_capture_is_refused_and_writes_nothing(
    running: dict[str, Any],
) -> None:
    """The silent-corruption case: never today's inputs under yesterday's key."""

    backend = running["backend"]
    key = "e" * 64
    backend.job_specs.put(key, _spec(context=_context("fpl-live-20250101T000000Z-deadbeef1234")))
    compute = build_advice_compute(backend.contexts, backend.job_specs)

    with pytest.raises(AdviceComputeRefused) as refusal:
        compute(_job(key))
    assert refusal.value.code == "CONTEXT_UNAVAILABLE"
    assert backend.cache.get(key) is None

    job = run_advice_worker_once(
        backend.queue, backend.cache, compute, at_utc="2026-09-01T10:01:00Z"
    )
    assert job is None  # nothing was queued; the refusal above is the whole story


def test_a_member_presses_the_button_and_gets_a_computed_answer(
    running: dict[str, Any],
) -> None:
    """POST, worker, GET — the actual request this backend exists to serve."""

    backend = running["backend"]
    client = TestClient(app_for_backend(backend))
    route = f"/api/v1/leagues/{LEAGUE_ID}/entries/{ENTRY_ID}/advice"
    body = {"strategy": COMPUTED_MODE, "window": COMPUTED_WINDOW}

    accepted = client.post(route, json=body)
    assert accepted.status_code == 202, accepted.text
    job_id = accepted.json()["job_id"]
    assert client.get(f"/api/v1/advice-jobs/{job_id}").json()["status"] == "queued"

    processed = run_advice_worker(
        backend.queue,
        backend.cache,
        build_advice_compute(backend.contexts, backend.job_specs),
        should_stop=_stop_after(3),
        max_jobs=1,
        metrics=backend.metrics,
    )
    assert processed == 1
    finished = client.get(f"/api/v1/advice-jobs/{job_id}").json()
    assert finished["status"] == "completed", finished

    served = client.get(route, params=body)
    assert served.status_code == 200, served.text
    document = served.json()
    assert document["contract_version"] == "provisional_league_ui_v1"
    payload = document["payload"]
    assert payload["entry_id"] == ENTRY_ID
    assert payload["league_id"] == LEAGUE_ID
    assert payload["season"] == SEASON
    assert payload["gameweek"] == 2
    assert payload["mode"] == COMPUTED_MODE
    assert payload["window"] == COMPUTED_WINDOW
    assert isinstance(payload["moves"], list)
    assert payload["solver_status"] in {"OPTIMAL", "FEASIBLE"}

    # A second ask is answered from the cache and starts no second solve.
    again = client.post(route, json=body)
    assert again.status_code == 200
    assert again.content == served.content
    assert backend.queue_depth() == 0
    assert len([job for job in backend.queue.jobs()]) == 1


def test_recomputing_one_job_produces_the_same_bytes(running: dict[str, Any]) -> None:
    """Byte-stability is what makes the cache's conflict check mean something.

    A wall-clock ``generated_at_utc`` would make an honest recomputation — after a
    recovered claim, say — indistinguishable from a determinism defect, so the document is
    stamped with the capture's instant instead.
    """

    backend = running["backend"]
    client = TestClient(app_for_backend(backend))
    route = f"/api/v1/leagues/{LEAGUE_ID}/entries/{ENTRY_ID}/advice"
    accepted = client.post(route, json={"strategy": COMPUTED_MODE, "window": COMPUTED_WINDOW})
    assert accepted.status_code == 202

    compute = build_advice_compute(backend.contexts, backend.job_specs)
    job = backend.queue.jobs()[0]
    first = compute(job)
    second = compute(job)
    assert first == second

    # Equal bytes alone would not prove this: two computes a moment apart share a
    # whole-second clock reading, so the field is pinned to its *source* instead.
    current = backend.contexts.current()
    assert current is not None
    capture = backend.contexts.capture(current)
    assert capture is not None
    assert json.loads(first)["generated_at_utc"] == capture.inputs.captured_at_utc
    assert capture.inputs.captured_at_utc != _now_stamp()


def test_a_failing_computation_ends_the_job_without_leaking_the_inside(
    running: dict[str, Any],
) -> None:
    backend = running["backend"]
    client = TestClient(app_for_backend(backend))
    route = f"/api/v1/leagues/{LEAGUE_ID}/entries/{ENTRY_ID}/advice"
    accepted = client.post(route, json={"strategy": COMPUTED_MODE, "window": COMPUTED_WINDOW})
    job_id = accepted.json()["job_id"]

    def explode(_job: AdviceJob) -> bytes:
        raise EntryError(f"secret path {backend.config.store_root} and a token abc123")

    run_advice_worker(
        backend.queue,
        backend.cache,
        explode,
        should_stop=_stop_after(3),
        max_jobs=1,
    )
    view = client.get(f"/api/v1/advice-jobs/{job_id}").json()
    assert view["status"] == "failed"
    assert view["error_code"] == "ADVICE_FAILED"
    assert "abc123" not in json.dumps(view)
    assert str(backend.config.store_root) not in json.dumps(view)

    served = client.get(route, params={"strategy": COMPUTED_MODE, "window": COMPUTED_WINDOW})
    assert served.status_code == 404, served.text
    assert "Traceback" not in served.text


def test_the_loop_stops_when_asked_and_finishes_the_job_in_hand(
    running: dict[str, Any],
) -> None:
    """A container stop must cost nobody their solve, and must not need a second signal."""

    backend = running["backend"]
    client = TestClient(app_for_backend(backend))
    client.post(
        f"/api/v1/leagues/{LEAGUE_ID}/entries/{ENTRY_ID}/advice",
        json={"strategy": COMPUTED_MODE, "window": COMPUTED_WINDOW},
    )
    stopped: list[bool] = []
    computed: list[str] = []

    def compute(job: AdviceJob) -> bytes:
        stopped.append(True)  # the signal lands mid-job
        computed.append(job.job_id)
        return b'{"contract_version":"x"}'

    def should_stop() -> bool:
        return bool(stopped)

    processed = run_advice_worker(
        backend.queue,
        backend.cache,
        compute,
        should_stop=should_stop,
        idle_seconds=0.0,
    )
    assert processed == 1
    assert len(computed) == 1
    assert backend.queue.jobs()[0].is_terminal


def test_an_empty_queue_waits_instead_of_spinning(running: dict[str, Any]) -> None:
    slept: list[float] = []
    calls: list[int] = []

    def should_stop() -> bool:
        calls.append(1)
        return len(calls) > 3

    run_advice_worker(
        running["backend"].queue,
        running["backend"].cache,
        lambda job: b"{}",
        should_stop=should_stop,
        sleep=slept.append,
        idle_seconds=1.0,
        poll_seconds=0.25,
    )
    assert slept  # it waited rather than claiming in a tight loop
    assert sum(slept) <= 4.0


def test_an_abandoned_job_is_walked_back_rather_than_lost(running: dict[str, Any]) -> None:
    """A worker that died mid-solve must not leave a member waiting forever."""

    backend = running["backend"]
    client = TestClient(app_for_backend(backend))
    client.post(
        f"/api/v1/leagues/{LEAGUE_ID}/entries/{ENTRY_ID}/advice",
        json={"strategy": COMPUTED_MODE, "window": COMPUTED_WINDOW},
    )
    claimed = backend.queue.claim(at_utc=_now_stamp())
    assert claimed is not None and claimed.status == "running"

    computed: list[str] = []

    def compute(job: AdviceJob) -> bytes:
        computed.append(job.job_id)
        return b'{"contract_version":"x"}'

    processed = run_advice_worker(
        backend.queue,
        backend.cache,
        compute,
        should_stop=lambda: bool(computed),
        lease_seconds=0.0,  # the previous claim's lease has plainly expired
        idle_seconds=0.0,
        max_jobs=1,
    )
    assert processed == 1
    assert computed == [claimed.job_id]
    assert backend.queue.jobs()[0].attempt == 2  # the retry is visible, not hidden


def test_an_ignored_rival_cannot_split_the_answer_or_the_spec(running: dict[str, Any]) -> None:
    """The api admits a rival on a rival-free strategy; the cache key drops it.

    So both requests address one answer, and the spec beside that address must drop the
    rival the same way. Without that normalization the second POST would meet a
    write-once store holding a different description of the same key — a 500 for a
    request the contract says is the first one again.

    One job, not two: the open-job index is keyed on the answer's address, so a parameter
    the strategy ignores cannot buy a second solve of the same plan.
    """

    backend = running["backend"]
    client = TestClient(app_for_backend(backend))
    route = f"/api/v1/leagues/{LEAGUE_ID}/entries/{ENTRY_ID}/advice"

    plain = client.post(route, json={"strategy": COMPUTED_MODE, "window": COMPUTED_WINDOW})
    with_rival = client.post(
        route,
        json={
            "strategy": COMPUTED_MODE,
            "window": COMPUTED_WINDOW,
            "rival_entry_id": RIVAL_ID,
        },
    )
    assert plain.status_code == 202, plain.text
    assert with_rival.status_code == 202, with_rival.text

    jobs = backend.queue.jobs()
    assert len(jobs) == 1
    assert len({job.cache_key for job in jobs}) == 1
    spec = backend.job_specs.get(jobs[0].cache_key)
    assert spec is not None
    assert spec.rival_entry_id is None

    processed = run_advice_worker(
        backend.queue,
        backend.cache,
        build_advice_compute(backend.contexts, backend.job_specs),
        should_stop=_stop_after(2 * len(jobs) + 2),
        idle_seconds=0.0,
        max_jobs=len(jobs),
    )
    assert processed == len(jobs)
    assert all(job.status == "completed" for job in backend.queue.jobs())


def test_a_changed_commit_under_the_same_capture_is_refused(running: dict[str, Any]) -> None:
    """A cache key is seven fields, not one.

    The capture is untouched; the deployment redeployed. Computing here would file an
    answer produced by new code under the old code's address — the same silent corruption
    a replaced capture would cause, reached through a different field.
    """

    backend = running["backend"]
    current = backend.contexts.current()
    assert current is not None
    stale = replace(current, repository_commit="9" * 40)
    key = "1" * 64
    backend.job_specs.put(key, _spec(context=stale))

    compute = build_advice_compute(backend.contexts, backend.job_specs)
    with pytest.raises(AdviceComputeRefused) as refusal:
        compute(_job(key))
    assert refusal.value.code == "CONTEXT_UNAVAILABLE"
    assert backend.cache.get(key) is None


def test_a_changed_configuration_under_the_same_capture_is_refused(
    running: dict[str, Any],
) -> None:
    backend = running["backend"]
    current = backend.contexts.current()
    assert current is not None
    stale = replace(current, configuration_fingerprint="2" * 64)
    key = "3" * 64
    backend.job_specs.put(key, _spec(context=stale))

    compute = build_advice_compute(backend.contexts, backend.job_specs)
    with pytest.raises(AdviceComputeRefused) as refusal:
        compute(_job(key))
    assert refusal.value.code == "CONTEXT_UNAVAILABLE"
    assert backend.cache.get(key) is None


def test_a_republished_handoff_replaces_the_context_without_a_new_capture(
    running: dict[str, Any],
) -> None:
    """Ops corrects a projection for the capture already loaded. The process must notice.

    Caching the context on the capture id alone made a corrected handoff invisible for the
    life of the process: every later answer would still be filed — and computed — under a
    projection that had been withdrawn.
    """

    backend = running["backend"]
    first = backend.contexts.current()
    assert first is not None

    deployment_module._handoff(running["handoff_root"], running["snapshot_id"], expected_points=7.5)
    second = backend.contexts.current()
    assert second is not None
    assert second.capture_snapshot_id == first.capture_snapshot_id
    assert second.projection_handoff_fingerprint != first.projection_handoff_fingerprint

    # And the withdrawn projection is no longer answerable.
    assert backend.contexts.capture(first) is None
    assert backend.contexts.capture(second) is not None


def test_a_request_in_a_new_context_does_not_join_the_old_contexts_open_job(
    running: dict[str, Any],
) -> None:
    """Dedup must be per answer, not per fingerprint.

    The request fingerprint omits the handoff, the commit and the configuration, so keying
    the open-job index on it handed the second caller a job whose result lands at an
    address that caller never reads: a completed job, then a "not computed" reply.
    """

    backend = running["backend"]
    client = TestClient(app_for_backend(backend))
    route = f"/api/v1/leagues/{LEAGUE_ID}/entries/{ENTRY_ID}/advice"
    body = {"strategy": COMPUTED_MODE, "window": COMPUTED_WINDOW}

    first = client.post(route, json=body)
    assert first.status_code == 202, first.text
    first_key = backend.queue.jobs()[0].cache_key

    deployment_module._handoff(
        running["handoff_root"], running["snapshot_id"], expected_points=8.25
    )
    second = client.post(route, json=body)
    assert second.status_code == 202, second.text

    assert second.json()["job_id"] != first.json()["job_id"]
    keys = {job.cache_key for job in backend.queue.jobs()}
    assert len(keys) == 2
    assert first_key in keys


def test_the_claim_stays_alive_while_a_long_computation_runs(
    running: dict[str, Any],
) -> None:
    """A live worker's claim must not look abandoned to a second worker.

    Driven with a short lease rather than a slow solve, so the test states the property
    without waiting five minutes for it.
    """

    backend = running["backend"]
    client = TestClient(app_for_backend(backend))
    client.post(
        f"/api/v1/leagues/{LEAGUE_ID}/entries/{ENTRY_ID}/advice",
        json={"strategy": COMPUTED_MODE, "window": COMPUTED_WINDOW},
    )
    stolen: list[str] = []

    def slow(job: AdviceJob) -> bytes:
        # While this "solve" runs, a second worker's recovery sweep looks at the queue.
        time.sleep(0.35)
        recovered = backend.queue.recover(at_utc=_now_stamp(), lease_seconds=0.2)
        stolen.extend(one.job_id for one in recovered)
        return b'{"contract_version":"x"}'

    processed = run_advice_worker_once(
        backend.queue,
        backend.cache,
        slow,
        at_utc=_now_stamp(),
        heartbeat_seconds=0.05,
    )
    assert processed is not None and processed.status == "completed"
    assert stolen == [], "a heartbeat-refreshed claim was recovered from under its owner"
