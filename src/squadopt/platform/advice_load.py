"""Bounded HTTP capacity probe for an explicitly selected advice deployment."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import threading
import time
from collections import Counter
from collections.abc import Mapping, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any
from urllib.error import HTTPError
from urllib.parse import urlencode
from urllib.request import Request, urlopen


def _http(url: str, *, body: Mapping[str, object] | None, timeout: float) -> tuple[int, bytes]:
    request = Request(
        url,
        data=None if body is None else json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urlopen(request, timeout=timeout) as response:
            return response.status, response.read()
    except HTTPError as error:
        return error.code, error.read()


def _percentile(values: list[float], fraction: float) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(len(ordered) * fraction) - 1)]


def run_burst(
    origin: str,
    requests: Sequence[Mapping[str, Any]],
    *,
    scenario: str,
    users: int,
    deadline_seconds: float = 300,
    poll_seconds: float = 0.2,
) -> dict[str, object]:
    """Measure one burst; failures remain failures, with no hidden warmup or retries.

    cache-hit is GET only and requires precomputed answers. dedup asks the first request
    repeatedly; distinct requires at least `users` unique request coordinates. POST may
    return an existing answer, which is reported and cannot count as new-job capacity.
    """
    if scenario not in {"cache-hit", "dedup", "distinct"} or users < 1 or not requests:
        raise ValueError("Supply a scenario, positive users and a nonempty request set.")
    if (
        not math.isfinite(deadline_seconds)
        or deadline_seconds <= 0
        or not math.isfinite(poll_seconds)
        or poll_seconds <= 0
    ):
        raise ValueError("Durations must be positive and finite.")
    required = {"league_id", "entry_id", "strategy", "window"}
    for coordinates in requests:
        if (
            not isinstance(coordinates, Mapping)
            or not required.issubset(coordinates)
            or set(coordinates) - required - {"rival_entry_id"}
        ):
            raise ValueError(
                "Request coordinates must contain league, entry, strategy and window only."
            )
        for name in ("league_id", "entry_id"):
            if type(coordinates[name]) is not int or coordinates[name] < 1:
                raise ValueError("Request identities must be positive integers.")
        rival = coordinates.get("rival_entry_id")
        if rival is not None and (type(rival) is not int or rival < 1):
            raise ValueError("Rival identity must be a positive integer or null.")
        if not isinstance(coordinates["strategy"], str) or type(coordinates["window"]) is not int:
            raise ValueError("Invalid strategy or window.")
    if scenario == "distinct":
        selected = list(requests[:users])
        if (
            len(selected) != users
            or len({json.dumps(item, sort_keys=True) for item in selected}) != users
        ):
            raise ValueError("Distinct capacity requires one different request per user.")
    else:
        selected = [
            requests[index % len(requests)] if scenario == "cache-hit" else requests[0]
            for index in range(users)
        ]
    barrier = threading.Barrier(users)
    started = time.monotonic()
    deadline = started + deadline_seconds
    samples: list[int] = []
    stop = threading.Event()

    def monitor() -> None:
        while not stop.is_set() and time.monotonic() < deadline:
            try:
                status, raw = _http(origin.rstrip("/") + "/metrics", body=None, timeout=2)
                if status == 200:
                    for line in raw.decode().splitlines():
                        if line.startswith("advice_queue_depth "):
                            samples.append(int(float(line.split()[1])))
            except (OSError, ValueError):
                pass
            stop.wait(poll_seconds)

    def one(coordinates: Mapping[str, Any]) -> dict[str, object]:
        barrier.wait(timeout=min(30, deadline_seconds))
        begin = time.monotonic()
        row: dict[str, object] = {"entry_id": coordinates["entry_id"]}
        body = {
            key: coordinates[key]
            for key in ("strategy", "window", "rival_entry_id")
            if key in coordinates
        }
        path = (
            f"/api/v1/leagues/{coordinates['league_id']}/entries/{coordinates['entry_id']}/advice"
        )
        query = {"strategy": body["strategy"], "window": body["window"]}
        if body.get("rival_entry_id") is not None:
            query["rival"] = body["rival_entry_id"]
        url = origin.rstrip("/") + path + "?" + urlencode(query)

        def call(target: str, payload: Mapping[str, object] | None = None) -> tuple[int, bytes]:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise TimeoutError("Burst deadline elapsed.")
            return _http(target, body=payload, timeout=min(10, remaining))

        try:
            status, raw = call(url, None if scenario == "cache-hit" else body)
            row.update(submit_status=status, submit_seconds=time.monotonic() - begin)
            if status == 202:
                job_id = json.loads(raw)["job_id"]
                row["job_id"] = job_id
                while True:
                    status, job_raw = call(origin.rstrip("/") + f"/api/v1/advice-jobs/{job_id}")
                    if status != 200:
                        raise ValueError(f"Poll returned HTTP {status}.")
                    job = json.loads(job_raw)
                    if job["status"] == "failed":
                        raise ValueError(f"Job failed: {job.get('error_code')}.")
                    if job["status"] == "completed":
                        status, raw = call(url)
                        break
                    time.sleep(min(poll_seconds, max(0, deadline - time.monotonic())))
            if status != 200:
                raise ValueError(f"Advice returned HTTP {status}.")
            from squadopt.platform.advice_documents import validate_advice_document

            validate_advice_document(raw)
            payload = json.loads(raw)["payload"]
            if (
                any(payload[key] != coordinates[key] for key in ("league_id", "entry_id", "window"))
                or payload["mode"] != coordinates["strategy"]
                or payload.get("rival_entry_id") != coordinates.get("rival_entry_id")
            ):
                raise ValueError("Advice identity differs from the submitted request.")
            row.update(outcome="completed", response_sha256=hashlib.sha256(raw).hexdigest())
        except (OSError, ValueError, KeyError, TypeError) as error:
            row.update(outcome="failed", error=str(error))
        row["total_seconds"] = time.monotonic() - begin
        return row

    observer = threading.Thread(target=monitor, daemon=True)
    observer.start()
    try:
        with ThreadPoolExecutor(max_workers=users) as pool:
            rows = list(pool.map(one, selected))
    finally:
        stop.set()
        observer.join(timeout=3)
    completed = [row for row in rows if row["outcome"] == "completed"]
    submit = [float(str(row["submit_seconds"])) for row in rows if "submit_seconds" in row]
    total = [float(str(row["total_seconds"])) for row in completed]
    return {
        "contract_version": "advice_capacity_v1",
        "scenario": scenario,
        "users": users,
        "wall_seconds": time.monotonic() - started,
        "completed": len(completed),
        "failed": len(rows) - len(completed),
        "submit_status_counts": dict(
            Counter(str(row.get("submit_status", "transport-error")) for row in rows)
        ),
        "unique_job_count": len({row["job_id"] for row in rows if "job_id" in row}),
        "submit_p50_seconds": _percentile(submit, 0.5),
        "submit_p95_seconds": _percentile(submit, 0.95),
        "completion_p50_seconds": _percentile(total, 0.5),
        "completion_p95_seconds": _percentile(total, 0.95),
        "sampled_peak_queue_depth": max(samples) if samples else None,
        "queue_samples": len(samples),
        "rows": rows,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origin", required=True)
    parser.add_argument("--requests", type=Path, required=True)
    parser.add_argument("--scenario", choices=("cache-hit", "dedup", "distinct"), required=True)
    parser.add_argument("--users", type=int, required=True)
    parser.add_argument("--deadline-seconds", type=float, default=300)
    parser.add_argument("--output", type=Path, required=True)
    arguments = parser.parse_args(argv)
    if arguments.output.exists() or not arguments.output.parent.is_dir():
        parser.error("Output must be a new file in an existing directory.")
    report = run_burst(
        arguments.origin,
        json.loads(arguments.requests.read_bytes()),
        scenario=arguments.scenario,
        users=arguments.users,
        deadline_seconds=arguments.deadline_seconds,
    )
    # A run is new evidence; never overwrite an earlier capacity report.
    with arguments.output.open("x", encoding="utf-8") as stream:
        json.dump(report, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return 0 if report["failed"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
