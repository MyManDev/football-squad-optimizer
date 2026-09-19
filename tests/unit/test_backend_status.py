"""Read-only status: existing metric/log shapes, partial logs and unavailable evidence."""

from __future__ import annotations

import http.client
import json
import os
import time
import urllib.error
from pathlib import Path

import pytest
from scripts import backend_status as status

METRICS = """# TYPE advice_queue_depth gauge
advice_queue_depth 2
advice_cache_hits_total 7
advice_cache_misses_total 3
advice_rejected_total{reason="DataError"} 1
advice_solve_seconds_bucket{le="300.0"} 5
advice_solve_seconds_sum 400
advice_solve_seconds_count 5
"""


def _logs(root: Path) -> None:
    records = [
        {"event": "advice_worker_warmed", "snapshot_id": "capture-old"},
        {"event": "advice_job_completed", "wall_seconds": 2},
        {"event": "advice_job_completed", "wall_seconds": 10},
        {"event": "advice_job_refused", "code": "TIME_BUDGET_EXCEEDED"},
        {"event": "advice_job_completed", "wall_seconds": True},
        {"event": "advice_job_completed", "wall_seconds": float("nan")},
    ]
    lines = [
        json.dumps({**record, "at_utc": f"2026-09-19T00:00:0{index}Z"})
        for index, record in enumerate(records)
    ]
    (root / "worker-1.out.log").write_text("\n".join(lines) + '\n{"event":', encoding="utf-8")
    # Ignored even when the caller supplies a directory containing live store files.
    (root / "run.json").write_text("not a log", encoding="utf-8")


def test_canned_metrics_and_actual_log_shapes_are_reported_without_invented_values(
    tmp_path: Path,
) -> None:
    _logs(tmp_path)
    requests: list[str] = []

    def transport(url: str) -> tuple[int, str]:
        requests.append(url)
        if url.endswith("/ready"):
            return 200, json.dumps({"ready": True, "checks": {"league_tree_matches_capture": True}})
        return (200, METRICS) if url.endswith("/metrics") else (200, "{}")

    code, report = status.status_report(
        "http://127.0.0.1:18764", "https://public.test", tmp_path, transport=transport
    )
    assert code == 0
    assert len(requests) == 3
    assert "Queue depth (API): 2" in report
    assert "hits=7; misses=3" in report
    assert "reason=DataError: 1" in report
    assert "Jobs by status (API metric outcomes): unavailable" in report
    assert "Solve median/slowest by window: unavailable" in report
    assert "n=2, median=6.000, slowest=10.000" in report
    assert "6 records, 2026-09-19T00:00:00Z to 2026-09-19T00:00:05Z; non-JSON lines=1" in report
    assert "TIME_BUDGET_EXCEEDED=1" in report
    assert "capture-old at" in report
    assert "Published capture ID: unavailable" in report


@pytest.mark.parametrize("failure", ["not-ready", "invalid-json", "unreachable", "public-down"])
def test_unready_or_unreachable_is_failure_and_other_sources_still_report(
    tmp_path: Path, failure: str
) -> None:
    def transport(url: str) -> tuple[int, str]:
        if url.endswith("/metrics"):
            return 200, METRICS
        if url.endswith("/health"):
            return (502 if failure == "public-down" else 200), "{}"
        if failure == "unreachable":
            raise urllib.error.URLError("offline")
        if failure == "invalid-json":
            return 200, "not json"
        return (503 if failure == "not-ready" else 200), json.dumps(
            {"ready": failure != "not-ready", "checks": {"capture_context": failure != "not-ready"}}
        )

    code, report = status.status_report(
        "http://127.0.0.1:18764", "https://public.test", tmp_path, transport=transport
    )
    assert code == (2 if failure == "public-down" else 1)
    assert report.startswith(
        "READY, public check failed" if failure == "public-down" else "NOT READY"
    )
    assert "Queue depth (API): 2" in report


def test_missing_metrics_are_unknown_and_invalid_samples_do_not_become_zero(tmp_path: Path) -> None:
    assert status.parse_metrics("advice_queue_depth NaN\nadvice_cache_hits_total -1") == []
    summary = status.read_logs(tmp_path / "missing")
    assert summary.unreadable == 1
    assert not summary.completed_seconds
    assert status._metric([], "advice_queue_depth") == status.UNAVAILABLE
    assert (
        status._labelled(
            status.parse_metrics('advice_jobs_total{outcome="completed"} 3'), "advice_jobs_total"
        )
        == "outcome=completed: 3"
    )


def test_transport_sends_named_user_agent_and_only_get(monkeypatch: pytest.MonkeyPatch) -> None:
    observed: list[object] = []

    def opened(request: object, *, timeout: int) -> object:
        observed.append(request)
        raise urllib.error.URLError("test only")

    monkeypatch.setattr(status.urllib.request, "urlopen", opened)
    with pytest.raises(urllib.error.URLError):
        status.get_text("https://public.test/health")
    request = observed[0]
    assert request.get_method() == "GET"
    assert request.get_header("User-agent") == status.USER_AGENT


@pytest.mark.parametrize("code", [0, 1, 2])
def test_exit_code_follows_readiness(monkeypatch: pytest.MonkeyPatch, code: int) -> None:
    monkeypatch.setattr(status, "status_report", lambda *args, **kwargs: (code, "test report"))
    assert status.main(["--base-url", "http://127.0.0.1:18764"]) == code


def test_non_loopback_metrics_target_is_rejected() -> None:
    with pytest.raises(SystemExit) as error:
        status.main(["--base-url", "https://public.test"])
    assert error.value.code == 2


@pytest.mark.parametrize(
    "error", [http.client.IncompleteRead(b""), http.client.BadStatusLine("bad")]
)
@pytest.mark.parametrize("endpoint,expected_code", [("ready", 1), ("metrics", 0), ("health", 2)])
def test_http_protocol_errors_keep_other_sources_available(
    tmp_path: Path, error: Exception, endpoint: str, expected_code: int
) -> None:
    def transport(url: str) -> tuple[int, str]:
        if url.endswith("/" + endpoint):
            raise error
        if url.endswith("/ready"):
            return 200, json.dumps({"ready": True, "checks": {"capture_context": True}})
        return 200, METRICS

    code, report = status.status_report(
        "http://127.0.0.1:18764", "https://public.test", tmp_path, transport=transport
    )
    assert code == expected_code
    assert type(error).__name__ in report
    assert "Logs:" in report


def test_log_age_is_bounded_by_mtime_and_report_counts_files(tmp_path: Path) -> None:
    _logs(tmp_path)
    old = tmp_path / "api-old.log"
    old.write_text("old access line", encoding="ascii")
    past = time.time() - 8 * 86400
    os.utime(old, (past, past))
    summary = status.read_logs(tmp_path)
    assert summary.files == 1 and summary.skipped_old == 1
    assert summary.ignored == 1
    older = status.read_logs(tmp_path, days=9)
    assert older.files == 2 and older.skipped_old == 0
    assert older.ignored == 2


def test_non_positive_days_rejected() -> None:
    with pytest.raises(SystemExit) as error:
        status.main(["--days", "0"])
    assert error.value.code == 2
