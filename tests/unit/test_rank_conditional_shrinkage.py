"""The rank-conditional shrinkage arithmetic, held to its pre-registration on synthetic rows.

The protocol (``docs/research/rank_conditional_shrinkage_prereg.md``) fixes the bucket edges,
the walk-forward fit, the non-negativity of every candidate projection and the eight-fold
history floor. Each is a test here, so a later edit to the arithmetic fails before it writes
a record.
"""

from __future__ import annotations

import pandas as pd
import pytest
from scripts.measure_rank_conditional_shrinkage import (
    ARM_A,
    ARM_B,
    CONTROL,
    _population,
    _residual_frame,
    prepare_arms,
)

from squadopt.evaluation import EvaluationFold
from squadopt.evaluation.component_handoff import PhaseCComponentHandoff
from squadopt.experiments.rank_conditional_shrinkage import (
    CONTRACT_VERSION,
    MIN_HISTORY_FOLDS,
    RANK_BUCKET_LABELS,
    RankShrinkageError,
    apply_position_shrinkage,
    apply_rank_debias,
    fit_position_shrinkage,
    fit_rank_debias,
    history_rows,
    projection_ranks,
    rank_bucket,
    realized_points,
    target_folds,
)


def _fold_id(index: int) -> str:
    return f"2021-22-gw{index + 2:02d}"


def _frame(folds: int, players: int = 130, *, bias: float = 0.0) -> pd.DataFrame:
    """Synthetic residual rows: projected falls with player id, realized is projected plus a
    rank-dependent shortfall (the winner's curse) plus ``bias``."""

    rows: list[dict[str, object]] = []
    for fold in range(folds):
        for player in range(players):
            projected = 10.0 - player * 0.05 + (fold % 3) * 0.01
            rank = player + 1
            shortfall = 3.0 if rank <= 5 else 2.0 if rank <= 15 else 0.0
            rows.append(
                {
                    "fold_id": _fold_id(fold),
                    "player_id": player + 1,
                    "position": ("GK", "DEF", "MID", "FWD")[player % 4],
                    "projected": projected,
                    "realized": projected - shortfall + bias,
                }
            )
    return pd.DataFrame(rows)


def test_the_contract_version_is_the_registered_one() -> None:
    assert CONTRACT_VERSION == "rank_conditional_shrinkage_v1"
    assert MIN_HISTORY_FOLDS == 8


@pytest.mark.parametrize(
    ("rank", "label"),
    [
        (1, "rank_001_005"),
        (5, "rank_001_005"),
        (6, "rank_006_015"),
        (15, "rank_006_015"),
        (16, "rank_016_030"),
        (30, "rank_016_030"),
        (31, "rank_031_060"),
        (60, "rank_031_060"),
        (61, "rank_061_120"),
        (120, "rank_061_120"),
        (121, "rank_121_plus"),
        (700, "rank_121_plus"),
    ],
)
def test_bucket_assignment_at_the_edges(rank: int, label: str) -> None:
    assert rank_bucket(rank) == label
    assert label in RANK_BUCKET_LABELS


def test_a_rank_below_one_is_refused() -> None:
    with pytest.raises(RankShrinkageError):
        rank_bucket(0)


def test_ranks_run_within_a_fold_and_break_ties_by_player_id() -> None:
    frame = pd.DataFrame(
        {
            "fold_id": ["f", "f", "f", "g"],
            "player_id": [30, 10, 20, 5],
            "position": ["MID", "MID", "FWD", "GK"],
            "projected": [4.0, 4.0, 7.0, 1.0],
            "realized": [0.0, 0.0, 0.0, 0.0],
        }
    )
    assert projection_ranks(frame).tolist() == [3, 2, 1, 1]


def test_realized_points_are_zero_on_a_blank() -> None:
    realized = realized_points(pd.Series([1, 0, 1]), pd.Series([7.0, None, 2.0]))
    assert realized.tolist() == [7.0, 0.0, 2.0]
    with pytest.raises(RankShrinkageError):
        realized_points(pd.Series([1, 1]), pd.Series([7.0, None]))


def test_target_folds_split_after_eight_folds_of_history() -> None:
    fold_ids = [_fold_id(index) for index in range(12)]
    burn_in, targets = target_folds(reversed(fold_ids))
    assert burn_in == tuple(fold_ids[:8])
    assert targets == tuple(fold_ids[8:])
    assert history_rows(_frame(12), targets[0])["fold_id"].nunique() == 8


def test_the_fit_refuses_fewer_than_eight_history_folds() -> None:
    with pytest.raises(RankShrinkageError, match="at least 8 history folds"):
        fit_rank_debias(_frame(7))
    with pytest.raises(RankShrinkageError, match="at least 8 history folds"):
        fit_position_shrinkage(_frame(7))


def test_the_runner_population_refuses_fewer_than_eight_history_folds() -> None:
    with pytest.raises(RankShrinkageError, match="No fold has"):
        _population([_fold_id(index) for index in range(8)], requested=None)
    burn_in, targets = _population([_fold_id(index) for index in range(9)], requested=None)
    assert len(burn_in) == 8 and targets == (_fold_id(8),)
    with pytest.raises(RankShrinkageError, match="burn-in"):
        _population([_fold_id(index) for index in range(9)], requested=(_fold_id(0),))


def test_rank_debias_recovers_the_bucket_shortfalls() -> None:
    table = fit_rank_debias(_frame(8))
    assert table.history_folds == 8
    assert table.corrections["rank_001_005"] == pytest.approx(-3.0)
    assert table.corrections["rank_006_015"] == pytest.approx(-2.0)
    assert table.corrections["rank_016_030"] == pytest.approx(0.0)
    assert table.corrections["rank_121_plus"] == pytest.approx(0.0)
    assert table.rows_per_bucket["rank_001_005"] == 40
    assert table.rows_per_bucket["rank_121_plus"] == 80


def test_the_fit_reads_history_rows_only() -> None:
    frame = _frame(9)
    target = _fold_id(8)
    history = history_rows(frame, target)
    reference = fit_rank_debias(history)
    poisoned = frame.copy()
    poisoned.loc[poisoned["fold_id"] == target, "realized"] = 1.0e6
    assert fit_rank_debias(history_rows(poisoned, target)) == reference
    assert fit_position_shrinkage(history_rows(poisoned, target)) == fit_position_shrinkage(history)


def test_apply_rank_debias_is_non_negative_and_moves_only_the_ranked_buckets() -> None:
    frame = _frame(9)
    target = _fold_id(8)
    table = fit_rank_debias(history_rows(frame, target))
    fold = frame.loc[frame["fold_id"] == target]
    adjusted = apply_rank_debias(fold, table)
    assert adjusted.index.equals(fold.index)
    assert bool((adjusted >= 0.0).all())
    ranks = projection_ranks(fold)
    top = adjusted[ranks <= 5] - fold.loc[ranks <= 5, "projected"]
    tail = adjusted[ranks > 15] - fold.loc[ranks > 15, "projected"]
    assert top.tolist() == pytest.approx([-3.0] * 5)
    assert tail.tolist() == pytest.approx([0.0] * int((ranks > 15).sum()))


def test_a_negative_projection_is_floored_at_zero() -> None:
    frame = _frame(9)
    target = _fold_id(8)
    fold = frame.loc[frame["fold_id"] == target].copy()
    fold.loc[fold.index[:5], "projected"] = [0.5, 0.4, 0.3, 0.2, 0.1]
    fold["projected"] = fold["projected"].astype("float64")
    table = fit_rank_debias(history_rows(frame, target))
    assert bool((apply_rank_debias(fold, table) >= 0.0).all())


def test_position_shrinkage_recovers_a_constructed_slope() -> None:
    frame = _frame(8)
    frame["realized"] = 1.0 + 0.6 * frame["projected"]
    table = fit_position_shrinkage(frame)
    for position in ("GK", "DEF", "MID", "FWD"):
        assert table.slopes[position] == pytest.approx(0.6)
        assert table.intercepts[position] == pytest.approx(1.0)
    fold = frame.loc[frame["fold_id"] == _fold_id(0)]
    adjusted = apply_position_shrinkage(fold, table)
    means = fold.groupby("position")["projected"].transform("mean")
    expected = (means + 0.6 * (fold["projected"] - means)).clip(lower=0.0)
    assert adjusted.tolist() == pytest.approx(expected.tolist())


def test_position_shrinkage_leaves_a_flat_position_unchanged() -> None:
    frame = _frame(8)
    frame.loc[frame["position"] == "GK", "projected"] = 2.0
    table = fit_position_shrinkage(frame)
    assert table.slopes["GK"] == 1.0


def test_apply_refuses_more_than_one_fold() -> None:
    frame = _frame(9)
    table = fit_rank_debias(history_rows(frame, _fold_id(8)))
    with pytest.raises(RankShrinkageError, match="exactly one fold"):
        apply_rank_debias(frame, table)


def test_the_residual_frame_composes_from_projection_and_handoff_rows() -> None:
    projections = pd.DataFrame(
        {
            "player_id": [1, 2, 3],
            "position": ["GK", "DEF", "MID"],
            "expected_points": [3.0, 5.5, 1.0],
        }
    )
    rows = pd.DataFrame(
        {
            "fold_id": ["2021-22-gw10"] * 3,
            "player_id": [3, 1, 2],
            "appearance_target": [0, 1, 1],
            "points_target": [None, 2.0, 9.0],
        }
    )
    frame = _residual_frame("2021-22-gw10", projections, rows)
    assert list(frame.columns) == ["fold_id", "player_id", "position", "projected", "realized"]
    by_player = frame.set_index("player_id")
    assert by_player.loc[1, "realized"] == 2.0
    assert by_player.loc[2, "projected"] == 5.5
    assert by_player.loc[3, "realized"] == 0.0


def test_prepare_arms_changes_only_the_expected_points_column() -> None:
    """The three arms share roster, prices, positions and outcomes; Arm A carries the fitted
    debias and Arm B the fitted shrinkage, computed from the folds before each target."""

    residuals = _frame(9, players=40)
    rows = pd.DataFrame(
        {
            "fold_id": residuals["fold_id"],
            "player_id": residuals["player_id"],
            "appearance_target": 1,
            "points_target": residuals["realized"],
        }
    )
    handoff = PhaseCComponentHandoff(
        rows=rows,
        roster=pd.DataFrame(),
        table_sha256="a" * 64,
        roster_sha256="b" * 64,
        manifest_sha256="c" * 64,
        repository_commit="d" * 40,
        model_version="phase_c_control_components_gbm_v1",
        feature_contract_version="features-v1",
        target_contract_version="targets-v1",
        dataset_contract_version="dataset-v1",
    )
    folds = []
    for fold_id, part in residuals.groupby("fold_id", sort=True):
        projections = pd.DataFrame(
            {
                "player_id": part["player_id"].to_numpy(),
                "name": [f"p{value}" for value in part["player_id"]],
                "team_id": 1,
                "position": part["position"].to_numpy(),
                "price_tenths": 50,
                "expected_points": part["projected"].to_numpy(),
            }
        )
        realized = pd.DataFrame(
            {
                "player_id": part["player_id"].to_numpy(),
                "total_points": part["realized"].to_numpy(),
                "minutes": 90,
            }
        )
        folds.append(
            EvaluationFold(fold_id=str(fold_id), projections=projections, realized_points=realized)
        )
    target = _fold_id(8)
    arms = prepare_arms(handoff, folds, (target,))
    control = arms.folds[CONTROL][0].projections
    debiased = arms.folds[ARM_A][0].projections
    shrunk = arms.folds[ARM_B][0].projections
    for frame in (debiased, shrunk):
        assert frame["player_id"].tolist() == control["player_id"].tolist()
        for column in ("name", "team_id", "position", "price_tenths"):
            assert frame[column].tolist() == control[column].tolist()
    table = arms.debias_tables[target]
    assert table.history_folds == 8
    fold_rows = residuals.loc[residuals["fold_id"] == target]
    expected = apply_rank_debias(fold_rows, table)
    assert debiased["expected_points"].tolist() == pytest.approx(expected.tolist())
    assert debiased["expected_points"].iloc[0] == pytest.approx(
        control["expected_points"].iloc[0] - 3.0
    )
    expected_b = apply_position_shrinkage(fold_rows, arms.shrinkage_tables[target])
    assert shrunk["expected_points"].tolist() == pytest.approx(expected_b.tolist())
