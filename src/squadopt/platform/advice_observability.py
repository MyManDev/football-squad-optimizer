"""Observability for the advice backend: structured lines, counters, readiness.

Three layers, each answering one operator question.

**Structured log** — what happened, per request and per job, as JSON lines carrying
the fields the plan names: request and job identity, the cache key, the request
coordinates, the phase, the solver's account, and how long things took. The shape
extends ``live/runlog.py``'s pattern (one JSON object per line, stable field names)
rather than inventing a second logging idiom; it lives here because the api may not
import ``live``.

**Metrics** — how the system is doing, as Prometheus text, no dependency: queue depth
(read from the queue at scrape time, because a gauge that counts events drifts from
the store it describes), job wait and solve histograms, cache hits and misses (the
hit rate is the capacity signal the scaling order reads first), solver statuses (the
FEASIBLE share is a product metric: a budget regression shows up here), and rejected
requests by reason.

**Readiness, apart from liveness** — ``/health`` answers "is the process up" and
touches no dependency; ``/ready`` answers "can this deployment serve" — is the cache
store writable, is a capture context loaded, is the league tree readable. Folded into
one endpoint, a full disk looks healthy; that is the failure this split exists for.
"""

from __future__ import annotations

import json
import logging
import time
from bisect import bisect_left
from collections.abc import Mapping
from typing import Final

_HISTOGRAM_BUCKETS: Final[tuple[float, ...]] = (
    0.1,
    0.5,
    1.0,
    2.5,
    5.0,
    10.0,
    30.0,
    60.0,
    120.0,
    300.0,
)


class AdviceLog:
    """JSON-line events for the advice path; one object per line, stable names."""

    def __init__(self, component: str, logger: logging.Logger | None = None) -> None:
        self._component = component
        self._logger = logger if logger is not None else logging.getLogger(f"advice.{component}")

    def event(self, name: str, **fields: object) -> None:
        record = {
            "event": name,
            "component": self._component,
            "at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            **{key: value for key, value in fields.items() if value is not None},
        }
        self._logger.info(json.dumps(record, sort_keys=True, default=str))


class _Histogram:
    def __init__(self) -> None:
        self.counts = [0] * (len(_HISTOGRAM_BUCKETS) + 1)
        self.total = 0.0
        self.observations = 0

    def observe(self, value: float) -> None:
        # Prometheus buckets are inclusive: an observation exactly at a boundary
        # belongs to that boundary's bucket, so the index is bisect_left, not right.
        self.counts[bisect_left(_HISTOGRAM_BUCKETS, value)] += 1
        self.total += value
        self.observations += 1


class AdviceMetrics:
    """In-process counters and histograms, rendered as Prometheus text on demand."""

    def __init__(self) -> None:
        self._counters: dict[tuple[str, tuple[tuple[str, str], ...]], int] = {}
        self._histograms: dict[str, _Histogram] = {}

    def increment(self, name: str, **labels: str) -> None:
        key = (name, tuple(sorted(labels.items())))
        self._counters[key] = self._counters.get(key, 0) + 1

    def observe(self, name: str, value: float) -> None:
        self._histograms.setdefault(name, _Histogram()).observe(value)

    def cache_hit(self) -> None:
        self.increment("advice_cache_hits_total")

    def cache_miss(self) -> None:
        self.increment("advice_cache_misses_total")

    def solver_status(self, status: str) -> None:
        self.increment("advice_solver_status_total", status=status)

    def rejected(self, reason: str) -> None:
        self.increment("advice_rejected_total", reason=reason)

    def job_wait_seconds(self, seconds: float) -> None:
        self.observe("advice_job_wait_seconds", seconds)

    def solve_seconds(self, seconds: float) -> None:
        self.observe("advice_solve_seconds", seconds)

    def render(self, *, queue_depth: int | None = None) -> str:
        """The scrape body. Queue depth is read at scrape time by the caller that has
        the queue, because a gauge that counts events drifts from the store."""

        lines: list[str] = []
        if queue_depth is not None:
            lines.append("# TYPE advice_queue_depth gauge")
            lines.append(f"advice_queue_depth {queue_depth}")
        seen_families: set[str] = set()
        for (name, labels), count in sorted(self._counters.items()):
            rendered_labels = (
                "{" + ",".join(f'{key}="{value}"' for key, value in labels) + "}" if labels else ""
            )
            if name not in seen_families:
                # TYPE metadata appears once per metric family, however many label
                # sets the family carries.
                lines.append(f"# TYPE {name} counter")
                seen_families.add(name)
            lines.append(f"{name}{rendered_labels} {count}")
        for name, histogram in sorted(self._histograms.items()):
            lines.append(f"# TYPE {name} histogram")
            cumulative = 0
            for bucket, count in zip(_HISTOGRAM_BUCKETS, histogram.counts, strict=False):
                cumulative += count
                lines.append(f'{name}_bucket{{le="{bucket}"}} {cumulative}')
            cumulative += histogram.counts[-1]
            lines.append(f'{name}_bucket{{le="+Inf"}} {cumulative}')
            lines.append(f"{name}_sum {histogram.total}")
            lines.append(f"{name}_count {histogram.observations}")
        return "\n".join(lines) + "\n"


def readiness_report(
    *,
    context_loaded: bool,
    league_tree_readable: bool,
    cache_writable: bool,
) -> tuple[bool, Mapping[str, bool]]:
    """One place decides what "ready" means, so the endpoint cannot drift from it."""

    checks = {
        "capture_context": context_loaded,
        "league_tree": league_tree_readable,
        "cache_store": cache_writable,
    }
    return all(checks.values()), checks
