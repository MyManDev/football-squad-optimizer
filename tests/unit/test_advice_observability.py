"""Observability: metrics that read true, readiness apart from liveness, JSON lines."""

import json
import logging
from pathlib import Path

from fastapi.testclient import TestClient

from squadopt.api.app import create_app
from squadopt.platform.advice_cache import FileAdviceCache
from squadopt.platform.advice_observability import (
    AdviceLog,
    AdviceMetrics,
    readiness_report,
)
from squadopt.platform.advice_queue import FileJobQueue, run_advice_worker_once
from squadopt.platform.advice_read import (
    AdviceReadStore,
    AdviceRequestContext,
    FileLeagueDirectory,
)
from squadopt.platform.advice_submit import AdviceSubmitService
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


class _Context:
    def current(self) -> AdviceRequestContext:
        return CONTEXT


def _publish_members(root: Path) -> None:
    payload = {
        "league_id": LEAGUE_ID,
        "league_name": "Test League",
        "season": "2026-27",
        "gameweek": 3,
        "members": [{"member_kind": "human", "entry_id": 313686}],
    }
    document = {"contract_version": "provisional_league_ui_v1", "payload": payload}
    path = root / "league" / "members.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(document), encoding="utf-8", newline="\n")


def test_the_scrape_reads_true_counts_and_live_queue_depth(tmp_path: Path) -> None:
    _publish_members(tmp_path / "site")
    cache = FileAdviceCache(tmp_path / "cache")
    queue = FileJobQueue(tmp_path / "jobs")
    reader = AdviceReadStore(
        FileLeagueDirectory(tmp_path / "site"), cache, _Context(), {"saf-puan": False}
    )
    metrics = AdviceMetrics()
    application = create_app(
        data_root=tmp_path / "site",
        advice_store=reader,
        advice_submit=AdviceSubmitService(reader, queue),
        metrics=metrics,
        queue_depth=lambda: len([j for j in queue.jobs() if j.status == "queued"]),
    )
    client = TestClient(application, raise_server_exceptions=False)
    url = f"/api/v1/leagues/{LEAGUE_ID}/entries/313686/advice"

    client.get(f"{url}?strategy=saf-puan&window=1")  # miss
    client.post(url, json={"strategy": "saf-puan", "window": 1})  # job
    client.get(f"/api/v1/leagues/{LEAGUE_ID}/entries/99/advice?strategy=saf-puan&window=1")

    scrape = client.get("/metrics")
    assert scrape.status_code == 200
    body = scrape.text
    assert "advice_queue_depth 1" in body  # read from the store at scrape time
    assert "advice_cache_misses_total" in body
    assert 'advice_rejected_total{reason="UnknownEntryError"} 1' in body
    assert "advice_jobs_submitted_total 1" in body


def test_the_worker_reports_solve_seconds_and_outcomes(tmp_path: Path) -> None:
    cache = FileAdviceCache(tmp_path / "cache")
    queue = FileJobQueue(tmp_path / "jobs")
    metrics = AdviceMetrics()
    queue.submit(
        AdviceJob(
            job_id="job-1",
            status="queued",
            request_fingerprint="a" * 64,
            cache_key="b" * 64,
            created_at_utc="2026-08-27T12:00:00Z",
            updated_at_utc="2026-08-27T12:00:00Z",
        )
    )

    run_advice_worker_once(
        queue, cache, lambda job: b"{}", at_utc="2026-08-27T12:00:30Z", metrics=metrics
    )

    body = metrics.render()
    assert 'advice_jobs_total{outcome="completed"} 1' in body
    assert "advice_solve_seconds_count 1" in body
    assert 'advice_solve_seconds_bucket{le="+Inf"} 1' in body


def test_readiness_is_separate_from_liveness(tmp_path: Path) -> None:
    """A full disk must not look healthy: /health stays up, /ready says no."""

    broken = create_app(
        data_root=tmp_path / "site",
        readiness=lambda: readiness_report(
            context_loaded=True, league_tree_readable=True, cache_writable=False
        ),
    )
    client = TestClient(broken, raise_server_exceptions=False)
    assert client.get("/health").status_code == 200
    not_ready = client.get("/ready")
    assert not_ready.status_code == 503
    assert not_ready.json()["checks"]["cache_store"] is False

    served = tmp_path / "site"
    served.mkdir(parents=True, exist_ok=True)
    static_app = create_app(data_root=served)
    static_client = TestClient(static_app, raise_server_exceptions=False)
    ready = static_client.get("/ready")
    assert ready.status_code == 200
    assert ready.json()["checks"] == {"site_data_root": True}
    assert static_client.get("/metrics").status_code == 404  # not enabled, said plainly

    hollow = create_app(data_root=tmp_path / "nowhere")
    hollow_client = TestClient(hollow, raise_server_exceptions=False)
    unready = hollow_client.get("/ready")
    assert unready.status_code == 503  # never ready by default, only by looking
    assert unready.json()["checks"] == {"site_data_root": False}


def test_the_log_writes_one_json_object_per_line(tmp_path: Path, caplog: "object") -> None:
    logger = logging.getLogger("advice.test")
    records: list[str] = []

    class _Capture(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record.getMessage())

    handler = _Capture()
    logger.addHandler(handler)
    logger.setLevel(logging.INFO)
    try:
        log = AdviceLog("worker", logger)
        log.event(
            "advice_job_completed",
            job_id="job-1",
            cache_key="b" * 64,
            wall_seconds=12.5,
            rival_entry_id=None,  # absent fields are dropped, not nulled
        )
    finally:
        logger.removeHandler(handler)

    assert len(records) == 1
    parsed = json.loads(records[0])
    assert parsed["event"] == "advice_job_completed"
    assert parsed["component"] == "worker"
    assert parsed["job_id"] == "job-1"
    assert "rival_entry_id" not in parsed
    assert parsed["at_utc"].endswith("Z")


def test_histogram_buckets_are_inclusive_at_their_boundaries() -> None:
    """The reviewer's exact case: an observation of 0.1 belongs to le="0.1"."""

    metrics = AdviceMetrics()
    metrics.observe("advice_solve_seconds", 0.1)
    body = metrics.render()
    assert 'advice_solve_seconds_bucket{le="0.1"} 1' in body


def test_type_metadata_appears_once_per_family() -> None:
    metrics = AdviceMetrics()
    metrics.solver_status("OPTIMAL")
    metrics.solver_status("FEASIBLE")
    body = metrics.render()
    assert body.count("# TYPE advice_solver_status_total counter") == 1
    assert 'advice_solver_status_total{status="OPTIMAL"} 1' in body
    assert 'advice_solver_status_total{status="FEASIBLE"} 1' in body


def test_the_worker_observes_wait_status_and_failed_solves(tmp_path: Path) -> None:
    """Wait at claim; solve latency on failure too; solver status from the payload."""

    import json as _json

    cache = FileAdviceCache(tmp_path / "cache")
    queue = FileJobQueue(tmp_path / "jobs")
    metrics = AdviceMetrics()

    document = _json.dumps(
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
                "solver_status": "FEASIBLE",
                "data_quality": "complete",
                "missing_fields": [],
            },
        }
    ).encode("utf-8")

    queue.submit(
        AdviceJob(
            job_id="job-ok",
            status="queued",
            request_fingerprint="a" * 64,
            cache_key="b" * 64,
            created_at_utc="2026-08-27T12:00:00Z",
            updated_at_utc="2026-08-27T12:00:00Z",
        )
    )
    run_advice_worker_once(
        queue, cache, lambda job: document, at_utc="2026-08-27T12:00:30Z", metrics=metrics
    )

    queue.submit(
        AdviceJob(
            job_id="job-bad",
            status="queued",
            request_fingerprint="c" * 64,
            cache_key="d" * 64,
            created_at_utc="2026-08-27T12:01:00Z",
            updated_at_utc="2026-08-27T12:01:00Z",
        )
    )

    def explode(job: AdviceJob) -> bytes:
        raise RuntimeError("nope")

    run_advice_worker_once(queue, cache, explode, at_utc="2026-08-27T12:01:30Z", metrics=metrics)

    body = metrics.render()
    assert "advice_job_wait_seconds_count 2" in body  # observed at claim, both jobs
    assert "advice_solve_seconds_count 2" in body  # failures are not omitted
    assert 'advice_solver_status_total{status="FEASIBLE"} 1' in body
    assert 'advice_jobs_total{outcome="failed"} 1' in body
