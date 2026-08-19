"""Tests for the scenario calibration audit.

The audit's job is honest bookkeeping: the frozen decision must never depend on the
scenarios it is measured against, PIT and coverage must come from the recorded
distributions, and the fold population must be exactly the objective's own.
"""

import json
from dataclasses import asdict

import pandas as pd
import pytest
from tests.fixtures.synthetic_gameweeks import SEASON, make_canonical_gameweeks

from squadopt.experiments import (
    ExperimentExecutionError,
    ScenarioAuditResult,
    ScenarioPolicyObjective,
    ScenarioPolicyObjectiveConfig,
    audit_scenario_calibration,
)

CONFIG = ScenarioPolicyObjectiveConfig(
    development_seasons=(SEASON,),
    scenario_count=32,
    min_history_folds=3,
    min_player_observations=2,
)

HISTORY_GAMEWEEKS = (2, 3, 4, 5, 6)


def _history() -> pd.DataFrame:
    panel = make_canonical_gameweeks()
    rows: list[dict[str, object]] = []
    for gameweek in HISTORY_GAMEWEEKS:
        week = panel.loc[panel["gameweek"] == gameweek]
        for row in week.itertuples(index=False):
            predicted = 2.5 + (int(row.player_id) % 4) * 0.5
            rows.append(
                {
                    "fold_id": f"{SEASON}-gw{gameweek:02d}",
                    "season": SEASON,
                    "gameweek": gameweek,
                    "player_id": int(row.player_id),
                    "team_id": int(row.team_id),
                    "position": str(row.position),
                    "predicted_points": predicted,
                    "realized_points": float(row.total_points),
                    "residual": float(row.total_points) - predicted,
                }
            )
    return pd.DataFrame(rows)


def _objective() -> ScenarioPolicyObjective:
    return ScenarioPolicyObjective(make_canonical_gameweeks(), _history(), CONFIG)


@pytest.fixture(scope="module")
def audit() -> ScenarioAuditResult:
    return audit_scenario_calibration(
        _objective(),
        _history(),
        form_window=5,
        bench_weight=0.1,
        points_threshold=30.0,
    )


def test_the_audit_covers_exactly_the_objectives_folds(audit: ScenarioAuditResult) -> None:
    objective = _objective()

    assert tuple(row.fold_id for row in audit.rows) == objective.development_fold_ids
    assert audit.diagnostics["fold_count"] == 4


def test_pit_and_rates_are_probabilities(audit: ScenarioAuditResult) -> None:
    for row in audit.rows:
        assert 0.0 <= row.probability_integral_transform <= 1.0
    assert 0.0 <= audit.mean_pit <= 1.0
    assert 0.0 <= audit.realized_below_scenario_quantile_rate <= 1.0
    assert 0.0 <= audit.predicted_bad_week_probability <= 1.0
    assert 0.0 <= audit.realized_bad_week_frequency <= 1.0


def test_player_coverage_is_reported_per_position(audit: ScenarioAuditResult) -> None:
    assert set(audit.player_interval_coverage) <= {"GK", "DEF", "MID", "FWD"}
    assert audit.player_interval_coverage
    for coverage in audit.player_interval_coverage.values():
        assert 0.0 <= coverage <= 1.0


def test_the_audit_is_deterministic(audit: ScenarioAuditResult) -> None:
    repeat = audit_scenario_calibration(
        _objective(),
        _history(),
        form_window=5,
        bench_weight=0.1,
        points_threshold=30.0,
    )

    assert [
        (row.fold_id, row.realized_score, row.probability_integral_transform) for row in repeat.rows
    ] == [
        (row.fold_id, row.realized_score, row.probability_integral_transform) for row in audit.rows
    ]
    assert repeat.mean_pit == audit.mean_pit


def test_an_out_of_range_quantile_is_refused() -> None:
    with pytest.raises(ExperimentExecutionError, match="lower_quantile"):
        audit_scenario_calibration(
            _objective(),
            _history(),
            form_window=5,
            bench_weight=0.1,
            lower_quantile=1.5,
        )


def test_a_non_objective_input_is_refused() -> None:
    with pytest.raises(ExperimentExecutionError, match="ScenarioPolicyObjective"):
        audit_scenario_calibration(
            "not an objective",  # type: ignore[arg-type]
            _history(),
            form_window=5,
            bench_weight=0.1,
        )


def test_a_development_shift_moves_every_fold_by_the_same_amount(
    audit: ScenarioAuditResult,
) -> None:
    shifted = audit_scenario_calibration(
        _objective(),
        _history(),
        form_window=5,
        bench_weight=0.1,
        points_threshold=30.0,
        selection_shift="development",
        development_shift_points=-10.0,
    )
    assert all(row.location_shift_points == -10.0 for row in shifted.rows)
    for plain, moved in zip(audit.rows, shifted.rows, strict=True):
        assert moved.scenario_mean_score == pytest.approx(plain.scenario_mean_score - 10.0)
        assert moved.realized_score == plain.realized_score
    assert shifted.mean_score_bias == pytest.approx(audit.mean_score_bias - 10.0)
    assert shifted.diagnostics["selection_shift"] == "development"


def test_a_dispersion_correction_scales_each_fold_around_its_centre(
    audit: ScenarioAuditResult,
) -> None:
    fixed = audit_scenario_calibration(
        _objective(),
        _history(),
        form_window=5,
        bench_weight=0.1,
        points_threshold=30.0,
        dispersion="development",
        development_dispersion_scale=2.0,
    )
    assert all(row.dispersion_scale == 2.0 for row in fixed.rows)
    for plain, wide in zip(audit.rows, fixed.rows, strict=True):
        assert wide.scenario_mean_score == pytest.approx(plain.scenario_mean_score)
        assert wide.scenario_lower_quantile_score == pytest.approx(
            plain.scenario_mean_score
            + 2.0 * (plain.scenario_lower_quantile_score - plain.scenario_mean_score)
        )
    assert fixed.diagnostics["dispersion"] == "development"
    assert fixed.diagnostics["mean_dispersion_scale"] == 2.0

    online = audit_scenario_calibration(
        _objective(),
        _history(),
        form_window=5,
        bench_weight=0.1,
        points_threshold=30.0,
        selection_shift="online",
        dispersion="online",
        online_warmup_folds=2,
    )
    rows = online.rows
    assert rows[0].dispersion_scale == 1.0 and rows[1].dispersion_scale == 1.0
    assert all(row.dispersion_scale > 0.0 for row in rows)
    # From the warm-up on, the scale is the RMS of the earlier folds' location-corrected
    # gaps in units of their own spread — earlier folds only, so it is leakage-safe.
    assert online.diagnostics["final_online_dispersion_scale"] == rows[-1].dispersion_scale
    with pytest.raises(ExperimentExecutionError, match="dispersion"):
        audit_scenario_calibration(
            _objective(), _history(), form_window=3, bench_weight=0.0, dispersion="magic"
        )
    with pytest.raises(ExperimentExecutionError, match="development_dispersion_scale"):
        audit_scenario_calibration(
            _objective(),
            _history(),
            form_window=3,
            bench_weight=0.0,
            dispersion="development",
            development_dispersion_scale=0.0,
        )


def test_an_online_shift_uses_only_earlier_folds(audit: ScenarioAuditResult) -> None:
    online = audit_scenario_calibration(
        _objective(),
        _history(),
        form_window=5,
        bench_weight=0.1,
        points_threshold=30.0,
        selection_shift="online",
        online_warmup_folds=1,
    )
    rows = online.rows
    assert rows[0].location_shift_points == 0.0
    # From the second fold on, the shift is minus the mean raw gap of the earlier folds.
    raw_gaps = [plain.scenario_mean_score - plain.realized_score for plain in audit.rows]
    for index in range(1, len(rows)):
        expected = -sum(raw_gaps[:index]) / index
        assert rows[index].location_shift_points == pytest.approx(expected)
    with pytest.raises(Exception, match="selection_shift"):
        audit_scenario_calibration(
            _objective(), _history(), form_window=3, bench_weight=0.0, selection_shift="magic"
        )
    with pytest.raises(Exception, match="fixture_counts_by_fold"):
        audit_scenario_calibration(
            _objective(),
            _history(),
            form_window=3,
            bench_weight=0.0,
            double_gameweek_scale=1.5,
        )


@pytest.mark.slow
def test_the_rank_rehearsal_reports_claimed_and_realized_per_budget() -> None:
    from squadopt.experiments import rehearse_rank_objective
    from squadopt.optimization import OptimizationConfig

    result = rehearse_rank_objective(
        _objective(),
        _history(),
        form_window=5,
        bench_weight=0.1,
        budgets=(0.0, None),
        claim_scenarios="held_out_half",
        optimization_config=OptimizationConfig(solver_time_limit_seconds=4.0),
    )
    assert result.diagnostics["claim_scenarios"] == "held_out_half"
    assert {s.expected_points_budget for s in result.summaries} <= {0.0, None}
    for summary in result.summaries:
        assert 0.0 <= summary.mean_claimed_probability <= 1.0
        assert 0.0 <= summary.mean_selection_probability <= 1.0
        assert 0.0 <= summary.realized_level_share <= 1.0
        assert summary.realized_ahead_frequency + summary.realized_level_share <= 1.0 + 1e-9
        low, high = summary.realized_ahead_interval
        assert low <= summary.realized_ahead_frequency <= high
        assert summary.folds >= 1
    for row in result.rows:
        assert row.realized_ahead == (row.realized_score > row.template_realized_score)
        assert row.realized_level == (row.realized_score == row.template_realized_score)
        assert not (row.realized_ahead and row.realized_level)
        # Under a held-out claim the budget binds on the selection half, so the cost
        # read on the claim half may be positive; the row keeps both probabilities.
        assert 0.0 <= row.selection_probability_ahead <= 1.0
        # The runner writes rows and summaries to JSON: built-in scalars only.
        json.dumps(asdict(row))
    for summary in result.summaries:
        json.dumps(asdict(summary))
    assert result.diagnostics["rival"].startswith("template")
