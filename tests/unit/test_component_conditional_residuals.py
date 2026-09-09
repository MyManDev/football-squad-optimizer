"""The opt-in conditional residual neighbourhood: same sampler, a narrower row choice.

Every pool is synthetic and readable: within a history fold the points residual encodes the
row (``index + 0.5``), the minutes residual equals the points residual, and the second fold
sits 100 points higher, so a sampled cell names its row, its fold and its pairing at once.
"""

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal
from tests.unit.test_component_scenarios import TARGET, _input_frame, _inputs, _snapshot

from squadopt.scenarios import ScenarioConfig
from squadopt.scenarios.components import (
    COMPONENT_SCENARIO_CONTRACT_VERSION,
    CONDITIONAL_RESIDUAL_CONTRACT_VERSION,
    UNUSED_SCENARIO_CONFIG_FIELDS,
    ComponentScenarioDraw,
    ConditionalResidualConfig,
    paired_conditional_residuals,
    sample_component_scenarios,
)
from squadopt.scenarios.models import ScenarioValidationError

ROWS = 40
FOLDS = {"2026-27-gw07": 0.0, "2026-27-gw08": 100.0}
EXPECTATIONS = (1.0, 5.0, 9.0)  # the three input players: low, middle, high


def _pool_frame() -> pd.DataFrame:
    records: list[dict[str, object]] = []
    for fold, offset in FOLDS.items():
        for index in range(ROWS):
            residual = offset + index + 0.5
            records.append(
                {
                    "fold_id": fold,
                    "player_id": 1000 + index,
                    "composition_route": "component_model",
                    "appearance_target": 1,
                    "expected_minutes_if_appearance": 45.0,
                    "raw_expected_points_if_appearance": 0.25 * index,  # 0.0 .. 9.75
                    "minutes_target": 45.0 + residual,
                    "points_target": 0.25 * index + residual,
                }
            )
    return pd.DataFrame(records)


def _draw(conditional: ConditionalResidualConfig | None, seed: int = 7) -> ComponentScenarioDraw:
    frame = _input_frame(appearance_probability=1.0)
    frame["fixture_count"] = 3  # ceiling 270; the largest minutes draw is 45 + 139.5
    frame["raw_expected_points_if_appearance"] = list(EXPECTATIONS)
    pool = paired_conditional_residuals(_pool_frame(), target=TARGET)
    return sample_component_scenarios(
        _inputs(frame),
        _snapshot(),  # type: ignore[arg-type]
        pool,
        TARGET,
        ScenarioConfig(scenario_count=300, deterministic_seed=seed),
        conditional_residuals=conditional,
    )


def _decoded_rows(draw: ComponentScenarioDraw) -> tuple[np.ndarray, np.ndarray]:
    """Per cell: the residual read from the points matrix, and the fold it names."""

    points = draw.scenarios.scenario_points.to_numpy()
    residual = points - np.array(EXPECTATIONS)[None, :]
    fold_offset = np.where(residual >= 100.0, 100.0, 0.0)
    return residual, fold_offset


def test_each_cell_draws_from_the_rows_nearest_the_players_expectation() -> None:
    config = ConditionalResidualConfig(fraction=0.25, minimum_rows=4)  # 10 of 40 rows
    draw = _draw(config)

    residual, fold_offset = _decoded_rows(draw)
    row_index = np.rint(residual - fold_offset - 0.5).astype(int)
    row_expectation = 0.25 * row_index
    assert row_index.min() >= 0 and row_index.max() < ROWS
    # A window of ten rows spaced 0.25 apart never reaches further than 1.5 points away,
    # and the low and high players cannot cross into each other's half of the fold.
    assert np.abs(row_expectation - np.array(EXPECTATIONS)[None, :]).max() <= 1.5
    assert row_expectation[:, 0].max() <= 3.0
    assert row_expectation[:, 2].min() >= 6.0
    assert len(set(row_index[:, 1].tolist())) > 1, "a window is a draw, not one fixed row"
    assert draw.scenarios.diagnostics["residual_selection"] == "conditional_neighbourhood"
    assert (
        draw.scenarios.diagnostics["component_sampler_contract_version"]
        == CONDITIONAL_RESIDUAL_CONTRACT_VERSION
    )
    assert draw.scenarios.diagnostics["conditional_residual_fallback_folds"] == 0


def test_the_pairing_and_the_source_fold_survive_the_narrower_choice() -> None:
    draw = _draw(ConditionalResidualConfig(fraction=0.25, minimum_rows=4))

    residual, fold_offset = _decoded_rows(draw)
    minutes_residual = draw.sampled_minutes.to_numpy() - 45.0
    assert np.allclose(minutes_residual, residual), "minutes and points come from one row"
    named = np.array([FOLDS[fold] for fold in draw.scenarios.source_fold_ids])
    assert (fold_offset == named[:, None]).all(), "every cell is inside its scenario's fold"


def test_appearances_and_source_folds_match_the_frozen_draw_seed_for_seed() -> None:
    """Only the row within the fold changes; the appearance and fold streams are shared."""

    frozen = _draw(None)
    candidate = _draw(ConditionalResidualConfig(fraction=0.25, minimum_rows=4))

    assert_frame_equal(frozen.sampled_appearances, candidate.sampled_appearances)
    assert frozen.scenarios.source_fold_ids == candidate.scenarios.source_fold_ids
    assert not frozen.scenarios.scenario_points.equals(candidate.scenarios.scenario_points)
    assert frozen.scenarios.scenario_fingerprint != candidate.scenarios.scenario_fingerprint
    assert frozen.component_fingerprint != candidate.component_fingerprint


def test_the_same_seed_reproduces_the_candidate_draw() -> None:
    config = ConditionalResidualConfig(fraction=0.25, minimum_rows=4)

    first = _draw(config)
    second = _draw(config)

    assert first.component_fingerprint == second.component_fingerprint
    assert_frame_equal(first.scenarios.scenario_points, second.scenarios.scenario_points)
    assert _draw(config, seed=8).component_fingerprint != first.component_fingerprint


def test_a_fold_smaller_than_the_window_is_used_whole_and_counted() -> None:
    draw = _draw(ConditionalResidualConfig(fraction=0.25, minimum_rows=100))

    residual, fold_offset = _decoded_rows(draw)
    row_index = np.rint(residual - fold_offset - 0.5).astype(int)
    assert draw.scenarios.diagnostics["conditional_residual_fallback_folds"] == 2
    assert draw.scenarios.diagnostics["conditional_residual_window_rows_mean"] == ROWS
    assert row_index.min() >= 0 and row_index.max() < ROWS
    assert len(set(row_index[:, 0].tolist())) > 10, "the whole fold is reachable"


def test_the_frozen_path_declares_itself_and_its_effective_settings() -> None:
    draw = _draw(None)

    diagnostics = draw.scenarios.diagnostics
    assert diagnostics["residual_selection"] == "fold_uniform"
    assert diagnostics["component_sampler_contract_version"] == COMPONENT_SCENARIO_CONTRACT_VERSION
    effective = diagnostics["effective_settings"]
    assert effective["scenario_count"] == 300 and effective["deterministic_seed"] == 7
    assert tuple(effective["unused_scenario_config_fields"]) == UNUSED_SCENARIO_CONFIG_FIELDS
    assert "conditional_residual_fraction" not in diagnostics


@pytest.mark.parametrize(
    "fraction, minimum_rows",
    [(0.0, 30), (1.5, 30), (float("nan"), 30), (0.15, 1), (0.15, 2.5), (True, 30)],
)
def test_the_candidate_config_refuses_bad_controls(fraction: object, minimum_rows: object) -> None:
    with pytest.raises(ScenarioValidationError):
        ConditionalResidualConfig(fraction=fraction, minimum_rows=minimum_rows)  # type: ignore[arg-type]
    with pytest.raises(ScenarioValidationError):
        _draw("not a config")  # type: ignore[arg-type]


def test_the_window_rule_is_the_declared_one() -> None:
    config = ConditionalResidualConfig(fraction=0.15, minimum_rows=30)

    assert config.window_rows(300) == 45  # ceil(0.15 * 300)
    assert config.window_rows(100) == 30  # the minimum wins over 15
    assert config.window_rows(20) == 20  # a small fold is used whole
