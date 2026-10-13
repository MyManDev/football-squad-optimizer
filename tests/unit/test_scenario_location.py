"""Tests for the opt-in per-player scenario location component.

The default must stay bit-identical to the original centered behavior; only an
explicit shrinkage value may move a player's scenario distribution, and only by that
player's own shrunk historical mean residual, never by a neighbor's. The audit that
measured the component against history was removed with its runner
(docs/scenario_calibration_correction_note.md keeps the reading), so these tests read the
generator directly.
"""

from dataclasses import replace

import numpy as np
import pandas as pd
import pytest
from tests.fixtures.synthetic_gameweeks import SEASON, make_canonical_gameweeks

from squadopt.backtest import DecisionPoint, baseline_projection_builder, rows_through
from squadopt.prediction import (
    PredictionProvenance,
    PredictionSnapshot,
    prepare_optimizer_projection,
)
from squadopt.scenarios import (
    ScenarioConfig,
    ScenarioConfigurationError,
    ScenarioSet,
    ScenarioTarget,
    generate_scenarios,
)

HISTORY_GAMEWEEKS = (2, 3, 4, 5, 6)
PLAYER_BIAS = {0: -2.0, 1: 0.0, 2: 1.0, 3: -1.0}
TARGET = ScenarioTarget(SEASON, 8)
CONFIG = ScenarioConfig(
    scenario_count=64,
    deterministic_seed=11,
    min_history_folds=3,
    min_player_observations=2,
)


def _history() -> pd.DataFrame:
    """Residuals with a deliberate, player-dependent mean bias."""

    panel = make_canonical_gameweeks()
    rows: list[dict[str, object]] = []
    for gameweek in HISTORY_GAMEWEEKS:
        week = panel.loc[panel["gameweek"] == gameweek]
        for row in week.itertuples(index=False):
            bias = PLAYER_BIAS[int(row.player_id) % 4]
            noise = float(((int(row.player_id) * 7 + gameweek * 3) % 5) - 2) / 2.0
            realized = float(row.total_points)
            predicted = max(0.0, realized - bias - noise)
            rows.append(
                {
                    "fold_id": f"{SEASON}-gw{gameweek:02d}",
                    "season": SEASON,
                    "gameweek": gameweek,
                    "player_id": int(row.player_id),
                    "team_id": int(row.team_id),
                    "position": str(row.position),
                    "predicted_points": predicted,
                    "realized_points": realized,
                    "residual": realized - predicted,
                }
            )
    return pd.DataFrame(rows)


def _snapshot() -> PredictionSnapshot:
    panel = make_canonical_gameweeks()
    decision = DecisionPoint(SEASON, TARGET.gameweek)
    projection = baseline_projection_builder(rows_through(panel, decision), decision)
    provenance = PredictionProvenance(
        model_name="synthetic-location-model",
        model_version="1.0.0",
        feature_contract_version="synthetic-location-features-v1",
        training_cutoff=f"{SEASON}:GW07",
        training_data_fingerprint="b" * 64,
    )
    return prepare_optimizer_projection(
        projection.drop(columns="expected_points"),
        projection.loc[:, ["player_id", "expected_points"]],
        provenance,
    )


def _scenarios(shrinkage: float | None) -> ScenarioSet:
    return generate_scenarios(
        _snapshot(),
        _history(),
        TARGET,
        replace(CONFIG, player_location_shrinkage=shrinkage),
    )


def _shift(located: ScenarioSet, centered: ScenarioSet) -> pd.Series:
    """Each player's scenario mean under the component minus the centered one."""

    return located.scenario_points.mean(axis=0) - centered.scenario_points.mean(axis=0)


def _expected_location(shrinkage: float) -> dict[int, float]:
    """`n / (n + shrinkage)` times the player's own mean residual, as the docstring says."""

    grouped = _history().groupby("player_id")["residual"]
    means, counts = grouped.mean(), grouped.size()
    return {
        int(player): float(counts[player] / (counts[player] + shrinkage) * means[player])
        for player in means.index
    }


def test_the_default_keeps_scenarios_centered_on_projections() -> None:
    config = ScenarioConfig()

    assert config.player_location_shrinkage is None

    centered = _scenarios(None)
    assert centered.diagnostics["player_location_shrinkage"] is None
    assert centered.diagnostics["players_with_location_history"] == 0
    assert centered.diagnostics["mean_absolute_player_location"] == 0.0


def test_the_location_component_moves_each_player_by_its_own_shrunk_mean_residual() -> None:
    """The draws are the same under both settings, so the whole difference between the two
    scenario sets is the location: one constant per player, its own shrunk mean residual."""

    centered = _scenarios(None)
    located = _scenarios(2.0)
    expected = _expected_location(2.0)

    difference = located.scenario_points - centered.scenario_points
    np.testing.assert_allclose(
        difference.to_numpy(), np.broadcast_to(difference.iloc[0].to_numpy(), difference.shape)
    )
    shift = _shift(located, centered)
    players = [int(player) for player in shift.index]
    assert located.diagnostics["players_with_location_history"] == sum(
        player in expected for player in players
    )
    assert located.diagnostics["players_with_location_history"] > 0
    for player, moved in zip(players, shift.to_numpy(), strict=True):
        assert moved == pytest.approx(expected.get(player, 0.0), abs=1e-9)
    assert located.diagnostics["mean_absolute_player_location"] == pytest.approx(
        float(np.abs(shift.to_numpy()).mean()), abs=1e-9
    )


def test_the_location_component_moves_the_scenario_mean_toward_each_players_bias() -> None:
    """Players the history over-projects move down and players it under-projects move up."""

    shift = _shift(_scenarios(2.0), _scenarios(None))
    groups = {
        bias: [float(shift[player]) for player in shift.index if int(player) % 4 == key]
        for key, bias in PLAYER_BIAS.items()
    }

    assert np.mean(groups[-2.0]) < np.mean(groups[-1.0]) < 0.0
    assert np.mean(groups[1.0]) > 0.0


def test_the_location_component_changes_the_scenario_fingerprint() -> None:
    assert _scenarios(None).scenario_fingerprint != _scenarios(2.0).scenario_fingerprint
    assert _scenarios(2.0).scenario_fingerprint == _scenarios(2.0).scenario_fingerprint


def test_zero_shrinkage_is_full_player_mean_not_off() -> None:
    """k=0 keeps the component on at full weight; only None disables it."""

    assert ScenarioConfig(player_location_shrinkage=0.0).player_location_shrinkage == 0.0

    shift = _shift(_scenarios(0.0), _scenarios(None))
    full_mean = _expected_location(0.0)
    assert any(abs(value) > 0.0 for value in full_mean.values())
    for player, moved in shift.items():
        assert moved == pytest.approx(full_mean.get(int(player), 0.0), abs=1e-9)


def test_a_negative_shrinkage_is_refused() -> None:
    with pytest.raises(ScenarioConfigurationError, match="player_location_shrinkage"):
        ScenarioConfig(player_location_shrinkage=-1.0)
