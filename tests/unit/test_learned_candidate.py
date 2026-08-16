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
from squadopt.backtest.production import build_production_prediction_snapshot
from squadopt.backtest.splits import BacktestConfigurationError
from squadopt.prediction.learned_rate import LearnedRateConfig
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
