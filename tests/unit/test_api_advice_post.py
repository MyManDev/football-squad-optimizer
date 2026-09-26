"""The POST: a hit, one open job per request, idempotency, CORS, and rate limits."""

import json
import sys
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from contextlib import suppress
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier, BrokenBarrierError, Event, Lock, Thread
from typing import Any

import pytest
from fastapi.testclient import TestClient

from squadopt.api.app import ADVICE_BODY_MAX_BYTES, create_app
from squadopt.platform.advice_cache import FileAdviceCache
from squadopt.platform.advice_job_spec import FileAdviceJobSpecStore
from squadopt.platform.advice_observability import API_COUNTER_FAMILIES, AdviceMetrics
from squadopt.platform.advice_queue import FileJobQueue, run_advice_worker_once
from squadopt.platform.advice_read import (
    AdviceReadStore,
    AdviceRequestContext,
    FileLeagueDirectory,
    PreferencePlayers,
)
from squadopt.platform.advice_submit import (
    AdviceSubmitService,
    FixedWindowRateLimiter,
    SubmitOutcome,
    client_address_bucket,
)
from squadopt.platform.jobs_contract import AdviceJob, JobError

LEAGUE_ID = 352490
CONTEXT = AdviceRequestContext(
    advice_contract_version="advice_v1",
    capture_snapshot_id="fpl-live-20260826T083133Z-d45f1bea8b68",
    season="2026-27",
    gameweek=3,
    projection_handoff_fingerprint="f" * 64,
    repository_commit="abc1234",
    configuration_fingerprint="d" * 64,
)
ADVICE_URL = f"/api/v1/leagues/{LEAGUE_ID}/entries/313686/advice"
BODY = {"strategy": "saf-puan", "window": 1}


def _valid_advice_document() -> bytes:
    return json.dumps(
        {
            "contract_version": "provisional_league_ui_v1",
            "generated_at_utc": "2026-08-27T12:00:00Z",
            "source_kind": "live",
            "payload": {
                "season": "2026-27",
                "gameweek": 3,
                "entry_id": 313686,
                "league_id": 352490,
                "mode": "saf-puan",
                "window": 1,
                "moves": [],
                "data_quality": "complete",
                "missing_fields": [],
            },
        }
    ).encode("utf-8")


class _Context:
    def current(self) -> AdviceRequestContext:
        return CONTEXT


def _publish_members(root: Path, *, gameweek: int = 3) -> None:
    payload = {
        "league_id": LEAGUE_ID,
        "league_name": "Test League",
        "season": "2026-27",
        "gameweek": gameweek,
        "members": [
            {"member_kind": "human", "entry_id": 313686},
            {"member_kind": "human", "entry_id": 2199732},
        ],
    }
    document = {"contract_version": "provisional_league_ui_v1", "payload": payload}
    path = root / "league" / "members.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8", newline="\n")


def _world(
    tmp_path: Path,
    *,
    allowed_origins: tuple[str, ...] = (),
    metrics: AdviceMetrics | None = None,
    submit_services: list[AdviceSubmitService] | None = None,
    utc_now: Callable[[], datetime] = lambda: datetime(2026, 8, 27, 12, 0, tzinfo=UTC),
    preference_players: Callable[[AdviceRequestContext, int, int], PreferencePlayers | None]
    | None = None,
    **app_kwargs: object,
):
    _publish_members(tmp_path / "site")
    cache = FileAdviceCache(tmp_path / "cache")
    queue = FileJobQueue(tmp_path / "jobs")
    reader = AdviceReadStore(
        FileLeagueDirectory(tmp_path / "site"),
        cache,
        _Context(),
        {"saf-puan": False, "fark-yarat": True},
        preference_players=preference_players,
    )
    submit = AdviceSubmitService(reader, queue, **app_kwargs)
    if submit_services is not None:
        submit_services.append(submit)
    application = create_app(
        data_root=tmp_path / "site",
        advice_store=reader,
        advice_submit=submit,
        metrics=metrics,
        allowed_origins=allowed_origins,
        utc_now=utc_now,
    )
    client = TestClient(application, raise_server_exceptions=False)
    return client, cache, queue


@pytest.mark.parametrize(
    ("now", "status"),
    [("2026-08-28T17:29:59Z", 202), ("2026-08-28T17:30:00Z", 422), ("2026-08-29T12:00:00Z", 422)],
)
def test_only_new_work_is_refused_at_the_captured_deadline(
    tmp_path: Path, now: str, status: int
) -> None:
    metrics = AdviceMetrics(zero_counters=API_COUNTER_FAMILIES)
    services: list[AdviceSubmitService] = []
    client, _cache, queue = _world(
        tmp_path,
        metrics=metrics,
        submit_services=services,
        specs=FileAdviceJobSpecStore(tmp_path / "specs"),
        deadline_for=lambda context: "2026-08-28T17:30:00Z",
        utc_now=lambda: datetime.fromisoformat(now),
    )
    before = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*.json")}
    response = client.post(ADVICE_URL, json=BODY)
    assert response.status_code == status
    if status == 422:
        assert response.json()["error"]["code"] == "DEADLINE_PASSED"
        reasons = response.json()["error"]["details"]["public_reason"]
        assert "Previously computed plans" in reasons["en"]
        assert "Önceden hesaplanan" in reasons["tr"]
        assert "Retry-After" not in response.headers
        assert before == {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*.json")}
        assert not queue.jobs()
        assert not services[0]._client_jobs
        assert "advice_deadline_refused_total 1\n" in metrics.render()
    else:
        assert len(queue.jobs()) == 1
        assert "advice_deadline_refused_total 0\n" in metrics.render()


def test_deadline_preserves_replays_cache_and_read_routes(tmp_path: Path) -> None:
    now = [datetime(2026, 8, 27, 12, 0, tzinfo=UTC)]
    client, cache, queue = _world(
        tmp_path,
        deadline_for=lambda context: "2026-08-28T17:30:00Z",
        utc_now=lambda: now[0],
    )
    headers = {"Idempotency-Key": "before-deadline"}
    first = client.post(ADVICE_URL, json=BODY, headers=headers)
    assert first.status_code == 202
    capabilities = client.get(f"/api/v1/leagues/{LEAGUE_ID}/capabilities").json()
    readiness = client.get("/ready").json()
    now[0] = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
    for replay_headers in (headers, {}):
        replay = client.post(ADVICE_URL, json=BODY, headers=replay_headers)
        assert replay.status_code == 202
        assert replay.json()["job_id"] == first.json()["job_id"]
    assert client.get(f"/api/v1/leagues/{LEAGUE_ID}/capabilities").json() == capabilities
    assert client.get("/ready").json() == readiness
    run_advice_worker_once(
        queue, cache, lambda _job: _valid_advice_document(), at_utc=now[0].isoformat()
    )
    assert client.post(ADVICE_URL, json=BODY).content == _valid_advice_document()
    assert client.get(ADVICE_URL, params=BODY).content == _valid_advice_document()
    assert len(queue.jobs()) == 1


def test_late_cache_hit_is_served_without_checking_deadline(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def unexpected_deadline(_context: AdviceRequestContext) -> str:
        pytest.fail("a cache hit must not consult the deadline")

    client, cache, queue = _world(tmp_path, deadline_for=unexpected_deadline)
    read = cache.get
    calls = 0

    def late_hit(key: str):
        nonlocal calls
        calls += 1
        if calls == 2:
            cache.put(key, _valid_advice_document())
        return read(key)

    monkeypatch.setattr(cache, "get", late_hit)
    response = client.post(ADVICE_URL, json=BODY)
    assert response.status_code == 200
    assert response.content == _valid_advice_document()
    assert not queue.jobs()


def test_the_whole_story_get_404_post_202_worker_poll_second_post_200(
    tmp_path: Path,
) -> None:
    """Plan §13.4, as a test: miss, job, work, completed, hit."""

    client, cache, queue = _world(tmp_path)
    get_url = f"{ADVICE_URL}?strategy=saf-puan&window=1"

    assert client.get(get_url).status_code == 404  # nothing computed

    first = client.post(ADVICE_URL, json=BODY)
    assert first.status_code == 202
    job_id = first.json()["job_id"]

    polled = client.get(f"/api/v1/advice-jobs/{job_id}")
    assert polled.status_code == 200
    assert polled.json()["status"] == "queued"

    def compute(job: AdviceJob) -> bytes:
        return _valid_advice_document()

    done = run_advice_worker_once(queue, cache, compute, at_utc="2026-08-27T18:00:00Z")
    assert done is not None and done.status == "completed"

    assert client.get(f"/api/v1/advice-jobs/{job_id}").json()["status"] == "completed"
    second = client.post(ADVICE_URL, json=BODY)
    assert second.status_code == 200  # a hit now, no new job
    assert second.content == _valid_advice_document()
    assert client.get(get_url).status_code == 200


@pytest.mark.parametrize(
    ("change", "message"),
    [
        ({"window": 2}, "window must be 1, 3, or 5."),
        ({"model": "other"}, "Unknown prediction model."),
        ({"chip": "bogus"}, "Unknown chip choice."),
        ({"top100_weight": 7}, "top100_weight must be one of [0, 5, 10, 20, 30, 40, 50]."),
    ],
)
def test_the_get_and_the_post_refuse_a_selection_with_one_answer(
    tmp_path: Path, change: dict[str, object], message: str
) -> None:
    """One parser reads both routes, so a value one refuses the other refuses the same way."""

    client, _cache, _queue = _world(tmp_path)
    selection = {**BODY, **change}

    for response in (
        client.post(ADVICE_URL, json=selection),
        client.get(ADVICE_URL, params=selection),
    ):
        assert response.status_code == 422
        error = response.json()["error"]
        assert (error["code"], error["message"]) == ("VALIDATION_FAILED", message)


def test_one_open_job_per_normalized_request(tmp_path: Path) -> None:
    client, _cache, queue = _world(tmp_path)

    first = client.post(ADVICE_URL, json=BODY)
    second = client.post(ADVICE_URL, json=BODY)  # another client, same ask

    assert first.status_code == 202 and second.status_code == 202
    assert first.json()["job_id"] == second.json()["job_id"]
    assert len([job for job in queue.jobs() if job.status == "queued"]) == 1


def test_the_idempotency_triple(tmp_path: Path) -> None:
    """Same key + same request: same job. Same key + different request: 409.
    Different key + same request: the same open job, deduplicated."""

    client, _cache, _queue = _world(tmp_path)
    key = {"Idempotency-Key": "client:advise:1"}

    first = client.post(ADVICE_URL, json=BODY, headers=key)
    replay = client.post(ADVICE_URL, json=BODY, headers=key)
    assert first.json()["job_id"] == replay.json()["job_id"]

    conflict = client.post(ADVICE_URL, json={"strategy": "saf-puan", "window": 3}, headers=key)
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"

    other_key = client.post(ADVICE_URL, json=BODY, headers={"Idempotency-Key": "client:advise:2"})
    assert other_key.json()["job_id"] == first.json()["job_id"]


def test_rate_limits_answer_429(tmp_path: Path) -> None:
    client, _cache, _queue = _world(
        tmp_path, rate_limiter=FixedWindowRateLimiter(limit=2, window_seconds=60.0)
    )

    assert client.post(ADVICE_URL, json=BODY).status_code == 202
    assert client.post(ADVICE_URL, json=BODY).status_code == 202
    third = client.post(ADVICE_URL, json=BODY)
    assert third.status_code == 429
    assert third.json()["error"]["code"] == "RATE_LIMITED"


def test_four_open_jobs_include_running_and_refusal_writes_no_job_or_spec(tmp_path: Path) -> None:
    metrics = AdviceMetrics(zero_counters=API_COUNTER_FAMILIES)
    client, _cache, queue = _world(
        tmp_path, specs=FileAdviceJobSpecStore(tmp_path / "specs"), metrics=metrics
    )
    other_url = ADVICE_URL.replace("313686", "2199732")
    for window in (1, 3, 5):
        assert client.post(ADVICE_URL, json={**BODY, "window": window}).status_code == 202
    assert client.post(other_url, json=BODY).status_code == 202
    assert queue.claim(at_utc="2026-08-27T12:01:00Z") is not None
    before = {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*.json")}
    refused = client.post(other_url, json={**BODY, "window": 3})
    assert refused.status_code == 429
    assert refused.json()["error"]["code"] == "OPEN_JOB_LIMITED"
    reasons = refused.json()["error"]["details"]["public_reason"]
    assert "Wait for one to finish" in reasons["en"]
    assert "Birinin bitmesini bekleyip" in reasons["tr"]
    assert "Retry-After" not in refused.headers  # There is no known completion time.
    assert before == {p.relative_to(tmp_path): p.read_bytes() for p in tmp_path.rglob("*.json")}
    assert "advice_open_job_refused_total 1\n" in metrics.render()
    assert all(b"testclient" not in content for content in before.values())
    with TestClient(client.app, client=("another-client", 123)) as other:
        assert other.post(other_url, json={**BODY, "window": 3}).status_code == 202


def test_dedup_replay_and_cache_hits_do_not_consume_or_require_a_slot(tmp_path: Path) -> None:
    client, cache, queue = _world(tmp_path, max_open_jobs_per_client=1)
    headers = {"Idempotency-Key": "first-request"}
    first = client.post(ADVICE_URL, json=BODY, headers=headers)
    for replay_headers in (headers, {"Idempotency-Key": "second-request"}, {}):
        replay = client.post(ADVICE_URL, json=BODY, headers=replay_headers)
        assert replay.status_code == 202
        assert replay.json()["job_id"] == first.json()["job_id"]
    assert len(queue.jobs()) == 1
    assert client.post(ADVICE_URL, json={**BODY, "window": 3}).status_code == 429
    cache.put(queue.jobs()[0].cache_key, _valid_advice_document())
    assert client.post(ADVICE_URL, json=BODY).status_code == 200


@pytest.mark.parametrize("terminal", ["completed", "failed", "missing"])
def test_admission_releases_finished_or_missing_jobs(tmp_path: Path, terminal: str) -> None:
    client, cache, queue = _world(tmp_path, max_open_jobs_per_client=1)
    first = client.post(ADVICE_URL, json=BODY)
    if terminal == "completed":
        run_advice_worker_once(
            queue, cache, lambda _job: _valid_advice_document(), at_utc="2026-08-27T12:01:00Z"
        )
    elif terminal == "failed":
        claimed = queue.claim(at_utc="2026-08-27T12:01:00Z")
        queue.store(
            claimed.transition(
                "failed", at_utc="2026-08-27T12:01:01Z", error=JobError("ADVICE_FAILED", "fixture")
            )
        )
    else:
        (tmp_path / "jobs" / f"{first.json()['job_id']}.json").unlink()
    assert client.post(ADVICE_URL, json={**BODY, "window": 3}).status_code == 202


def test_simultaneous_submissions_cannot_overbook_one_address(tmp_path: Path) -> None:
    client, _cache, queue = _world(tmp_path, max_open_jobs_per_client=1)
    ready = Barrier(3)

    def post(window: int) -> int:
        with TestClient(client.app) as requester:
            ready.wait(timeout=10)
            return requester.post(ADVICE_URL, json={**BODY, "window": window}).status_code

    with ThreadPoolExecutor(max_workers=3) as callers:
        assert sorted(callers.map(post, (1, 3, 5))) == [202, 429, 429]
    assert len(queue.jobs()) == 1


def test_a_late_cache_publication_is_not_refused_at_the_cap(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, cache, queue = _world(tmp_path, max_open_jobs_per_client=1)
    assert client.post(ADVICE_URL, json={**BODY, "window": 3}).status_code == 202
    original = FileJobQueue.submit_unless_cached

    def publish_before_transaction(self, job, **kwargs):
        cache.put(job.cache_key, _valid_advice_document())
        return original(self, job, **kwargs)

    monkeypatch.setattr(FileJobQueue, "submit_unless_cached", publish_before_transaction)
    assert client.post(ADVICE_URL, json=BODY).status_code == 200
    assert len(queue.jobs()) == 1


def test_a_new_api_process_does_not_recover_client_addresses_from_disk(tmp_path: Path) -> None:
    client, _cache, _queue = _world(tmp_path, max_open_jobs_per_client=1)
    assert client.post(ADVICE_URL, json=BODY).status_code == 202
    restarted, _cache, queue = _world(tmp_path, max_open_jobs_per_client=1)
    assert restarted.post(ADVICE_URL, json={**BODY, "window": 3}).status_code == 202
    assert len(queue.jobs()) == 2


def test_two_api_processes_have_independent_caps_over_one_store(tmp_path: Path) -> None:
    first, _cache, queue = _world(tmp_path, max_open_jobs_per_client=1)
    second, _cache, _queue = _world(tmp_path, max_open_jobs_per_client=1)
    assert first.post(ADVICE_URL, json=BODY).status_code == 202
    assert second.post(ADVICE_URL, json={**BODY, "window": 3}).status_code == 202
    for client in (first, second):
        assert client.post(ADVICE_URL, json={**BODY, "window": 5}).status_code == 429
    assert len(queue.jobs()) == 2


def test_admission_does_not_add_another_full_history_scan(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _cache, queue = _world(tmp_path)
    assert client.post(ADVICE_URL, json=BODY).status_code == 202
    original = queue.jobs
    calls = 0

    def history():
        nonlocal calls
        calls += 1
        assert calls == 1  # Only the existing idempotency/attempt history lookup.
        return original()

    monkeypatch.setattr(queue, "jobs", history)
    assert client.post(ADVICE_URL, json={**BODY, "window": 3}).status_code == 202
    assert calls == 1


@pytest.mark.parametrize("failure", ["spec", "queue"])
def test_failed_preparation_or_publication_leaves_no_job_or_occupied_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    specs = FileAdviceJobSpecStore(tmp_path / "specs")
    services: list[AdviceSubmitService] = []
    client, _cache, queue = _world(
        tmp_path, specs=specs, max_open_jobs_per_client=1, submit_services=services
    )

    def fail(*_args):
        raise OSError("fixture write failure")

    with monkeypatch.context() as patch:
        if failure == "spec":
            patch.setattr(specs, "put", fail)
        else:
            patch.setattr(queue, "submit_unique", fail)
        assert client.post(ADVICE_URL, json=BODY).status_code == 500
    assert services[0]._client_jobs == {}  # Free now, before another admission prunes.
    assert queue.jobs() == ()
    assert client.post(ADVICE_URL, json={**BODY, "window": 3}).status_code == 202


def test_a_cache_hit_spends_no_rate_limit_token(tmp_path: Path) -> None:
    """Opening a computed plan again is a read; the budget is for requests that need work."""

    client, cache, queue = _world(
        tmp_path, rate_limiter=FixedWindowRateLimiter(limit=2, window_seconds=60.0)
    )
    assert client.post(ADVICE_URL, json=BODY).status_code == 202  # the first of two tokens
    done = run_advice_worker_once(
        queue, cache, lambda _job: _valid_advice_document(), at_utc="2026-08-27T18:00:00Z"
    )
    assert done is not None and done.status == "completed"

    # More hits in a row than the whole budget, and none of them is refused.
    for _ in range(3):
        hit = client.post(ADVICE_URL, json=BODY)
        assert hit.status_code == 200
        assert hit.content == _valid_advice_document()

    # A miss is still charged: the second token is there, and after it the limit holds.
    assert client.post(ADVICE_URL, json={**BODY, "window": 3}).status_code == 202
    refused = client.post(ADVICE_URL, json={**BODY, "window": 5})
    assert refused.status_code == 429
    assert refused.json()["error"]["code"] == "RATE_LIMITED"
    # Even with the budget spent, the computed plan still opens.
    assert client.post(ADVICE_URL, json=BODY).status_code == 200


# --- the member's budget is spent on admitted work, and only on ids the capture has ------

ENTRY_BUCKET = f"entry:{CONTEXT.capture_snapshot_id}:313686"
SQUAD = frozenset(range(1, 16))
ROSTER = frozenset(range(1, 701))


def _players(context: AdviceRequestContext, league_id: int, entry_id: int) -> PreferencePlayers:
    assert context == CONTEXT and league_id == LEAGUE_ID
    return PreferencePlayers(squad=SQUAD, roster=ROSTER)


def _outcome(response: Any) -> str:
    return "JOB" if response.status_code == 202 else response.json()["error"]["code"]


def test_forty_distinct_avoid_lists_leave_the_entry_budget_for_another_client(
    tmp_path: Path,
) -> None:
    """The audit's run: one address, forty misses, and another client still computes.

    Every avoid list is a different address, so each POST is a miss. Before the fix each
    one charged the member's (capture, entry) bucket before deduplication and before the
    open-job cap, so thirty of them emptied it and the next client was told to wait 60 s.
    """

    limiter = FixedWindowRateLimiter(limit=30, window_seconds=60.0)
    client, _cache, queue = _world(tmp_path, rate_limiter=limiter, preference_players=_players)

    outcomes = [
        _outcome(
            client.post(ADVICE_URL, json={**BODY, "preferences": {"avoid_players": [100 + n]}})
        )
        for n in range(40)
    ]

    assert outcomes.count("JOB") == 4
    assert outcomes.count("OPEN_JOB_LIMITED") == 26
    assert outcomes.count("RATE_LIMITED") == 10  # the address's own budget, 30 misses
    assert limiter._counts[ENTRY_BUCKET][1] == 4  # only the admitted jobs were charged
    with TestClient(client.app, client=("another-client", 123)) as other:
        response = other.post(ADVICE_URL, json={**BODY, "window": 3})
    assert response.status_code == 202, response.text
    assert len(queue.jobs()) == 5


def test_joining_an_open_job_spends_no_entry_token(tmp_path: Path) -> None:
    limiter = FixedWindowRateLimiter(limit=2, window_seconds=60.0)
    client, _cache, queue = _world(tmp_path, rate_limiter=limiter)
    first = client.post(ADVICE_URL, json=BODY)
    assert first.status_code == 202
    with TestClient(client.app, client=("another-client", 123)) as other:
        joined = other.post(ADVICE_URL, json=BODY)
        assert joined.status_code == 202
        assert joined.json()["job_id"] == first.json()["job_id"]
        # The member's second token is still there for new work.
        assert other.post(ADVICE_URL, json={**BODY, "window": 3}).status_code == 202
    # And the entry bucket still holds: two admitted jobs were its whole budget.
    with TestClient(client.app, client=("a-third-client", 123)) as third:
        refused = third.post(ADVICE_URL, json={**BODY, "window": 5})
    assert refused.status_code == 429
    assert refused.json()["error"]["code"] == "RATE_LIMITED"
    assert refused.headers["Retry-After"] == "60"
    assert len(queue.jobs()) == 2


def test_an_open_job_refusal_spends_no_entry_token(tmp_path: Path) -> None:
    services: list[AdviceSubmitService] = []
    limiter = FixedWindowRateLimiter(limit=2, window_seconds=60.0)
    client, _cache, queue = _world(
        tmp_path, rate_limiter=limiter, max_open_jobs_per_client=1, submit_services=services
    )
    assert client.post(ADVICE_URL, json=BODY).status_code == 202
    refused = client.post(ADVICE_URL, json={**BODY, "window": 3})
    assert _outcome(refused) == "OPEN_JOB_LIMITED"
    assert limiter._counts[ENTRY_BUCKET][1] == 1
    with TestClient(client.app, client=("another-client", 123)) as other:
        assert other.post(ADVICE_URL, json={**BODY, "window": 3}).status_code == 202
    assert len(queue.jobs()) == 2
    assert sorted(services[0]._client_jobs.values()) == ["another-client", "testclient"]


def test_new_work_refused_at_preparation_spends_no_entry_token(tmp_path: Path) -> None:
    limiter = FixedWindowRateLimiter(limit=1, window_seconds=60.0)
    client, _cache, queue = _world(
        tmp_path, rate_limiter=limiter, deadline_for=lambda context: "2026-08-27T11:00:00Z"
    )
    assert _outcome(client.post(ADVICE_URL, json=BODY)) == "DEADLINE_PASSED"
    assert limiter.has_room(ENTRY_BUCKET)
    assert queue.jobs() == ()


def test_a_full_entry_bucket_refuses_with_no_job_and_no_reservation(tmp_path: Path) -> None:
    services: list[AdviceSubmitService] = []
    limiter = FixedWindowRateLimiter(limit=1, window_seconds=60.0)
    client, _cache, queue = _world(tmp_path, rate_limiter=limiter, submit_services=services)
    assert client.post(ADVICE_URL, json=BODY).status_code == 202
    with TestClient(client.app, client=("another-client", 123)) as other:
        refused = other.post(ADVICE_URL, json={**BODY, "window": 3})
    assert _outcome(refused) == "RATE_LIMITED"
    assert len(queue.jobs()) == 1
    assert list(services[0]._client_jobs.values()) == ["testclient"]


@pytest.mark.parametrize(
    ("host", "bucket"),
    [
        ("2001:db8:1:2:aaaa:bbbb:cccc:dddd", "2001:db8:1:2::/64"),
        ("2001:db8:1:2::1", "2001:db8:1:2::/64"),
        ("2001:DB8:1:2::1", "2001:db8:1:2::/64"),
        ("fe80::1%eth0", "fe80::/64"),
        ("::ffff:203.0.113.9", "203.0.113.9"),
        ("203.0.113.9", "203.0.113.9"),
        ("testclient", "testclient"),
        ("unknown", "unknown"),
    ],
)
def test_a_client_is_counted_by_its_ipv4_address_or_its_ipv6_64(host: str, bucket: str) -> None:
    assert client_address_bucket(host) == bucket


def test_addresses_in_one_ipv6_64_share_one_budget_and_one_open_job_cap(tmp_path: Path) -> None:
    other_url = ADVICE_URL.replace("313686", "2199732")

    def post(client: TestClient, host: str, url: str) -> str:
        with TestClient(client.app, client=(host, 443)) as requester:
            return _outcome(requester.post(url, json=BODY))

    limited, _cache, _queue = _world(
        tmp_path / "rate", rate_limiter=FixedWindowRateLimiter(limit=1, window_seconds=60.0)
    )
    assert post(limited, "2001:db8:1:2::1", ADVICE_URL) == "JOB"
    assert post(limited, "2001:db8:1:2::ffff", other_url) == "RATE_LIMITED"
    assert post(limited, "2001:db8:1:3::1", other_url) == "JOB"

    capped, _cache, _queue = _world(tmp_path / "open", max_open_jobs_per_client=1)
    assert post(capped, "2001:db8:1:2::1", ADVICE_URL) == "JOB"
    assert post(capped, "2001:db8:1:2::2", other_url) == "OPEN_JOB_LIMITED"
    assert post(capped, "2001:db8:1:3::1", other_url) == "JOB"


def test_the_limiter_forgets_a_bucket_once_its_window_has_passed() -> None:
    now = [0.0]
    limiter = FixedWindowRateLimiter(limit=1, window_seconds=60.0, clock=lambda: now[0])
    for index in range(100):
        assert limiter.allow(f"ip:client-{index}")
    assert limiter.has_room("ip:unseen") and not limiter.has_room("ip:client-0")
    assert not limiter.allow("ip:client-0")
    assert len(limiter._counts) == 100  # looking spends nothing and stores nothing

    now[0] = 60.0
    assert limiter.allow("ip:late")
    assert set(limiter._counts) == {"ip:late"}
    assert limiter.allow("ip:client-0")  # a forgotten bucket starts a fresh window


@pytest.mark.parametrize(
    "preferences",
    [
        {"keep_players": [16]},
        {"avoid_players": [701]},
        {"keep_players": [1], "avoid_players": [2**53 - 1]},
    ],
    ids=["kept-not-held", "avoided-not-in-roster", "one-good-one-unknown"],
)
def test_players_the_capture_does_not_have_are_refused_before_any_work(
    tmp_path: Path, preferences: dict[str, list[int]]
) -> None:
    limiter = FixedWindowRateLimiter(limit=1, window_seconds=60.0)
    client, _cache, queue = _world(tmp_path, rate_limiter=limiter, preference_players=_players)

    posted = client.post(ADVICE_URL, json={**BODY, "preferences": preferences})
    read = client.get(ADVICE_URL, params={**BODY, "preferences": json.dumps(preferences)})

    for response in (posted, read):
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "UNSUPPORTED_ADVICE_REQUEST"
    assert queue.jobs() == ()
    # The refusal spent nothing: the one token still admits a request the capture can hold.
    accepted = {"keep_players": [1, 15], "avoid_players": [700]}
    assert client.post(ADVICE_URL, json={**BODY, "preferences": accepted}).status_code == 202


@pytest.mark.parametrize(
    "players",
    [None, lambda _context, _league, _entry: None],
    ids=["no-squad-reader", "squad-unreadable"],
)
def test_named_players_are_refused_when_the_squad_cannot_be_read(
    tmp_path: Path,
    players: Callable[[AdviceRequestContext, int, int], PreferencePlayers | None] | None,
) -> None:
    client, _cache, queue = _world(tmp_path, preference_players=players)
    refused = client.post(ADVICE_URL, json={**BODY, "preferences": {"avoid_players": [5]}})
    assert _outcome(refused) == "UNSUPPORTED_ADVICE_REQUEST"
    # The two flags name no player and need no squad.
    flags = {"no_hits": True, "save_chips": True}
    assert client.post(ADVICE_URL, json={**BODY, "preferences": flags}).status_code == 202
    assert len(queue.jobs()) == 1


def test_a_tree_from_another_week_is_not_ready_and_queues_nothing(tmp_path: Path) -> None:
    """Last week's members beside this week's capture: refused as readiness, both named."""

    client, _cache, queue = _world(
        tmp_path, rate_limiter=FixedWindowRateLimiter(limit=1, window_seconds=60.0)
    )
    _publish_members(tmp_path / "site", gameweek=2)

    refused = client.post(ADVICE_URL, json=BODY)
    assert refused.status_code == 503
    error = refused.json()["error"]
    assert error["code"] == "NOT_READY"
    assert "2026-27 gameweek 2" in error["message"]
    assert "2026-27 gameweek 3" in error["message"]
    assert queue.jobs() == ()
    assert client.get(f"{ADVICE_URL}?strategy=saf-puan&window=1").status_code == 503

    # The week's tree lands; nothing restarts, and the refusal spent no token.
    _publish_members(tmp_path / "site", gameweek=3)
    assert client.post(ADVICE_URL, json=BODY).status_code == 202


def test_post_validation_and_the_unknown_entry_refusal(tmp_path: Path) -> None:
    client, _cache, _queue = _world(tmp_path)

    assert client.post(ADVICE_URL, json={"strategy": "saf-puan"}).status_code == 422
    assert client.post(ADVICE_URL, json={"strategy": "saf-puan", "window": 2}).status_code == 422
    unknown = client.post(f"/api/v1/leagues/{LEAGUE_ID}/entries/42/advice", json=BODY)
    assert unknown.status_code == 404
    assert unknown.json()["error"]["code"] == "UNKNOWN_ENTRY"


def test_cors_is_an_allowlist_never_a_wildcard(tmp_path: Path) -> None:
    _publish_members(tmp_path / "site")
    application = create_app(
        data_root=tmp_path / "site",
        allowed_origins=("https://squadopt.example",),
    )
    client = TestClient(application, raise_server_exceptions=False)

    allowed = client.options(
        ADVICE_URL,
        headers={
            "Origin": "https://squadopt.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert allowed.headers.get("access-control-allow-origin") == "https://squadopt.example"

    denied = client.options(
        ADVICE_URL,
        headers={
            "Origin": "https://elsewhere.example",
            "Access-Control-Request-Method": "POST",
        },
    )
    assert denied.headers.get("access-control-allow-origin") is None

    try:
        create_app(data_root=tmp_path / "site", allowed_origins=("*",))
        raise AssertionError("a wildcard allowlist must be refused")
    except ValueError:
        pass


def test_an_allowed_origin_may_read_how_long_a_refusal_asked_it_to_wait(tmp_path: Path) -> None:
    """A browser shows a page only the response headers the server exposes to it."""

    origin = "https://squadopt.example"
    client, _cache, _queue = _world(
        tmp_path,
        allowed_origins=(origin,),
        rate_limiter=FixedWindowRateLimiter(limit=1, window_seconds=45.0),
    )
    assert client.post(ADVICE_URL, json=BODY, headers={"Origin": origin}).status_code == 202
    refused = client.post(ADVICE_URL, json=BODY, headers={"Origin": origin})
    assert refused.status_code == 429
    assert refused.headers["Retry-After"] == "45"
    assert refused.headers.get("access-control-allow-origin") == origin
    exposed = refused.headers.get("access-control-expose-headers", "")
    assert "retry-after" in [name.strip().lower() for name in exposed.split(",")]

    elsewhere = client.post(ADVICE_URL, json=BODY, headers={"Origin": "https://elsewhere.example"})
    assert elsewhere.headers.get("access-control-allow-origin") is None


def test_the_strict_body_refuses_extras_and_bool_windows(tmp_path: Path) -> None:
    """The reviewed parser gaps: undeclared keys and window=true must be 422s."""

    client, _cache, _queue = _world(tmp_path)

    extra = client.post(ADVICE_URL, json={**BODY, "surprise": 1})
    assert extra.status_code == 422
    assert "surprise" in extra.json()["error"]["message"]

    bool_window = client.post(ADVICE_URL, json={"strategy": "saf-puan", "window": True})
    assert bool_window.status_code == 422


@pytest.mark.parametrize(
    "content_type",
    [None, "text/plain", "text/plain; charset=utf-8", "application/x-www-form-urlencoded"],
)
def test_a_body_that_is_not_declared_json_is_refused_unread(
    tmp_path: Path, content_type: str | None
) -> None:
    """A cross-site form can send these without a preflight; none of them may file a job."""

    client, _cache, queue = _world(tmp_path)
    headers = {"Origin": "https://elsewhere.example"}
    if content_type is not None:
        headers["Content-Type"] = content_type

    refused = client.post(ADVICE_URL, content=json.dumps(BODY).encode(), headers=headers)

    assert refused.status_code == 415
    assert refused.json()["error"]["code"] == "UNSUPPORTED_MEDIA_TYPE"
    assert queue.jobs() == ()


@pytest.mark.parametrize(
    "content_type", ["application/json; charset=utf-8", "Application/JSON", "application/json"]
)
def test_json_with_a_charset_or_any_case_is_accepted(tmp_path: Path, content_type: str) -> None:
    client, _cache, queue = _world(tmp_path)

    accepted = client.post(
        ADVICE_URL, content=json.dumps(BODY).encode(), headers={"Content-Type": content_type}
    )

    assert accepted.status_code == 202
    assert len(queue.jobs()) == 1


def test_a_body_over_the_cap_is_refused_before_it_is_parsed(tmp_path: Path) -> None:
    client, _cache, queue = _world(tmp_path)
    too_large = {**BODY, "preferences": {"keep_players": [1] * 3000}}
    # Not JSON at all: a 413 rather than a 422 shows the size is checked before parsing.
    unreadable = b"{" + b" " * ADVICE_BODY_MAX_BYTES
    for raw in (json.dumps(too_large).encode(), unreadable):
        assert len(raw) > ADVICE_BODY_MAX_BYTES

        refused = client.post(ADVICE_URL, content=raw, headers={"Content-Type": "application/json"})

        assert refused.status_code == 413
        assert refused.json()["error"]["code"] == "PAYLOAD_TOO_LARGE"
        assert str(ADVICE_BODY_MAX_BYTES) in refused.json()["error"]["message"]
    assert queue.jobs() == ()


def test_a_body_exactly_at_the_cap_is_read(tmp_path: Path) -> None:
    client, _cache, queue = _world(tmp_path)
    compact = json.dumps(BODY).encode()
    at_cap = compact + b" " * (ADVICE_BODY_MAX_BYTES - len(compact))
    assert len(at_cap) == ADVICE_BODY_MAX_BYTES

    accepted = client.post(ADVICE_URL, content=at_cap, headers={"Content-Type": "application/json"})

    assert accepted.status_code == 202
    assert len(queue.jobs()) == 1


def test_the_largest_body_the_page_can_build_is_well_under_the_cap() -> None:
    """Every field at its maximum, serialized the way the web client's JSON.stringify does."""

    largest = {
        "preferences": {
            "keep_players": [2**53 - 1 - index for index in range(15)],
            "avoid_players": [2**53 - 16 - index for index in range(15)],
            "no_hits": True,
            "save_chips": True,
        },
        "strategy": "a" * 64,
        "window": 5,
        "rival_entry_id": 2**53 - 1,
        "model": "football",
        "top100_weight": 50,
        "managers_word": True,
        "chip": "wildcard",
    }
    encoded = json.dumps(largest, separators=(",", ":")).encode()

    assert len(encoded) == 795
    assert len(encoded) * 5 <= ADVICE_BODY_MAX_BYTES


@pytest.mark.parametrize(
    "raw",
    [b"not json", b"\xff\xfe", b"[" * 2000 + b"]" * 2000],
    ids=["text", "not-utf8", "nested-2000-deep"],
)
def test_a_body_that_is_not_json_is_a_validation_failure(tmp_path: Path, raw: bytes) -> None:
    client, _cache, queue = _world(tmp_path)

    refused = client.post(ADVICE_URL, content=raw, headers={"Content-Type": "application/json"})

    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "VALIDATION_FAILED"
    assert queue.jobs() == ()


@pytest.mark.parametrize(
    "strategy", ["", "Saf-Puan", "saf puan", "saf-puan\n", "-saf", "a" * 65, "<script>"]
)
def test_the_body_strategy_follows_the_query_pattern(tmp_path: Path, strategy: str) -> None:
    client, _cache, queue = _world(tmp_path)

    refused = client.post(ADVICE_URL, json={"strategy": strategy, "window": 1})

    assert refused.status_code == 422
    assert refused.json()["error"]["code"] == "VALIDATION_FAILED"
    if strategy:
        assert strategy not in refused.json()["error"]["message"]  # never echoed back
    assert queue.jobs() == ()


def test_idempotency_history_survives_terminal_jobs(tmp_path: Path) -> None:
    """A key's meaning does not expire with its job (reviewed finding 2)."""

    client, cache, queue = _world(tmp_path)
    key = {"Idempotency-Key": "client:sticky:1"}
    first = client.post(ADVICE_URL, json=BODY, headers=key)
    assert first.status_code == 202

    def compute(job: AdviceJob) -> bytes:
        return _valid_advice_document()

    run_advice_worker_once(queue, cache, compute, at_utc="2026-08-27T18:00:00Z")

    # Same key, different request, after the job is terminal: still a conflict.
    conflict = client.post(ADVICE_URL, json={"strategy": "saf-puan", "window": 3}, headers=key)
    assert conflict.status_code == 409

    # Same key, same request, after completion: the cached answer, no new job.
    replay = client.post(ADVICE_URL, json=BODY, headers=key)
    assert replay.status_code == 200
    assert replay.content == _valid_advice_document()


def test_two_racing_submitters_converge_on_one_open_job(tmp_path: Path) -> None:
    """The reviewed scan-then-submit race, forced at the queue's atomic index."""

    import threading

    _client_unused, _cache, queue = _world(tmp_path)
    fingerprint = "a" * 64
    barrier = threading.Barrier(2)
    winners: list[str] = []

    def submit(suffix: int) -> None:
        record = AdviceJob(
            job_id=f"advice-race-{suffix}",
            status="queued",
            request_fingerprint=fingerprint,
            cache_key="b" * 64,
            created_at_utc="2026-08-27T12:00:00Z",
            updated_at_utc="2026-08-27T12:00:00Z",
        )
        barrier.wait(timeout=5)
        winner, _created = queue.submit_unique(record)
        winners.append(winner.job_id)

    threads = [threading.Thread(target=submit, args=(index,)) for index in (1, 2)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=10)

    assert len(set(winners)) == 1  # both callers hold the same open job
    open_jobs = [job for job in queue.jobs() if job.status == "queued"]
    assert len(open_jobs) == 1


@pytest.mark.parametrize("completion_boundary", ["cache-read", "history-read"])
@pytest.mark.parametrize("retry_key", [None, "client:another-request"])
def test_completion_after_a_cache_miss_does_not_enqueue_another_job(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    completion_boundary: str,
    retry_key: str | None,
) -> None:
    """A worker can finish between POST's initial miss and its enqueue decision."""

    client, cache, queue = _world(tmp_path)
    first = client.post(ADVICE_URL, json=BODY)
    assert first.status_code == 202
    worker_queue = FileJobQueue(tmp_path / "jobs")
    finished = False

    def finish() -> None:
        nonlocal finished
        if finished:
            return
        finished = True
        result = run_advice_worker_once(
            worker_queue,
            cache,
            lambda _job: _valid_advice_document(),
            at_utc="2026-08-27T18:00:00Z",
            terminal_at_utc=lambda: "2026-08-27T18:00:01Z",
        )
        assert result is not None and result.status == "completed"

    if completion_boundary == "cache-read":
        original_cached = AdviceReadStore.cached

        def stale_miss(reader: AdviceReadStore, key: str) -> bytes | None:
            answer = original_cached(reader, key)
            finish()
            return answer

        monkeypatch.setattr(AdviceReadStore, "cached", stale_miss)
    else:
        original_jobs = queue.jobs

        def stale_history() -> tuple[AdviceJob, ...]:
            history = original_jobs()
            finish()
            return history

        monkeypatch.setattr(queue, "jobs", stale_history)

    headers = {} if retry_key is None else {"Idempotency-Key": retry_key}
    replay = client.post(ADVICE_URL, json=BODY, headers=headers)

    assert finished
    assert replay.status_code == 200, replay.text
    assert replay.content == _valid_advice_document()
    jobs = worker_queue.jobs()
    assert len(jobs) == 1
    assert jobs[0].job_id == first.json()["job_id"]
    assert jobs[0].status == "completed"


def test_the_public_job_view_carries_no_private_fields(tmp_path: Path) -> None:
    """The stored record is not the public record (reviewed finding 4)."""

    client, cache, queue = _world(tmp_path)
    key = {"Idempotency-Key": "client:secret-ish:1"}
    posted = client.post(ADVICE_URL, json=BODY, headers=key)
    job_id = posted.json()["job_id"]

    def explode(job: AdviceJob) -> bytes:
        raise RuntimeError(r"boom at C:\Users\ertug\secret\place")

    run_advice_worker_once(queue, cache, explode, at_utc="2026-08-27T18:00:00Z")

    view = client.get(f"/api/v1/advice-jobs/{job_id}").json()
    assert view["contract_version"] == "advice_job_view_v1"
    assert view["status"] == "failed"
    assert view["error_code"] == "ADVICE_FAILED"
    assert "idempotency_key" not in view
    assert "secret-ish" not in json.dumps(view)
    assert "ertug" not in json.dumps(view)  # no raw worker text, no host paths


@pytest.mark.parametrize(
    "body",
    [
        {"strategy": "saf-puan", "window": 1, "rival_entry_id": 2199732},
        {"strategy": "fark-yarat", "window": 1},
        {"strategy": "fark-yarat", "window": 3, "rival_entry_id": 2199732},
        {"strategy": "fark-yarat", "window": 1, "rival_entry_id": 313686},
    ],
)
def test_unsupported_computations_never_enter_the_queue(tmp_path: Path, body: dict) -> None:
    client, _cache, queue = _world(tmp_path)
    posted = client.post(ADVICE_URL, json=body)
    params = {"strategy": body["strategy"], "window": body["window"]}
    if "rival_entry_id" in body:
        params["rival"] = body["rival_entry_id"]
    read = client.get(ADVICE_URL, params=params)
    for response in (posted, read):
        assert response.status_code == 422
        assert response.json()["error"]["code"] == "UNSUPPORTED_ADVICE_REQUEST"
    assert queue.jobs() == ()


@pytest.mark.parametrize("broken", [b'{"private":"corrupt"}', b"null"])
def test_get_and_post_refuse_identical_corrupt_cache_without_new_job(
    tmp_path: Path,
    broken: bytes,
) -> None:
    client, cache, queue = _world(tmp_path)
    posted = client.post(ADVICE_URL, json=BODY)
    job = queue.load(posted.json()["job_id"])
    cache.put(job.cache_key, broken)
    for response in (
        client.get(ADVICE_URL, params=BODY),
        client.post(ADVICE_URL, json=BODY),
    ):
        assert response.status_code == 500
        assert response.json()["error"]["code"] == "INTERNAL_ERROR"
        assert "corrupt" not in response.text
    assert len(queue.jobs()) == 1


def test_a_torn_cache_entry_is_computed_again_not_an_error_for_good(tmp_path: Path) -> None:
    client, cache, queue = _world(tmp_path)
    posted = client.post(ADVICE_URL, json=BODY)
    job = queue.load(posted.json()["job_id"])
    run_advice_worker_once(
        queue, cache, lambda _job: _valid_advice_document(), at_utc="2026-08-27T18:00:00Z"
    )
    path = tmp_path / "cache" / job.cache_key[:2] / f"{job.cache_key}.json"
    path.write_bytes(b"")  # what a power loss before the fsync could leave behind

    missed = client.get(ADVICE_URL, params=BODY)
    assert missed.status_code == 404
    assert missed.json()["error"]["code"] == "NOT_COMPUTED"
    assert [p.name.startswith(f"{path.name}.damaged-") for p in path.parent.iterdir()] == [True]
    again = client.post(ADVICE_URL, json=BODY)
    assert again.status_code == 202
    assert again.json()["job_id"] != job.job_id
    run_advice_worker_once(
        queue, cache, lambda _job: _valid_advice_document(), at_utc="2026-08-27T18:05:00Z"
    )
    assert client.get(ADVICE_URL, params=BODY).content == _valid_advice_document()


def test_a_torn_job_spec_is_written_again_not_a_conflict_for_good(tmp_path: Path) -> None:
    from squadopt.platform.advice_job_spec import FileAdviceJobSpecStore

    specs = FileAdviceJobSpecStore(tmp_path / "specs")
    client, cache, queue = _world(tmp_path, specs=specs)
    posted = client.post(ADVICE_URL, json=BODY)
    job = queue.load(posted.json()["job_id"])
    path = tmp_path / "specs" / job.cache_key[:2] / f"{job.cache_key}.json"
    written = path.read_bytes()
    path.write_bytes(b"\x00" * len(written))  # the name linked, the bytes never written

    def compute_from_spec(claimed: AdviceJob) -> bytes:
        specs.get(claimed.cache_key)  # the worker cannot read what it was asked
        return _valid_advice_document()

    failed = run_advice_worker_once(queue, cache, compute_from_spec, at_utc="2026-08-27T18:00:00Z")
    assert failed is not None and failed.status == "failed"

    again = client.post(ADVICE_URL, json=BODY)
    assert again.status_code == 202  # was 409 REQUEST_CONFLICT on every later request
    assert path.read_bytes() == written
    run_advice_worker_once(queue, cache, compute_from_spec, at_utc="2026-08-27T18:05:00Z")
    assert client.post(ADVICE_URL, json=BODY).content == _valid_advice_document()


def test_corrupt_job_is_unavailable_not_missing(tmp_path: Path) -> None:
    client, _cache, _queue = _world(tmp_path)
    posted = client.post(ADVICE_URL, json=BODY)
    identifier = posted.json()["job_id"]
    (tmp_path / "jobs" / f"{identifier}.json").write_bytes(b"bad json")
    response = client.get(f"/api/v1/advice-jobs/{identifier}")
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "QUEUE_INTEGRITY_ERROR"


# --- submit-path failures are the client's or the moment's, never a 500 -----------------


def test_a_malformed_idempotency_key_is_refused_and_spends_no_token(tmp_path: Path) -> None:
    client, _cache, queue = _world(
        tmp_path, rate_limiter=FixedWindowRateLimiter(limit=1, window_seconds=60.0)
    )

    for bad in ("has spaces", "x" * 200, "-leading"):
        refused = client.post(ADVICE_URL, json=BODY, headers={"Idempotency-Key": bad})
        assert refused.status_code == 422, bad
        assert refused.json()["error"]["code"] == "VALIDATION_FAILED"
    assert queue.jobs() == ()
    # The one token is still there for a request that can be accepted.
    assert client.post(ADVICE_URL, json=BODY).status_code == 202


def test_a_rate_limited_client_is_told_when_to_come_back(tmp_path: Path) -> None:
    client, _cache, _queue = _world(
        tmp_path, rate_limiter=FixedWindowRateLimiter(limit=1, window_seconds=45.0)
    )
    assert client.post(ADVICE_URL, json=BODY).status_code == 202
    refused = client.post(ADVICE_URL, json=BODY)
    assert refused.status_code == 429
    assert refused.headers["Retry-After"] == "45"


def _failing_submit(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, error: Exception):
    client, _cache, queue = _world(tmp_path)

    def refuse(*_args: object, **_kwargs: object) -> None:
        raise error

    monkeypatch.setattr(FileJobQueue, "submit_unless_cached", refuse)
    return client, queue


def test_a_busy_queue_lock_is_not_ready_with_a_retry_after(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from squadopt.platform.queue_contracts import QueueLockTimeout

    client, _queue = _failing_submit(tmp_path, monkeypatch, QueueLockTimeout("busy"))
    response = client.post(ADVICE_URL, json=BODY)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "NOT_READY"
    assert int(response.headers["Retry-After"]) >= 1


def test_a_refused_queue_write_is_unavailable_not_an_internal_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from squadopt.platform.queue_contracts import AdviceQueueError

    client, _queue = _failing_submit(
        tmp_path, monkeypatch, AdviceQueueError("Job 'advice-x-1' already exists at C:/store.")
    )
    response = client.post(ADVICE_URL, json=BODY)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "QUEUE_UNAVAILABLE"
    assert "C:/store" not in response.text  # the queue's own words stay in the log


def test_two_meanings_under_one_address_is_a_conflict(tmp_path: Path) -> None:
    from squadopt.platform.advice_job_spec import AdviceJobSpec, FileAdviceJobSpecStore

    specs = FileAdviceJobSpecStore(tmp_path / "specs")
    client, _cache, queue = _world(tmp_path, specs=specs)
    accepted = client.post(ADVICE_URL, json=BODY)
    assert accepted.status_code == 202
    job = queue.load(accepted.json()["job_id"])
    # The address already records another question: written by hand here, a defect if it
    # ever happens for real, and either way the client's answer is a 409, not a 500.
    path = tmp_path / "specs" / job.cache_key[:2] / f"{job.cache_key}.json"
    other = AdviceJobSpec(
        league_id=LEAGUE_ID, entry_id=2199732, strategy="saf-puan", window=1, context=CONTEXT
    )
    path.write_text(json.dumps(other.as_payload(), sort_keys=True), encoding="utf-8")
    (tmp_path / "jobs" / f"{job.job_id}.json").unlink()
    for index in (tmp_path / "jobs").glob("open-*.idx"):
        index.unlink()

    response = client.post(ADVICE_URL, json=BODY)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "REQUEST_CONFLICT"


def test_a_slow_submit_does_not_hold_other_requests(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    services: list[AdviceSubmitService] = []
    client, _cache, queue = _world(tmp_path, submit_services=services)
    submit = services[0].submit
    entered, release = Event(), Event()

    def slow_submit(**fields: object) -> SubmitOutcome:
        entered.set()
        # Sleeps until the test lets it go; the bound makes a regression fail, not hang.
        release.wait(timeout=5)
        return submit(**fields)

    monkeypatch.setattr(services[0], "submit", slow_submit)
    # One client is one event loop, shared by both requests as uvicorn's one loop is.
    with TestClient(client.app) as shared, ThreadPoolExecutor(max_workers=1) as poster:
        pending = poster.submit(shared.post, ADVICE_URL, json=BODY)
        assert entered.wait(timeout=10)
        health = shared.get("/health")
        answered_while_submitting = not pending.done()
        release.set()
        accepted = pending.result(timeout=10)
    assert health.status_code == 200
    assert answered_while_submitting
    assert accepted.status_code == 202
    assert [job.job_id for job in queue.jobs()] == [accepted.json()["job_id"]]


def test_the_rate_limiter_counts_every_thread() -> None:
    limiter = FixedWindowRateLimiter(2000, 3600.0)
    allowed: list[int] = []
    tally = Lock()
    start = Barrier(8)

    def spend() -> None:
        start.wait(timeout=10)
        mine = sum(limiter.allow("ip:203.0.113.9") for _ in range(500))
        with tally:
            allowed.append(mine)

    # A tiny switch interval makes the threads interleave inside allow; unlocked, the
    # read and the write of one bucket's count raced and let far more than the limit in.
    interval = sys.getswitchinterval()
    sys.setswitchinterval(1e-6)
    try:
        threads = [Thread(target=spend) for _ in range(8)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join(timeout=30)
    finally:
        sys.setswitchinterval(interval)
    assert len(allowed) == 8
    assert sum(allowed) == 2000


def test_one_key_sent_for_two_requests_at_once_is_still_a_conflict(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    client, _cache, queue = _world(tmp_path)
    scan = queue.jobs
    both_read = Barrier(2)

    def history() -> tuple[AdviceJob, ...]:
        # Holds each submission after its history read until the other has read too, so
        # an unserialized check lets both see an empty history and both enqueue. Serialized,
        # the second can never arrive while the first waits, and the timeout lets it go.
        found = scan()
        with suppress(BrokenBarrierError):
            both_read.wait(timeout=2)
        return found

    monkeypatch.setattr(queue, "jobs", history)
    key = {"Idempotency-Key": "client:shared:1"}
    requests = (BODY, {**BODY, "window": 3})
    # One client is one event loop, shared by both requests as uvicorn's one loop is.
    with TestClient(client.app) as shared, ThreadPoolExecutor(max_workers=2) as posters:
        answers = list(
            posters.map(lambda body: shared.post(ADVICE_URL, json=body, headers=key), requests)
        )
    monkeypatch.setattr(queue, "jobs", scan)

    assert sorted(answer.status_code for answer in answers) == [202, 409]
    accepted, refused = sorted(answers, key=lambda answer: answer.status_code)
    assert refused.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"
    assert [
        job.job_id for job in queue.jobs() if job.idempotency_key == key["Idempotency-Key"]
    ] == [accepted.json()["job_id"]]
    # The accepted request keeps its key: replayed, it is the same job, not a conflict.
    body = requests[answers.index(accepted)]
    replay = client.post(ADVICE_URL, json=body, headers=key)
    assert replay.status_code == 202
    assert replay.json()["job_id"] == accepted.json()["job_id"]
