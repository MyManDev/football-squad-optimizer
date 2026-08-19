"""Tests for the opt-in per-player scenario location component.

The default must stay bit-identical to the original centered behavior; only an
explicit shrinkage value may move a player's scenario distribution, and only by that
player's own shrunk historical mean residual — never by a neighbor's.
"""

import pandas as pd
import pytest
from tests.fixtures.synthetic_gameweeks import SEASON, make_canonical_gameweeks

from squadopt.experiments import (
    ScenarioPolicyObjective,
    ScenarioPolicyObjectiveConfig,
    audit_scenario_calibration,
)
from squadopt.scenarios import ScenarioConfig, ScenarioConfigurationError

HISTORY_GAMEWEEKS = (2, 3, 4, 5, 6)
PLAYER_BIAS = {0: -2.0, 1: 0.0, 2: 1.0, 3: -1.0}


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


def _config(shrinkage: float | None) -> ScenarioPolicyObjectiveConfig:
    return ScenarioPolicyObjectiveConfig(
        development_seasons=(SEASON,),
        scenario_count=32,
        min_history_folds=3,
        min_player_observations=2,
        player_location_shrinkage=shrinkage,
    )


def _audit_bias(shrinkage: float | None) -> float:
    objective = ScenarioPolicyObjective(make_canonical_gameweeks(), _history(), _config(shrinkage))
    audit = audit_scenario_calibration(
        objective,
        _history(),
        form_window=5,
        bench_weight=0.1,
        points_threshold=30.0,
    )
    return audit.mean_score_bias


def test_the_default_keeps_scenarios_centered_on_projections() -> None:
    config = ScenarioConfig()

    assert config.player_location_shrinkage is None


def test_the_location_component_moves_the_scenario_mean_toward_reality() -> None:
    """With systematic per-player bias in history, the shrunk location must shrink
    the decision-level gap between scenario means and realized scores."""

    centered_bias = _audit_bias(None)
    located_bias = _audit_bias(2.0)

    assert abs(located_bias) < abs(centered_bias)


def test_the_location_component_changes_the_configuration_fingerprint() -> None:
    assert _config(None).configuration_fingerprint != _config(2.0).configuration_fingerprint
    assert _config(2.0).configuration_fingerprint == _config(2.0).configuration_fingerprint


def test_zero_shrinkage_is_full_player_mean_not_off() -> None:
    """k=0 keeps the component on at full weight; only None disables it."""

    assert _config(0.0).player_location_shrinkage == 0.0
    assert _config(None).player_location_shrinkage is None


def test_a_negative_shrinkage_is_refused() -> None:
    with pytest.raises(ScenarioConfigurationError, match="player_location_shrinkage"):
        ScenarioConfig(player_location_shrinkage=-1.0)
