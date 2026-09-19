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
advice_open_job_refused_total 2
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
    assert "Open-job refusals (API): 2" in report
    assert "Jobs by status (API): unavailable" in report
    assert "window 3, retained logs only): unavailable" in report
    assert "Completions without window (retained logs): 2" in report
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
    assert status._metric([], "advice_open_job_refused_total") == status.UNAVAILABLE
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


def test_job_gauges_and_initial_zero_counters_are_distinct_from_unexposed(tmp_path: Path) -> None:
    from squadopt.platform.advice_observability import API_COUNTER_FAMILIES, AdviceMetrics

    metrics = AdviceMetrics(zero_counters=API_COUNTER_FAMILIES)
    body = metrics.render(
        queue_depth=2,
        jobs_by_status={
            "queued": 1,
            "running": 1,
            "completed": 7,
            "failed": 0,
        },
    )
    _, report = status.status_report(
        "http://127.0.0.1:18764",
        "https://public.test",
        tmp_path,
        transport=lambda url: (200, body) if url.endswith("/metrics") else (503, "{}"),
    )
    assert "status=completed: 7" in report and "status=running: 1" in report
    assert "hits=0; misses=0" in report
    assert "Request refusals (API): 0" in report
    assert "Open-job refusals (API): 0" in report
    assert status._labelled([], "advice_rejected_total") == status.UNAVAILABLE


def test_window_summaries_use_exact_completed_samples_and_keep_legacy_counts(
    tmp_path: Path,
) -> None:
    records = [
        {"window": 1, "wall_seconds": 1},
        {"window": 1, "wall_seconds": 9},
        {"window": 3, "wall_seconds": 30},
        {"window": 5, "wall_seconds": 50},
        {"wall_seconds": 7},
        {"window": True, "wall_seconds": 8},
    ]
    lines = [
        json.dumps({"event": "advice_job_completed", "at_utc": "2026-09-19T00:00:00Z", **r})
        for r in records
    ]
    lines.append(
        json.dumps(
            {
                "event": "advice_job_failed",
                "at_utc": "2026-09-19T00:00:01Z",
                "window": 1,
                "wall_seconds": 100,
            }
        )
    )
    (tmp_path / "worker-1.log").write_text("\n".join(lines), encoding="utf-8")
    _, report = status.status_report(
        "http://127.0.0.1:18764",
        "https://public.test",
        tmp_path,
        transport=lambda url: (503, "{}"),
    )
    assert "window 1, retained logs only): n=2, median=5.000, slowest=9.000" in report
    assert "window 3, retained logs only): n=1, median=30.000, slowest=30.000" in report
    assert "window 5, retained logs only): n=1, median=50.000, slowest=50.000" in report
    assert "all windows, retained logs only): n=6, median=8.500, slowest=50.000" in report
    assert "Completions without window (retained logs): 2" in report


def test_latest_startup_trust_reports_only_declared_fields(tmp_path: Path) -> None:
    records = [
        {
            "event": "advice_forwarded_trust",
            "component": "api",
            "at_utc": "2026-09-19T01:00:00Z",
            "trust_status": "enabled",
            "trust_source": "uvicorn commandline",
            "forwarded_allow_ips": "192.0.2.20",
            "forwarded_allow_ips_set": True,
            "forwarded_allow_ips_count": 1,
            "proxy_headers_source": "uvicorn commandline",
            "client_address": "198.51.100.9",
        },
        {
            "event": "advice_forwarded_trust",
            "component": "api",
            "at_utc": "2026-09-19T02:00:00Z",
            "trust_status": "unverified",
            "trust_source": "unknown launcher",
        },
    ]
    (tmp_path / "api-1.log").write_text(
        "\n".join(json.dumps(record) for record in records), encoding="utf-8"
    )
    _, report = status.status_report(
        "http://127.0.0.1:18764", "https://public.test", tmp_path, transport=lambda url: (200, "{}")
    )
    assert (
        "Forwarded-header trust (last API startup in retained logs, not a live check): unverified"
        in report
    )
    assert 'source="unknown launcher"' in report
    assert "198.51.100.9" not in report
    assert "configured allowlist" not in report
    (tmp_path / "api-1.log").write_text(json.dumps(records[0]), encoding="utf-8")
    _, report = status.status_report(
        "http://127.0.0.1:18764", "https://public.test", tmp_path, transport=lambda url: (200, "{}")
    )
    assert "allowlist explicitly set=true" in report
    assert "allowlist entries=1" in report
    assert "192.0.2.20" not in report
    assert 'source="uvicorn commandline"' in report
    assert "198.51.100.9" not in report
