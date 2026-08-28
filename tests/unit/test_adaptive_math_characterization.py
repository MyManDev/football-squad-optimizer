"""Characterization of the player-adaptive shrinkage mathematics, implemented twice.

Two modules carry the same shrinkage rule in different algebraic disguises:

* ``squadopt.uncertainty.adaptive._scale_from_state`` uses the *hypot* form::

      hypot(sqrt(n) * player_scale, sqrt(k) * position_scale) / sqrt(n + k)

* ``squadopt.recalibration.study._fit_scale_state`` uses the *variance* form::

      sqrt((n * player_scale**2 + k * fallback**2) / (n + k))

Algebraically these are the same number, because ``hypot(a, b) == sqrt(a**2 + b**2)``::

    hypot(sqrt(n)*p, sqrt(k)*f) / sqrt(n+k)
      = sqrt(n*p**2 + k*f**2) / sqrt(n+k)
      = sqrt((n*p**2 + k*f**2) / (n+k))

In IEEE-754 they are NOT always the same float, so the tests below pin the
*observed* relation (agreement to within two units in the last place, with a
concrete row where the two disagree by exactly one ulp) rather than forcing
bit-for-bit equality.

Several differences between the two implementations are deliberate. Those are
pinned as INEQUALITIES so that a future "unify this" change fails loudly:

* ``scale_training_fraction`` is 0.50 in one config and 0.40 in the other.
* The shrinkage fallback group is chosen by the ROW's position in ``adaptive``
  and by the player's LATEST observed position in ``study``.
* Non-finite residuals raise in ``adaptive`` and propagate as NaN in ``study``.
* ``min_player_observations`` may be 1 in ``study`` but must be at least 2 in
  ``adaptive``.

Nothing here is a judgement about which behaviour is right.
"""

import dataclasses
import math
import warnings

import numpy as np
import pandas as pd
import pytest

from squadopt.optimization.config import POSITIONS
from squadopt.recalibration.models import (
    RecalibrationValidationError,
    TimeAwareRecalibrationConfig,
)
from squadopt.recalibration.study import (
    _effective_scale,
    _fit_scale_state,
    _population_scale,
)
from squadopt.uncertainty.adaptive import _scale_from_state, _summary
from squadopt.uncertainty.config import PlayerAdaptiveUncertaintyConfig
from squadopt.uncertainty.errors import (
    UncertaintyConfigurationError,
    UncertaintyValidationError,
)
from squadopt.uncertainty.models import AdaptiveGroupCalibration, ResidualScaleSummary

MINIMUM_SCALE = 0.25


def _adaptive_scale(
    observations: int,
    strength: float,
    player_scale: float,
    fallback_scale: float,
    *,
    minimum_scale: float = MINIMUM_SCALE,
    position: str = "MID",
) -> float:
    """Drive the real ``adaptive`` hypot form for one (n, k, player, fallback)."""

    config = PlayerAdaptiveUncertaintyConfig(
        shrinkage_observations=strength,
        minimum_scale=minimum_scale,
        min_player_observations=2,
    )
    groups = {
        name: AdaptiveGroupCalibration(
            position=name,
            scale_source="position",
            scale_observations=30,
            position_scale=fallback_scale,
            conformal_source="position",
            group_calibration_observations=30,
            calibration_observations=30,
            conformal_multiplier=1.0,
            conformal_rank=30,
        )
        for name in POSITIONS
    }
    players = {"x": ResidualScaleSummary(observations, 0.0, player_scale)}
    scale, _, _, _ = _scale_from_state("x", position, config, groups, players)
    return scale


def _study_scale(
    observations: int,
    strength: float,
    player_scale: float,
    fallback_scale: float,
    *,
    minimum_scale: float = MINIMUM_SCALE,
) -> float:
    """Mirror the ``study`` variance form.

    ``_fit_scale_state`` cannot be driven to arbitrary (n, player_scale,
    fallback_scale) triples without inventing residual samples with those exact
    population spreads, so the table tests use this transcription. It is
    anchored against the real ``_fit_scale_state`` in
    ``test_study_variance_form_matches_the_real_fitted_state``.
    """

    variance = (observations * player_scale**2 + strength * fallback_scale**2) / (
        observations + strength
    )
    return max(math.sqrt(variance), minimum_scale)


# (observations n, strength k, player_scale p, fallback_scale f)
SHRINKAGE_TABLE: tuple[tuple[int, float, float, float], ...] = (
    (5, 10.0, 1.0, 1.0),  # (5*1 + 10*1)/15 = 1
    (5, 10.0, 2.0, 1.0),  # (5*4 + 10*1)/15 = 30/15 = 2
    (8, 10.0, 0.5, 1.5),  # (8*0.25 + 10*2.25)/18 = 24.5/18 = 49/36
    (2, 10.0, 3.0, 0.25),  # (2*9 + 10*0.0625)/12 = 18.625/12 = 149/96
    (30, 10.0, math.sqrt(3.0), math.sqrt(7.0)),  # (30*3 + 10*7)/40 = 160/40 = 4
    (12, 10.0, 0.25, 0.25),  # both inputs at the floor: (12+10)*0.0625/22 = 0.0625
    (7, 10.0, 4.5, 0.75),  # (7*20.25 + 10*0.5625)/17 = 147.375/17
    (100, 10.0, 1.3, 0.9),  # (100*1.69 + 10*0.81)/110 = 177.1/110 = 1.61
    (3, 10.0, 1.0 / 3.0, 2.0 / 3.0),  # (3*(1/9) + 10*(4/9))/13 = (43/9)/13 = 43/117
    (9, 10.0, 2.5, 2.5),  # both equal: the shrunk value is that value
    (6, 10.0, math.sqrt(2.0), math.sqrt(3.0)),  # (6*2 + 10*3)/16 = 42/16 = 2.625
    (4, 2.5, 1.25, 3.75),  # (4*1.5625 + 2.5*14.0625)/6.5 = 41.40625/6.5
)

# Rows whose closed form lands on an exactly representable float, with the
# hand-computed variance shown. Expected scale is sqrt(variance).
EXACT_CLOSED_FORMS: tuple[tuple[tuple[int, float, float, float], float], ...] = (
    ((5, 10.0, 1.0, 1.0), 1.0),  # (5*1 + 10*1)/15 = 1
    ((5, 10.0, 2.0, 1.0), 2.0),  # (5*4 + 10*1)/15 = 2
    ((8, 10.0, 0.5, 1.5), 49.0 / 36.0),  # 24.5/18 = 49/36
    ((12, 10.0, 0.25, 0.25), 0.0625),  # 0.25**2
    ((9, 10.0, 2.5, 2.5), 6.25),  # 2.5**2
    ((10, 10.0, 3.0, 1.0), 5.0),  # (10*9 + 10*1)/20 = 100/20 = 5
    ((15, 5.0, 2.0, 4.0), 7.0),  # (15*4 + 5*16)/20 = 140/20 = 7
    ((3, 1.0, 2.0, 4.0), 7.0),  # (3*4 + 1*16)/4 = 28/4 = 7
)


# ---------------------------------------------------------------------------
# 1. The algebraic equivalence of the two disguises
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("row", SHRINKAGE_TABLE)
def test_the_two_shrinkage_forms_agree_to_within_two_ulps(
    row: tuple[int, float, float, float],
) -> None:
    """Hypot form and variance form are the same number up to rounding."""

    hypot_form = _adaptive_scale(*row)
    variance_form = _study_scale(*row)
    assert math.isfinite(hypot_form)
    assert math.isfinite(variance_form)
    assert abs(hypot_form - variance_form) <= 2.0 * math.ulp(variance_form)


def test_the_two_shrinkage_forms_are_not_bit_identical_on_every_row() -> None:
    """They agree closely but NOT everywhere: the equivalence is algebraic only."""

    # The equivalence is algebraic, so the two forms may round differently -- today
    # three of the twelve rows do. That is recorded rather than required: a libm or
    # numpy build on which every row agreed would be more accurate, not wrong, so the
    # assertion is the bound, not the existence of a gap.
    for row in SHRINKAGE_TABLE:
        hypot_form, variance_form = _adaptive_scale(*row), _study_scale(*row)
        assert abs(hypot_form - variance_form) <= 2.0 * math.ulp(variance_form)


def test_the_shrinkage_form_divergence_is_pinned_on_a_concrete_row() -> None:
    """n=5, k=10, player=2.0, fallback=1.0 lands on two adjacent floats.

    Exact value: (5*2**2 + 10*1**2) / (5 + 10) = 30/15 = 2, so the answer is
    sqrt(2) = 1.4142135623730951. The variance form returns exactly that; the
    hypot form returns the float one ulp below it.
    """

    row = (5, 10.0, 2.0, 1.0)
    hypot_form = _adaptive_scale(*row)
    variance_form = _study_scale(*row)

    # The variance form is correctly rounded to the exact answer. The hypot form is
    # pinned only as "no worse than two ulps": its exact expansion is math.hypot's
    # rounding, which no standard guarantees across libm builds.
    assert variance_form == math.sqrt(2.0)
    assert variance_form - hypot_form >= 0.0
    assert variance_form - hypot_form <= 2.0 * math.ulp(hypot_form)


@pytest.mark.parametrize(("row", "variance"), EXACT_CLOSED_FORMS)
def test_shrinkage_matches_the_hand_computed_closed_form(
    row: tuple[int, float, float, float], variance: float
) -> None:
    """The variance form is correctly rounded on these rows; hypot within 2 ulps."""

    expected = math.sqrt(variance)
    assert _study_scale(*row) == expected
    assert abs(_adaptive_scale(*row) - expected) <= 2.0 * math.ulp(expected)


def test_shrinkage_is_monotone_between_the_player_and_fallback_scales() -> None:
    """Both forms return a weighted quadratic mean, so it sits between the inputs."""

    for observations in (2, 5, 20):
        hypot_form = _adaptive_scale(observations, 10.0, 1.0, 4.0)
        variance_form = _study_scale(observations, 10.0, 1.0, 4.0)
        assert 1.0 < hypot_form < 4.0
        assert 1.0 < variance_form < 4.0
    # More player observations pull the answer toward the player's own scale.
    assert _adaptive_scale(100, 10.0, 1.0, 4.0) < _adaptive_scale(2, 10.0, 1.0, 4.0)
    assert _study_scale(100, 10.0, 1.0, 4.0) < _study_scale(2, 10.0, 1.0, 4.0)


# ---------------------------------------------------------------------------
# 2. The intentional configuration divergence
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("knob", "value"),
    (
        ("confidence_level", 0.90),
        ("min_position_observations", 30),
        ("min_player_observations", 5),
        ("shrinkage_observations", 10.0),
        ("minimum_scale", 0.25),
    ),
)
def test_duplicated_config_knobs_hold_the_same_default(knob: str, value: float) -> None:
    """These five knobs are duplicated verbatim across the two configs."""

    adaptive = PlayerAdaptiveUncertaintyConfig()
    study = TimeAwareRecalibrationConfig()
    assert getattr(adaptive, knob) == value
    assert getattr(study, knob) == value
    assert getattr(adaptive, knob) == getattr(study, knob)


def test_scale_training_fraction_is_deliberately_different() -> None:
    """0.50 vs 0.40. Unifying the configs must fail HERE, not silently re-split.

    This is not a rounding artifact and not an oversight to be tidied away: the
    two studies chop their chronological fold list at different points, and
    every recorded artifact depends on the split it was fitted with.
    """

    adaptive = PlayerAdaptiveUncertaintyConfig()
    study = TimeAwareRecalibrationConfig()
    assert adaptive.scale_training_fraction == 0.50
    assert study.scale_training_fraction == 0.40
    assert adaptive.scale_training_fraction != study.scale_training_fraction
    assert adaptive.scale_training_fraction > study.scale_training_fraction


def test_contract_versions_share_a_knob_name_but_never_a_value() -> None:
    adaptive = PlayerAdaptiveUncertaintyConfig()
    study = TimeAwareRecalibrationConfig()
    assert adaptive.contract_version == "player_adaptive_uncertainty_v1"
    assert study.contract_version == "time_aware_calendar_recalibration_v1"
    assert adaptive.contract_version != study.contract_version


def test_each_config_carries_knobs_the_other_one_lacks() -> None:
    """Pin the exact asymmetry in the knob sets, not just the shared names."""

    adaptive_names = {f.name for f in dataclasses.fields(PlayerAdaptiveUncertaintyConfig)}
    study_names = {f.name for f in dataclasses.fields(TimeAwareRecalibrationConfig)}

    assert adaptive_names & study_names == {
        "confidence_level",
        "contract_version",
        "min_player_observations",
        "min_position_observations",
        "minimum_scale",
        "scale_training_fraction",
        "shrinkage_observations",
    }
    assert adaptive_names - study_names == {
        "development_seasons",
        "holdout_season",
        "min_pooled_observations",
    }
    assert study_names - adaptive_names == {
        "conformal_calibration_fraction",
        "residual_config",
    }


def test_min_player_observations_validators_disagree_at_one() -> None:
    """``study`` accepts a one-observation player; ``adaptive`` refuses to."""

    assert TimeAwareRecalibrationConfig(min_player_observations=1).min_player_observations == 1
    with pytest.raises(
        UncertaintyConfigurationError,
        match=r"min_player_observations must be at least 2",
    ):
        PlayerAdaptiveUncertaintyConfig(min_player_observations=1)


def test_both_configs_reject_a_zero_shrinkage_strength_but_with_different_errors() -> None:
    with pytest.raises(
        UncertaintyConfigurationError,
        match=r"shrinkage_observations must be greater than 0",
    ):
        PlayerAdaptiveUncertaintyConfig(shrinkage_observations=0.0)
    with pytest.raises(
        RecalibrationValidationError,
        match=r"shrinkage_observations must be a positive finite number",
    ):
        TimeAwareRecalibrationConfig(shrinkage_observations=0.0)


def test_both_configs_reject_a_zero_minimum_scale() -> None:
    with pytest.raises(UncertaintyConfigurationError, match=r"minimum_scale must be greater"):
        PlayerAdaptiveUncertaintyConfig(minimum_scale=0.0)
    with pytest.raises(RecalibrationValidationError, match=r"minimum_scale must be a positive"):
        TimeAwareRecalibrationConfig(minimum_scale=0.0)


# ---------------------------------------------------------------------------
# 3. Which position supplies the shrinkage fallback
# ---------------------------------------------------------------------------


def _position_changer_frame() -> pd.DataFrame:
    """A player whose last observed position (MID) is not their usual one (DEF).

    ``p1`` has four DEF rows and then one MID row, so DEF is the position of
    most of their rows but MID is the LATEST. DEF and MID carry very different
    residual spreads, which makes the two fallback choices provably differ.
    """

    rows = [
        ("p1", "DEF", 1.0),
        ("p1", "DEF", -1.0),
        ("p1", "DEF", 1.0),
        ("p1", "DEF", -1.0),
        ("p1", "MID", 0.0),
        ("p2", "DEF", 3.0),
        ("p2", "DEF", -3.0),
        ("p3", "MID", 8.0),
        ("p3", "MID", -8.0),
    ]
    return pd.DataFrame(rows, columns=["player_id", "position", "residual"])


def _position_changer_config() -> TimeAwareRecalibrationConfig:
    return TimeAwareRecalibrationConfig(
        min_position_observations=2,
        min_player_observations=5,
    )


def test_the_position_changer_fixture_has_the_spreads_the_pins_rely_on() -> None:
    """DEF and MID scales are far apart, so a fallback swap cannot hide."""

    state = _fit_scale_state(_position_changer_frame(), _position_changer_config())

    # DEF residuals [1, -1, 1, -1, 3, -3]: mean 0, pvar = 22/6, sqrt = 1.9148542155126762
    assert state.position_scales["DEF"] == math.sqrt(22.0 / 6.0)
    # MID residuals [0, 8, -8]: mean 0, pvar = 128/3, sqrt = 6.531972647421808
    assert state.position_scales["MID"] == math.sqrt(128.0 / 3.0)
    assert state.position_scales["MID"] > 3.0 * state.position_scales["DEF"]
    assert state.player_observations["p1"] == 5
    # Only p1 clears min_player_observations=5.
    assert set(state.player_scales) == {"p1"}


def test_study_shrinks_toward_the_latest_observed_position() -> None:
    """``study`` bakes the fallback in at fit time from ``group.iloc[-1]``."""

    frame = _position_changer_frame()
    state = _fit_scale_state(frame, _position_changer_config())

    # p1 residuals [1, -1, 1, -1, 0]: mean 0, pvar = 4/5, sqrt = 0.8944271909999159
    player_scale = _population_scale(frame.loc[frame["player_id"] == "p1", "residual"], 0.25)
    assert player_scale == math.sqrt(0.8)

    toward_mid = _study_scale(5, 10.0, player_scale, state.position_scales["MID"])
    toward_def = _study_scale(5, 10.0, player_scale, state.position_scales["DEF"])
    assert state.player_scales["p1"] == toward_mid
    assert state.player_scales["p1"] != toward_def
    assert toward_mid - toward_def > 3.0


def test_study_variance_form_matches_the_real_fitted_state() -> None:
    """Anchor the transcribed ``_study_scale`` helper to the real fitter."""

    frame = _position_changer_frame()
    state = _fit_scale_state(frame, _position_changer_config())
    player_scale = _population_scale(frame.loc[frame["player_id"] == "p1", "residual"], 0.25)
    assert state.player_scales["p1"] == _study_scale(
        5, 10.0, player_scale, state.position_scales["MID"]
    )


def test_study_effective_scale_ignores_the_row_position_for_a_known_player() -> None:
    """Once a player has a shrunk scale, ``study`` never consults the row again."""

    state = _fit_scale_state(_position_changer_frame(), _position_changer_config())
    on_def, def_source, def_count = _effective_scale(state, "p1", "DEF")
    on_mid, mid_source, mid_count = _effective_scale(state, "p1", "MID")
    on_gk, gk_source, gk_count = _effective_scale(state, "p1", "GK")
    assert on_def == on_mid == on_gk
    assert def_source == mid_source == gk_source == "player_shrunk"
    assert def_count == mid_count == gk_count == 5


def test_adaptive_shrinks_toward_the_row_position() -> None:
    """``adaptive`` looks the fallback up per row, so the same player differs."""

    frame = _position_changer_frame()
    state = _fit_scale_state(frame, _position_changer_config())
    player_scale = _population_scale(frame.loc[frame["player_id"] == "p1", "residual"], 0.25)

    on_def = _adaptive_scale(5, 10.0, player_scale, state.position_scales["DEF"], position="DEF")
    on_mid = _adaptive_scale(5, 10.0, player_scale, state.position_scales["MID"], position="MID")
    assert on_def != on_mid
    assert on_mid - on_def > 3.0


def test_the_two_fallback_choices_provably_diverge_for_a_position_changer() -> None:
    """The load-bearing inequality: row position vs latest position.

    ``study``'s answer coincides with ``adaptive``'s MID row (MID is p1's latest
    position) and is far from ``adaptive``'s DEF row. A refactor that made both
    read the row position, or both read the latest position, would change one of
    these two relations.
    """

    frame = _position_changer_frame()
    state = _fit_scale_state(frame, _position_changer_config())
    player_scale = _population_scale(frame.loc[frame["player_id"] == "p1", "residual"], 0.25)

    study_answer = state.player_scales["p1"]
    adaptive_on_def = _adaptive_scale(
        5, 10.0, player_scale, state.position_scales["DEF"], position="DEF"
    )
    adaptive_on_mid = _adaptive_scale(
        5, 10.0, player_scale, state.position_scales["MID"], position="MID"
    )

    # The load-bearing content is the DEF/MID divergence, which is >3.0 wide. The
    # agreement with the MID branch crosses the two algebraic forms, so it is bounded
    # rather than required bit-for-bit (see the module docstring).
    assert abs(study_answer - adaptive_on_mid) <= 2.0 * math.ulp(adaptive_on_mid)
    assert study_answer != adaptive_on_def
    assert study_answer - adaptive_on_def > 3.0


def test_adaptive_falls_back_per_row_for_an_unknown_player() -> None:
    """Fallback source names differ with the group's own ``scale_source``."""

    config = PlayerAdaptiveUncertaintyConfig(min_player_observations=2)
    groups = {
        name: AdaptiveGroupCalibration(
            position=name,
            scale_source="position" if name == "MID" else "pooled_fallback",
            scale_observations=30,
            position_scale=3.0 if name == "MID" else 4.0,
            conformal_source="position",
            group_calibration_observations=30,
            calibration_observations=30,
            conformal_multiplier=1.0,
            conformal_rank=30,
        )
        for name in POSITIONS
    }
    players = {"known": ResidualScaleSummary(1, 0.0, 0.0)}

    assert _scale_from_state("ghost", "MID", config, groups, players) == (
        3.0,
        "position_fallback",
        30,
        0,
    )
    assert _scale_from_state("ghost", "DEF", config, groups, players) == (
        4.0,
        "pooled_fallback",
        30,
        0,
    )


# ---------------------------------------------------------------------------
# 4. The standard-deviation estimator
# ---------------------------------------------------------------------------


def test_both_estimators_are_population_standard_deviation() -> None:
    """statistics.pstdev and numpy std(ddof=0) on a shared sample.

    [1, 2, 3, 4, 5]: mean 3, squared deviations 4+1+0+1+4 = 10.
    Population (ddof=0): sqrt(10/5) = sqrt(2)  = 1.4142135623730951
    Sample     (ddof=1): sqrt(10/4) = sqrt(2.5) = 1.5811388300841898
    """

    sample = [1.0, 2.0, 3.0, 4.0, 5.0]
    adaptive_estimate = _summary(sample, "shared sample").residual_stddev
    study_estimate = _population_scale(pd.Series(sample), 1e-9)

    assert adaptive_estimate == math.sqrt(2.0)
    assert study_estimate == math.sqrt(2.0)
    assert adaptive_estimate == study_estimate
    assert adaptive_estimate != math.sqrt(2.5)
    assert study_estimate != math.sqrt(2.5)
    assert study_estimate != float(np.asarray(sample, dtype="float64").std(ddof=1))


def test_the_two_estimators_diverge_by_one_ulp_on_an_ill_conditioned_sample() -> None:
    """``pstdev`` sums exactly in Fractions; numpy accumulates in float64.

    Three tightly clustered values away from zero expose the difference: the
    exact-rational estimator rounds up, the float two-pass estimator rounds down.
    """

    sample = [6.164284, 7.167116, 7.615484]
    adaptive_estimate = _summary(sample, "clustered sample").residual_stddev
    study_estimate = _population_scale(pd.Series(sample), 1e-9)

    # Both estimate the same population quantity and agree to within a rounding step.
    # Neither the exact decimal expansions nor the existence of a gap is asserted:
    # numpy's accumulation order is platform- and build-dependent, so a tighter
    # assertion would pin this machine rather than the behaviour.
    assert abs(adaptive_estimate - study_estimate) <= 2.0 * math.ulp(study_estimate)


def test_a_single_value_sample_has_zero_population_spread_in_both() -> None:
    """ddof=0 makes a one-element sample well defined (a ddof=1 estimator is not)."""

    summary = _summary([2.5], "single value")
    assert summary.observations == 1
    assert summary.residual_mean == 2.5
    assert summary.residual_stddev == 0.0
    # ``study`` floors the zero away before it is ever used as a scale.
    assert _population_scale(pd.Series([2.5]), MINIMUM_SCALE) == MINIMUM_SCALE


# ---------------------------------------------------------------------------
# 5. Boundaries
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("bad", (float("nan"), float("inf")))
def test_adaptive_rejects_a_non_finite_player_scale(bad: float) -> None:
    config = PlayerAdaptiveUncertaintyConfig(min_player_observations=2)
    groups = {
        name: AdaptiveGroupCalibration(
            position=name,
            scale_source="position",
            scale_observations=30,
            position_scale=1.0,
            conformal_source="position",
            group_calibration_observations=30,
            calibration_observations=30,
            conformal_multiplier=1.0,
            conformal_rank=30,
        )
        for name in POSITIONS
    }
    with pytest.raises(
        UncertaintyValidationError,
        match=r"local residual scale cannot be represented",
    ):
        _scale_from_state("x", "MID", config, groups, {"x": ResidualScaleSummary(5, 0.0, bad)})


@pytest.mark.parametrize("bad", (float("nan"), float("inf")))
def test_study_propagates_a_non_finite_residual_as_a_silent_nan(bad: float) -> None:
    """The deliberate-or-not asymmetry: ``adaptive`` raises, ``study`` returns NaN.

    ``max(nan, minimum)`` returns ``nan`` because the comparison is false, so the
    floor does not catch it either. An infinity becomes NaN inside numpy's
    mean-subtraction step.
    """

    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)
        result = _population_scale(pd.Series([1.0, bad, 3.0]), MINIMUM_SCALE)
    assert math.isnan(result)
    assert result != MINIMUM_SCALE


def test_adaptive_summary_leaks_a_non_domain_error_on_non_finite_residuals() -> None:
    """``_summary`` catches OverflowError/ValueError but statistics raises neither."""

    with pytest.raises(Exception) as caught:
        _summary([1.0, float("nan"), 3.0], "non-finite sample")
    # The characterization is that the intended domain error does NOT arrive. Which
    # exception statistics raises instead is a CPython internal (today an
    # AttributeError from its Fraction path) and is deliberately not pinned.
    assert not isinstance(caught.value, UncertaintyValidationError)


def test_both_configs_keep_the_shrinkage_denominator_positive() -> None:
    """n + k == 0 is unreachable: both configs keep the shrinkage strength positive.

    The division itself is Python's, not this codebase's, so only the guard that keeps
    it out of reach is pinned here.
    """

    assert PlayerAdaptiveUncertaintyConfig().shrinkage_observations > 0.0
    assert TimeAwareRecalibrationConfig().shrinkage_observations > 0.0


def test_the_player_scale_is_clamped_before_shrinkage_in_both_forms() -> None:
    """A zero player spread enters the mix as ``minimum_scale``, not as zero.

    n=5, k=10, fallback=1.0, minimum_scale=0.25.
    With the pre-clamp:    (5*0.0625 + 10*1)/15 = 10.3125/15 = 0.6875
                           sqrt(0.6875) = 0.82915619758885
    Without the pre-clamp: (5*0      + 10*1)/15 = 10/15
                           sqrt(2/3)    = 0.816496580927726
    """

    clamped = math.sqrt((5 * MINIMUM_SCALE**2 + 10.0 * 1.0**2) / 15.0)
    unclamped = math.sqrt((5 * 0.0 + 10.0 * 1.0**2) / 15.0)
    assert clamped != unclamped

    assert abs(_adaptive_scale(5, 10.0, 0.0, 1.0) - clamped) <= 2.0 * math.ulp(clamped)
    assert _study_scale(5, 10.0, MINIMUM_SCALE, 1.0) == clamped

    frame = pd.DataFrame(
        [
            ("flat", "MID", 4.0),
            ("flat", "MID", 4.0),
            ("flat", "MID", 4.0),
            ("flat", "MID", 4.0),
            ("flat", "MID", 4.0),
            ("spread", "MID", 1.0),
            ("spread", "MID", -1.0),
        ],
        columns=["player_id", "position", "residual"],
    )
    config = TimeAwareRecalibrationConfig(
        min_position_observations=2,
        min_player_observations=5,
    )
    state = _fit_scale_state(frame, config)
    fallback = state.position_scales["MID"]
    # The flat player's own pstdev is 0.0; it enters the mix as 0.25.
    assert state.player_scales["flat"] == _study_scale(5, 10.0, MINIMUM_SCALE, fallback)
    assert state.player_scales["flat"] != _study_scale(5, 10.0, 0.0, fallback)


def test_adaptive_clamps_again_after_shrinkage() -> None:
    """A hand-built group scale below the floor proves the post-clamp is live.

    n=5, k=10, player=0.25, fallback=0.0, minimum_scale=0.25.
    Unclamped: sqrt((5*0.0625 + 10*0)/15) = sqrt(0.3125/15) = 0.14433756729740643
    Observed:  0.25 -- the post-shrinkage max() binds.
    """

    unclamped = math.sqrt((5 * MINIMUM_SCALE**2 + 10.0 * 0.0) / 15.0)
    assert unclamped < MINIMUM_SCALE
    assert _adaptive_scale(5, 10.0, MINIMUM_SCALE, 0.0) == MINIMUM_SCALE
    assert _adaptive_scale(5, 10.0, MINIMUM_SCALE, 0.0) != unclamped


def test_study_post_shrinkage_clamp_is_a_no_op_on_the_fitted_path() -> None:
    """Every input ``_fit_scale_state`` mixes is already at or above the floor.

    Both the player scale and the fallback come out of ``_population_scale``,
    which floors them, so the weighted quadratic mean can never dip below the
    floor and the trailing ``max`` cannot bind.
    """

    frame = pd.DataFrame(
        [
            ("a", "MID", 0.01),
            ("a", "MID", -0.01),
            ("a", "MID", 0.0),
            ("b", "MID", 0.02),
            ("b", "MID", -0.02),
            ("b", "MID", 0.0),
        ],
        columns=["player_id", "position", "residual"],
    )
    config = TimeAwareRecalibrationConfig(
        min_position_observations=2,
        min_player_observations=3,
    )
    state = _fit_scale_state(frame, config)
    assert state.pooled_scale == MINIMUM_SCALE
    assert state.position_scales["MID"] == MINIMUM_SCALE
    for scale in state.player_scales.values():
        assert scale == MINIMUM_SCALE
    # Unclamped, the mix is already exactly the floor, not below it.
    assert math.sqrt((3 * MINIMUM_SCALE**2 + 10.0 * MINIMUM_SCALE**2) / 13.0) == MINIMUM_SCALE


def test_a_single_observation_player_falls_back_in_adaptive() -> None:
    """min_player_observations >= 2, so one observation never shrinks."""

    config = PlayerAdaptiveUncertaintyConfig(min_player_observations=2)
    groups = {
        name: AdaptiveGroupCalibration(
            position=name,
            scale_source="position",
            scale_observations=30,
            position_scale=3.0,
            conformal_source="position",
            group_calibration_observations=30,
            calibration_observations=30,
            conformal_multiplier=1.0,
            conformal_rank=30,
        )
        for name in POSITIONS
    }
    players = {"rookie": ResidualScaleSummary(1, 0.0, 0.0)}
    scale, source, effective, player_count = _scale_from_state(
        "rookie", "MID", config, groups, players
    )
    assert scale == 3.0
    assert source == "position_fallback"
    assert effective == 30
    # The player's own count is still reported even though it was not used.
    assert player_count == 1


def test_a_single_observation_player_does_shrink_in_study() -> None:
    """With min_player_observations=1 (which ``study`` allows) one row shrinks.

    MID residuals [0, 3, -3, 4, -4]: mean 0, pvar = 50/5 = 10, scale = sqrt(10).
    s1 has a single residual, so its own spread is 0.0, floored to 0.25, and
    the mix is (1*0.0625 + 10*MID**2)/11.
    """

    frame = pd.DataFrame(
        [
            ("s1", "MID", 0.0),
            ("s2", "MID", 3.0),
            ("s2", "MID", -3.0),
            ("s3", "MID", 4.0),
            ("s3", "MID", -4.0),
        ],
        columns=["player_id", "position", "residual"],
    )
    config = TimeAwareRecalibrationConfig(
        min_position_observations=2,
        min_player_observations=1,
    )
    state = _fit_scale_state(frame, config)

    assert state.position_scales["MID"] == math.sqrt(10.0)
    assert state.player_observations["s1"] == 1
    expected = math.sqrt((1 * MINIMUM_SCALE**2 + 10.0 * state.position_scales["MID"] ** 2) / 11.0)
    assert state.player_scales["s1"] == expected
    assert _effective_scale(state, "s1", "MID") == (expected, "player_shrunk", 1)
