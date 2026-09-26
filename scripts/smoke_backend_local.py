"""Take one advice request through a running backend, end to end, and time it.

    python -m scripts.smoke_backend_local --base-url http://127.0.0.1:8000 \
        --league 352490 --entry 5662073

The same walk a member's browser makes when the button is pressed: is the process up
(``/health``), can it answer (``/ready``), is the league connected, then a ``saf-puan``
window-1 request, the job polled to a terminal state, and the stored answer read back. It
prints the solver status and the seconds between the POST and the completed job.

Exit code 0 only when every step held. A backend that is not ready is a failure here and
its checks are printed, because which one is false is the whole diagnosis
(``docs/backend_runbook.md``, "Readiness").

Standard library only, on purpose: it has to run on a machine that has Python and nothing
else, against a tunnel as readily as against loopback. ``--origin`` adds the browser's
half of the question, whether the CORS allowlist names the site that will be calling.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass

DEFAULT_STRATEGY = "saf-puan"
DEFAULT_WINDOW = 1
# The site's own patience: 150 polls two seconds apart (web useAdviceJob.ts).
DEFAULT_TIMEOUT_SECONDS = 300.0
DEFAULT_POLL_SECONDS = 2.0
DEFAULT_REQUEST_TIMEOUT_SECONDS = 30.0
# Named, because a proxy in front of the api may refuse the library's default agent.
USER_AGENT = "squadopt-backend-smoke/1"
TERMINAL_STATUSES = ("completed", "failed")


class SmokeFailure(Exception):
    """One step did not hold; the message says which and what was seen."""


@dataclass(frozen=True, slots=True)
class HttpAnswer:
    status: int
    headers: Mapping[str, str]
    body: bytes

    def json(self) -> object:
        try:
            return json.loads(self.body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as error:
            raise SmokeFailure(
                f"expected JSON, got {self.body[:120]!r} (status {self.status})"
            ) from error


Transport = Callable[[str, str, bytes | None, Mapping[str, str]], HttpAnswer]


def http_transport(timeout_seconds: float = DEFAULT_REQUEST_TIMEOUT_SECONDS) -> Transport:
    """The real transport. A 4xx or 5xx is an answer to inspect, not an exception."""

    def send(method: str, url: str, body: bytes | None, headers: Mapping[str, str]) -> HttpAnswer:
        request = urllib.request.Request(url, data=body, method=method, headers=dict(headers))
        try:
            with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
                return HttpAnswer(response.status, dict(response.headers.items()), response.read())
        except urllib.error.HTTPError as error:
            return HttpAnswer(error.code, dict(error.headers.items()), error.read())
        except (urllib.error.URLError, TimeoutError, ConnectionError) as error:
            raise SmokeFailure(f"{method} {url} did not answer: {error}") from error

    return send


def _object(answer: HttpAnswer, step: str) -> dict[str, object]:
    document = answer.json()
    if not isinstance(document, dict):
        raise SmokeFailure(f"{step}: expected a JSON object, got {type(document).__name__}")
    return document


def _expect_status(answer: HttpAnswer, expected: tuple[int, ...], step: str) -> None:
    if answer.status not in expected:
        raise SmokeFailure(
            f"{step}: expected HTTP {' or '.join(map(str, expected))}, got {answer.status}: "
            f"{answer.body[:300].decode('utf-8', 'replace')}"
        )


def run_smoke(
    base_url: str,
    league_id: int,
    entry_id: int,
    *,
    strategy: str = DEFAULT_STRATEGY,
    window: int = DEFAULT_WINDOW,
    rival_entry_id: int | None = None,
    origin: str | None = None,
    timeout_seconds: float = DEFAULT_TIMEOUT_SECONDS,
    poll_seconds: float = DEFAULT_POLL_SECONDS,
    transport: Transport | None = None,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
    report: Callable[[str], None] = print,
) -> int:
    """Walk the path once; return the process exit code.

    The transport, the clock and the sleep are injected so a test drives the walk without
    a network and without waiting, and the command line owns the real ones.
    """

    send = transport if transport is not None else http_transport()
    root = base_url.rstrip("/")
    headers: dict[str, str] = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if origin:
        headers["Origin"] = origin
    advice_path = f"/api/v1/leagues/{league_id}/entries/{entry_id}/advice"
    advice_query = f"{advice_path}?strategy={strategy}&window={window}"
    if rival_entry_id is not None:
        advice_query += f"&rival={rival_entry_id}"

    def get(path: str) -> HttpAnswer:
        return send("GET", root + path, None, headers)

    try:
        health = get("/health")
        _expect_status(health, (200,), "/health")
        report("health: ok")

        ready = get("/ready")
        ready_document = _object(ready, "/ready")
        if ready.status != 200 or ready_document.get("ready") is not True:
            raise SmokeFailure(
                f"/ready: not ready (HTTP {ready.status}), checks {ready_document.get('checks')}"
            )
        report(f"ready: ok {json.dumps(ready_document.get('checks'), sort_keys=True)}")

        league = get(f"/api/v1/leagues/{league_id}")
        _expect_status(league, (200,), "league state")
        league_document = _object(league, "league state")
        if league_document.get("connected") is not True:
            raise SmokeFailure(f"league {league_id} is not connected on this backend")
        report(
            f"league: connected, season {league_document.get('season')} "
            f"gameweek {league_document.get('gameweek')}, "
            f"{league_document.get('member_count')} members"
        )

        body = json.dumps(
            {"strategy": strategy, "window": window, "rival_entry_id": rival_entry_id}
        )
        started = clock()
        posted = send(
            "POST",
            root + advice_path,
            body.encode("utf-8"),
            {**headers, "Content-Type": "application/json"},
        )
        _expect_status(posted, (200, 202), "POST advice")
        if origin:
            allowed = {key.lower(): value for key, value in posted.headers.items()}.get(
                "access-control-allow-origin"
            )
            if allowed != origin:
                raise SmokeFailure(
                    f"CORS: the answer allows {allowed!r}, not {origin!r}; a browser on that "
                    "origin would be refused (SQUADOPT_BACKEND_ALLOWED_ORIGINS)"
                )
            report(f"cors: {origin} allowed")

        if posted.status == 200:
            # Already computed under this exact context; nothing was queued, so there is
            # no solve to time and saying "0 s" would claim a measurement nobody made.
            report("request: answered from the cache, no job filed")
            elapsed: float | None = None
        else:
            job_id = _object(posted, "POST advice").get("job_id")
            if not isinstance(job_id, str) or not job_id:
                raise SmokeFailure("POST advice: 202 without a job_id")
            report(f"request: job {job_id} filed")
            elapsed = _poll(get, job_id, started, clock, sleep, timeout_seconds, poll_seconds)

        advice = get(advice_query)
        _expect_status(advice, (200,), "GET advice")
        payload = _object(advice, "GET advice").get("payload")
        if not isinstance(payload, dict):
            raise SmokeFailure("GET advice: the document has no payload object")
        if payload.get("entry_id") != entry_id or payload.get("mode") != strategy:
            raise SmokeFailure(
                f"GET advice: asked for entry {entry_id} {strategy}, got entry "
                f"{payload.get('entry_id')} {payload.get('mode')}"
            )
        report(f"advice: solver_status {payload.get('solver_status')}")
        report(f"advice: source_snapshot_id {payload.get('source_snapshot_id')}")
        if elapsed is None:
            report("elapsed: not measured (cache hit)")
        else:
            report(f"elapsed: {elapsed:.1f} s from POST to completed")
    except SmokeFailure as failure:
        report(f"FAILED: {failure}")
        return 1
    report("smoke: ok")
    return 0


def _poll(
    get: Callable[[str], HttpAnswer],
    job_id: str,
    started: float,
    clock: Callable[[], float],
    sleep: Callable[[float], None],
    timeout_seconds: float,
    poll_seconds: float,
) -> float:
    """Poll until the job is terminal; return seconds since the POST, or fail."""

    seen: str | None = None
    while True:
        answer = get(f"/api/v1/advice-jobs/{job_id}")
        _expect_status(answer, (200,), "job status")
        document = _object(answer, "job status")
        status = document.get("status")
        waited = clock() - started
        if status in TERMINAL_STATUSES:
            if status == "failed":
                raise SmokeFailure(
                    f"job {job_id} failed after {waited:.1f} s with "
                    f"error_code {document.get('error_code')}"
                )
            return waited
        seen = status if isinstance(status, str) else seen
        if waited >= timeout_seconds:
            raise SmokeFailure(
                f"job {job_id} still {seen} after {waited:.1f} s; is a worker running "
                "against the same store?"
            )
        sleep(poll_seconds)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--base-url", required=True, help="for example http://127.0.0.1:8000")
    parser.add_argument("--league", type=int, required=True)
    parser.add_argument("--entry", type=int, required=True)
    parser.add_argument("--strategy", default=DEFAULT_STRATEGY)
    parser.add_argument("--window", type=int, default=DEFAULT_WINDOW, choices=(1, 3, 5))
    parser.add_argument(
        "--rival", type=int, default=None, help="the rival entry a rival strategy is asked against"
    )
    parser.add_argument(
        "--origin",
        default=None,
        help="send this Origin and require the answer to allow it (the browser's check)",
    )
    parser.add_argument("--timeout-seconds", type=float, default=DEFAULT_TIMEOUT_SECONDS)
    parser.add_argument("--poll-seconds", type=float, default=DEFAULT_POLL_SECONDS)
    arguments = parser.parse_args(argv)
    if arguments.timeout_seconds <= 0.0 or arguments.poll_seconds <= 0.0:
        parser.error("--timeout-seconds and --poll-seconds must be positive.")
    return run_smoke(
        arguments.base_url,
        arguments.league,
        arguments.entry,
        strategy=arguments.strategy,
        window=arguments.window,
        rival_entry_id=arguments.rival,
        origin=arguments.origin,
        timeout_seconds=arguments.timeout_seconds,
        poll_seconds=arguments.poll_seconds,
    )


if __name__ == "__main__":
    sys.exit(main())
