"""Independent action arithmetic and scope checks for raw point accounting."""

import math
from dataclasses import FrozenInstanceError, asdict, replace
from decimal import Decimal
from fractions import Fraction

import numpy as np
import pytest

from squadopt.contracts.football_point_accounting import (
    ComponentMoments,
    PointCoefficients,
    RawPointResult,
    clip_points,
    raw_points,
)

WEIGHTS = PointCoefficients(1, 2, 6, 3, 4, 2)
MOMENTS = ComponentMoments(0.8, 0.5, 0.3, 1.1, 0.5, 0.3, 0.5)
MOMENT_FIELDS = tuple(asdict(MOMENTS))
COEFFICIENT_FIELDS = tuple(asdict(WEIGHTS))
INVALID_NUMBERS = (True, np.bool_(False), None, "0.5", math.nan, math.inf, -math.inf)


def test_independent_action_worlds_reconstruct_unconditional_raw_points():
    # Each world lists probability, credited minutes, G/A, CS/DC and signed
    # residual points. The first world has no minutes and a declared card term.
    worlds = (
        (0.2, 0, 0, 0, False, False, -1),
        (0.3, 35, 1, 2, False, True, -1),
        (0.5, 90, 0, 1, True, False, 2),
    )
    expected = 0.0
    for probability, minutes, goals, assists, clean, dc, residual in worlds:
        appearance = 0 if minutes == 0 else (1 if minutes < 60 else 2)
        realized = appearance + 6 * goals + 3 * assists + 4 * clean + 2 * dc + residual
        expected += probability * realized
    result = raw_points(MOMENTS, WEIGHTS)
    assert expected == pytest.approx(9.5)
    assert result.raw_expected_points == pytest.approx(expected)
    assert result.short_play_points == pytest.approx(0.3)
    assert result.long_play_points == 1
    assert result.goal_points == pytest.approx(1.8)
    assert result.assist_points == pytest.approx(3.3)
    assert result.clean_sheet_points == 2
    assert result.defcon_points == pytest.approx(0.6)
    assert result.residual_points == 0.5


def test_unconditional_counts_and_residual_are_not_multiplied_by_q():
    moments = ComponentMoments(0.25, 0, 1.5, 2, 0, 0, -1.75)
    score = raw_points(moments, WEIGHTS)
    assert score.goal_points == 9
    assert score.assist_points == 6
    assert score.residual_points == -1.75
    assert score.raw_expected_points == 13.5


def test_native_conditional_residual_conversion_belongs_to_caller():
    q, conditional_residual = 0.25, -4.0
    result = raw_points(ComponentMoments(q, 0, 0, 0, 0, 0, q * conditional_residual), WEIGHTS)
    assert result.residual_points == -1
    assert result.raw_expected_points == -0.75
    assert clip_points(result.raw_expected_points) == 0


def test_nonstandard_explicit_appearance_weights_follow_realized_action_law():
    weights = replace(WEIGHTS, short_play=2.5, long_play=1)
    moments = ComponentMoments(0.8, 0.3, 0, 0, 0, 0, 0)
    # An explicitly supplied rule can reward a short appearance differently.
    expected = 0.5 * 2.5 + 0.3 * 1
    result = raw_points(moments, weights)
    assert result.raw_expected_points == expected
    assert result.short_play_points == 1.25
    assert result.long_play_points == 0.3


def test_supplied_nonlinear_clean_sheet_mixture_is_preserved():
    clean = 0.5 * math.exp(-0.1) + 0.5 * math.exp(-3.0)
    plug_in_mean = math.exp(-1.55)
    moments = ComponentMoments(1, 1, 0, 0, clean, 0, 0)
    result = raw_points(moments, WEIGHTS)
    assert clean > plug_in_mean
    assert result.clean_sheet_points == 4 * clean
    assert result.raw_expected_points == 2 + 4 * clean
    assert result.moments is moments
    assert result.coefficients is WEIGHTS


def test_supplied_defcon_award_moment_does_not_require_a_distribution():
    moments = ComponentMoments(0.7, 0.2, 0, 0, 0, 0.6, 0)
    result = raw_points(moments, WEIGHTS)
    assert result.defcon_points == 1.2
    assert result.raw_expected_points == pytest.approx(2.1)
    assert result.moments.defcon_probability == 0.6


@pytest.mark.parametrize("p0,p60", [(0.8, 0.2), (0.999999, 0.000001)])
def test_default_nested_support_is_strict_even_for_binary_roundoff(p0, p60):
    q = 1 - p0
    if p60 > q:
        with pytest.raises(ValueError, match="p60 cannot exceed appearance_probability"):
            ComponentMoments(q, p60, 0, 0, 0, 0, 0)
    else:
        # This representation can round on the other side, but no implicit
        # tolerance exists for a separately supplied neighboring p60 value.
        q = math.nextafter(p60, 0)
        with pytest.raises(ValueError, match="p60 cannot exceed appearance_probability"):
            ComponentMoments(q, p60, 0, 0, 0, 0, 0)


@pytest.mark.parametrize("p0,p60", [(0.8, 0.2), (0.999999, 0.000001)])
def test_declared_bounded_support_roundoff_preserves_native_values_and_points(p0, p60):
    q = 1 - p0
    budget = 4 * math.ulp(1.0)
    moments = ComponentMoments(q, p60, 0, 0, p60, q, -0.4, support_roundoff=budget)
    result = raw_points(moments, WEIGHTS)
    assert moments.appearance_probability == q
    assert moments.p60 == moments.clean_sheet_probability == p60
    assert moments.defcon_probability == q
    assert moments.support_roundoff == budget
    assert result.short_play_points == q - p60
    assert result.moments is moments
    # Each supplied binary value is held exactly. The budget never contributes
    # to scoring and does not replace the moments by a normalized distribution.
    expected = float(
        Fraction(q) + Fraction(p60) + 4 * Fraction(p60) + 2 * Fraction(q) - Fraction(0.4)
    )
    assert result.raw_expected_points == expected


@pytest.mark.parametrize(
    "field,base_field",
    [
        ("p60", "appearance_probability"),
        ("clean_sheet_probability", "p60"),
        ("defcon_probability", "appearance_probability"),
    ],
)
def test_roundoff_budget_applies_only_to_declared_nested_support(field, base_field):
    fields = asdict(ComponentMoments(0.5, 0.5, 0, 0, 0.5, 0.5, 0))
    higher = math.nextafter(fields[base_field], 1)
    gap = higher - fields[base_field]
    fields[field] = higher
    fields["support_roundoff"] = gap
    accepted = ComponentMoments(**fields)
    assert getattr(accepted, field) == higher
    assert getattr(accepted, base_field) == 0.5
    fields["support_roundoff"] = math.nextafter(gap, 0)
    with pytest.raises(ValueError, match=f"moment.{field} cannot exceed"):
        ComponentMoments(**fields)


@pytest.mark.parametrize(
    "field,base_field",
    [
        ("p60", "appearance_probability"),
        ("clean_sheet_probability", "p60"),
        ("defcon_probability", "appearance_probability"),
    ],
)
def test_maximum_roundoff_budget_cannot_admit_gross_nested_violations(field, base_field):
    fields = asdict(ComponentMoments(0.5, 0.5, 0, 0, 0.5, 0.5, 0))
    fields[field] = fields[base_field] + 1e-10
    fields["support_roundoff"] = 4 * math.ulp(1.0)
    with pytest.raises(ValueError, match=f"moment.{field} cannot exceed"):
        ComponentMoments(**fields)


@pytest.mark.parametrize(
    "value", [True, math.nan, math.inf, -math.inf, -1e-18, math.nextafter(4 * math.ulp(1.0), 1)]
)
def test_invalid_support_roundoff_metadata_is_refused(value):
    with pytest.raises(ValueError, match=r"moment\.support_roundoff"):
        replace(MOMENTS, support_roundoff=value)


@pytest.mark.parametrize(
    "field", ["p60", "clean_sheet_probability", "defcon_probability", "goals", "assists"]
)
def test_roundoff_does_not_create_activity_at_exactly_zero_appearance(field):
    fields = asdict(ComponentMoments(0, 0, 0, 0, 0, 0, -1, support_roundoff=4 * math.ulp(1.0)))
    fields[field] = math.ulp(1.0)
    with pytest.raises(ValueError, match="support"):
        ComponentMoments(**fields)


def test_roundoff_does_not_create_clean_sheet_support_at_exactly_zero_p60():
    with pytest.raises(ValueError, match="Zero p60"):
        ComponentMoments(0.5, 0, 0, 0, math.ulp(1.0), 0, 0, support_roundoff=4 * math.ulp(1.0))


@pytest.mark.parametrize(
    "field", ["appearance_probability", "p60", "clean_sheet_probability", "defcon_probability"]
)
def test_support_budget_does_not_relax_individual_unit_interval(field):
    fields = asdict(ComponentMoments(1, 1, 0, 0, 1, 1, 0, support_roundoff=4 * math.ulp(1.0)))
    fields[field] = math.nextafter(1.0, math.inf)
    with pytest.raises(ValueError, match=f"moment.{field}.*\\[0, 1\\]"):
        ComponentMoments(**fields)


def test_averaging_clipped_states_is_distinct_from_clipping_their_mean():
    first = ComponentMoments(1, 0, 0, 0, 0, 0, -3)
    second = replace(first, residual_expected_points=1)
    first_raw = raw_points(first, WEIGHTS).raw_expected_points
    second_raw = raw_points(second, WEIGHTS).raw_expected_points
    mean = replace(first, residual_expected_points=-1)
    averaged_raw = raw_points(mean, WEIGHTS).raw_expected_points
    assert first_raw == -2
    assert second_raw == 2
    assert averaged_raw == 0
    assert 0.5 * clip_points(first_raw) + 0.5 * clip_points(second_raw) == 1
    assert clip_points(averaged_raw) == 0


@pytest.mark.parametrize("residual", [-2.0, 0.0, 2.0])
def test_zero_minute_independently_declared_residual_is_preserved(residual):
    score = raw_points(ComponentMoments(0, 0, 0, 0, 0, 0, residual), WEIGHTS)
    assert score.raw_expected_points == residual
    assert score.short_play_points == score.long_play_points == 0
    assert score.residual_points == residual
    assert clip_points(score.raw_expected_points) == max(0, residual)


def test_full_appearance_and_multiple_actions_have_no_probability_count_cap():
    result = raw_points(ComponentMoments(1, 1, 2, 3, 1, 1, -0.5), WEIGHTS)
    assert result.raw_expected_points == 28.5
    assert result.short_play_points == 0
    assert result.long_play_points == 2


def test_zero_coefficients_leave_only_the_supplied_signed_residual():
    zero = PointCoefficients(0, 0, 0, 0, 0, 0)
    result = raw_points(replace(MOMENTS, residual_expected_points=-3), zero)
    assert result.raw_expected_points == -3


def test_tiny_gain_survives_full_term_cancellation_without_rounded_subgroups():
    moments = ComponentMoments(1, 0, 1e16, 0, 0, 0, -1e16)
    first_weights = PointCoefficients(1e-16, 0, 1, 0, 0, 0)
    next_weights = replace(first_weights, short_play=1.1e-16)
    first = raw_points(moments, first_weights).raw_expected_points
    second = raw_points(moments, next_weights).raw_expected_points
    exact_first = float(Fraction(1e-16) + Fraction(1e16) - Fraction(1e16))
    exact_second = float(Fraction(1.1e-16) + Fraction(1e16) - Fraction(1e16))
    assert first == exact_first == 1e-16
    assert second == exact_second == 1.1e-16
    assert second > first
    naive = 0.0
    for term in (1e-16, 1e16, -1e16):
        naive += term
    assert naive == 0


@pytest.mark.parametrize("signed", [-1e-300, 1e-300])
def test_tiny_signed_residual_is_not_rounded_or_given_a_tie_epsilon(signed):
    result = raw_points(ComponentMoments(0, 0, 0, 0, 0, 0, signed), WEIGHTS)
    assert result.raw_expected_points == signed
    assert clip_points(result.raw_expected_points) == (signed if signed > 0 else 0)


@pytest.mark.parametrize("field", MOMENT_FIELDS)
@pytest.mark.parametrize("value", INVALID_NUMBERS)
def test_invalid_moment_numbers_refuse_with_named_field(field, value):
    with pytest.raises(ValueError, match=f"moment.{field}"):
        replace(MOMENTS, **{field: value})


@pytest.mark.parametrize("field", COEFFICIENT_FIELDS)
@pytest.mark.parametrize("value", INVALID_NUMBERS)
def test_invalid_coefficient_numbers_refuse_with_named_field(field, value):
    with pytest.raises(ValueError, match=f"coefficient.{field}"):
        replace(WEIGHTS, **{field: value})


@pytest.mark.parametrize(
    ("value", "kind"),
    [(None, "NoneType"), ("0.5", "str"), (Decimal("0.5"), "Decimal"), ([0.5], "list")],
)
def test_unsupported_number_types_are_named_without_a_boolean_claim(value, kind):
    with pytest.raises(ValueError, match=rf"coefficient\.goals .*not {kind}\.") as refused:
        replace(WEIGHTS, goals=value)
    assert "Boolean" not in str(refused.value)
    with pytest.raises(ValueError, match=r"moment\.goals .*not a Boolean\."):
        replace(MOMENTS, goals=True)


@pytest.mark.parametrize("field", COEFFICIENT_FIELDS)
def test_negative_coefficients_are_refused(field):
    with pytest.raises(ValueError, match=f"coefficient.{field}.*nonnegative"):
        replace(WEIGHTS, **{field: -0.1})


@pytest.mark.parametrize(
    "field", [field for field in MOMENT_FIELDS if field != "residual_expected_points"]
)
def test_negative_unsigned_moments_are_refused(field):
    with pytest.raises(ValueError, match=f"moment.{field}.*nonnegative"):
        replace(MOMENTS, **{field: -0.1})


@pytest.mark.parametrize(
    "field", ["appearance_probability", "p60", "clean_sheet_probability", "defcon_probability"]
)
def test_probability_above_one_refuses_without_normalization(field):
    with pytest.raises(ValueError, match=f"moment.{field}.*\\[0, 1\\]"):
        replace(MOMENTS, **{field: 1.1})


@pytest.mark.parametrize(
    ("changes", "message"),
    [
        ({"p60": 0.9}, "p60 cannot exceed"),
        ({"clean_sheet_probability": 0.6}, "clean_sheet_probability cannot exceed"),
        ({"defcon_probability": 0.9}, "defcon_probability cannot exceed"),
    ],
)
def test_joint_probability_support_is_refused(changes, message):
    with pytest.raises(ValueError, match=message):
        replace(MOMENTS, **changes)


@pytest.mark.parametrize("field", ["goals", "assists"])
def test_zero_minute_appearance_cannot_receive_attacking_counts(field):
    blank = ComponentMoments(0, 0, 0, 0, 0, 0, 0)
    with pytest.raises(ValueError, match="positive-minute appearance support"):
        replace(blank, **{field: 0.1})


@pytest.mark.parametrize("value", INVALID_NUMBERS)
def test_clip_requires_a_finite_real_raw_value(value):
    with pytest.raises(ValueError, match="raw points"):
        clip_points(value)


@pytest.mark.parametrize("field", ["goals", "assists"])
def test_individual_multiplication_overflow_is_refused(field):
    coefficients = replace(WEIGHTS, **{field: 1e308})
    moments = replace(MOMENTS, **{field: 2})
    with pytest.raises(ValueError, match="overflowed finite point support"):
        raw_points(moments, coefficients)


def test_summation_overflow_is_refused_even_with_individually_finite_terms():
    weights = PointCoefficients(0, 0, 1, 1, 0, 0)
    moments = ComponentMoments(1, 0, 1e308, 1e308, 0, 0, 0)
    with pytest.raises(ValueError, match="summation overflowed"):
        raw_points(moments, weights)


@pytest.mark.parametrize("record", ["moments", "coefficients", "clip"])
def test_integer_to_float_overflow_is_a_named_value_error(record):
    huge = 10**1000
    with pytest.raises(ValueError, match="finite real number"):
        if record == "moments":
            replace(MOMENTS, goals=huge)
        elif record == "coefficients":
            replace(WEIGHTS, goals=huge)
        else:
            clip_points(huge)


@pytest.mark.parametrize(
    ("moments", "coefficients", "message"),
    [(None, WEIGHTS, "moments"), (MOMENTS, {}, "coefficients")],
)
def test_scoring_requires_validated_typed_records(moments, coefficients, message):
    with pytest.raises(ValueError, match=message):
        raw_points(moments, coefficients)


@pytest.mark.parametrize("record", [MOMENTS, WEIGHTS, raw_points(MOMENTS, WEIGHTS)])
def test_inputs_and_named_output_are_frozen(record):
    field = next(iter(asdict(record)))
    with pytest.raises(FrozenInstanceError):
        setattr(record, field, 0)


def test_result_construction_cannot_bypass_scoring_or_change_inputs():
    before_moments, before_weights = asdict(MOMENTS), asdict(WEIGHTS)
    first = raw_points(MOMENTS, WEIGHTS)
    direct = RawPointResult(MOMENTS, WEIGHTS)
    assert first == direct
    assert first.raw_expected_points == 9.5
    assert asdict(MOMENTS) == before_moments
    assert asdict(WEIGHTS) == before_weights
    assert isinstance(first.raw_expected_points, float)
    assert isinstance(WEIGHTS.short_play, float)
    assert isinstance(MOMENTS.goals, float)


def test_numpy_real_scalars_are_explicitly_accepted_as_finite_values():
    moments = replace(MOMENTS, goals=np.float32(0.5))
    weights = replace(WEIGHTS, goals=np.int64(6))
    result = raw_points(moments, weights)
    assert result.goal_points == 3
    assert type(result.goal_points) is float
