"""The backend smoke walks the real routes and fails on the first thing that does not hold.

Driven against a stub HTTP server rather than a fake transport, because what the script
gets wrong in practice is HTTP: a 503 that is an answer and not an exception, a 202 whose
body has to be read, a header whose case is the server's choice.
"""

from __future__ import annotations

import json
import threading
from collections.abc import Iterator
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from scripts import smoke_backend_local as smoke

LEAGUE = 352490
ENTRY = 101
JOB = "advice-0123456789abcdef-1"
ORIGIN = "https://squadopt.mymandev.com"


class StubBackend:
    """The five routes, with the few knobs a failure needs."""

    def __init__(self) -> None:
        self.ready = True
        self.connected = True
        self.post_status = 202
        self.job_statuses = ["queued", "running", "completed"]
        self.error_code: str | None = None
        self.allow_origin: str | None = ORIGIN
        self.requests: list[tuple[str, str, dict[str, object] | None]] = []
        self.user_agents: set[str] = set()

    def advice(self) -> dict[str, object]:
        return {
            "contract_version": "league_view_v1",
            "payload": {
                "entry_id": ENTRY,
                "mode": "saf-puan",
                "solver_status": "OPTIMAL",
                "source_snapshot_id": "fpl-live-stub",
            },
        }

    def answer(self, method: str, path: str) -> tuple[int, dict[str, object]]:
        if path == "/health":
            return 200, {"service": "stub"}
        if path == "/ready":
            checks = {"capture_context": self.ready, "league_tree": True, "cache_store": True}
            return (200 if self.ready else 503), {"ready": self.ready, "checks": checks}
        if path == f"/api/v1/leagues/{LEAGUE}":
            return 200, {"connected": self.connected, "season": "2026-27", "gameweek": 5}
        if path.startswith(f"/api/v1/leagues/{LEAGUE}/entries/{ENTRY}/advice"):
            if method == "POST" and self.post_status == 202:
                return 202, {"job_id": JOB, "status": "queued"}
            return 200, self.advice()
        if path == f"/api/v1/advice-jobs/{JOB}":
            status = (
                self.job_statuses.pop(0) if len(self.job_statuses) > 1 else self.job_statuses[0]
            )
            error = self.error_code if status == "failed" else None
            return 200, {"job_id": JOB, "status": status, "error_code": error}
        return 404, {"error": {"code": "NOT_FOUND"}}


@pytest.fixture
def backend() -> Iterator[tuple[StubBackend, str]]:
    stub = StubBackend()

    class Handler(BaseHTTPRequestHandler):
        def _serve(self, method: str) -> None:
            length = int(self.headers.get("Content-Length") or 0)
            body = json.loads(self.rfile.read(length)) if length else None
            stub.requests.append((method, self.path, body))
            stub.user_agents.add(self.headers.get("User-Agent", ""))
            status, document = stub.answer(method, self.path)
            encoded = json.dumps(document).encode("utf-8")
            self.send_response(status)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(encoded)))
            if stub.allow_origin and self.headers.get("Origin"):
                # Lower case on purpose: header names are case-insensitive on the wire.
                self.send_header("access-control-allow-origin", stub.allow_origin)
            self.end_headers()
            self.wfile.write(encoded)

        def do_GET(self) -> None:
            self._serve("GET")

        def do_POST(self) -> None:
            self._serve("POST")

        def log_message(self, format: str, *args: object) -> None:
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield stub, f"http://127.0.0.1:{server.server_port}"
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)


def _run(base_url: str, **overrides: object) -> tuple[int, list[str]]:
    lines: list[str] = []
    options: dict[str, object] = {"sleep": lambda _seconds: None, "report": lines.append}
    options.update(overrides)
    code = smoke.run_smoke(base_url, LEAGUE, ENTRY, **options)  # type: ignore[arg-type]
    return code, lines


def test_a_filed_job_is_polled_to_completion_and_the_answer_read_back(
    backend: tuple[StubBackend, str],
) -> None:
    stub, base_url = backend

    code, lines = _run(base_url + "/")

    assert code == 0
    assert lines[-1] == "smoke: ok"
    assert "advice: solver_status OPTIMAL" in lines
    assert any(line.startswith("elapsed: ") and "POST to completed" in line for line in lines)
    polls = [path for _method, path, _body in stub.requests if path.endswith(JOB)]
    assert len(polls) == 3
    posted = [body for method, _path, body in stub.requests if method == "POST"]
    assert posted == [{"strategy": "saf-puan", "window": 1, "rival_entry_id": None}]
    assert stub.requests[-1][1].endswith("/advice?strategy=saf-puan&window=1")
    assert stub.user_agents == {smoke.USER_AGENT}


def test_a_cache_hit_claims_no_elapsed_time(backend: tuple[StubBackend, str]) -> None:
    stub, base_url = backend
    stub.post_status = 200

    code, lines = _run(base_url)

    assert code == 0
    assert "elapsed: not measured (cache hit)" in lines
    assert not any(path.endswith(JOB) for _method, path, _body in stub.requests)


def test_an_unready_backend_fails_and_names_the_checks(backend: tuple[StubBackend, str]) -> None:
    stub, base_url = backend
    stub.ready = False

    code, lines = _run(base_url)

    assert code == 1
    assert lines[-1].startswith("FAILED: /ready: not ready (HTTP 503)")
    assert "'capture_context': False" in lines[-1]
    assert not any(method == "POST" for method, _path, _body in stub.requests)


def test_a_league_that_is_not_connected_fails(backend: tuple[StubBackend, str]) -> None:
    stub, base_url = backend
    stub.connected = False

    code, lines = _run(base_url)

    assert code == 1
    assert "not connected" in lines[-1]


def test_a_failed_job_fails_with_its_code(backend: tuple[StubBackend, str]) -> None:
    stub, base_url = backend
    stub.job_statuses = ["running", "failed"]
    stub.error_code = "CONTEXT_UNAVAILABLE"

    code, lines = _run(base_url)

    assert code == 1
    assert "error_code CONTEXT_UNAVAILABLE" in lines[-1]


def test_a_job_nobody_computes_times_out(backend: tuple[StubBackend, str]) -> None:
    stub, base_url = backend
    stub.job_statuses = ["queued"]
    ticks = iter(range(0, 10_000, 40))

    code, lines = _run(base_url, clock=lambda: float(next(ticks)), timeout_seconds=100.0)

    assert code == 1
    assert "still queued" in lines[-1]
    assert "is a worker running" in lines[-1]


def test_an_origin_the_answer_does_not_allow_fails(backend: tuple[StubBackend, str]) -> None:
    stub, base_url = backend
    stub.allow_origin = "https://somewhere.else"

    code, lines = _run(base_url, origin=ORIGIN)

    assert code == 1
    assert lines[-1].startswith("FAILED: CORS:")


def test_an_allowed_origin_is_reported(backend: tuple[StubBackend, str]) -> None:
    _stub, base_url = backend

    code, lines = _run(base_url, origin=ORIGIN)

    assert code == 0
    assert f"cors: {ORIGIN} allowed" in lines


def test_a_rival_is_sent_in_the_body_and_the_read(backend: tuple[StubBackend, str]) -> None:
    stub, base_url = backend

    code, _lines = _run(base_url, rival_entry_id=202)

    assert code == 0
    posted = [body for method, _path, body in stub.requests if method == "POST"]
    assert posted == [{"strategy": "saf-puan", "window": 1, "rival_entry_id": 202}]
    assert stub.requests[-1][1].endswith("&rival=202")


def test_nothing_listening_is_a_failure_not_a_traceback() -> None:
    lines: list[str] = []

    code = smoke.run_smoke(
        "http://127.0.0.1:9",
        LEAGUE,
        ENTRY,
        transport=smoke.http_transport(timeout_seconds=2.0),
        report=lines.append,
    )

    assert code == 1
    assert lines[-1].startswith("FAILED: GET http://127.0.0.1:9/health did not answer")


def test_the_command_line_refuses_a_non_positive_timeout() -> None:
    with pytest.raises(SystemExit):
        smoke.main(
            ["--base-url", "http://x", "--league", "1", "--entry", "1", "--poll-seconds", "0"]
        )
