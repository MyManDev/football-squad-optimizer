"""Characterize the selected-XI downside diagnostic at its public experiment boundary."""

from dataclasses import replace
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from squadopt.experiments.downside_dependence import (
    INCONCLUSIVE,
    JOINT_UNDERREPRESENTED,
    MARGINAL_AND_JOINT_MISS,
    NO_JOINT_EVIDENCE,
    DownsideReading,
    classify,
    read_fold,
    summarise,
)
from squadopt.experiments.shadow_squad_calibration import (
    SquadFold,
    SquadShadowConfig,
    SquadShadowError,
)

_PLAYERS = tuple(range(1, 12))


def _projections() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "player_id": _PLAYERS,
            "name": [f"P{player}" for player in _PLAYERS],
            "team_id": [10, 10, 11, 11, 12, 13, 14, 15, 16, 17, 18],
            "position": [
                "GK",
                "DEF",
                "DEF",
                "DEF",
                "MID",
                "MID",
                "MID",
                "MID",
                "FWD",
                "FWD",
                "FWD",
            ],
            "price_tenths": [50] * 11,
            "expected_points": [5.0] * 11,
        }
    )


def _fold(realized: list[float] | None = None) -> SquadFold:
    values = [4.0] * 4 + [6.0] * 7 if realized is None else realized
    return SquadFold(
        fold_id="2023-24-gw10",
        season="2023-24",
        gameweek=10,
        projections=_projections(),
        realized_points=pd.DataFrame({"player_id": _PLAYERS, "total_points": values}),
        prior_fold_ids=tuple(f"2022-23-gw{week:02d}" for week in range(1, 10)),
    )


class _Decision:
    has_solution = True

    def __init__(self, starters: tuple[int, ...] = _PLAYERS) -> None:
        self.starting_xi = pd.DataFrame({"player_id": starters})
        self.selected_squad = self.starting_xi
        self.captain = {"player_id": starters[0]}


def _install(
    monkeypatch: pytest.MonkeyPatch,
    *,
    matrix: np.ndarray | None = None,
    decision: _Decision | None = None,
) -> np.ndarray:
    from squadopt.experiments import downside_dependence as module

    scenario_residuals = (
        np.asarray(
            [
                [-2.0] * 4 + [2.0] * 7,
                [-1.0, 1.0] * 5 + [-1.0],
                [1.0, -1.0] * 5 + [1.0],
                [2.0] * 7 + [-2.0] * 4,
            ],
            dtype="float64",
        )
        if matrix is None
        else matrix
    )
    points = scenario_residuals + 5.0
    snapshot = SimpleNamespace(table=_projections())
    scenarios = SimpleNamespace(
        scenario_points=pd.DataFrame(points, columns=_PLAYERS),
    )
    chosen = _Decision() if decision is None else decision

    def evaluate(decision: object, scenarios: object, config: object) -> object:
        raw = scenarios.scenario_points.to_numpy(dtype="float64").sum(axis=1)  # type: ignore[attr-defined]
        raw += scenarios.scenario_points[1].to_numpy(dtype="float64")  # type: ignore[attr-defined]
        scores = raw + config.location_shift_points  # type: ignore[attr-defined]
        return SimpleNamespace(scenario_scores=tuple(scores))

    monkeypatch.setattr(module, "optimize_squad_once", lambda *args: chosen)
    monkeypatch.setattr(module, "prepare_optimizer_projection", lambda *args: snapshot)
    monkeypatch.setattr(module, "generate_scenarios", lambda *args: scenarios)
    monkeypatch.setattr(module, "evaluate_fixed_decision", evaluate)
    monkeypatch.setattr(
        module,
        "score_realized_squad_points",
        lambda decision, frame: float(frame["total_points"].sum() + frame.iloc[0]["total_points"]),
    )
    return scenario_residuals


def test_read_fold_uses_one_fixed_xi_and_player_marginal_quartiles(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    residuals = _install(monkeypatch)
    reading = read_fold(
        _fold(),
        pd.DataFrame({"fold_id": []}),
        (),
        None,
        SquadShadowConfig(),
    )
    thresholds = np.quantile(residuals, 0.25, axis=0, method="linear")
    scenario_events = residuals < thresholds
    realized_events = (np.asarray([4.0] * 4 + [6.0] * 7) - 5.0) < thresholds

    assert reading.realized_downside_count == int(realized_events.sum())
    assert reading.expected_marginal_rate == pytest.approx(float(scenario_events.mean()))
    assert reading.realized_marginal_rate == pytest.approx(float(realized_events.mean()))
    assert reading.count_mid_pit == pytest.approx(
        float(
            (
                (scenario_events.sum(axis=1) < realized_events.sum()).sum()
                + 0.5 * (scenario_events.sum(axis=1) == realized_events.sum()).sum()
            )
            / len(scenario_events)
        )
    )


def test_read_fold_splits_same_team_and_different_team_pairs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install(monkeypatch)
    reading = read_fold(
        _fold([0.0] * 4 + [6.0] * 7),
        pd.DataFrame({"fold_id": []}),
        (),
        None,
        SquadShadowConfig(),
    )
    assert reading.realized_same_team_joint_rate is not None
    assert reading.expected_same_team_joint_rate is not None
    assert reading.realized_same_team_joint_rate == pytest.approx(1.0)
    assert reading.realized_joint_rate == pytest.approx(6 / 55)
    assert reading.realized_different_team_joint_rate == pytest.approx(4 / 53)


def test_threshold_comparison_is_strict(monkeypatch: pytest.MonkeyPatch) -> None:
    matrix = np.tile(np.asarray([-2.0, -1.0, 0.0, 1.0])[:, None], (1, 11))
    _install(monkeypatch, matrix=matrix)
    threshold = float(np.quantile(matrix[:, 0], 0.25, method="linear"))
    reading = read_fold(
        _fold([5.0 + threshold] * 11),
        pd.DataFrame({"fold_id": []}),
        (),
        None,
        SquadShadowConfig(),
    )
    assert reading.realized_downside_count == 0


@pytest.mark.parametrize(
    ("starters", "message"),
    [
        (tuple(range(1, 11)), "exactly eleven distinct"),
        ((1,) * 11, "exactly eleven distinct"),
    ],
)
def test_read_fold_refuses_an_invalid_xi(
    monkeypatch: pytest.MonkeyPatch, starters: tuple[int, ...], message: str
) -> None:
    _install(monkeypatch, decision=_Decision(starters))
    with pytest.raises(SquadShadowError, match=message):
        read_fold(_fold(), pd.DataFrame({"fold_id": []}), (), None, SquadShadowConfig())


def test_read_fold_refuses_a_missing_realized_starter(monkeypatch: pytest.MonkeyPatch) -> None:
    _install(monkeypatch)
    fold = _fold()
    missing = SquadFold(
        fold_id=fold.fold_id,
        season=fold.season,
        gameweek=fold.gameweek,
        projections=fold.projections,
        realized_points=fold.realized_points.iloc[:-1].copy(),
        prior_fold_ids=fold.prior_fold_ids,
    )
    with pytest.raises(SquadShadowError, match="cover each starter exactly once"):
        read_fold(missing, pd.DataFrame({"fold_id": []}), (), None, SquadShadowConfig())


def _reading(
    *,
    marginal_gap: float,
    joint_gap: float,
    same_gap: float | None = 0.0,
    season: str = "2023-24",
) -> DownsideReading:
    expected_marginal = 0.25
    expected_joint = 0.06
    expected_same = 0.08 if same_gap is not None else None
    return DownsideReading(
        fold_id=f"{season}-gw10",
        season=season,
        realized_marginal_rate=expected_marginal + marginal_gap,
        expected_marginal_rate=expected_marginal,
        realized_joint_rate=expected_joint + joint_gap,
        expected_joint_rate=expected_joint,
        realized_same_team_joint_rate=(
            expected_same + same_gap if expected_same is not None and same_gap is not None else None
        ),
        expected_same_team_joint_rate=expected_same,
        realized_different_team_joint_rate=0.05 + joint_gap,
        expected_different_team_joint_rate=0.05,
        realized_downside_count=3,
        count_mid_pit=0.6,
        count_above_q90=False,
        covariance_contribution=2.0,
        full_score_pit=0.5,
        full_score_below_q10=False,
    )


def _summary(marginal_interval: tuple[float, float], joint: tuple[float, float, float]) -> dict:
    return {
        "fold_count": 37,
        "marginal_downside_rate": {
            "gap": {
                "mean": 0.0,
                "bootstrap_low": marginal_interval[0],
                "bootstrap_high": marginal_interval[1],
            }
        },
        "all_pair_joint_downside_rate": {
            "gap": {"mean": joint[0], "bootstrap_low": joint[1], "bootstrap_high": joint[2]}
        },
    }


def test_classification_localizes_joint_dependence_only_when_marginals_cover_zero() -> None:
    summary = _summary((-0.01, 0.02), (0.04, 0.01, 0.07))
    assert classify(summary) == JOINT_UNDERREPRESENTED


def test_classification_keeps_a_marginal_miss_mixed() -> None:
    summary = _summary((0.02, 0.08), (0.05, 0.01, 0.09))
    assert classify(summary) == MARGINAL_AND_JOINT_MISS


def test_classification_reports_no_joint_evidence_when_interval_reaches_zero() -> None:
    summary = _summary((-0.01, 0.02), (0.01, -0.02, 0.04))
    assert classify(summary) == NO_JOINT_EVIDENCE


def test_classification_refuses_too_few_folds() -> None:
    summary = _summary((-0.01, 0.02), (0.04, 0.01, 0.07))
    summary["fold_count"] = 29
    assert classify(summary) == INCONCLUSIVE


def test_summary_keeps_missing_same_team_pairs_missing() -> None:
    readings = [_reading(marginal_gap=0.0, joint_gap=0.03, same_gap=None) for _ in range(30)]
    summary = summarise(readings)
    assert summary["same_team_joint_downside_gap"] is None
    assert summary["all_pair_joint_downside_rate"]["gap"]["mean"] == pytest.approx(0.03)  # type: ignore[index]


def test_control_replay_requires_the_recorded_full_score_values() -> None:
    from scripts.run_downside_dependence import _control_replay

    from squadopt.experiments.tail_diagnostic import RECORDED_MEAN_PIT

    readings = [
        replace(
            _reading(marginal_gap=0.0, joint_gap=0.0, season="2024-25"),
            fold_id=f"2024-25-gw{week:02d}",
            full_score_pit=RECORDED_MEAN_PIT,
            full_score_below_q10=week <= 8,
        )
        for week in range(1, 38)
    ]
    assert _control_replay(readings)["reproduced"] is True
    drifted = [
        replace(readings[0], full_score_pit=RECORDED_MEAN_PIT + 0.01),
        *readings[1:],
    ]
    assert _control_replay(drifted)["reproduced"] is False
