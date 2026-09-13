"""How much the live member-week record can support, and never that it supports it.

The unit of observation in the live record is the member-week and the cluster is the week.
The members share one week's fixtures, one projection and heavily overlapping squads, so
fifteen rows drawn from one week are not fifteen independent observations. How far from
independent they are is a single quantity, the within-week correlation, and it decides
whether the record answers in months or in years. This module estimates that quantity,
turns it into an effective count, and reports the precision that count buys.

It reports nothing about the direction or the size of any difference. Every returned number
is a function of counts and variances only, which two invariance tests pin: adding a constant
to every difference, or negating every difference, leaves every returned field equal.

Why the clustering enters analytically instead of through the existing resampler.
``squadopt.evaluation.statistics.season_aware_moving_block_interval`` returns a percentile
interval on a mean difference, and a mean difference between what was published and what a
member actually did is precisely the verdict this module must not produce, so that estimator
has nothing to do here. Its cluster is also the wrong object: it preserves contiguous runs
along a fold index because adjacent folds are adjacent weeks of one series, while the
dependence here is exchangeability within one week across members. Feeding it member-week
rows would resample contiguous windows that straddle members inside a week and split weeks
across block boundaries, which understates the clustering, the optimistic direction. At the
scale this instrument exists to describe it is degenerate anyway: with a single season label
it yields one distinct resample for two, three or four weeks, so its interval has zero width
for the first weeks of a season.

The designated future reuse, deliberately not built here. A later lane that does want an
interval on the live mean should feed ``season_aware_moving_block_interval`` one value per
week, that week's member mean, keyed by season, because collapsing to the cluster mean is how
clustering is handled when the cluster is the resampling unit. It returns a zero-width
interval until a season holds more than ``PromotionPolicy.moving_block_length`` settled weeks.

The minimum detectable effect uses the same normal formula the recorded backtest precision
uses, ``(z_(1-alpha/2) + z_power) * sd / sqrt(n)``. Only ``n`` changes, from independent folds
to the effective count the clustering earns, so the live number can be read beside the
backtest floor. ``docs/measurement_instrument.json`` records that floor at alpha 0.05 and
power 0.80, which is why those are the defaults here; a different rate or a substituted
standard error would make the two numbers incomparable while they still looked comparable.
The formula is written out rather than imported because it lives in
``squadopt.experiments.fold_precision``, which this layer may not import, and a test pins the
two to the same recorded digits so they cannot drift apart in silence.

One difference in contrast, which no arithmetic here can repair. A member-week difference is a
recorded publication's net points minus what the member actually scored, a descriptive
counterfactual between a published record and a member's own choices. The backtest difference
is candidate minus control between two systems. Both are paired weekly point differences, so
the same formula applies and the two minimum detectable effects are commensurable AS
PRECISION, but they are not the same contrast and neither is evidence about the other.

The correlation is expected to be substantial, for the reasons in the first paragraph, but
expected is not measured. Below two settled weeks there is no between-week degree of freedom
and the correlation is not estimable, so the reading refuses instead of guessing. The refusal
carries no correlation, no effective count and no horizon, because zero correlation is the
most optimistic answer available and a refusal that could be read as zero would understate
the horizon by roughly the average number of members in a week.
"""

import math
from collections.abc import Sequence
from dataclasses import dataclass
from numbers import Integral, Real
from statistics import NormalDist
from typing import ClassVar, Final, Literal

from squadopt.evaluation.models import EvaluationValidationError

LIVE_SERIES_METHOD_VERSION: Final = "member_week_cluster_power_v1"
MINIMUM_WEEKS_FOR_CORRELATION: Final = 2

RefusalReason = Literal[
    "no_settled_member_weeks",
    "single_settled_week",
    "no_within_week_replication",
    "no_variation",
]


def _finite(value: object, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise EvaluationValidationError(f"{label} must be a real number.")
    number = float(value)
    if not math.isfinite(number):
        raise EvaluationValidationError(f"{label} must be finite, got {number!r}.")
    return number


def _identity(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, Integral):
        raise EvaluationValidationError(f"{label} must be an integer.")
    number = int(value)
    if number <= 0:
        raise EvaluationValidationError(f"{label} must be positive, got {number}.")
    return number


@dataclass(frozen=True, slots=True)
class MemberWeekComparison:
    """One settled member-week: its cluster key, its member and its paired difference."""

    season: str
    gameweek: int
    entry_id: int
    difference: float

    def __post_init__(self) -> None:
        if not isinstance(self.season, str) or not self.season.strip():
            raise EvaluationValidationError("season must be a non-empty string.")
        object.__setattr__(self, "season", self.season.strip())
        object.__setattr__(self, "gameweek", _identity(self.gameweek, "gameweek"))
        object.__setattr__(self, "entry_id", _identity(self.entry_id, "entry_id"))
        object.__setattr__(self, "difference", _finite(self.difference, "difference"))


@dataclass(frozen=True, slots=True)
class DetectionPolicy:
    """The two rates a minimum detectable effect is quoted at.

    The defaults are the rates ``docs/measurement_instrument.json`` already records the
    backtest fold precision at, so a live reading is on the same axis as that floor. The
    promotion gate's own ``PromotionPolicy.confidence_level`` is a different, pre-registered
    quantity for a different decision; a caller who wants it may pass it here.
    """

    confidence_level: float = 0.95
    power: float = 0.80

    def __post_init__(self) -> None:
        for name in ("confidence_level", "power"):
            value = _finite(getattr(self, name), name)
            if not 0.0 < value < 1.0:
                raise EvaluationValidationError(f"{name} must be strictly between 0 and 1.")
            object.__setattr__(self, name, value)


DEFAULT_DETECTION_POLICY: Final = DetectionPolicy()


def _normal_sum(policy: DetectionPolicy) -> float:
    normal = NormalDist()
    upper = 1.0 - (1.0 - policy.confidence_level) / 2.0
    return normal.inv_cdf(upper) + normal.inv_cdf(policy.power)


def detectable_effect(
    standard_deviation: float,
    observations: float,
    *,
    policy: DetectionPolicy = DEFAULT_DETECTION_POLICY,
) -> float:
    """Smallest difference a two-sided test would detect at these rates and this count.

    ``observations`` is an effective count wherever the rows are clustered, never the raw
    row count, so the same call serves independent folds and clustered member-weeks.
    """

    deviation = _finite(standard_deviation, "standard_deviation")
    count = _finite(observations, "observations")
    if deviation < 0.0:
        raise EvaluationValidationError("standard_deviation cannot be negative.")
    if count <= 0.0:
        raise EvaluationValidationError("observations must be positive.")
    return _normal_sum(policy) * (deviation / math.sqrt(count))


@dataclass(frozen=True, slots=True)
class NotYetEstimable:
    """The record cannot yet carry a within-week correlation, and names no number for it.

    There is no correlation attribute, no effective count and no horizon method on this
    class on purpose: reading one off a refusal must fail loudly rather than return the most
    optimistic value available. Branch on ``isinstance(reading, LiveSeriesPower)``.
    """

    reason: RefusalReason
    member_weeks: int
    weeks: int
    method_version: str = LIVE_SERIES_METHOD_VERSION
    estimable: ClassVar[Literal[False]] = False


@dataclass(frozen=True, slots=True)
class WeeksToDetect:
    """Weeks a stated effect would need, under the accumulation already observed.

    The three assumptions are named here rather than buried in a docstring: the projection
    holds the observed members per week, the observed within-week correlation and the
    observed dispersion fixed, and a record that changes shape will not follow it.
    """

    effect: float
    total_weeks: int
    additional_weeks: int
    assumed_members_per_week: float
    assumed_within_week_correlation: float


@dataclass(frozen=True, slots=True)
class LiveSeriesPower:
    """What the settled record can support: dispersion, clustering and the precision they buy.

    ``within_week_correlation`` is the raw one-way random-effects moment estimate and may be
    negative on a small record. ``design_effect`` floors it at zero and itself at one, so a
    noisy negative estimate can never report more effective observations than member-weeks;
    ``correlation_floored`` says when that happened rather than hiding it. The two degrees of
    freedom are on the face of the result because the first estimable reading rests on one
    between-week degree of freedom and is very noisy.
    """

    member_weeks: int
    weeks: int
    average_members_per_week: float
    within_week_correlation: float
    correlation_floored: bool
    design_effect: float
    effective_observations: float
    member_week_standard_deviation: float
    minimum_detectable_effect: float
    between_week_degrees_of_freedom: int
    within_week_degrees_of_freedom: int
    confidence_level: float
    power: float
    method_version: str = LIVE_SERIES_METHOD_VERSION
    estimable: ClassVar[Literal[True]] = True

    def weeks_to_detect(self, effect: float) -> WeeksToDetect:
        """Weeks of record a stated effect would need, at the clustering already observed."""

        stated = _finite(effect, "effect")
        if stated <= 0.0:
            raise EvaluationValidationError("effect must be positive.")
        policy = DetectionPolicy(self.confidence_level, self.power)
        required = (
            (_normal_sum(policy) * self.member_week_standard_deviation / stated) ** 2
            * self.design_effect
            / self.average_members_per_week
        )
        total = math.ceil(required)
        return WeeksToDetect(
            effect=stated,
            total_weeks=total,
            additional_weeks=max(0, total - self.weeks),
            assumed_members_per_week=self.average_members_per_week,
            assumed_within_week_correlation=self.within_week_correlation,
        )


LiveSeriesReading = NotYetEstimable | LiveSeriesPower


def _clusters(comparisons: Sequence[MemberWeekComparison]) -> dict[tuple[str, int], list[float]]:
    """Group the differences by week, refusing a member counted twice in one week."""

    grouped: dict[tuple[str, int], list[float]] = {}
    seen: set[tuple[str, int, int]] = set()
    for row in comparisons:
        identity = (row.season, row.gameweek, row.entry_id)
        if identity in seen:
            raise EvaluationValidationError(
                f"Member {row.entry_id} appears twice in {row.season} gameweek {row.gameweek}."
            )
        seen.add(identity)
        grouped.setdefault((row.season, row.gameweek), []).append(
            _finite(row.difference, "difference")
        )
    return grouped


def read_live_series(
    comparisons: Sequence[MemberWeekComparison],
    *,
    policy: DetectionPolicy = DEFAULT_DETECTION_POLICY,
) -> LiveSeriesReading:
    """Report the clustered precision of the settled record, or refuse to report it.

    The season is part of the cluster key, so a season rollover cannot merge two different
    weeks that share a gameweek number into one cluster.
    """

    grouped = _clusters(comparisons)
    sizes = [len(values) for values in grouped.values()]
    member_weeks = sum(sizes)
    weeks = len(sizes)
    if member_weeks == 0:
        return NotYetEstimable("no_settled_member_weeks", 0, 0)
    if weeks < MINIMUM_WEEKS_FOR_CORRELATION:
        return NotYetEstimable("single_settled_week", member_weeks, weeks)
    if member_weeks == weeks:
        return NotYetEstimable("no_within_week_replication", member_weeks, weeks)
    differences = [value for values in grouped.values() for value in values]
    grand = sum(differences) / member_weeks
    total_squares = sum((value - grand) ** 2 for value in differences)
    if total_squares == 0.0:
        return NotYetEstimable("no_variation", member_weeks, weeks)

    between = 0.0
    within = 0.0
    for values in grouped.values():
        mean = sum(values) / len(values)
        between += len(values) * (mean - grand) ** 2
        within += sum((value - mean) ** 2 for value in values)
    between_degrees = weeks - 1
    within_degrees = member_weeks - weeks
    mean_between = between / between_degrees
    mean_within = within / within_degrees
    # Kish's average cluster size, which is what a week of unequal membership weighs.
    members_per_week = sum(size * size for size in sizes) / member_weeks
    # The moment estimator's own size term; both equal the common size when the weeks agree.
    size_term = (member_weeks - members_per_week) / between_degrees
    correlation = (mean_between - mean_within) / (mean_between + (size_term - 1.0) * mean_within)
    design_effect = max(1.0, 1.0 + (members_per_week - 1.0) * max(0.0, correlation))
    effective = member_weeks / design_effect
    deviation = math.sqrt(total_squares / (member_weeks - 1))
    return LiveSeriesPower(
        member_weeks=member_weeks,
        weeks=weeks,
        average_members_per_week=members_per_week,
        within_week_correlation=correlation,
        correlation_floored=correlation < 0.0,
        design_effect=design_effect,
        effective_observations=effective,
        member_week_standard_deviation=deviation,
        minimum_detectable_effect=detectable_effect(deviation, effective, policy=policy),
        between_week_degrees_of_freedom=between_degrees,
        within_week_degrees_of_freedom=within_degrees,
        confidence_level=policy.confidence_level,
        power=policy.power,
    )
