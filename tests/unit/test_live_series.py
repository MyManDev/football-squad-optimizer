"""The live record reports its own precision, refuses below two weeks, and judges nobody."""

import math
from dataclasses import asdict
from statistics import NormalDist

import pytest

from squadopt.evaluation.live_series import (
    DetectionPolicy,
    LiveSeriesPower,
    MemberWeekComparison,
    NotYetEstimable,
    detectable_effect,
    read_live_series,
)
from squadopt.evaluation.models import EvaluationValidationError

SEASON = "2026-27"
# The two normal quantiles the recorded fold precision is quoted at, written out here so the
# test reaches the pinned digits by its own path rather than through the module under test.
Z_SUM = NormalDist().inv_cdf(0.975) + NormalDist().inv_cdf(0.8)

# Three weeks of four members. Week means 0, 10 and 2 against a grand mean of exactly 4, and
# the same within-week deviations (-6, -2, 2, 6) in every week. Every intermediate below is
# an exact binary fraction, so the invariance tests can demand equality rather than closeness.
BALANCED = {
    4: (-6.0, -2.0, 2.0, 6.0),
    5: (4.0, 8.0, 12.0, 16.0),
    6: (-4.0, 0.0, 4.0, 8.0),
}
# Hand arithmetic for BALANCED, from the sums of squares and never from the module.
# Between: 4*(0-4)^2 + 4*(10-4)^2 + 4*(2-4)^2 = 224 on 2 degrees of freedom, so MSB = 112.
# Within: 80 per week, 240 on 9 degrees of freedom, so MSW = 80/3. Equal sizes give a size
# term of 4, so the correlation is (112 - 80/3) / (112 + 3 * 80/3) = (256/3)/192 = 4/9.
CORRELATION = 4.0 / 9.0
DESIGN_EFFECT = 7.0 / 3.0  # 1 + (4 - 1) * 4/9
EFFECTIVE = 36.0 / 7.0  # 12 / (7/3)
DEVIATION = math.sqrt((224.0 + 240.0) / 11.0)

# Fifteen members a week over four weeks: week means -3, -1, 1, 3 and the deviations -7..7.
# MSB = 15 * 20 / 3 = 100 and MSW = 1120 / 56 = 20, so the correlation is 80/380.
FIFTEEN = {
    week: tuple(mean + float(index - 7) for index in range(15))
    for week, mean in zip((1, 2, 3, 4), (-3.0, -1.0, 1.0, 3.0), strict=True)
}


def rows(weeks: dict[int, tuple[float, ...]]) -> list[MemberWeekComparison]:
    """One comparison per member-week, members numbered inside each week."""

    return [
        MemberWeekComparison(SEASON, week, 100 + index, value)
        for week, values in weeks.items()
        for index, value in enumerate(values)
    ]


def estimable(weeks: dict[int, tuple[float, ...]]) -> LiveSeriesPower:
    reading = read_live_series(rows(weeks))
    assert isinstance(reading, LiveSeriesPower)
    return reading


@pytest.mark.parametrize(
    ("weeks", "reason", "member_weeks", "count"),
    [
        ({}, "no_settled_member_weeks", 0, 0),
        ({4: tuple(float(member) for member in range(15))}, "single_settled_week", 15, 1),
        ({4: (1.0,), 5: (2.0,)}, "no_within_week_replication", 2, 2),
        ({4: (2.0, 2.0), 5: (2.0, 2.0), 6: (2.0, 2.0)}, "no_variation", 6, 3),
    ],
)
def test_a_record_that_cannot_carry_a_correlation_names_no_number_for_it(
    weeks: dict[int, tuple[float, ...]],
    reason: str,
    member_weeks: int,
    count: int,
) -> None:
    reading = read_live_series(rows(weeks))
    assert isinstance(reading, NotYetEstimable)
    assert (reading.reason, reading.member_weeks, reading.weeks) == (reason, member_weeks, count)
    assert reading.estimable is False
    # Zero correlation is the most optimistic answer available. A refusal that could be read
    # as zero would understate the horizon, so there is nothing here to read as zero.
    for attribute in (
        "within_week_correlation",
        "design_effect",
        "effective_observations",
        "minimum_detectable_effect",
        "weeks_to_detect",
    ):
        assert not hasattr(reading, attribute)
    assert set(asdict(reading)) == {"reason", "member_weeks", "weeks", "method_version"}


def test_the_balanced_record_reproduces_the_hand_computed_clustering() -> None:
    reading = estimable(BALANCED)
    assert reading.member_weeks == 12 and reading.weeks == 3
    assert reading.average_members_per_week == pytest.approx(4.0)
    assert reading.within_week_correlation == pytest.approx(CORRELATION)
    assert reading.correlation_floored is False
    assert reading.design_effect == pytest.approx(DESIGN_EFFECT)
    assert reading.effective_observations == pytest.approx(EFFECTIVE)
    assert reading.member_week_standard_deviation == pytest.approx(DEVIATION)
    assert reading.minimum_detectable_effect == pytest.approx(
        Z_SUM * DEVIATION / math.sqrt(EFFECTIVE)
    )
    assert reading.between_week_degrees_of_freedom == 2
    assert reading.within_week_degrees_of_freedom == 9
    assert reading.estimable is True


def test_members_who_agree_inside_a_week_leave_one_observation_per_week() -> None:
    reading = estimable({1: (5.0,) * 4, 2: (-3.0,) * 4, 3: (1.0,) * 4})
    assert reading.within_week_correlation == pytest.approx(1.0)
    assert reading.design_effect == pytest.approx(reading.average_members_per_week)
    assert reading.effective_observations == pytest.approx(float(reading.weeks))


@pytest.mark.parametrize(
    ("deviation", "observations", "expected"),
    [
        # docs/measurement_instrument.json, the unconditional 147-fold floor and the
        # 123-fold forward-diagnostic row. The live instrument has to read beside these, so
        # the formula is pinned to their recorded digits rather than restated near them.
        (15.097098212213622, 147.0, 3.488499380776099),
        (14.965840328147138, 123.0, 3.780527390694307),
    ],
)
def test_the_effect_formula_matches_the_recorded_backtest_precision(
    deviation: float,
    observations: float,
    expected: float,
) -> None:
    assert detectable_effect(deviation, observations) == pytest.approx(expected, rel=1e-12)


def test_a_smaller_effective_count_can_only_ask_for_more() -> None:
    assert detectable_effect(10.0, 40.0) > detectable_effect(10.0, 160.0)
    assert detectable_effect(10.0, 4.0) == pytest.approx(detectable_effect(20.0, 16.0))


@pytest.mark.parametrize(
    "weeks",
    [
        BALANCED,
        FIFTEEN,
        {1: (-10.0, 10.0), 2: (-10.0, 10.0)},
        {1: (1.0, 5.0, 9.0), 2: (2.0, 4.0), 3: (-8.0, -1.0, 3.0, 11.0), 4: (0.0, 6.0)},
    ],
)
def test_clustering_never_invents_observations(weeks: dict[int, tuple[float, ...]]) -> None:
    reading = estimable(weeks)
    assert reading.design_effect >= 1.0
    assert reading.effective_observations <= reading.member_weeks
    assert reading.minimum_detectable_effect > 0.0


def test_a_negative_estimate_is_floored_in_the_open_and_buys_nothing() -> None:
    reading = estimable({1: (-10.0, 10.0), 2: (-10.0, 10.0)})
    assert reading.within_week_correlation < 0.0
    assert reading.correlation_floored is True
    assert reading.design_effect == 1.0
    assert reading.effective_observations == float(reading.member_weeks)


@pytest.mark.parametrize(
    "changed",
    [
        {week: tuple(value + 7.0 for value in values) for week, values in BALANCED.items()},
        {week: tuple(-value for value in values) for week, values in BALANCED.items()},
    ],
)
def test_no_shift_or_sign_of_the_differences_can_move_a_single_field(
    changed: dict[int, tuple[float, ...]],
) -> None:
    # Every returned number is a function of counts and variances, so the instrument cannot
    # express which column scored better or by how much, only how precisely it could tell.
    assert asdict(estimable(changed)) == asdict(estimable(BALANCED))


def test_the_horizon_is_monotone_and_never_asks_for_weeks_already_held() -> None:
    reading = estimable(FIFTEEN)
    near = reading.weeks_to_detect(1.0)
    far = reading.weeks_to_detect(4.0)
    assert near.total_weeks >= far.total_weeks
    assert near.additional_weeks == near.total_weeks - reading.weeks
    assert far.additional_weeks >= 0
    assert near.effect == 1.0
    assert near.assumed_members_per_week == reading.average_members_per_week
    assert near.assumed_within_week_correlation == reading.within_week_correlation


def test_a_more_correlated_record_can_only_need_more_weeks() -> None:
    loose = estimable(FIFTEEN)
    tight = estimable({week: (values[7],) * 15 for week, values in FIFTEEN.items()})
    assert tight.within_week_correlation > loose.within_week_correlation
    assert tight.design_effect > loose.design_effect


def test_treating_the_record_as_independent_would_understate_the_horizon() -> None:
    # The pin the refusal exists for. At fifteen members a week and a correlation near 0.2,
    # pretending the member-weeks are independent shortens the horizon several times over.
    reading = estimable(FIFTEEN)
    assert reading.within_week_correlation == pytest.approx(80.0 / 380.0)
    independent = math.ceil(
        (Z_SUM * reading.member_week_standard_deviation / 1.0) ** 2
        / reading.average_members_per_week
    )
    assert 3.0 <= reading.weeks_to_detect(1.0).total_weeks / independent <= 4.5


@pytest.mark.parametrize("effect", [0.0, -1.0, math.inf, math.nan])
def test_a_horizon_needs_a_real_effect(effect: float) -> None:
    with pytest.raises(EvaluationValidationError):
        estimable(BALANCED).weeks_to_detect(effect)


def test_one_member_counted_twice_in_a_week_is_refused_rather_than_counted() -> None:
    duplicated = [*rows(BALANCED), MemberWeekComparison(SEASON, 4, 100, 3.0)]
    with pytest.raises(EvaluationValidationError, match="twice"):
        read_live_series(duplicated)


def test_the_same_member_in_two_weeks_and_two_seasons_stays_separate() -> None:
    reading = read_live_series(
        [
            MemberWeekComparison(SEASON, 4, 100, 1.0),
            MemberWeekComparison(SEASON, 5, 100, 2.0),
            MemberWeekComparison("2027-28", 4, 100, 3.0),
        ]
    )
    assert isinstance(reading, NotYetEstimable)
    assert reading == NotYetEstimable("no_within_week_replication", 3, 3)


@pytest.mark.parametrize(
    "arguments",
    [
        (SEASON, 4, 100, math.nan),
        (SEASON, 4, 100, math.inf),
        (SEASON, 0, 100, 1.0),
        (SEASON, 4, True, 1.0),
        ("   ", 4, 100, 1.0),
    ],
)
def test_a_comparison_that_cannot_be_counted_is_refused_at_the_boundary(
    arguments: tuple[str, int, int, float],
) -> None:
    with pytest.raises(EvaluationValidationError):
        MemberWeekComparison(*arguments)


@pytest.mark.parametrize(
    "policy",
    [{"confidence_level": 1.0}, {"confidence_level": 0.0}, {"power": 1.5}, {"power": math.nan}],
)
def test_a_rate_outside_its_range_is_not_a_rate(policy: dict[str, float]) -> None:
    with pytest.raises(EvaluationValidationError):
        DetectionPolicy(**policy)


def test_a_stricter_policy_travels_through_the_reading() -> None:
    strict = DetectionPolicy(confidence_level=0.99, power=0.9)
    reading = read_live_series(rows(BALANCED), policy=strict)
    assert isinstance(reading, LiveSeriesPower)
    assert (reading.confidence_level, reading.power) == (0.99, 0.9)
    recorded = estimable(BALANCED)
    assert reading.minimum_detectable_effect > recorded.minimum_detectable_effect
    assert reading.weeks_to_detect(1.0).total_weeks > recorded.weeks_to_detect(1.0).total_weeks


@pytest.mark.parametrize(
    ("deviation", "observations"),
    [(-1.0, 10.0), (1.0, 0.0), (1.0, -4.0), (math.nan, 10.0), (1.0, math.inf)],
)
def test_precision_cannot_be_read_off_impossible_inputs(
    deviation: float,
    observations: float,
) -> None:
    with pytest.raises(EvaluationValidationError):
        detectable_effect(deviation, observations)
