"""The worker: a claimed job becomes a real answer, or a stated refusal.

The end-to-end test here runs the actual ``advise_entry`` against a real capture and a real
projection handoff, through the real queue and the real cache. It is not a measurement and
it fits no scientific claim; it is the check that the parts compose into the thing a member
presses a button for.
"""

import json
import logging
import threading
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
import tests.unit.test_top100_weight as top100_tests
from fastapi.testclient import TestClient
from tests.fixtures.backend_app import app_for_capture
from tests.unit.test_projection_horizon_builder import _calendar

import squadopt.application.top100_weight as switches_module_top100
import squadopt.platform.advice_switches as switches_module
import squadopt.platform.advice_worker as worker_module
from squadopt.application.advice import (
    COMPUTED_MODE,
    COMPUTED_WINDOW,
    AdviseEntryRequest,
    EntryError,
    advise_entry,
    advise_with_top100,
)
from squadopt.application.advice_menu import ManagersWordNotSolved
from squadopt.application.weekly_plan import rotation_artifact
from squadopt.data.snapshots import write_snapshot
from squadopt.platform.advice_cache import FileAdviceCache
from squadopt.platform.advice_job_spec import (
    AdviceJobSpec,
    AdviceJobSpecConflictError,
    FileAdviceJobSpecStore,
)
from squadopt.platform.advice_observability import (
    WORKER_COUNTER_FAMILIES,
    AdviceLog,
    AdviceMetrics,
)
from squadopt.platform.advice_queue import (
    AdviceComputeRefused,
    FileJobQueue,
    run_advice_worker_once,
)
from squadopt.platform.advice_read import AdviceRequestContext
from squadopt.platform.advice_worker import build_advice_compute, run_advice_worker
from squadopt.platform.backend_runtime import BackendConfig, build_backend
from squadopt.platform.jobs_contract import AdviceJob
from squadopt.platform.queue_contracts import QueueLockTimeout

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
            FIXTURES_PAYLOAD: _calendar(gameweeks=(1, 2, 3)),
            **_entry_payloads(ENTRY_ID, 1),
        },
    )
    return written.snapshot_id


@pytest.fixture(name="running")
def _running(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """A deployment whose capture actually holds the member's squad."""

    return _deployment(tmp_path, monkeypatch)


def _deployment(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, **configured: Any
) -> dict[str, Any]:
    monkeypatch.setenv("SQUADOPT_REPOSITORY_COMMIT", "c" * 40)
    snapshot_root = tmp_path / "snapshots"
    handoff_root = tmp_path / "handoffs"
    site_root = tmp_path / "site"
    snapshot_id = _capture_with_entries(snapshot_root)
    deployment_module._handoff(handoff_root, snapshot_id)
    deployment_module._publish_members(site_root, RIVAL_ID)
    store_root = tmp_path / "store"
    store_root.mkdir()
    backend = build_backend(
        BackendConfig(
            store_root=store_root,
            site_data_root=site_root,
            snapshot_root=snapshot_root,
            handoff_root=handoff_root,
            **configured,
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


@pytest.mark.parametrize("fails", [False, True])
def test_workers_warm_before_claiming_and_again_when_the_identity_changes(
    running: dict[str, Any], monkeypatch: pytest.MonkeyPatch, fails: bool
) -> None:
    backend = running["backend"]
    loaded: list[str] = []
    events: list[tuple[str, dict[str, object]]] = []
    capture = backend.contexts.capture
    claim = backend.queue.claim
    rounds = 0

    def warm(context):
        loaded.append(context.projection_handoff_fingerprint)
        if fails:
            raise OSError("synthetic unreadable capture")
        return capture(context)

    def checked_claim(**kwargs):
        nonlocal rounds
        assert len(loaded) == (1 if rounds < 2 else 2)
        rounds += 1
        if rounds == 2:
            deployment_module._handoff(
                running["handoff_root"], running["snapshot_id"], expected_points=4.0
            )
        return claim(**kwargs)

    monkeypatch.setattr(backend.contexts, "capture", warm)
    monkeypatch.setattr(backend.queue, "claim", checked_claim)
    monkeypatch.setattr(
        backend.log, "event", lambda event, **fields: events.append((event, fields))
    )
    assert (
        run_advice_worker(
            backend.queue,
            backend.cache,
            lambda job: b"unused",
            contexts=backend.contexts,
            log=backend.log,
            should_stop=_stop_after(3),
            idle_seconds=0,
        )
        == 0
    )
    assert rounds == 3 and len(set(loaded)) == 2
    reported = [
        fields
        for event, fields in events
        if event == ("advice_worker_warm_failed" if fails else "advice_worker_warmed")
    ]
    assert len(reported) == 2
    assert all(fields["snapshot_id"] == running["snapshot_id"] for fields in reported)
    if not fails:
        assert all(
            isinstance(fields["seconds"], float) and fields["seconds"] >= 0 for fields in reported
        )
        assert all(fields["seconds"] == round(fields["seconds"], 3) for fields in reported)


def test_a_locked_capture_directory_does_not_stop_worker_claims(running, monkeypatch):
    backend = running["backend"]
    claims, events = [], []

    def unavailable():
        raise PermissionError("synthetic locked capture directory")

    monkeypatch.setattr(backend.contexts, "current", unavailable)
    monkeypatch.setattr(backend.queue, "claim", lambda **kwargs: claims.append(True))
    monkeypatch.setattr(
        backend.log, "event", lambda event, **fields: events.append((event, fields))
    )
    assert (
        run_advice_worker(
            backend.queue,
            backend.cache,
            lambda job: b"unused",
            contexts=backend.contexts,
            log=backend.log,
            should_stop=_stop_after(1),
            idle_seconds=0,
        )
        == 0
    )
    assert claims == [True]
    assert events == [
        (
            "advice_worker_warm_failed",
            {
                "reason": "synthetic locked capture directory",
                "snapshot_id": None,
            },
        )
    ]


@pytest.mark.parametrize(
    "error_code", [None, "ADVICE_FAILED", "CONTEXT_UNAVAILABLE", "DETERMINISM_DEFECT"]
)
def test_terminal_timestamp_is_read_after_computation(
    tmp_path: Path, error_code: str | None, caplog: pytest.LogCaptureFixture
) -> None:
    queue = FileJobQueue(tmp_path / "jobs")
    cache = FileAdviceCache(tmp_path / "cache")
    queued = replace(_job("a" * 64), status="queued")
    queue.submit(queued)
    original = b'{"answer":"original"}'
    answer = b'{"answer":"computed"}'
    if error_code == "DETERMINISM_DEFECT":
        cache.put(queued.cache_key, original)
    claimed_at = datetime(2026, 9, 1, 10, 1, tzinfo=UTC)
    finished_at = datetime(2026, 9, 1, 10, 2, tzinfo=UTC)
    clock = [claimed_at]
    claims: list[AdviceJob] = []
    fields: dict[str, object] = {}

    def compute(job: AdviceJob) -> bytes:
        fields.update(window=3, strategy="saf-puan")
        claims.append(job)
        clock[0] = finished_at
        if error_code == "ADVICE_FAILED":
            raise RuntimeError("Computation failed.")
        if error_code == "CONTEXT_UNAVAILABLE":
            raise AdviceComputeRefused(error_code, "The context is no longer available.")
        return answer

    caplog.set_level(logging.INFO, logger="advice.worker")
    processed = run_advice_worker(
        queue,
        cache,
        compute,
        should_stop=_stop_after(1),
        now=lambda: clock[0],
        max_jobs=1,
        heartbeat_seconds=None,
        log=AdviceLog("worker"),
        job_log_fields=fields,
    )

    assert processed == 1
    events = [
        json.loads(record.message) for record in caplog.records if record.name == "advice.worker"
    ]
    terminal_event = events[-1]
    assert terminal_event["window"] == 3 and terminal_event["strategy"] == "saf-puan"
    assert len(claims) == 1 and claims[0].status == "running"
    assert claims[0].updated_at_utc == "2026-09-01T10:01:00Z"
    terminal = queue.load(queued.job_id)
    assert terminal is not None
    assert terminal.created_at_utc == queued.created_at_utc
    assert terminal.updated_at_utc == "2026-09-01T10:02:00Z"
    if error_code is None:
        assert terminal.status == "completed" and terminal.error is None
        assert terminal.result_ref == queued.cache_key
        assert cache.get(queued.cache_key) == answer
    else:
        assert terminal.status == "failed" and terminal.result_ref is None
        assert terminal.error is not None and terminal.error.code == error_code
        expected = original if error_code == "DETERMINISM_DEFECT" else None
        assert cache.get(queued.cache_key) == expected


def test_claim_clears_previous_coordinates_before_an_early_callback_failure(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    queue = FileJobQueue(tmp_path / "jobs")
    queue.submit(replace(_job("a" * 64), status="queued"))
    fields: dict[str, object] = {"window": 5, "strategy": "fark-yarat"}

    def compute(job: AdviceJob) -> bytes:
        raise RuntimeError("Failed before reading a specification.")

    caplog.set_level(logging.INFO, logger="advice.worker")
    result = run_advice_worker_once(
        queue,
        FileAdviceCache(tmp_path / "cache"),
        compute,
        at_utc="2026-09-01T10:01:00Z",
        log=AdviceLog("worker"),
        job_log_fields=fields,
    )
    assert result is not None and result.status == "failed"
    events = [
        json.loads(record.message) for record in caplog.records if record.name == "advice.worker"
    ]
    assert events[-1]["event"] == "advice_job_failed"
    assert "window" not in events[-1] and "strategy" not in events[-1]


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
    store_root = tmp_path / "store"
    store_root.mkdir()
    backend = build_backend(
        BackendConfig(
            store_root=store_root,
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
    store_root = tmp_path / "store"
    store_root.mkdir()
    backend = build_backend(
        BackendConfig(
            store_root=store_root,
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
    fields: dict[str, object] = {}
    compute = build_advice_compute(backend.contexts, backend.job_specs, job_log_fields=fields)

    with pytest.raises(AdviceComputeRefused) as refusal:
        compute(_job(key))
    assert refusal.value.code == "CONTEXT_UNAVAILABLE"
    assert fields == {"window": COMPUTED_WINDOW, "strategy": COMPUTED_MODE}
    # A following job with no readable spec must not inherit the previous coordinates.
    with pytest.raises(AdviceComputeRefused) as unreadable:
        compute(_job("d" * 64))
    assert unreadable.value.code == "REQUEST_UNREADABLE"
    assert fields == {}
    assert backend.cache.get(key) is None

    job = run_advice_worker_once(
        backend.queue, backend.cache, compute, at_utc="2026-09-01T10:01:00Z"
    )
    assert job is None  # nothing was queued; the refusal above is the whole story


@pytest.mark.parametrize("chip", [None, "bboost"])
def test_a_member_presses_the_button_and_gets_a_computed_answer(
    running: dict[str, Any],
    chip: str | None,
) -> None:
    """POST, worker, GET — the actual request this backend exists to serve."""

    backend = running["backend"]
    client = TestClient(app_for_capture(backend, world_module.GW2_CAPTURED_AT))
    route = f"/api/v1/leagues/{LEAGUE_ID}/entries/{ENTRY_ID}/advice"
    body = {"strategy": COMPUTED_MODE, "window": COMPUTED_WINDOW}
    if chip is not None:
        body["chip"] = chip
        capabilities = client.get(f"/api/v1/leagues/{LEAGUE_ID}/capabilities").json()
        assert chip in capabilities["chips"]["held_by_entry"][str(ENTRY_ID)]

    accepted = client.post(route, json=body)
    assert accepted.status_code == 202, accepted.text
    job_id = accepted.json()["job_id"]
    assert client.get(f"/api/v1/advice-jobs/{job_id}").json()["status"] == "queued"

    fields: dict[str, object] = {}
    processed = run_advice_worker(
        backend.queue,
        backend.cache,
        build_advice_compute(backend.contexts, backend.job_specs, job_log_fields=fields),
        should_stop=_stop_after(3),
        max_jobs=1,
        metrics=backend.metrics,
        log=backend.log,
        job_log_fields=fields,
    )
    assert processed == 1
    assert fields == {"window": COMPUTED_WINDOW, "strategy": COMPUTED_MODE}
    finished = client.get(f"/api/v1/advice-jobs/{job_id}").json()
    assert finished["status"] == "completed", json.dumps(finished)

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
    if chip is not None:
        assert payload["chip_choice"]["chip"] == chip

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
    client = TestClient(app_for_capture(backend, world_module.GW2_CAPTURED_AT))
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
    client = TestClient(app_for_capture(backend, world_module.GW2_CAPTURED_AT))
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
    client = TestClient(app_for_capture(backend, world_module.GW2_CAPTURED_AT))
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

    give_up = _stop_after(4)

    def should_stop() -> bool:
        # Bounded as well as intentional: if the POST above ever fails to queue anything,
        # "stop once a job has been computed" never becomes true and this hangs the suite
        # instead of failing it.
        return bool(stopped) or give_up()

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
    client = TestClient(app_for_capture(backend, world_module.GW2_CAPTURED_AT))
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


def test_a_rival_free_request_refuses_a_rival_without_changing_the_spec(
    running: dict[str, Any],
) -> None:
    """Reader and worker agree; an unsupported rival cannot create another job/spec."""

    backend = running["backend"]
    client = TestClient(app_for_capture(backend, world_module.GW2_CAPTURED_AT))
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
    assert with_rival.status_code == 422, with_rival.text
    assert with_rival.json()["error"]["code"] == "UNSUPPORTED_ADVICE_REQUEST"

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
    client = TestClient(app_for_capture(backend, world_module.GW2_CAPTURED_AT))
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
    client = TestClient(app_for_capture(backend, world_module.GW2_CAPTURED_AT))
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


def test_an_idempotency_key_replayed_in_a_new_context_is_a_conflict(
    running: dict[str, Any],
) -> None:
    """The key names a retry of one request, and the answer moved out from under it.

    The fingerprint cannot see a republished handoff, so the replay matched the older job
    and was handed it with a 202. The caller would poll that job to completion and then be
    told its own answer had never been computed.
    """

    backend = running["backend"]
    client = TestClient(app_for_capture(backend, world_module.GW2_CAPTURED_AT))
    route = f"/api/v1/leagues/{LEAGUE_ID}/entries/{ENTRY_ID}/advice"
    body = {"strategy": COMPUTED_MODE, "window": COMPUTED_WINDOW}
    header = {"Idempotency-Key": "client:advise:merge-review"}

    first = client.post(route, json=body, headers=header)
    assert first.status_code == 202, first.text

    # The same key, replayed under the same context, still means "this again".
    replay = client.post(route, json=body, headers=header)
    assert replay.status_code == 202, replay.text
    assert replay.json()["job_id"] == first.json()["job_id"]

    deployment_module._handoff(
        running["handoff_root"], running["snapshot_id"], expected_points=6.75
    )
    moved = client.post(route, json=body, headers=header)
    assert moved.status_code == 409, moved.text
    assert moved.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    # And no job was created for the new context under the old job's name.
    assert len(backend.queue.jobs()) == 1


def test_two_concurrent_contexts_get_two_job_ids_rather_than_a_collision(
    running: dict[str, Any],
) -> None:
    """A redeploy sharing a mount: same store, same capture, same request, two commits.

    It has to be concurrent to bite. Run in sequence, the second submission counts the
    first and picks the next ordinal, so the names differ by accident. Run together — both
    reading the queue before either writes, which is what two api replicas do — naming the
    job after the request fingerprint gives them one name, and a create-once name means one
    caller gets 202 and the other a 500.

    The barrier sits inside the queue read, so the interleaving is pinned rather than hoped
    for, and it has a timeout so a regression fails rather than hangs.
    """

    config = running["backend"].config
    older = build_backend(config)
    with pytest.MonkeyPatch.context() as redeployed:
        redeployed.setenv("SQUADOPT_REPOSITORY_COMMIT", "d" * 40)
        newer = build_backend(config)

    assert older.contexts.current() != newer.contexts.current()
    # Warm both gates here, in one thread. The race under test is the queue read; letting
    # two threads probe the same store at once would add noise this test is not about.
    assert older.probe.passed() and newer.probe.passed()

    barrier = threading.Barrier(2)

    class _Together:
        """The real queue, with both submitters made to read history at the same moment."""

        def __init__(self, inner: Any) -> None:
            self._inner = inner

        def __getattr__(self, name: str) -> Any:
            return getattr(self._inner, name)

        def jobs(self) -> Any:
            history = self._inner.jobs()
            barrier.wait(timeout=10.0)
            return history

    outcomes: dict[str, Any] = {}

    def submit(name: str, backend: Any) -> None:
        try:
            outcomes[name] = backend.submit.submit(
                league_id=LEAGUE_ID,
                entry_id=ENTRY_ID,
                strategy=COMPUTED_MODE,
                window=COMPUTED_WINDOW,
                rival_entry_id=None,
                idempotency_key=None,
                client_bucket="test",
                at_utc=world_module.GW2_CAPTURED_AT,
            )
        except Exception as error:  # recorded, so the assertion names it
            outcomes[name] = error

    threads = [
        threading.Thread(target=submit, args=("older", older), daemon=True),
        threading.Thread(target=submit, args=("newer", newer), daemon=True),
    ]
    for backend in (older, newer):
        object.__setattr__(backend.submit, "_queue", _Together(backend.queue))
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=30.0)
        assert not thread.is_alive()

    for name, outcome in outcomes.items():
        assert not isinstance(outcome, Exception), f"{name}: {outcome!r}"
        assert outcome.job is not None

    jobs = older.queue.jobs()
    assert len({job.job_id for job in jobs}) == 2, jobs
    assert len({job.cache_key for job in jobs}) == 2, jobs


def test_a_store_that_breaks_later_stops_the_worker_taking_new_work(
    running: dict[str, Any],
) -> None:
    """Healthy at startup is not healthy for ever, and the gate is asked every round."""

    backend = running["backend"]
    client = TestClient(app_for_capture(backend, world_module.GW2_CAPTURED_AT))
    client.post(
        f"/api/v1/leagues/{LEAGUE_ID}/entries/{ENTRY_ID}/advice",
        json={"strategy": COMPUTED_MODE, "window": COMPUTED_WINDOW},
    )
    claims: list[str] = []
    recoveries: list[str] = []

    class _Watched:
        """The real queue, with the two calls that take work made observable."""

        def __init__(self, inner: Any) -> None:
            self._inner = inner

        def __getattr__(self, name: str) -> Any:
            return getattr(self._inner, name)

        def claim(self, *, at_utc=None, clock=None) -> Any:
            result = self._inner.claim(at_utc=at_utc, clock=clock)
            claims.append(result.updated_at_utc if result else "empty")
            return result

        def recover(self, *, at_utc=None, clock=None, lease_seconds: float = 300.0) -> Any:
            result = self._inner.recover(at_utc=at_utc, clock=clock, lease_seconds=lease_seconds)
            recoveries.append(result[0].updated_at_utc if result else "empty")
            return result

    healthy = [True]
    processed = run_advice_worker(
        _Watched(backend.queue),
        backend.cache,
        lambda job: b'{"contract_version":"x"}',
        should_stop=_stop_after(4),
        store_ready=lambda: healthy[0],
        idle_seconds=0.0,
        heartbeat_seconds=None,
    )
    assert processed == 1
    assert claims and recoveries

    healthy[0] = False
    before_claims, before_recoveries = len(claims), len(recoveries)
    run_advice_worker(
        _Watched(backend.queue),
        backend.cache,
        lambda job: b'{"contract_version":"x"}',
        should_stop=_stop_after(5),
        store_ready=lambda: healthy[0],
        idle_seconds=0.0,
        heartbeat_seconds=None,
    )
    assert len(claims) == before_claims, "a broken store was still claimed against"
    assert len(recoveries) == before_recoveries, "a broken store was still recovered from"


# --- the worker survives a busy queue and names what it cannot read ----------------------


class _BusyThenFine:
    """A queue whose lock is held by someone else for its first two transactions."""

    def __init__(self, queue: FileJobQueue) -> None:
        self._queue = queue
        self.refused: list[str] = []

    def __getattr__(self, name: str) -> Any:
        return getattr(self._queue, name)

    def recover(self, **kwargs: Any) -> Any:
        if "recover" not in self.refused:
            self.refused.append("recover")
            raise QueueLockTimeout("Queue metadata transaction is busy.")
        return self._queue.recover(**kwargs)

    def claim(self, **kwargs: Any) -> Any:
        if "claim" not in self.refused:
            self.refused.append("claim")
            raise QueueLockTimeout("Queue metadata transaction is busy.")
        return self._queue.claim(**kwargs)


def test_a_busy_queue_lock_does_not_end_the_worker(running: dict[str, Any]) -> None:
    backend = running["backend"]
    client = TestClient(app_for_capture(backend, world_module.GW2_CAPTURED_AT))
    route = f"/api/v1/leagues/{LEAGUE_ID}/entries/{ENTRY_ID}/advice"
    assert client.post(route, json={"strategy": COMPUTED_MODE, "window": 1}).status_code == 202
    queue = _BusyThenFine(backend.queue)
    waits: list[float] = []

    processed = run_advice_worker(
        queue,
        backend.cache,
        lambda _job: b'{"computed":true}',
        should_stop=_stop_after(40),
        sleep=waits.append,
        idle_seconds=0.5,
        poll_seconds=0.5,
        max_jobs=1,
        metrics=backend.metrics,
    )

    # Both refusals were waited out, a recovery that could not run was tried again on the
    # next round, and the job was still computed by the same process.
    assert queue.refused == ["recover", "claim"]
    assert processed == 1
    assert len(waits) >= 2
    assert "advice_worker_queue_busy_total 2" in backend.metrics.render(queue_depth=0)


# --- the worker survives an unexpected error in a round ----------------------------------


class _Flaky:
    """A queue whose named operation raises the queued errors first; ``None`` lets one through."""

    def __init__(self, queue: FileJobQueue, operation: str, errors: list[Exception | None]) -> None:
        self._queue = queue
        self._operation = operation
        self._errors = errors
        self.raised: list[str] = []

    def __getattr__(self, name: str) -> Any:
        real = getattr(self._queue, name)
        if name != self._operation:
            return real

        def flaky(*args: Any, **kwargs: Any) -> Any:
            error = self._errors.pop(0) if self._errors else None
            if error is not None:
                self.raised.append(type(error).__name__)
                raise error
            return real(*args, **kwargs)

        return flaky


def _queued(
    job_id: str = "advice-0123456789abcdef-1", at: str = "2026-09-01T10:00:00Z"
) -> AdviceJob:
    return replace(
        _job("a" * 64), job_id=job_id, status="queued", created_at_utc=at, updated_at_utc=at
    )


def test_an_error_from_claim_does_not_end_the_worker(
    tmp_path: Path, caplog: pytest.LogCaptureFixture
) -> None:
    queue = FileJobQueue(tmp_path / "jobs")
    queue.submit(_queued())
    flaky = _Flaky(queue, "claim", [PermissionError(13, "Access is denied")])
    metrics = AdviceMetrics(zero_counters=WORKER_COUNTER_FAMILIES)
    waits: list[float] = []
    caplog.set_level(logging.INFO, logger="advice.worker")

    processed = run_advice_worker(
        flaky,
        FileAdviceCache(tmp_path / "cache"),
        lambda _job: b'{"computed":true}',
        should_stop=_stop_after(20),
        sleep=waits.append,
        idle_seconds=0.5,
        poll_seconds=0.5,
        max_jobs=1,
        heartbeat_seconds=None,
        metrics=metrics,
        log=AdviceLog("worker"),
    )

    # The claim that raised was logged and waited out, and the same process then took the
    # next job and finished it.
    assert flaky.raised == ["PermissionError"]
    assert processed == 1
    done = queue.load(_queued().job_id)
    assert done is not None and done.status == "completed"
    assert waits == [0.5]
    events = [
        json.loads(record.getMessage())
        for record in caplog.records
        if record.name == "advice.worker"
    ]
    failed = [event for event in events if event["event"] == "advice_worker_round_failed"]
    assert len(failed) == 1
    assert failed[0]["error_type"] == "PermissionError"
    assert failed[0]["consecutive"] == 1 and failed[0]["backoff_seconds"] == 0.5
    assert "Traceback" in failed[0]["trace"]
    assert "advice_worker_round_failed_total 1" in metrics.render()


def test_rounds_that_keep_failing_back_off_up_to_a_cap_and_a_good_round_resets_it(
    tmp_path: Path,
) -> None:
    queue = FileJobQueue(tmp_path / "jobs")
    queue.submit(_queued("advice-0123456789abcdef-1", "2026-09-01T10:00:00Z"))
    queue.submit(_queued("advice-0123456789abcdef-2", "2026-09-01T10:00:01Z"))
    errors: list[Exception | None] = [OSError("store gone") for _ in range(3)]
    flaky = _Flaky(queue, "claim", [*errors, None, OSError("store gone"), None])
    waits: list[float] = []

    processed = run_advice_worker(
        flaky,
        FileAdviceCache(tmp_path / "cache"),
        lambda _job: b'{"computed":true}',
        should_stop=_stop_after(40),
        sleep=waits.append,
        idle_seconds=0.5,
        poll_seconds=10.0,
        max_backoff_seconds=1.5,
        max_jobs=2,
        heartbeat_seconds=None,
    )

    assert processed == 2
    # Doubling from one idle, held at the cap, and back to one idle after a good round.
    assert waits == [0.5, 1.0, 1.5, 0.5]


def test_a_failure_record_that_cannot_be_written_leaves_the_job_to_recovery(
    tmp_path: Path,
) -> None:
    queue = FileJobQueue(tmp_path / "jobs")
    queue.submit(_queued())
    flaky = _Flaky(queue, "store", [PermissionError(13, "Access is denied")])
    attempts: list[int] = []

    def compute(job: AdviceJob) -> bytes:
        attempts.append(job.attempt)
        if job.attempt == 1:
            raise RuntimeError("the first attempt fails")
        return b'{"computed":true}'

    processed = run_advice_worker(
        flaky,
        FileAdviceCache(tmp_path / "cache"),
        compute,
        should_stop=_stop_after(20),
        sleep=lambda _seconds: None,
        idle_seconds=0.5,
        poll_seconds=0.5,
        recover_every_seconds=0.0,
        lease_seconds=0.0,
        max_jobs=1,
        heartbeat_seconds=None,
    )

    assert flaky.raised == ["PermissionError"]
    assert processed == 1 and attempts == [1, 2]
    done = queue.load(_queued().job_id)
    assert done is not None and done.status == "completed" and done.attempt == 2


def test_a_clock_behind_a_jobs_stamp_is_waited_out_rather_than_fatal(tmp_path: Path) -> None:
    queue = FileJobQueue(tmp_path / "jobs")
    queue.submit(_queued(at="2026-09-01T10:05:00Z"))
    clock = [datetime(2026, 9, 1, 10, 0, tzinfo=UTC)]  # five minutes behind the job
    waits: list[float] = []

    def sleep(seconds: float) -> None:
        waits.append(seconds)
        clock[0] = datetime(2026, 9, 1, 10, 6, tzinfo=UTC)  # the clock catches up

    processed = run_advice_worker(
        queue,
        FileAdviceCache(tmp_path / "cache"),
        lambda _job: b'{"computed":true}',
        should_stop=_stop_after(20),
        now=lambda: clock[0],
        sleep=sleep,
        idle_seconds=0.5,
        poll_seconds=0.5,
        max_jobs=1,
        heartbeat_seconds=None,
    )

    assert processed == 1 and waits == [0.5]
    done = queue.load(_queued().job_id)
    assert done is not None and done.status == "completed"


@pytest.mark.parametrize("stop", [KeyboardInterrupt, SystemExit])
def test_an_interrupt_still_ends_the_worker(tmp_path: Path, stop: type[BaseException]) -> None:
    queue = FileJobQueue(tmp_path / "jobs")
    queue.submit(_queued())

    class _Interrupted:
        def __getattr__(self, name: str) -> Any:
            return getattr(queue, name)

        def claim(self, **_kwargs: Any) -> Any:
            raise stop()

    with pytest.raises(stop):
        run_advice_worker(
            _Interrupted(),
            FileAdviceCache(tmp_path / "cache"),
            lambda _job: b'{"computed":true}',
            should_stop=_stop_after(20),
            sleep=lambda _seconds: None,
            idle_seconds=0.5,
            heartbeat_seconds=None,
        )


def test_an_unreadable_spec_is_a_request_unreadable_refusal(running: dict[str, Any]) -> None:
    backend = running["backend"]
    compute = build_advice_compute(backend.contexts, backend.job_specs)
    store = running["backend"].config.spec_root
    for key, stored in (
        ("a" * 64, b"not json at all"),
        ("b" * 64, b'{"contract_version":"advice_job_spec_v1","league_id":1}'),
        ("c" * 64, json.dumps({**_spec().as_payload(), "switches": {"top100": {}}}).encode()),
    ):
        path = store / key[:2] / f"{key}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(stored)
        with pytest.raises(AdviceComputeRefused) as refusal:
            compute(_job(key))
        assert refusal.value.code == "REQUEST_UNREADABLE", stored


def test_a_member_the_capture_does_not_hold_is_named_not_a_generic_failure(
    running: dict[str, Any],
) -> None:
    """The member directory lists the rival; the capture holds only the member's squad."""

    backend = running["backend"]
    client = TestClient(app_for_capture(backend, world_module.GW2_CAPTURED_AT))
    compute = build_advice_compute(backend.contexts, backend.job_specs)
    for entry, body in (
        (RIVAL_ID, {"strategy": COMPUTED_MODE, "window": 1}),
        (ENTRY_ID, {"strategy": "ortak-koru", "window": 1, "rival_entry_id": RIVAL_ID}),
    ):
        accepted = client.post(f"/api/v1/leagues/{LEAGUE_ID}/entries/{entry}/advice", json=body)
        assert accepted.status_code == 202, accepted.text
        job = run_advice_worker_once(backend.queue, backend.cache, compute, at_utc=_now_stamp())
        assert job is not None and job.status == "failed"
        assert job.error is not None and job.error.code == "ENTRY_NOT_IN_CAPTURE"
        view = client.get(f"/api/v1/advice-jobs/{job.job_id}").json()
        assert view["error_code"] == "ENTRY_NOT_IN_CAPTURE"


def test_a_word_not_solved_for_one_member_is_named_not_a_generic_failure(
    running: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The menu says the word could not be applied; the job carries that, not a fault."""

    backend = running["backend"]
    client = TestClient(app_for_capture(backend, world_module.GW2_CAPTURED_AT))

    def not_solved(*_args: Any, **_kwargs: Any) -> dict[str, object]:
        raise ManagersWordNotSolved("The manager's word could not be applied to this plan.")

    monkeypatch.setattr(worker_module, "advise_menu_entry", not_solved)
    accepted = client.post(
        f"/api/v1/leagues/{LEAGUE_ID}/entries/{ENTRY_ID}/advice",
        json={"strategy": COMPUTED_MODE, "window": 1},
    )
    assert accepted.status_code == 202, accepted.text
    compute = build_advice_compute(backend.contexts, backend.job_specs)
    job = run_advice_worker_once(backend.queue, backend.cache, compute, at_utc=_now_stamp())
    assert job is not None and job.status == "failed"
    assert job.error is not None and job.error.code == "MANAGERS_WORD_NOT_SOLVED"
    assert job.error.message == "The manager's word could not be applied to this plan."
    view = client.get(f"/api/v1/advice-jobs/{job.job_id}").json()
    assert (view["status"], view["error_code"]) == ("failed", "MANAGERS_WORD_NOT_SOLVED")
    # Any other refusal from the menu is still the unexpected failure it was.
    monkeypatch.setattr(
        worker_module,
        "advise_menu_entry",
        lambda *_a, **_k: (_ for _ in ()).throw(EntryError("something else")),
    )
    again = client.post(
        f"/api/v1/leagues/{LEAGUE_ID}/entries/{ENTRY_ID}/advice",
        json={"strategy": COMPUTED_MODE, "window": 1},
    )
    assert again.status_code == 202, again.text
    other = run_advice_worker_once(backend.queue, backend.cache, compute, at_utc=_now_stamp())
    assert other is not None and other.error is not None
    assert other.error.code == "ADVICE_FAILED"


# --- the member menu's switches, through the real solver ---------------------------------


def _served_bytes(backend: Any, advice: dict[str, Any], captured_at_utc: str) -> bytes:
    document = {
        "contract_version": "provisional_league_ui_v1",
        "generated_at_utc": captured_at_utc,
        "source_kind": "live",
        "payload": advice,
    }
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")


def test_a_plain_request_is_cached_as_advise_entrys_own_bytes(running: dict[str, Any]) -> None:
    """The default path through ``advise_menu_entry`` moves no byte of what is served."""

    backend = running["backend"]
    client = TestClient(app_for_capture(backend, world_module.GW2_CAPTURED_AT))
    route = f"/api/v1/leagues/{LEAGUE_ID}/entries/{ENTRY_ID}/advice"
    body = {"strategy": COMPUTED_MODE, "window": COMPUTED_WINDOW}
    job_id = client.post(route, json=body).json()["job_id"]
    compute = build_advice_compute(backend.contexts, backend.job_specs, cache=backend.cache)
    done = run_advice_worker_once(backend.queue, backend.cache, compute, at_utc=_now_stamp())
    assert done is not None and done.status == "completed", done

    job = backend.queue.load(job_id)
    spec = backend.job_specs.get(job.cache_key)
    assert spec.switches == {} and "switches" not in spec.as_payload()
    capture = backend.contexts.capture(spec.context)
    expected = advise_entry(
        AdviseEntryRequest(season=SEASON, gameweek=2, league_id=LEAGUE_ID, entry_id=ENTRY_ID),
        provider=capture.provider,
        inputs=capture.inputs,
        projection=capture.projection,
        rules=capture.rules,
        horizon_builder=capture.horizon_builder,
    )
    assert backend.cache.get(job.cache_key) == _served_bytes(
        backend, expected, capture.inputs.captured_at_utc
    )


def _work(backend: Any, jobs: int = 1) -> int:
    return run_advice_worker(
        backend.queue,
        backend.cache,
        build_advice_compute(backend.contexts, backend.job_specs, cache=backend.cache),
        should_stop=_stop_after(3 * jobs + 3),
        max_jobs=jobs,
        idle_seconds=0.0,
        metrics=backend.metrics,
    )


def test_preferences_round_trip_through_http_worker_cache(running):
    backend = running["backend"]
    client = TestClient(app_for_capture(backend, world_module.GW2_CAPTURED_AT))
    route = f"/api/v1/leagues/{LEAGUE_ID}/entries/{ENTRY_ID}/advice"
    preferences = {
        "keep_players": [1001, 1004],
        "avoid_players": [],
        "no_hits": True,
        "save_chips": True,
    }
    body = {"strategy": "saf-puan", "window": 1, "preferences": preferences}
    response = client.post(route, json=body, headers={"Idempotency-Key": "preferences:one"})
    assert response.status_code == 202, response.text
    assert _work(backend) == 1
    result = client.get(
        route, params={"strategy": "saf-puan", "window": 1, "preferences": json.dumps(preferences)}
    )
    assert result.status_code == 200, result.text
    payload = result.json()["payload"]
    assert payload["preferences"] == preferences
    assert payload["transfer_hit_points"] == 0
    assert {1001, 1004} <= {p["player_id"] for p in payload["starting_xi"] + payload["bench"]}
    assert client.get(route, params={"strategy": "saf-puan", "window": 1}).status_code == 404
    conflict = client.post(
        route,
        json={**body, "preferences": {"no_hits": False}},
        headers={"Idempotency-Key": "preferences:one"},
    )
    assert conflict.status_code == 409
    invalid = client.post(
        route, json={**body, "preferences": {"keep_players": [1], "avoid_players": [1]}}
    )
    assert invalid.status_code == 422
    # Ids the capture does not have for this member are refused before a job exists:
    # 1002 is on the roster but not in the fifteen, 1025 is not on the roster at all.
    jobs_before = backend.queue.jobs()
    for unknown in ({"keep_players": [1002]}, {"avoid_players": [1025]}):
        refused = client.post(route, json={**body, "preferences": unknown})
        assert refused.status_code == 422, refused.text
        assert refused.json()["error"]["code"] == "UNSUPPORTED_ADVICE_REQUEST"
    assert backend.queue.jobs() == jobs_before
    for malformed in (None, "", []):
        invalid = client.post(route, json={**body, "preferences": malformed})
        assert invalid.status_code == 422
        invalid_read = client.get(
            route,
            params={"strategy": "saf-puan", "window": 1, "preferences": json.dumps(malformed)},
        )
        assert invalid_read.status_code == 422
    assert (
        client.get(
            route, params={"strategy": "saf-puan", "window": 1, "preferences": ""}
        ).status_code
        == 422
    )


def _export_top100(
    running: dict[str, Any], artifact_root: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    backend = running["backend"]
    context = backend.contexts.current()
    assert context is not None
    capture = backend.contexts.capture(context)
    directory = artifact_root / "phase_b"
    directory.mkdir(parents=True, exist_ok=True)
    top100_tests._artifact(
        directory,
        monkeypatch,
        capture.inputs,
        capture.projection,
        top100_tests._favoured(capture.projection, list(SQUAD_CODES)),
    )


def test_a_member_asks_for_a_top100_setting_and_gets_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """POST with a setting, worker, GET with the same query: the switched-on button."""

    artifact_root = tmp_path / "artifacts"
    running = _deployment(tmp_path, monkeypatch, artifact_root=artifact_root)
    backend = running["backend"]
    client = TestClient(app_for_capture(backend, world_module.GW2_CAPTURED_AT))
    route = f"/api/v1/leagues/{LEAGUE_ID}/entries/{ENTRY_ID}/advice"
    body = {"strategy": COMPUTED_MODE, "window": COMPUTED_WINDOW, "top100_weight": 20}
    capabilities = f"/api/v1/leagues/{LEAGUE_ID}/capabilities"

    # Configured, but the week's export has not landed: refused by name, nothing queued.
    early = client.post(route, json=body)
    assert early.status_code == 422
    assert early.json()["error"]["code"] == "TOP100_INPUTS_UNAVAILABLE"
    assert client.get(capabilities).json()["top100"] == {"available": False, "weights": [0]}
    assert backend.queue.jobs() == ()

    # The export lands and both processes notice without a restart.
    _export_top100(running, artifact_root, monkeypatch)
    assert client.get(capabilities).json()["top100"]["available"] is True

    accepted = client.post(route, json=body)
    assert accepted.status_code == 202, accepted.text
    assert _work(backend) == 1
    finished = client.get(f"/api/v1/advice-jobs/{accepted.json()['job_id']}").json()
    assert finished["status"] == "completed", finished

    served = client.get(route, params=body)
    assert served.status_code == 200, served.text
    payload = served.json()["payload"]
    assert payload["top100"]["weight"] == 20
    assert payload["top100"]["table_sha256"] == "c" * 64
    assert payload["mode"] == COMPUTED_MODE and payload["window"] == COMPUTED_WINDOW
    assert payload["expected_points_cost"] >= 0

    # The same ask again is a hit; the plain plan is a different address, still uncomputed.
    again = client.post(route, json=body)
    assert again.status_code == 200 and again.content == served.content
    plain = {"strategy": COMPUTED_MODE, "window": COMPUTED_WINDOW}
    assert client.get(route, params=plain).status_code == 404

    # It is the batch's document: the same producer, the same inputs, the same payload.
    context = backend.contexts.current()
    capture = backend.contexts.capture(context)
    assert capture.top100_counts is not None
    direct = advise_with_top100(
        AdviseEntryRequest(season=SEASON, gameweek=2, league_id=LEAGUE_ID, entry_id=ENTRY_ID),
        weight=20,
        counts=capture.top100_counts,
        provider=capture.provider,
        inputs=capture.inputs,
        projection=capture.projection,
        rules=capture.rules,
    ).payload
    assert payload == json.loads(json.dumps(direct))


def test_without_the_inputs_configured_a_setting_is_refused_by_name(
    running: dict[str, Any],
) -> None:
    backend = running["backend"]
    client = TestClient(app_for_capture(backend, world_module.GW2_CAPTURED_AT))
    route = f"/api/v1/leagues/{LEAGUE_ID}/entries/{ENTRY_ID}/advice"
    for body, code in (
        ({"top100_weight": 20}, "TOP100_INPUTS_UNAVAILABLE"),
        ({"managers_word": True}, "MANAGERS_WORD_UNAVAILABLE"),
    ):
        refused = client.post(route, json={"strategy": COMPUTED_MODE, "window": 1, **body})
        assert refused.status_code == 422
        assert refused.json()["error"]["code"] == code
        read = client.get(route, params={"strategy": COMPUTED_MODE, "window": 1, **body})
        assert read.status_code == 422 and read.json()["error"]["code"] == code
    assert backend.queue.jobs() == ()
    # Nothing was projected to find that out: the api stays the reader it was.
    assert backend.contexts._context is None


def test_a_job_accepted_against_one_export_is_not_computed_from_another(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact_root = tmp_path / "artifacts"
    running = _deployment(tmp_path, monkeypatch, artifact_root=artifact_root)
    backend = running["backend"]
    client = TestClient(app_for_capture(backend, world_module.GW2_CAPTURED_AT))
    route = f"/api/v1/leagues/{LEAGUE_ID}/entries/{ENTRY_ID}/advice"
    body = {"strategy": COMPUTED_MODE, "window": COMPUTED_WINDOW, "top100_weight": 20}
    _export_top100(running, artifact_root, monkeypatch)
    first = client.post(route, json=body)
    assert first.status_code == 202

    # Ops replaces the week's export before the worker reaches the job.
    patched = switches_module_top100.read_player_evidence_artifact

    def replaced(*paths: Any) -> Any:
        evidence = patched(*paths).copy()
        evidence.attrs.update({**patched(*paths).attrs, "table_sha256": "9" * 64})
        return evidence

    monkeypatch.setattr(switches_module_top100, "read_player_evidence_artifact", replaced)
    table = next((artifact_root / "phase_b").glob("*.csv"))
    table.write_text("replaced", encoding="utf-8")

    assert _work(backend) == 1
    view = client.get(f"/api/v1/advice-jobs/{first.json()['job_id']}").json()
    assert (view["status"], view["error_code"]) == ("failed", "SWITCH_INPUTS_CHANGED")
    # Asking again is answered from the export that is there now, at its own address.
    second = client.post(route, json=body)
    assert second.status_code == 202 and second.json()["job_id"] != first.json()["job_id"]
    assert _work(backend) == 1
    assert client.get(route, params=body).json()["payload"]["top100"]["table_sha256"] == "9" * 64


def test_a_member_switches_the_managers_word_on_and_gets_it(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    artifact_root = tmp_path / "artifacts"
    fixture = tmp_path / "club_news.fixture.json"
    fixture.write_text("{}", encoding="utf-8")
    running = _deployment(
        tmp_path, monkeypatch, artifact_root=artifact_root, club_news_source=fixture
    )
    backend = running["backend"]
    table, manifest = rotation_artifact(
        artifact_root / "rotation", SEASON, 2, running["snapshot_id"]
    )
    table.parent.mkdir(parents=True)
    table.write_text("rows", encoding="utf-8")
    manifest.write_text(json.dumps({"table_sha256": "7" * 64}), encoding="utf-8")
    words = top100_tests._words(STARTING_ELEVEN[-1])
    monkeypatch.setattr(switches_module, "load_manager_words", lambda *_a, **_k: words)

    client = TestClient(app_for_capture(backend, world_module.GW2_CAPTURED_AT))
    route = f"/api/v1/leagues/{LEAGUE_ID}/entries/{ENTRY_ID}/advice"
    body = {"strategy": COMPUTED_MODE, "window": COMPUTED_WINDOW, "managers_word": True}
    capabilities = client.get(f"/api/v1/leagues/{LEAGUE_ID}/capabilities").json()
    assert capabilities["managers_word"] == {"available": True}
    assert capabilities["top100"]["available"] is False

    accepted = client.post(route, json=body)
    assert accepted.status_code == 202, accepted.text
    job = backend.queue.load(accepted.json()["job_id"])
    assert backend.job_specs.get(job.cache_key).switches == {
        "managers_word": {
            "rule_version": "managers_word_rule_v1",
            "rotation_table_sha256": "7" * 64,
            "source_kind": words.source_kind,
            "source_label": words.source_label,
        }
    }
    assert _work(backend) == 1
    served = client.get(route, params={**body, "managers_word": "true"})
    assert served.status_code == 200, served.text
    payload = served.json()["payload"]
    assert payload["evidence"]["kind"] == "managers_word"
    assert STARTING_ELEVEN[-1] not in {p["player_id"] for p in payload["starting_xi"]}
    # With the word and a setting together there are no counts here: refused by name.
    both = client.post(route, json={**body, "top100_weight": 5})
    assert both.status_code == 422
    assert both.json()["error"]["code"] == "TOP100_INPUTS_UNAVAILABLE"


@pytest.mark.parametrize("chip", [None, "bboost"])
def test_a_selection_the_planner_cannot_solve_is_named_and_its_diagnostic_is_not_served(
    running: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    chip: str | None,
) -> None:
    """The jobs endpoint is public: it names the outcome and carries none of the solver's text."""

    from squadopt.application.advice_menu import PLAN_NOT_FOUND_ERRORS

    backend = running["backend"]
    client = TestClient(app_for_capture(backend, world_module.GW2_CAPTURED_AT))
    diagnostic = "deterministic time used was 12.0, relative gap was 0.31"

    def no_plan(*_args: Any, **_kwargs: Any) -> dict[str, object]:
        raise PLAN_NOT_FOUND_ERRORS[1](diagnostic)

    monkeypatch.setattr(worker_module, "advise_menu_entry", no_plan)
    accepted = client.post(
        f"/api/v1/leagues/{LEAGUE_ID}/entries/{ENTRY_ID}/advice",
        json={"strategy": COMPUTED_MODE, "window": 1, **({"chip": chip} if chip else {})},
    )
    assert accepted.status_code == 202, accepted.text
    compute = build_advice_compute(backend.contexts, backend.job_specs)
    job = run_advice_worker_once(backend.queue, backend.cache, compute, at_utc=_now_stamp())
    assert job is not None and job.status == "failed"
    assert job.error is not None and job.error.code == "PLAN_NOT_FOUND"
    assert "deterministic" not in job.error.message and "gap" not in job.error.message
    served = client.get(f"/api/v1/advice-jobs/{job.job_id}")
    assert served.json()["error_code"] == "PLAN_NOT_FOUND"
    assert "deterministic" not in served.text


def test_chip_entry_error_is_private_through_the_real_menu_branch(
    running: dict[str, Any], monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    import logging

    import squadopt.application.advice_menu as menu
    from squadopt.platform.advice_observability import AdviceLog

    diagnostic = "Entry 987654 re-adds to 123.456 points but planner counted 234.567"

    def fail(*args: Any, **kwargs: Any) -> Any:
        raise EntryError(diagnostic)

    monkeypatch.setattr(menu, "advise_with_chip", fail)
    backend = running["backend"]
    client = TestClient(app_for_capture(backend, world_module.GW2_CAPTURED_AT))
    response = client.post(
        f"/api/v1/leagues/{LEAGUE_ID}/entries/{ENTRY_ID}/advice",
        json={"strategy": COMPUTED_MODE, "window": 1, "chip": "bboost"},
    )
    assert response.status_code == 202, response.text
    logger = logging.getLogger("test.chip-refusal")
    with caplog.at_level(logging.INFO, logger=logger.name):
        job = run_advice_worker_once(
            backend.queue,
            backend.cache,
            build_advice_compute(backend.contexts, backend.job_specs),
            at_utc=_now_stamp(),
            log=AdviceLog("worker", logger=logger),
        )
    assert job is not None and job.status == "failed"
    served = client.get(f"/api/v1/advice-jobs/{job.job_id}")
    assert served.json()["error_code"] == "PLAN_NOT_FOUND"
    for detail in ("987654", "re-adds", "123.456", "234.567"):
        assert detail not in served.text
    assert diagnostic in caplog.text


def test_accepted_chip_with_artifacts_does_not_prepare_a_projection(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    state = _deployment(tmp_path, monkeypatch, artifact_root=tmp_path / "artifacts")
    backend = state["backend"]
    client = TestClient(app_for_capture(backend, world_module.GW2_CAPTURED_AT))
    response = client.post(
        f"/api/v1/leagues/{LEAGUE_ID}/entries/{ENTRY_ID}/advice",
        json={"strategy": COMPUTED_MODE, "window": 1, "chip": "bboost"},
    )
    assert response.status_code == 202, response.text
    assert backend.contexts._context is None
