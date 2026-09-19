"""Read backend health and operator logs without opening queue or cache documents.

Run with ``python -m scripts.backend_status``. Log summaries cover the retained lines,
not necessarily the running process. Missing metrics are unknown, never zero.
"""

from __future__ import annotations

import argparse
import http.client
import json
import math
import re
import statistics
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import Counter
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

USER_AGENT = "squadopt-backend-status/1"
UNAVAILABLE = "unavailable: not exposed"
DEFAULT_LOG_DIR = Path(__file__).resolve().parents[1] / "data/runtime/backend/logs"
Transport = Callable[[str], tuple[int, str]]
Metric = tuple[str, dict[str, str], float]


def get_text(url: str) -> tuple[int, str]:
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT}, method="GET")
    try:
        with urllib.request.urlopen(request, timeout=5) as response:
            return response.status, response.read().decode("utf-8")
    except urllib.error.HTTPError as error:
        with error:
            return error.code, error.read().decode("utf-8", errors="replace")


def parse_metrics(text: str) -> list[Metric]:
    """Read the backend's flat Prometheus samples, ignoring comments and bad values."""
    samples: list[Metric] = []
    for line in text.splitlines():
        match = re.fullmatch(r"([a-zA-Z_:][\w:]*)(?:\{(.*)\})?\s+(\S+)", line.strip())
        if match is None:
            continue
        try:
            value = float(match[3])
            labels = {
                key: json.loads(quoted)
                for key, quoted in re.findall(r'(\w+)=("(?:[^"\\]|\\.)*")', match[2] or "")
            }
        except (ValueError, json.JSONDecodeError):
            continue
        if math.isfinite(value) and value >= 0:
            samples.append((match[1], labels, value))
    return samples


def _metric(samples: list[Metric], name: str) -> str:
    values = [f"{value:g}" for key, labels, value in samples if key == name and not labels]
    return values[0] if len(values) == 1 else UNAVAILABLE


def _labelled(samples: list[Metric], name: str) -> str:
    values = [
        f"{','.join(f'{key}={value}' for key, value in sorted(labels.items()))}: {count:g}"
        for metric, labels, count in samples
        if metric == name and labels
    ]
    return "; ".join(values) or _metric(samples, name)


@dataclass
class LogSummary:
    records: int = 0
    files: int = 0
    skipped_old: int = 0
    ignored: int = 0
    unreadable: int = 0
    first: str = ""
    last: str = ""
    capture: tuple[str, str] | None = None
    forwarded_trust: tuple[str, str] | None = None
    completed_seconds: list[float] = field(default_factory=list)
    window_seconds: dict[int, list[float]] = field(default_factory=dict)
    completions_without_window: int = 0
    refusals: Counter[str] = field(default_factory=Counter)


def read_logs(directory: Path, *, days: int = 7) -> LogSummary:
    """Only append-only api/worker logs; never walk into the store or follow links."""
    summary = LogSummary()
    cutoff = time.time() - days * 86400
    try:
        paths = sorted(directory.iterdir())
    except OSError:
        summary.unreadable += 1
        return summary
    for path in paths:
        if path.is_symlink() or not path.name.startswith(("api-", "worker-")):
            continue
        if path.suffix not in (".log", ".jsonl"):
            continue
        try:
            if path.stat().st_mtime < cutoff:
                summary.skipped_old += 1
                continue
            with path.open("r", encoding="utf-8-sig", errors="replace") as stream:
                summary.files += 1
                for line in stream:
                    try:
                        record = json.loads(line)
                    except ValueError:
                        summary.ignored += 1
                        continue  # Includes a torn final line while the writer appends.
                    if not isinstance(record, dict):
                        summary.ignored += 1
                        continue
                    stamp = record.get("at_utc")
                    if not isinstance(stamp, str) or not re.fullmatch(
                        r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", stamp
                    ):
                        summary.ignored += 1
                        continue
                    summary.records += 1
                    summary.first = min(summary.first or stamp, stamp)
                    summary.last = max(summary.last, stamp)
                    event = record.get("event")
                    if event == "advice_forwarded_trust" and record.get("component") == "api":
                        trust = record.get("trust_status")
                        source = record.get("trust_source")
                        allowlist_set = record.get("forwarded_allow_ips_set")
                        allowlist_count = record.get("forwarded_allow_ips_count")
                        proxy_source = record.get("proxy_headers_source")
                        if (
                            trust in ("enabled", "disabled", "unverified")
                            and isinstance(source, str)
                            and (
                                summary.forwarded_trust is None
                                or stamp > summary.forwarded_trust[0]
                            )
                        ):
                            description = f"{trust}; source={json.dumps(source)}"
                            if isinstance(allowlist_set, bool):
                                description += (
                                    f"; allowlist explicitly set={json.dumps(allowlist_set)}"
                                )
                            if type(allowlist_count) is int and allowlist_count >= 0:
                                description += f"; allowlist entries={allowlist_count}"
                            if isinstance(proxy_source, str):
                                description += f"; proxy-header source={json.dumps(proxy_source)}"
                            summary.forwarded_trust = (stamp, description)
                    capture = record.get("snapshot_id")
                    if (
                        event in ("advice_worker_warmed", "advice_context_loaded")
                        and isinstance(capture, str)
                        and (summary.capture is None or stamp > summary.capture[0])
                    ):
                        summary.capture = (stamp, capture)
                    seconds = record.get("wall_seconds")
                    if (
                        event == "advice_job_completed"
                        and isinstance(seconds, (int, float))
                        and not isinstance(seconds, bool)
                        and math.isfinite(seconds)
                        and seconds >= 0
                    ):
                        summary.completed_seconds.append(float(seconds))
                        window = record.get("window")
                        if type(window) is int and window in (1, 3, 5):
                            summary.window_seconds.setdefault(window, []).append(float(seconds))
                        else:
                            summary.completions_without_window += 1
                    code = record.get("code")
                    if event == "advice_job_refused" and isinstance(code, str):
                        summary.refusals[code] += 1
        except OSError:
            summary.unreadable += 1
    return summary


def status_report(
    base_url: str, public_url: str, log_dir: Path, *, days: int = 7, transport: Transport = get_text
) -> tuple[int, str]:
    lines: list[str] = []
    ready = False
    public_healthy = False
    samples: list[Metric] = []
    for name, url in (
        ("Loopback ready", base_url.rstrip("/") + "/ready"),
        ("Loopback metrics", base_url.rstrip("/") + "/metrics"),
        ("Public health", public_url.rstrip("/") + "/health"),
    ):
        try:
            code, body = transport(url)
            lines.append(f"{name}: HTTP {code}")
            if name == "Loopback ready":
                document = json.loads(body)
                if not isinstance(document, dict):
                    raise ValueError("expected readiness object")
                checks = document.get("checks", {})
                if not isinstance(checks, dict):
                    raise ValueError("expected readiness checks")
                ready = code == 200 and document.get("ready") is True and bool(checks)
                ready = ready and all(value is True for value in checks.values())
                lines.append(
                    "Checks: " + ", ".join(f"{key}={value}" for key, value in checks.items())
                )
                lines.append(
                    "Capture vs published tree: "
                    f"{checks.get('league_tree_matches_capture', UNAVAILABLE)}"
                )
            elif name == "Loopback metrics" and code == 200:
                samples = parse_metrics(body)
            elif name == "Public health":
                public_healthy = code == 200
        except (OSError, ValueError, http.client.HTTPException) as error:
            lines.append(f"{name}: unavailable ({type(error).__name__})")
            if name == "Loopback ready":
                ready = False
    lines.extend(
        [
            f"Queue depth (API): {_metric(samples, 'advice_queue_depth')}",
            f"Jobs by status (API): {_labelled(samples, 'advice_jobs')}",
            f"Cache (API): hits={_metric(samples, 'advice_cache_hits_total')}; "
            f"misses={_metric(samples, 'advice_cache_misses_total')}",
            f"Request refusals (API): {_labelled(samples, 'advice_rejected_total')}",
            f"Open-job refusals (API): {_metric(samples, 'advice_open_job_refused_total')}",
        ]
    )
    logs = read_logs(log_dir, days=days)
    lines.append(
        "Forwarded-header trust (last API startup in retained logs, not a live check): "
        + (
            f"{logs.forwarded_trust[1]} at {logs.forwarded_trust[0]}"
            if logs.forwarded_trust
            else UNAVAILABLE
        )
    )
    lines.append(
        f"Logs: {logs.records} records, {logs.first or 'unknown'} to {logs.last or 'unknown'}; "
        f"non-JSON lines={logs.ignored}, unreadable={logs.unreadable}; "
        f"files read={logs.files}, skipped old={logs.skipped_old} (modified in last {days} days)"
    )
    lines.append(
        "Last logged capture (historical): "
        + (f"{logs.capture[1]} at {logs.capture[0]}" if logs.capture else UNAVAILABLE)
    )
    lines.append("Published capture ID: " + UNAVAILABLE)
    for window in (1, 3, 5):
        values = logs.window_seconds.get(window, [])
        summary = (
            f"n={len(values)}, median={statistics.median(values):.3f}, slowest={max(values):.3f}"
            if values
            else "unavailable: no completion samples"
        )
        lines.append(f"Completed job wall seconds (window {window}, retained logs only): {summary}")
    lines.append(f"Completions without window (retained logs): {logs.completions_without_window}")
    if logs.completed_seconds:
        values = logs.completed_seconds
        lines.append(
            f"Completed job wall seconds (all windows, retained logs only): n={len(values)}, "
            f"median={statistics.median(values):.3f}, slowest={max(values):.3f}"
        )
    else:
        lines.append("Completed job wall seconds: unavailable: no completion samples")
    lines.append(
        "Job refusals (retained logs): "
        + (
            ", ".join(f"{key}={count}" for key, count in sorted(logs.refusals.items()))
            or "none observed"
        )
    )
    code = 0 if ready and public_healthy else (2 if ready else 1)
    lines.insert(0, {0: "READY", 1: "NOT READY", 2: "READY, public check failed"}[code])
    return code, "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", default="http://127.0.0.1:8000")
    parser.add_argument("--public-url", default="https://squadopt-api.mymandev.com")
    parser.add_argument("--log-dir", type=Path, default=DEFAULT_LOG_DIR)
    parser.add_argument("--days", type=int, default=7, help="Read logs modified in the last N days")
    args = parser.parse_args(argv)
    base = urllib.parse.urlsplit(args.base_url)
    if base.hostname not in ("127.0.0.1", "localhost", "::1") or base.scheme != "http":
        parser.error("--base-url must use HTTP on loopback")
    if args.days < 1:
        parser.error("--days must be a positive integer")
    code, report = status_report(args.base_url, args.public_url, args.log_dir, days=args.days)
    print(report)
    return code


if __name__ == "__main__":
    raise SystemExit(main())
