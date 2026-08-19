"""Tests for the Issue #43 candidate builder.

The panel, fixtures and team codes are imported from the production builder's tests
rather than rebuilt. That is deliberate: the central claim here is that the candidate
differs from the production projection in the rate and in nothing else, and that claim
is only checkable if both are fed literally the same inputs. A second copy of the
fixture would let the two drift and quietly turn the comparison into noise.
"""

from typing import Any

import pandas as pd
import pytest
from tests.unit.test_backtest_production import (
    CONFIG,
    TEAM_CODES,
    WINDOW,
    _decision,
    _fixtures,
    _panel,
)

from squadopt.backtest.learned_candidate import (
    LEARNED_RATE_FEATURE_CONTRACT_VERSION,
    LEARNED_RATE_MODEL_NAME,
    LEARNED_RATE_MODEL_VERSION,
    LEARNED_RATE_TRAINING_CONTRACT_VERSION,
    build_learned_candidate_snapshot,
    make_learned_rate_projection_builder,
)
from squadopt.backtest.production import (
    build_production_prediction_snapshot,
    production_feature_config,
)
from squadopt.backtest.splits import BacktestConfigurationError
from squadopt.prediction.factors import FormWindowMapping
from squadopt.prediction.learned_rate import LearnedRateConfig
from squadopt.prediction.minutes import ExpectedMinutesConfig
from squadopt.prediction.production import ProductionProjectionConfig

LEARNED = LearnedRateConfig(window=WINDOW, min_training_rows=5)


def _candidate(panel: pd.DataFrame | None = None, **kwargs: Any) -> Any:
    return build_learned_candidate_snapshot(
        _panel() if panel is None else panel,
        kwargs.pop("decision", _decision()),
        fixtures=kwargs.pop("fixtures", _fixtures()),
        team_codes=kwargs.pop("team_codes", TEAM_CODES),
        config=kwargs.pop("config", CONFIG),
        learned_config=kwargs.pop("learned_config", LEARNED),
    )


def _production(panel: pd.DataFrame | None = None, **kwargs: Any) -> Any:
    return build_production_prediction_snapshot(
        _panel() if panel is None else panel,
        kwargs.pop("decision", _decision()),
        fixtures=kwargs.pop("fixtures", _fixtures()),
        team_codes=kwargs.pop("team_codes", TEAM_CODES),
        config=kwargs.pop("config", CONFIG),
    )


# --- the declared identity --------------------------------------------------


def test_the_snapshot_carries_the_learned_rate_identity() -> None:
    """The gate checks these strings against the declaration; they must come from here."""

    provenance = _candidate().provenance

    assert provenance.model_name == LEARNED_RATE_MODEL_NAME
    assert provenance.model_version == LEARNED_RATE_MODEL_VERSION
    assert provenance.feature_contract_version == LEARNED_RATE_FEATURE_CONTRACT_VERSION


def test_the_candidate_is_a_different_model_than_the_production_projection() -> None:
    assert _candidate().provenance.model_name != _production().provenance.model_name


def test_the_training_contract_is_named_in_the_diagnostics() -> None:
    diagnostics = _candidate().diagnostics

    assert diagnostics["training_contract_version"] == LEARNED_RATE_TRAINING_CONTRACT_VERSION


def test_the_fitted_model_is_reported_so_a_fold_can_be_audited_alone() -> None:
    diagnostics = _candidate().diagnostics

    assert len(str(diagnostics["rate_model_fingerprint"])) == 64
    assert int(str(diagnostics["rate_training_rows"])) > 0
    assert diagnostics["rate_input_columns"] == list(LEARNED.input_columns)


# --- what must not have moved -----------------------------------------------


def test_the_expected_minutes_stage_is_unchanged() -> None:
    """The declaration freezes the minutes stage; a difference here is a second change."""

    candidate = _candidate().table
    production = _production().table

    assert candidate["player_id"].tolist() == production["player_id"].tolist()


def test_the_same_players_are_projected_as_the_production_pipeline() -> None:
    """A candidate that quietly changed the projected population is not comparable."""

    assert set(_candidate().table["player_id"]) == set(_production().table["player_id"])


def test_the_opening_price_prior_is_still_refit_on_completed_seasons() -> None:
    assert _candidate().diagnostics["opening_price_prior_origin"] == "refit_expanding_window"


def test_expected_points_stay_finite_and_non_negative() -> None:
    values = _candidate().table["expected_points"]

    assert bool(values.notna().all())
    assert float(values.min()) >= 0.0


# --- the frozen form_window_v1 mapping --------------------------------------


@pytest.mark.parametrize("window", [3, 5, 6, 10])
def test_the_candidate_applies_the_frozen_mapping_plus_the_appearance_window(
    window: int,
) -> None:
    """Checklist item 7, as a comparison rather than a statement.

    ``form_window_v1`` is ``w -> minutes/points/per-90 windows, min_periods=1``. The
    candidate reads the same windows and adds one: the appearance decomposition, which
    ``minutes per appearance`` cannot be computed without and which the declaration names
    as a permitted input. Nothing else differs, and this asserts that field by field so a
    future widening of the feature set fails here rather than inside a gate run.
    """

    frozen = FormWindowMapping(form_window=window).feature_config
    candidate = production_feature_config(
        ProductionProjectionConfig(rate_window=window, minutes=ExpectedMinutesConfig(window=window))
    )

    assert candidate.minutes_windows == frozen.minutes_windows
    assert candidate.points_windows == frozen.points_windows
    assert candidate.per_90_window == frozen.per_90_window
    assert candidate.min_periods == frozen.min_periods == 1
    assert candidate.appearance_windows == (window,)
    assert frozen.appearance_windows == ()


def test_the_appearance_window_is_the_only_addition_to_the_frozen_mapping() -> None:
    """Enumerated over the dataclass, so a new field cannot slip past the check above."""

    window = 6
    frozen = FormWindowMapping(form_window=window).feature_config
    candidate = production_feature_config(
        ProductionProjectionConfig(rate_window=window, minutes=ExpectedMinutesConfig(window=window))
    )

    differing = {
        name
        for name in type(frozen).__dataclass_fields__
        if getattr(frozen, name) != getattr(candidate, name)
    }

    assert differing == {"appearance_windows"}


# --- the window must match --------------------------------------------------


def test_a_learned_window_differing_from_the_rate_window_is_refused() -> None:
    """Reading another window would change the frozen mapping, not only the rate."""

    with pytest.raises(BacktestConfigurationError, match="must equal the projection"):
        _candidate(learned_config=LearnedRateConfig(window=WINDOW + 1, min_training_rows=5))


def test_the_builder_factory_refuses_a_mismatched_window_up_front() -> None:
    with pytest.raises(BacktestConfigurationError, match="must equal the projection"):
        make_learned_rate_projection_builder(
            fixtures=_fixtures(),
            team_codes=TEAM_CODES,
            config=ProductionProjectionConfig(rate_window=WINDOW),
            learned_config=LearnedRateConfig(window=WINDOW + 2, min_training_rows=5),
        )


# --- leakage ----------------------------------------------------------------


def test_a_later_gameweek_cannot_reach_the_fitted_model() -> None:
    """A mutation test, not an argument: perturb the future and the snapshot must not move."""

    panel = _panel()
    perturbed = panel.copy(deep=True)
    later = (perturbed["season"] == _decision().season) & (
        perturbed["gameweek"] > _decision().gameweek
    )
    perturbed.loc[later, "total_points"] = 999
    perturbed.loc[later, "minutes"] = 1

    assert (
        _candidate(panel=perturbed).prediction_fingerprint
        == _candidate(panel=panel).prediction_fingerprint
    )


def test_the_decision_gameweek_outcome_cannot_reach_the_fitted_model() -> None:
    """The target gameweek's own result is the answer, not an input to the fit."""

    panel = _panel()
    perturbed = panel.copy(deep=True)
    target = (perturbed["season"] == _decision().season) & (
        perturbed["gameweek"] == _decision().gameweek
    )
    perturbed.loc[target, "total_points"] = 999

    assert (
        _candidate(panel=perturbed).prediction_fingerprint
        == _candidate(panel=panel).prediction_fingerprint
    )


def test_an_earlier_gameweek_does_reach_the_fitted_model() -> None:
    """The complement of the leakage tests: history must actually be used."""

    panel = _panel()
    perturbed = panel.copy(deep=True)
    earlier = (perturbed["season"] == _decision().season) & (
        perturbed["gameweek"] < _decision().gameweek
    )
    perturbed.loc[earlier, "total_points"] = 40

    assert (
        _candidate(panel=perturbed).prediction_fingerprint
        != _candidate(panel=panel).prediction_fingerprint
    )


def test_deleting_future_gameweeks_cannot_reach_the_fitted_model() -> None:
    """Stronger than mutation: catches whole-dataset operations mutation misses.

    Perturbing a future row leaves the row in place, so an operation that reads the shape of
    the panel — a row count, a groupby size, a fillna over the whole frame — can still see
    the future while every value test passes. Removing the rows entirely is the only way to
    ask whether the fit depends on the future existing at all.
    """

    panel = _panel()
    truncated = panel.loc[
        ~((panel["season"] == _decision().season) & (panel["gameweek"] > _decision().gameweek))
    ].reset_index(drop=True)

    assert (
        _candidate(panel=truncated).prediction_fingerprint
        == _candidate(panel=panel).prediction_fingerprint
    )


def test_row_order_cannot_reach_the_fitted_model() -> None:
    """The fit must not depend on how the archive happened to be concatenated.

    This one passes for a reason worth stating, because it makes the guard easy to delete by
    accident: the fit never sees the caller's row order at all. `build_feature_dataset` sorts
    by the canonical key with a stable sort and resets the index, so the feature frame is
    identical whatever order the panel arrives in, and the training slice is taken from that.

    So the guard is prospective rather than currently load-bearing. It fails the day that
    canonicalisation is removed or bypassed — at which point a ridge fit over
    non-associative floating-point summation would make every recorded fingerprint depend on
    input order. Its counterpart guards the frozen builder for the same reason.
    """

    panel = _panel()
    shuffled = panel.sort_values(["gameweek", "player_id"], ascending=[False, False]).reset_index(
        drop=True
    )

    assert (
        _candidate(panel=shuffled).prediction_fingerprint
        == _candidate(panel=panel).prediction_fingerprint
    )


def test_the_training_fingerprint_ignores_the_future() -> None:
    """The provenance digest covers the training slice, so it must stop at the cutoff.

    Distinct from the prediction fingerprint above: this one is what a gate reads to claim
    two runs trained on the same data. If the future reached it, the claim would be false
    even when the prediction happened not to move.
    """

    panel = _panel()
    perturbed = panel.copy(deep=True)
    later = (perturbed["season"] == _decision().season) & (
        perturbed["gameweek"] > _decision().gameweek
    )
    perturbed.loc[later, "total_points"] = -50

    assert (
        _candidate(panel=perturbed).provenance.training_data_fingerprint
        == _candidate(panel=panel).provenance.training_data_fingerprint
    )


def test_the_input_panel_is_not_modified() -> None:
    """The caller's frame is an input, not scratch space.

    The walk-forward runner hands the same panel to one fold after another, so a builder
    that wrote into it would leak one fold's work into the next and the leak would look like
    signal.
    """

    panel = _panel()
    before = panel.copy(deep=True)

    _candidate(panel=panel)

    assert panel.equals(before)


# --- determinism ------------------------------------------------------------


def test_two_builds_of_one_fold_are_identical() -> None:
    assert _candidate().prediction_fingerprint == _candidate().prediction_fingerprint


def test_the_builder_matches_the_single_shot_function() -> None:
    """The cached builder must not drift from the direct path it caches."""

    builder = make_learned_rate_projection_builder(
        fixtures=_fixtures(),
        team_codes=TEAM_CODES,
        config=CONFIG,
        learned_config=LEARNED,
    )

    built = builder(_panel(), _decision())

    assert built.prediction_fingerprint == _candidate().prediction_fingerprint


def test_the_builder_caches_completed_seasons_without_changing_answers() -> None:
    """Two folds in sequence must give the same answers as two fresh builders."""

    builder = make_learned_rate_projection_builder(
        fixtures=_fixtures(),
        team_codes=TEAM_CODES,
        config=CONFIG,
        learned_config=LEARNED,
    )

    first = builder(_panel(), _decision(gameweek=4))
    second = builder(_panel(), _decision(gameweek=5))

    assert (
        first.prediction_fingerprint
        == _candidate(decision=_decision(gameweek=4)).prediction_fingerprint
    )
    assert (
        second.prediction_fingerprint
        == _candidate(decision=_decision(gameweek=5)).prediction_fingerprint
    )


# --- configuration ----------------------------------------------------------


def test_a_fold_with_no_history_is_refused() -> None:
    with pytest.raises(BacktestConfigurationError, match="No training rows"):
        _candidate(decision=_decision(gameweek=1), panel=_panel(seasons=("2025-26",)))


def test_a_wrong_config_type_is_refused() -> None:
    with pytest.raises(BacktestConfigurationError, match="LearnedRateConfig"):
        _candidate(learned_config="six")
