"""Tests for preparing evaluator-ready folds from a historical panel."""

import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from tests.fixtures.synthetic_gameweeks import (
    GAMEWEEK_COUNT,
    PREVIOUS_SEASON,
    SEASON,
    make_canonical_gameweeks,
    make_two_season_gameweeks,
)

from squadopt.backtest import (
    BacktestConfigurationError,
    DecisionPoint,
    baseline_projection_builder,
    build_walk_forward_fold,
    build_walk_forward_folds,
)
from squadopt.data import PROJECTION_REQUIRED_COLUMNS
from squadopt.evaluation import EvaluationFold

DECISION = DecisionPoint(season=SEASON, gameweek=6)


# --- fold shape -------------------------------------------------------------


def test_a_fold_carries_the_projection_contract_and_realized_outcomes() -> None:
    fold = build_walk_forward_fold(make_canonical_gameweeks(), DECISION)

    assert isinstance(fold, EvaluationFold)
    assert fold.fold_id == DECISION.fold_id
    assert list(fold.projections.columns) == list(PROJECTION_REQUIRED_COLUMNS)
    assert list(fold.realized_points.columns) == ["player_id", "total_points"]


def test_projections_and_realized_points_cover_the_same_players() -> None:
    fold = build_walk_forward_fold(make_canonical_gameweeks(), DECISION)

    assert set(fold.projections["player_id"]) == set(fold.realized_points["player_id"])


def test_fold_metadata_records_the_decision() -> None:
    fold = build_walk_forward_fold(make_canonical_gameweeks(), DECISION)

    assert fold.metadata["season"] == SEASON
    assert fold.metadata["gameweek"] == DECISION.gameweek
    assert fold.metadata["visible_rows"] > 0


def test_one_fold_per_decision_point_in_chronological_order() -> None:
    folds = build_walk_forward_folds(make_two_season_gameweeks())
    ids = [fold.fold_id for fold in folds]

    assert len(folds) == 2 * (GAMEWEEK_COUNT - 1)
    assert ids == sorted(ids)
    assert len(set(ids)) == len(ids)
    assert ids[0].startswith(PREVIOUS_SEASON)
    assert ids[-1].startswith(SEASON)


def test_restricting_seasons_produces_folds_for_those_seasons_only() -> None:
    folds = build_walk_forward_folds(make_two_season_gameweeks(), seasons=[SEASON])

    assert {str(fold.metadata["season"]) for fold in folds} == {SEASON}


# --- leakage --------------------------------------------------------------


def test_a_fold_is_unchanged_when_later_gameweeks_never_existed() -> None:
    """Fold-level truncation equivalence: the strongest statement available here."""

    panel = make_canonical_gameweeks()
    truncated = panel.loc[panel["gameweek"] <= DECISION.gameweek].reset_index(drop=True)

    from_full = build_walk_forward_fold(panel, DECISION)
    from_truncated = build_walk_forward_fold(truncated, DECISION)

    assert_frame_equal(from_truncated.projections, from_full.projections)
    assert_frame_equal(from_truncated.realized_points, from_full.realized_points)


@pytest.mark.parametrize("column", ["total_points", "minutes"])
def test_rewriting_later_outcomes_cannot_move_a_projection(column: str) -> None:
    panel = make_canonical_gameweeks()
    baseline = build_walk_forward_fold(panel, DECISION)

    mutated = panel.copy(deep=True)
    later = mutated["gameweek"] > DECISION.gameweek
    mutated.loc[later, column] = mutated.loc[later, column] + 500

    assert_frame_equal(build_walk_forward_fold(mutated, DECISION).projections, baseline.projections)


def test_rewriting_the_decision_gameweek_outcome_cannot_move_its_projection() -> None:
    """The canonical failure: scoring the decision with data that shaped it."""

    panel = make_canonical_gameweeks()
    baseline = build_walk_forward_fold(panel, DECISION)

    mutated = panel.copy(deep=True)
    at_decision = mutated["gameweek"] == DECISION.gameweek
    mutated.loc[at_decision, "total_points"] = 999

    rebuilt = build_walk_forward_fold(mutated, DECISION)

    assert_frame_equal(rebuilt.projections, baseline.projections)
    # ...but the realized side must follow the change, or nothing is being scored.
    assert (rebuilt.realized_points["total_points"] == 999).all()


def test_an_earlier_season_change_moves_only_folds_after_it() -> None:
    panel = make_two_season_gameweeks()
    baseline = {fold.fold_id: fold.projections for fold in build_walk_forward_folds(panel)}

    mutated = panel.copy(deep=True)
    mutated.loc[mutated["season"] == PREVIOUS_SEASON, "total_points"] = -50
    rebuilt = {fold.fold_id: fold.projections for fold in build_walk_forward_folds(mutated)}

    # The later season resets its rolling windows, so its folds are untouched.
    for fold_id, projections in rebuilt.items():
        if fold_id.startswith(SEASON):
            assert_frame_equal(projections, baseline[fold_id])


def test_folds_do_not_depend_on_input_row_order() -> None:
    panel = make_two_season_gameweeks()
    shuffled = panel.sort_values(["player_id", "gameweek"]).reset_index(drop=True)

    baseline = build_walk_forward_folds(panel)
    reordered = build_walk_forward_folds(shuffled)

    assert [fold.fold_id for fold in reordered] == [fold.fold_id for fold in baseline]
    for expected, actual in zip(baseline, reordered, strict=True):
        assert_frame_equal(actual.projections, expected.projections)


def test_the_input_panel_is_not_mutated() -> None:
    panel = make_two_season_gameweeks()
    original = panel.copy(deep=True)

    build_walk_forward_folds(panel)

    assert_frame_equal(panel, original)


def test_folds_are_deterministic() -> None:
    panel = make_canonical_gameweeks()

    first = build_walk_forward_folds(panel)
    second = build_walk_forward_folds(panel)

    for expected, actual in zip(first, second, strict=True):
        assert_frame_equal(actual.projections, expected.projections)
        assert_frame_equal(actual.realized_points, expected.realized_points)


# --- projection contract ----------------------------------------------------


def test_projections_satisfy_the_optimizer_validator() -> None:
    from squadopt import OptimizationConfig
    from squadopt.optimization.validation import validate_players

    for fold in build_walk_forward_folds(make_canonical_gameweeks()):
        validate_players(fold.projections, OptimizationConfig())


def test_projections_stay_finite_non_negative_and_integral_priced() -> None:
    for fold in build_walk_forward_folds(make_canonical_gameweeks()):
        assert fold.projections["expected_points"].notna().all()
        assert (fold.projections["expected_points"] >= 0).all()
        assert str(fold.projections["price_tenths"].dtype) == "int64"


def test_player_id_representation_is_consistent_across_folds() -> None:
    """The evaluator rejects representation drift rather than coercing identifiers."""

    folds = build_walk_forward_folds(make_two_season_gameweeks())
    kinds = {str(fold.projections["player_id"].dtype) for fold in folds}
    realized_kinds = {str(fold.realized_points["player_id"].dtype) for fold in folds}

    assert len(kinds) == 1
    assert kinds == realized_kinds


# --- injected projection builder --------------------------------------------


def test_a_custom_projection_builder_is_used() -> None:
    """Sprint 2 swaps in a fitted model without touching the splitting logic."""

    seen: list[tuple[int, int]] = []

    def flat_builder(visible: pd.DataFrame, decision: DecisionPoint) -> pd.DataFrame:
        seen.append((decision.gameweek, int(visible["gameweek"].max())))
        table = baseline_projection_builder(visible, decision)
        return table.assign(expected_points=1.0)

    folds = build_walk_forward_folds(make_canonical_gameweeks(), projection_builder=flat_builder)

    assert seen, "the custom builder was never called"
    assert all(fold.projections["expected_points"].eq(1.0).all() for fold in folds)


def test_the_builder_never_sees_rows_after_the_decision() -> None:
    """The guarantee is structural: later rows are absent from what it receives."""

    highest: list[int] = []

    def recording_builder(visible: pd.DataFrame, decision: DecisionPoint) -> pd.DataFrame:
        assert int(visible["gameweek"].max()) <= decision.gameweek
        highest.append(int(visible["gameweek"].max()))
        return baseline_projection_builder(visible, decision)

    build_walk_forward_folds(make_canonical_gameweeks(), projection_builder=recording_builder)

    assert highest == sorted(highest)


def test_a_builder_returning_something_other_than_a_frame_is_rejected() -> None:
    with pytest.raises(BacktestConfigurationError, match="must return a DataFrame"):
        build_walk_forward_fold(
            make_canonical_gameweeks(),
            DECISION,
            projection_builder=lambda visible, decision: None,  # type: ignore[arg-type,return-value]
        )


# --- guards -----------------------------------------------------------------


def test_a_panel_too_short_for_any_decision_is_reported() -> None:
    panel = make_canonical_gameweeks()
    one_gameweek = panel.loc[panel["gameweek"] == 1].reset_index(drop=True)

    with pytest.raises(BacktestConfigurationError, match="No decision points remain"):
        build_walk_forward_folds(one_gameweek)


def test_the_opening_gameweek_fold_can_be_requested_and_uses_the_price_prior() -> None:
    folds = build_walk_forward_folds(make_canonical_gameweeks(), min_prior_gameweeks_in_season=0)
    opening = next(fold for fold in folds if fold.metadata["gameweek"] == 1)

    assert opening.projections["expected_points"].nunique() > 1
