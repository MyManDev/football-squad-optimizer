"""The POST: a hit, one open job per request, idempotency, CORS, and rate limits."""

import json
from pathlib import Path

from fastapi.testclient import TestClient

from squadopt.api.app import create_app
from squadopt.platform.advice_cache import FileAdviceCache
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
from squadopt.platform.jobs_contract import AdviceJob

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


class _Context:
    def current(self) -> AdviceRequestContext:
        return CONTEXT


def _publish_members(root: Path) -> None:
    payload = {
        "league_id": LEAGUE_ID,
        "league_name": "Test League",
        "season": "2026-27",
        "gameweek": 3,
        "members": [
            {"member_kind": "human", "entry_id": 313686},
            {"member_kind": "human", "entry_id": 2199732},
        ],
    }
    document = {"contract_version": "provisional_league_ui_v1", "payload": payload}
    path = root / "league" / "members.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8", newline="\n")


def _world(tmp_path: Path, **app_kwargs: object):
    _publish_members(tmp_path / "site")
    cache = FileAdviceCache(tmp_path / "cache")
    queue = FileJobQueue(tmp_path / "jobs")
    reader = AdviceReadStore(
        FileLeagueDirectory(tmp_path / "site"), cache, _Context(), {"saf-puan": False}
    )
    submit = AdviceSubmitService(reader, queue, **app_kwargs)
    application = create_app(data_root=tmp_path / "site", advice_store=reader, advice_submit=submit)
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
        return b'{"payload": {"moves": []}}'

    done = run_advice_worker_once(queue, cache, compute, at_utc="2026-08-27T18:00:00Z")
    assert done is not None and done.status == "completed"

    assert client.get(f"/api/v1/advice-jobs/{job_id}").json()["status"] == "completed"
    second = client.post(ADVICE_URL, json=BODY)
    assert second.status_code == 200  # a hit now, no new job
    assert second.content == b'{"payload": {"moves": []}}'
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
