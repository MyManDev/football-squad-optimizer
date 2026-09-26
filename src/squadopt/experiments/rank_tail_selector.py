"""The rank criterion under measurement: one tail mean of the gap per rival, summed.

Pre-registered in ``docs/rank_tail_selector_prereg.md`` before this module was written.
Nothing here is on the member path, nothing here is published, and nothing here decides a
plan today: this is the arithmetic the measurement runs, kept separate from the runner that
feeds it so the property tests have something exact to stand on.

**What it computes.** For candidate ``k``, rival ``j`` and scenario ``s`` the gap is
``g(k, j, s) = score(k, s) - score(j, s)``, both scored on the same draw so shared players
cancel inside the scenario rather than in expectation. Each rival contributes one *tail mean*
of its own gap, on the side its captured standings gap selects, and the contributions are
summed at equal weight. Every rival enters at once. The equal weight needs no measurement:
one rival passed is one place gained.

- **behind** -- the member trails, so variance is worth paying for: the mean of the *best*
  ``m`` of the ``S`` gaps.
- **ahead** -- the member leads, so variance is worth avoiding: the mean of the *worst* ``m``.
- **level** -- inside the band: the mean of all ``S``.

**Why the answer is an integer.** Candidates are compared by a Python ``int`` over a common
denominator, the construction already at ``scenarios/selection.py:60-63``. Mixing a tail mean
(denominator ``m``) with a full mean (denominator ``S``) across rivals is exactly what that
construction is for. No comparison turns on a float's last bits, and ties break to the lowest
candidate index, which puts the control first -- the same rule as
``scenarios/selection.py:258-262``.

**The null.** At a tail fraction of one, ``m == S``, every side collapses to the same sum, and
the criterion's argmax is the argmax of the candidate's own total. That is today's mean
selector exactly, not approximately. It is the arm the measurement runs to check the
instrument rather than the idea.

**Shift equivariance, which is the whole licence for the design.** Adding a constant ``e`` to
one rival's per-scenario scores moves ``g`` by ``-e`` at every scenario. A constant shift
preserves the order of the values, so the tail keeps the same members, and every candidate's
term for that rival moves by the same amount. The argmax cannot change. Three pre-registered
attempts to publish rank probabilities failed on *location* -- ``docs/rival_calibration.md:8-9``
records a claimed 0.763 against a realized 0.345 -- and this criterion is invariant to exactly
that defect. It is **not** invariant to a rival edge that moves with the scenario, which the
pre-registration names as an unmeasured limit.

The equivariance is exact rather than approximate because the shift is applied before scaling:
``scale_expected_points`` reads ``Decimal(str(value))``, so a score and a shift that are both
representable at ``TAIL_POINTS_SCALE`` scale exactly and their integers subtract exactly.

**Where the band edge comes from.** It does not come from here. ``band_edge_points`` lives in
``application/strategies/rule.py``, which sits above this layer, so the caller reads the edge
there and hands it in as a number. That keeps one band in the repository rather than two, and
keeps the measurement laboratory out of the product's imports.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from enum import StrEnum
from fractions import Fraction
from math import ceil, isfinite
from numbers import Real
from typing import Final

from squadopt.evaluation.promotion import ExperimentConfigurationError
from squadopt.optimization.coefficients import scale_expected_points

#: This criterion by name and version. A change to the arithmetic, the sides or the
#: tie-break is a new version, so a record written under one cannot be read as the other.
RANK_TAIL_SELECTOR_CONTRACT_VERSION: Final = "rank_tail_mean_selector_v1"

#: The integer scale every score is carried at, matching ``PHASE_E_POINTS_SCALE``.
TAIL_POINTS_SCALE: Final = 1000

#: The pre-registered arms, as exact fractions rather than floats: ``m`` is a count and must
#: not depend on how ``0.30 * 1000`` rounds.
TAIL_FRACTION_GRID: Final[tuple[Fraction, ...]] = (
    Fraction(1, 10),
    Fraction(1, 5),
    Fraction(3, 10),
    Fraction(1, 2),
    Fraction(1, 1),
)

#: The null arm. It must reproduce the mean selector's pick on every fold, bit for bit.
NULL_TAIL_FRACTION: Final = Fraction(1, 1)


class TailSide(StrEnum):
    """Which tail of its own gap one rival contributes."""

    BEHIND = "behind"
    LEVEL = "level"
    AHEAD = "ahead"


@dataclass(frozen=True, slots=True)
class RankTailSelection:
    """One fold's pick and the exact integers behind it.

    ``criterion_points`` is the same quantity read back into points: the sum over rivals of
    that rival's tail mean of the gap. It is points-denominated by construction, which is
    what keeps the criterion inside the declared publishable currency even though no part of
    it is published.
    """

    selected_index: int
    scenario_count: int
    tail_size: int
    tail_fraction: Fraction
    criterion_by_candidate: tuple[int, ...]
    contract_version: str = RANK_TAIL_SELECTOR_CONTRACT_VERSION

    @property
    def criterion_int(self) -> int:
        """The winning candidate's exact comparison value."""

        return self.criterion_by_candidate[self.selected_index]

    @property
    def criterion_points(self) -> float:
        """The winning value in points, for the artifact and for nothing else."""

        denominator = TAIL_POINTS_SCALE * self.scenario_count * self.tail_size
        return self.criterion_int / denominator


def tail_side_from_gap(points_ahead_of_rival: float, band_edge: float) -> TailSide:
    """Read one rival's side off the captured standings gap and the published band edge.

    ``points_ahead_of_rival`` is signed, negative when the member trails, and ``band_edge``
    is what ``application/strategies/rule.py::band_edge_points`` returned for the window. The
    comparison is the rule's own, at the rule's own edge: a second constant here would be a
    second band, and the whipsaw the band exists to stop would come back through it.
    """

    edge = _finite(band_edge, "band_edge")
    if edge < 0.0:
        raise ExperimentConfigurationError("band_edge must not be negative.")
    gap = _finite(points_ahead_of_rival, "points_ahead_of_rival")
    if gap < -edge:
        return TailSide.BEHIND
    if gap > edge:
        return TailSide.AHEAD
    return TailSide.LEVEL


def select_rank_tail_candidate(
    candidate_scores: Sequence[Sequence[float]],
    rival_scores: Sequence[Sequence[float]],
    rival_sides: Sequence[TailSide],
    *,
    tail_fraction: Fraction,
) -> RankTailSelection:
    """Pick the candidate with the highest summed per-rival tail mean of the gap.

    ``candidate_scores`` is one row per candidate and ``rival_scores`` one row per rival,
    every row the same scenario draw in the same scenario order -- the caller's single draw
    is what makes a shared player cancel inside a scenario. Index zero of
    ``candidate_scores`` is the control; on an exact tie it wins, so a criterion that cannot
    separate the menu returns today's answer rather than an arbitrary one.
    """

    if tail_fraction not in TAIL_FRACTION_GRID:
        raise ExperimentConfigurationError(
            f"tail_fraction must be one of the pre-registered arms {TAIL_FRACTION_GRID!r}."
        )
    candidates = _scaled_rows(candidate_scores, "candidate_scores")
    rivals = _scaled_rows(rival_scores, "rival_scores")
    sides = tuple(rival_sides)
    if len(sides) != len(rivals):
        raise ExperimentConfigurationError("Every rival needs exactly one side.")
    if any(not isinstance(side, TailSide) for side in sides):
        raise ExperimentConfigurationError("rival_sides must be TailSide members.")
    scenarios = len(candidates[0])
    if any(len(row) != scenarios for row in (*candidates, *rivals)):
        raise ExperimentConfigurationError(
            "Candidates and rivals must be scored on the same scenario draw."
        )
    tail = ceil(tail_fraction * scenarios)

    # The common denominator is ``scenarios * tail``. A tail term carries denominator
    # ``tail`` and is lifted by ``scenarios``; a level term carries denominator
    # ``scenarios`` and is lifted by ``tail``. At a tail fraction of one the two lifts are
    # the same number, which is why the null reproduces the mean selector exactly rather
    # than to within a rounding.
    totals: list[int] = []
    for candidate in candidates:
        total = 0
        for rival, side in zip(rivals, sides, strict=True):
            gaps = [own - theirs for own, theirs in zip(candidate, rival, strict=True)]
            if side is TailSide.LEVEL:
                total += sum(gaps) * tail
            elif side is TailSide.AHEAD:
                total += sum(sorted(gaps)[:tail]) * scenarios
            else:
                total += sum(sorted(gaps)[-tail:]) * scenarios
        totals.append(total)

    # ``max`` returns the first maximal element, so an exact tie keeps the lowest index and
    # the control wins it.
    selected = max(range(len(totals)), key=totals.__getitem__)
    return RankTailSelection(
        selected_index=selected,
        scenario_count=scenarios,
        tail_size=tail,
        tail_fraction=tail_fraction,
        criterion_by_candidate=tuple(totals),
    )


def _finite(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, Real):
        raise ExperimentConfigurationError(f"{name} must be a finite number.")
    number = float(value)
    if not isfinite(number):
        raise ExperimentConfigurationError(f"{name} must be a finite number.")
    return number


def _scaled_rows(rows: Sequence[Sequence[float]], name: str) -> tuple[tuple[int, ...], ...]:
    """Carry every score to its exact integer before anything is subtracted or sorted."""

    frozen = tuple(rows)
    if not frozen:
        raise ExperimentConfigurationError(f"{name} must hold at least one row.")
    scaled: list[tuple[int, ...]] = []
    for row in frozen:
        values = tuple(row)
        if not values:
            raise ExperimentConfigurationError(f"Every {name} row must hold at least one score.")
        scaled.append(
            tuple(
                scale_expected_points(_finite(value, f"{name} score"), TAIL_POINTS_SCALE)
                for value in values
            )
        )
    return tuple(scaled)


__all__ = [
    "NULL_TAIL_FRACTION",
    "RANK_TAIL_SELECTOR_CONTRACT_VERSION",
    "TAIL_FRACTION_GRID",
    "TAIL_POINTS_SCALE",
    "RankTailSelection",
    "TailSide",
    "select_rank_tail_candidate",
    "tail_side_from_gap",
]
