"""A capacity report must preserve failures instead of counting accepted jobs as success."""

import json

import pytest

from squadopt.platform import advice_load

REQUEST = {"league_id": 352490, "entry_id": 101, "strategy": "saf-puan", "window": 1}


def test_capacity_reports_terminal_failure_for_every_waiting_client(monkeypatch) -> None:
    def http(url, *, body, timeout):
        if url.endswith("/metrics"):
            return 200, b"advice_queue_depth 1\n"
        if body is not None:
            return 202, b'{"job_id":"test-job"}'
        return 200, json.dumps({"status": "failed", "error_code": "ADVICE_FAILED"}).encode()

    monkeypatch.setattr(advice_load, "_http", http)
    report = advice_load.run_burst("http://example.invalid", [REQUEST], scenario="dedup", users=3)
    assert report["completed"] == 0
    assert report["failed"] == 3
    assert report["unique_job_count"] == 1
    assert report["completion_p95_seconds"] is None
    assert all("ADVICE_FAILED" in row["error"] for row in report["rows"])


def test_rate_limited_requests_remain_failed_and_are_not_retried(monkeypatch) -> None:
    calls = []

    def http(url, *, body, timeout):
        if url.endswith("/metrics"):
            return 200, b"advice_queue_depth 0\n"
        calls.append(url)
        return 429, b"{}"

    monkeypatch.setattr(advice_load, "_http", http)
    report = advice_load.run_burst(
        "http://example.invalid", [REQUEST], scenario="cache-hit", users=4
    )
    assert report["submit_status_counts"] == {"429": 4}
    assert report["failed"] == len(calls) == 4


def test_distinct_probe_refuses_duplicate_coordinates_before_network(monkeypatch) -> None:
    def http(*args, **kwargs):
        pytest.fail("Invalid capacity inputs must not reach a deployment.")

    monkeypatch.setattr(advice_load, "_http", http)
    with pytest.raises(ValueError, match="different request"):
        advice_load.run_burst(
            "http://example.invalid", [REQUEST, REQUEST], scenario="distinct", users=2
        )
