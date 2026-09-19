"""The POST: a hit, one open job per request, idempotency, CORS, and rate limits."""

import json
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime
from pathlib import Path
from threading import Barrier

import pytest
from fastapi.testclient import TestClient

from squadopt.api.app import create_app
from squadopt.platform.advice_cache import FileAdviceCache
from squadopt.platform.advice_job_spec import FileAdviceJobSpecStore
from squadopt.platform.advice_observability import API_COUNTER_FAMILIES, AdviceMetrics
from squadopt.platform.advice_queue import FileJobQueue, run_advice_worker_once
from squadopt.platform.advice_read import (
    AdviceReadStore,
    AdviceRequestContext,
    FileLeagueDirectory,
)
from squadopt.platform.advice_submit import (
    AdviceSubmitService,
    FixedWindowRateLimiter,
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
    )
    submit = AdviceSubmitService(reader, queue, **app_kwargs)
    application = create_app(
        data_root=tmp_path / "site",
        advice_store=reader,
        advice_submit=submit,
        metrics=metrics,
        allowed_origins=allowed_origins,
        utc_now=lambda: datetime(2026, 8, 27, 12, 0, tzinfo=UTC),
    )
    client = TestClient(application, raise_server_exceptions=False)
    return client, cache, queue


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


def test_a_failed_spec_write_leaves_no_job_or_occupied_slot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    specs = FileAdviceJobSpecStore(tmp_path / "specs")
    client, _cache, queue = _world(tmp_path, specs=specs, max_open_jobs_per_client=1)
    original = specs.put

    def fail(_key, _spec):
        raise OSError("fixture write failure")

    monkeypatch.setattr(specs, "put", fail)
    assert client.post(ADVICE_URL, json=BODY).status_code == 500
    assert queue.jobs() == ()
    monkeypatch.setattr(specs, "put", original)
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
