"""Prepared-fold evaluation over the synthetic Sprint 0 pipeline."""

from tests.fixtures.synthetic_gameweeks import SEASON, make_canonical_gameweeks

from squadopt import EvaluationConfig, EvaluationFold, evaluate_prepared_folds
from squadopt.features import build_feature_dataset
from squadopt.prediction import build_projection_table


def test_synthetic_projections_can_be_evaluated_against_later_outcomes() -> None:
    canonical = make_canonical_gameweeks()
    features = build_feature_dataset(canonical)
    folds: list[EvaluationFold] = []
    for gameweek in (3, 4):
        projections = build_projection_table(features, season=SEASON, gameweek=gameweek)
        outcomes = canonical.loc[
            (canonical["season"] == SEASON) & (canonical["gameweek"] == gameweek),
            ["player_id", "total_points"],
        ].reset_index(drop=True)
        folds.append(
            EvaluationFold(
                fold_id=f"{SEASON}-GW{gameweek:02d}",
                projections=projections,
                realized_points=outcomes,
                metadata={"season": SEASON, "gameweek": gameweek},
            )
        )

    result = evaluate_prepared_folds(
        folds,
        EvaluationConfig(run_metadata={"dataset_version": "synthetic-panel-v1"}),
    )

    assert result.summary.attempted_folds == 2
    assert result.summary.feasible_folds == 2
    assert result.summary.scored_folds == 2
    assert result.summary.feasibility_rate == 1.0
    assert result.summary.turnover_observations == 1
    assert result.summary.mean_realized_squad_points is not None
    assert result.folds[0].metadata == {"season": SEASON, "gameweek": 3}

    for fold in result.folds:
        optimization_result = fold.optimization_result
        assert optimization_result.captain is not None
        gameweek = int(fold.metadata["gameweek"])
        points = canonical.loc[
            (canonical["season"] == SEASON) & (canonical["gameweek"] == gameweek)
        ].set_index("player_id")["total_points"]
        expected = sum(points.loc[optimization_result.starting_xi["player_id"]])
        expected += points.loc[optimization_result.captain["player_id"]]
        assert fold.realized_squad_points == float(expected)
