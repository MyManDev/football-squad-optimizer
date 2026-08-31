"""Leakage-safe cohort selection and aggregate manager benchmarks."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from numbers import Integral, Real
from statistics import median
from typing import Final

from squadopt.evaluation.models import EvaluationValidationError

TOP_MANAGER_COHORT_VERSION: Final = "as_of_top_100_v1"
TOP_MANAGER_COHORT_SIZE: Final = 100
TOP_MANAGER_MINIMUM_COVERAGE_COUNT: Final = 80


def _positive_integer(value: object, name: str) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral) or int(value) < 1:
        raise EvaluationValidationError(f"{name} must be a positive integer.")
    return int(value)


def _utc_timestamp(value: object, name: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise EvaluationValidationError(f"{name} must be a non-empty UTC timestamp string.")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as error:
        raise EvaluationValidationError(f"{name} is not an ISO-8601 timestamp.") from error
    if parsed.tzinfo is None or parsed.utcoffset() != UTC.utcoffset(parsed):
        raise EvaluationValidationError(f"{name} must carry the UTC offset.")
    return parsed.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class RankedManager:
    """One public entry and the rank observable at a declared capture time."""

    entry_id: int
    rank: int

    def __post_init__(self) -> None:
        object.__setattr__(self, "entry_id", _positive_integer(self.entry_id, "entry_id"))
        object.__setattr__(self, "rank", _positive_integer(self.rank, "rank"))


@dataclass(frozen=True, slots=True)
class AsOfTop100Cohort:
    """Exactly the pre-outcome top 100; entry ids remain runtime-only data."""

    target_gameweek: int
    entry_ids: tuple[int, ...]
    captured_at_utc: str
    deadline_timestamp_utc: str
    source_snapshot_id: str
    contract_version: str = TOP_MANAGER_COHORT_VERSION

    def __post_init__(self) -> None:
        gameweek = _positive_integer(self.target_gameweek, "target_gameweek")
        if gameweek == 1:
            raise EvaluationValidationError(
                "Gameweek 1 has no honest current-season as-of Top-100 cohort."
            )
        entries = tuple(_positive_integer(value, "entry_id") for value in self.entry_ids)
        if len(entries) != TOP_MANAGER_COHORT_SIZE or len(set(entries)) != len(entries):
            raise EvaluationValidationError(
                "An as-of Top-100 cohort must contain exactly 100 distinct entries."
            )
        captured = _utc_timestamp(self.captured_at_utc, "captured_at_utc")
        deadline = _utc_timestamp(self.deadline_timestamp_utc, "deadline_timestamp_utc")
        if captured > deadline:
            raise EvaluationValidationError(
                "The Top-100 membership capture must not be later than the target deadline."
            )
        if not isinstance(self.source_snapshot_id, str) or not self.source_snapshot_id.strip():
            raise EvaluationValidationError("source_snapshot_id must be a non-empty string.")
        if self.contract_version != TOP_MANAGER_COHORT_VERSION:
            raise EvaluationValidationError(
                f"contract_version must be {TOP_MANAGER_COHORT_VERSION!r}."
            )
        object.__setattr__(self, "target_gameweek", gameweek)
        object.__setattr__(self, "entry_ids", entries)
        object.__setattr__(self, "captured_at_utc", captured.isoformat().replace("+00:00", "Z"))
        object.__setattr__(
            self, "deadline_timestamp_utc", deadline.isoformat().replace("+00:00", "Z")
        )
        object.__setattr__(self, "source_snapshot_id", self.source_snapshot_id.strip())


@dataclass(frozen=True, slots=True)
class Top100BenchmarkResult:
    """Privacy-safe aggregate of one settled system-versus-cohort comparison."""

    target_gameweek: int
    target_count: int
    valid_count: int
    coverage: float
    status: str
    cohort_mean_points: float | None
    cohort_median_points: float | None
    system_points: float
    system_minus_cohort_mean: float | None
    cohort_contract_version: str = TOP_MANAGER_COHORT_VERSION


def select_as_of_top_100(
    rankings: Sequence[RankedManager],
    *,
    target_gameweek: int,
    captured_at_utc: str,
    deadline_timestamp_utc: str,
    source_snapshot_id: str,
) -> AsOfTop100Cohort:
    """Freeze the first 100 of a complete pre-deadline ranking without backfill."""

    records = tuple(rankings)
    if any(not isinstance(record, RankedManager) for record in records):
        raise EvaluationValidationError("rankings must contain RankedManager values.")
    entry_ids = [record.entry_id for record in records]
    if len(entry_ids) != len(set(entry_ids)):
        raise EvaluationValidationError("Rankings contain a duplicate entry_id.")
    if len(records) < TOP_MANAGER_COHORT_SIZE:
        raise EvaluationValidationError(
            "At least 100 ranked entries are required to freeze the Top-100 cohort."
        )
    ordered = sorted(records, key=lambda record: (record.rank, record.entry_id))
    return AsOfTop100Cohort(
        target_gameweek=target_gameweek,
        entry_ids=tuple(record.entry_id for record in ordered[:TOP_MANAGER_COHORT_SIZE]),
        captured_at_utc=captured_at_utc,
        deadline_timestamp_utc=deadline_timestamp_utc,
        source_snapshot_id=source_snapshot_id,
    )


def aggregate_top_100_scores(
    cohort: AsOfTop100Cohort,
    manager_scores: Mapping[int, float],
    *,
    system_points: float,
) -> Top100BenchmarkResult:
    """Aggregate only frozen cohort members and abstain below 80% coverage."""

    if not isinstance(cohort, AsOfTop100Cohort):
        raise EvaluationValidationError("cohort must be an AsOfTop100Cohort instance.")
    if not isinstance(manager_scores, Mapping):
        raise EvaluationValidationError("manager_scores must be an entry-to-score mapping.")
    if isinstance(system_points, bool) or not isinstance(system_points, Real):
        raise EvaluationValidationError("system_points must be a finite number.")
    normalized_system = float(system_points)
    if not math.isfinite(normalized_system):
        raise EvaluationValidationError("system_points must be a finite number.")

    cohort_ids = set(cohort.entry_ids)
    outside = sorted(set(manager_scores) - cohort_ids)
    if outside:
        raise EvaluationValidationError(
            "manager_scores contains entries outside the frozen Top-100 cohort; "
            f"examples: {outside[:10]!r}."
        )
    scores: list[float] = []
    for entry_id, value in manager_scores.items():
        if isinstance(entry_id, bool) or not isinstance(entry_id, Integral):
            raise EvaluationValidationError("manager_scores keys must be integer entry ids.")
        if isinstance(value, bool) or not isinstance(value, Real):
            raise EvaluationValidationError("manager_scores values must be finite numbers.")
        score = float(value)
        if not math.isfinite(score):
            raise EvaluationValidationError("manager_scores values must be finite numbers.")
        scores.append(score)

    valid_count = len(scores)
    coverage = valid_count / TOP_MANAGER_COHORT_SIZE
    if valid_count < TOP_MANAGER_MINIMUM_COVERAGE_COUNT:
        return Top100BenchmarkResult(
            target_gameweek=cohort.target_gameweek,
            target_count=TOP_MANAGER_COHORT_SIZE,
            valid_count=valid_count,
            coverage=coverage,
            status="insufficient_coverage",
            cohort_mean_points=None,
            cohort_median_points=None,
            system_points=normalized_system,
            system_minus_cohort_mean=None,
        )

    mean_score = sum(scores) / valid_count
    return Top100BenchmarkResult(
        target_gameweek=cohort.target_gameweek,
        target_count=TOP_MANAGER_COHORT_SIZE,
        valid_count=valid_count,
        coverage=coverage,
        status="scored",
        cohort_mean_points=mean_score,
        cohort_median_points=float(median(scores)),
        system_points=normalized_system,
        system_minus_cohort_mean=normalized_system - mean_score,
    )


__all__ = [
    "TOP_MANAGER_COHORT_SIZE",
    "TOP_MANAGER_COHORT_VERSION",
    "TOP_MANAGER_MINIMUM_COVERAGE_COUNT",
    "AsOfTop100Cohort",
    "RankedManager",
    "Top100BenchmarkResult",
    "aggregate_top_100_scores",
    "select_as_of_top_100",
]
