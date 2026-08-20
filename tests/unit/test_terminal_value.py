"""The terminal-value study: row construction, leakage, the baseline, and the gate.

Synthetic chain artifacts written to a temporary directory — the committed artifacts are
not available everywhere the tests run, and the point is the machinery.
"""

import json
from pathlib import Path

import numpy as np
import pytest

from squadopt.experiments.config import ExperimentConfigurationError, ExperimentExecutionError
from squadopt.experiments.terminal_value import (
    CHIP_NAMES,
    HOLDING_VALUE_POINTS,
    TARGET_COLUMN,
    TerminalValueConfig,
    baseline_prediction,
    load_state_rows,
    run_terminal_value_study,
)

SEASONS = ("2021-22", "2022-23", "2023-24")


def _chain(*, weeks: int, weekly_net: float, chips_enabled: bool, chip_at: dict[int, str]):
    return {
        "chips_enabled": chips_enabled,
        "chips_played": {str(k): v for k, v in chip_at.items()},
        "lookahead": 1,
        "weeks": [
            {
                "gameweek": index + 2,
                "net_points": weekly_net + (5.0 if (index + 2) in chip_at else 0.0),
                "bank_after_tenths": 10 + index,
                "squad_sell_value_tenths": 990 - index,
                "free_transfers_after": 1,
                "chip": chip_at.get(index + 2),
            }
            for index in range(weeks)
        ],
    }


def _write(root: Path, directory: str, season: str, chains: list[dict]) -> None:
    folder = root / directory
    folder.mkdir(parents=True, exist_ok=True)
    (folder / f"{season}.json").write_text(json.dumps({"chains": chains}), encoding="utf-8")


def _store(root: Path, *, weekly: float = 50.0) -> TerminalValueConfig:
    for season in SEASONS:
        _write(
            root,
            "season_chain",
            season,
            [
                _chain(weeks=10, weekly_net=weekly, chips_enabled=False, chip_at={}),
                _chain(weeks=10, weekly_net=weekly, chips_enabled=True, chip_at={5: "bboost"}),
            ],
        )
    return TerminalValueConfig(chain_directories=("season_chain",), seasons=SEASONS)


def test_the_locked_holdout_is_refused_by_configuration() -> None:
    with pytest.raises(ExperimentConfigurationError, match="locked holdout"):
        TerminalValueConfig(seasons=("2024-25", "2025-26"))


def test_rows_carry_the_state_after_the_decision_and_the_future_net(tmp_path: Path) -> None:
    config = _store(tmp_path)
    rows = load_state_rows(tmp_path, config)
    # 10 weeks yield 9 rows per chain (the final week has no future), 2 chains, 3 seasons.
    assert len(rows) == 9 * 2 * 3
    first = rows.loc[rows["remaining_weeks"] == 9].iloc[0]
    # Nine plain weeks at 50, one of them chip-boosted by 5 in the enabled chain.
    assert first[TARGET_COLUMN] in (450.0, 455.0)
    last = rows.loc[rows["remaining_weeks"] == 1].iloc[0]
    assert last[TARGET_COLUMN] == 50.0


def test_a_played_chip_leaves_the_hand_from_that_week_on(tmp_path: Path) -> None:
    config = _store(tmp_path)
    rows = load_state_rows(tmp_path, config)
    enabled = rows.loc[rows["source"].str.contains("chain1")]
    before = enabled.loc[enabled["gameweek"] < 5, "has_bboost"]
    after = enabled.loc[enabled["gameweek"] >= 5, "has_bboost"]
    assert (before == 1.0).all()
    assert (after == 0.0).all()
    # Chips the variant does not offer are never in hand.
    assert (enabled["has_freehit"] == 0.0).all()


def test_a_disabled_chain_holds_no_chips(tmp_path: Path) -> None:
    config = _store(tmp_path)
    rows = load_state_rows(tmp_path, config)
    disabled = rows.loc[rows["source"].str.contains("chain0")]
    for name in CHIP_NAMES:
        assert (disabled[f"has_{name}"] == 0.0).all()


def test_the_target_never_reads_across_chains_or_seasons(tmp_path: Path) -> None:
    """Poisoning one season's nets must not move another season's targets."""

    config = _store(tmp_path)
    clean = load_state_rows(tmp_path, config)
    poisoned_root = tmp_path / "poisoned"
    for season in SEASONS:
        weekly = 999.0 if season == "2023-24" else 50.0
        _write(
            poisoned_root,
            "season_chain",
            season,
            [
                _chain(weeks=10, weekly_net=weekly, chips_enabled=False, chip_at={}),
                _chain(weeks=10, weekly_net=weekly, chips_enabled=True, chip_at={5: "bboost"}),
            ],
        )
    poisoned = load_state_rows(poisoned_root, config)
    for season in ("2021-22", "2022-23"):
        left = clean.loc[clean["season"] == season, TARGET_COLUMN].to_numpy()
        right = poisoned.loc[poisoned["season"] == season, TARGET_COLUMN].to_numpy()
        np.testing.assert_array_equal(left, right)


def test_an_empty_store_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ExperimentExecutionError, match="No chain artifact"):
        load_state_rows(tmp_path, TerminalValueConfig(seasons=SEASONS))


def test_the_baseline_is_average_weeks_plus_chips_in_hand(tmp_path: Path) -> None:
    config = _store(tmp_path)
    rows = load_state_rows(tmp_path, config)
    training = rows.loc[rows["season"] != "2023-24"]
    held = rows.loc[rows["season"] == "2023-24"]
    predictions = baseline_prediction(held, training)
    weekly = float((training[TARGET_COLUMN] / training["remaining_weeks"]).mean())
    for value, (_, row) in zip(predictions, held.iterrows(), strict=True):
        expected = row["remaining_weeks"] * weekly + sum(
            HOLDING_VALUE_POINTS[name] * row[f"has_{name}"] for name in CHIP_NAMES
        )
        assert value == pytest.approx(expected)


def test_the_study_runs_leave_one_season_out_and_applies_the_gate(tmp_path: Path) -> None:
    config = _store(tmp_path)
    study = run_terminal_value_study(tmp_path, config)
    assert {score.season for score in study.seasons} == set(SEASONS)
    assert study.rows == 9 * 2 * 3
    assert set(study.verdict) >= {"pooled_improvement", "seasons_better", "passes"}
    assert isinstance(study.verdict["passes"], bool)
    assert study.diagnostics["promotion_available"] is False
    bands = dict(study.by_phase)
    assert sum(int(values["rows"]) for values in bands.values()) == study.rows
