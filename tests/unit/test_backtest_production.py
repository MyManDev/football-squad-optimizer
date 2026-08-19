"""Tests for the production walk-forward builder.

The leakage tests are the point of this file. A shifted feature is an argument; a
mutation test is evidence. Each one perturbs something the builder must not be able to
see and asserts the snapshot is unchanged down to its fingerprint.
"""

from typing import Any

import pandas as pd
import pytest

from squadopt.backtest.production import (
    PRODUCTION_FEATURE_CONTRACT_VERSION,
    PRODUCTION_MODEL_NAME,
    PRODUCTION_MODEL_VERSION,
    build_production_prediction_snapshot,
    make_production_projection_builder,
    production_feature_config,
)
from squadopt.backtest.splits import BacktestConfigurationError, DecisionPoint
from squadopt.data.schema import FIXTURE_COLUMNS
from squadopt.prediction.minutes import ExpectedMinutesConfig
from squadopt.prediction.production import ProductionProjectionConfig

WINDOW = 3
CONFIG = ProductionProjectionConfig(
    rate_window=WINDOW, minutes=ExpectedMinutesConfig(window=WINDOW)
)
SEASONS = ("2024-25", "2025-26")
TARGET_SEASON = "2025-26"
TARGET_GAMEWEEK = 5

TEAMS = ("Arsenal", "Liverpool")
TEAM_CODES = pd.DataFrame(
    [
        {"season": season, "name": name, "code": code}
        for season in SEASONS
        for name, code in zip(TEAMS, (3, 14), strict=True)
    ]
)

# Enough players to satisfy squad constraints is unnecessary here: the builder is
# exercised, not the optimizer.
PLAYERS = (
    (1, "Arsenal", "GK", 45),
    (2, "Arsenal", "DEF", 55),
    (3, "Arsenal", "MID", 85),
    (4, "Liverpool", "MID", 95),
    (5, "Liverpool", "FWD", 105),
)


def _panel(
    *,
    gameweeks: int = 6,
    seasons: tuple[str, ...] = SEASONS,
    minutes: int = 80,
    points: int = 4,
) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for season in seasons:
        for gameweek in range(1, gameweeks + 1):
            for player_id, team, position, price in PLAYERS:
                rows.append(
                    {
                        "season": season,
                        "gameweek": gameweek,
                        "player_id": player_id,
                        "name": f"Player {player_id}",
                        "team_id": team,
                        "position": position,
                        "price_tenths": price,
                        "minutes": minutes,
                        "total_points": points + player_id,
                    }
                )
    return pd.DataFrame(rows)


def _fixtures(*, gameweeks: int = 6, doubles: tuple[int, ...] = ()) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    fixture_id = 0
    for season in SEASONS:
        for gameweek in range(1, gameweeks + 1):
            repeats = 2 if gameweek in doubles else 1
            for _ in range(repeats):
                fixture_id += 1
                shared: dict[str, Any] = {
                    "snapshot_id": "vaastav-8c97b2a",
                    "captured_at_utc": pd.NA,
                    "season": season,
                    "gameweek": gameweek,
                    "fixture_id": fixture_id,
                    "kickoff_time_utc": "2025-08-15T19:00:00Z",
                    "deadline_timestamp_utc": pd.NA,
                    "status": "final",
                }
                rows.append(
                    {
                        **shared,
                        "team_id": 3,
                        "opponent_team_id": 14,
                        "is_home": True,
                        "fixture_difficulty": 2,
                    }
                )
                rows.append(
                    {
                        **shared,
                        "team_id": 14,
                        "opponent_team_id": 3,
                        "is_home": False,
                        "fixture_difficulty": 4,
                    }
                )
    frame = pd.DataFrame(rows, columns=list(FIXTURE_COLUMNS))
    for column in ("gameweek", "fixture_id", "team_id", "opponent_team_id"):
        frame[column] = frame[column].astype("int64")
    frame["is_home"] = frame["is_home"].astype("boolean")
    frame["fixture_difficulty"] = frame["fixture_difficulty"].astype("Int64")
    for column in (
        "snapshot_id",
        "season",
        "kickoff_time_utc",
        "status",
        "captured_at_utc",
        "deadline_timestamp_utc",
    ):
        frame[column] = frame[column].astype("string")
    return frame


def _decision(gameweek: int = TARGET_GAMEWEEK) -> DecisionPoint:
    return DecisionPoint(season=TARGET_SEASON, gameweek=gameweek)


def _snapshot(panel: pd.DataFrame | None = None, **kwargs: Any) -> Any:
    return build_production_prediction_snapshot(
        _panel() if panel is None else panel,
        kwargs.pop("decision", _decision()),
        fixtures=kwargs.pop("fixtures", _fixtures()),
        team_codes=kwargs.pop("team_codes", TEAM_CODES),
        config=kwargs.pop("config", CONFIG),
    )


# --- the contract -----------------------------------------------------------


def test_the_snapshot_carries_the_projection_contract() -> None:
    snapshot = _snapshot()

    for column in ("player_id", "name", "team_id", "position", "price_tenths", "expected_points"):
        assert column in snapshot.table.columns


def test_one_row_per_player_in_the_target_gameweek() -> None:
    snapshot = _snapshot()

    assert len(snapshot.table) == len(PLAYERS)


def test_expected_points_are_finite_and_non_negative() -> None:
    snapshot = _snapshot()

    values = snapshot.table["expected_points"].astype("float64")
    assert values.notna().all()
    assert (values >= 0).all()


def test_provenance_names_the_model_and_its_contract() -> None:
    snapshot = _snapshot()

    assert snapshot.provenance.model_name == PRODUCTION_MODEL_NAME
    assert snapshot.provenance.model_version == PRODUCTION_MODEL_VERSION
    assert snapshot.provenance.feature_contract_version == PRODUCTION_FEATURE_CONTRACT_VERSION


def test_the_training_cutoff_precedes_the_decision() -> None:
    snapshot = _snapshot()

    assert snapshot.provenance.training_cutoff == f"{TARGET_SEASON}:GW04"


def test_the_feature_config_is_derived_from_the_projection_config() -> None:
    """A window tuned in one place must not be read from another."""

    derived = production_feature_config(CONFIG)

    assert derived.per_90_window == CONFIG.rate_window
    assert derived.appearance_windows == (CONFIG.minutes.window,)


# --- leakage ----------------------------------------------------------------


def test_perturbing_the_target_gameweeks_outcome_changes_nothing() -> None:
    """The row being predicted must not contribute its own result."""

    baseline = _snapshot()

    tampered = _panel()
    mask = (tampered["season"] == TARGET_SEASON) & (tampered["gameweek"] == TARGET_GAMEWEEK)
    tampered.loc[mask, "total_points"] = 1000
    tampered.loc[mask, "minutes"] = 0

    changed = _snapshot(tampered)

    assert changed.prediction_fingerprint == baseline.prediction_fingerprint


def test_perturbing_every_future_outcome_changes_nothing() -> None:
    baseline = _snapshot()

    tampered = _panel()
    mask = (tampered["season"] == TARGET_SEASON) & (tampered["gameweek"] >= TARGET_GAMEWEEK)
    tampered.loc[mask, "total_points"] = tampered.loc[mask, "total_points"] + 1000

    changed = _snapshot(tampered)

    assert changed.prediction_fingerprint == baseline.prediction_fingerprint


def test_deleting_future_gameweeks_changes_nothing() -> None:
    """Stronger than mutation: catches whole-dataset operations mutation misses."""

    baseline = _snapshot()

    truncated = _panel()
    truncated = truncated.loc[
        ~((truncated["season"] == TARGET_SEASON) & (truncated["gameweek"] > TARGET_GAMEWEEK))
    ].reset_index(drop=True)

    changed = _snapshot(truncated)

    assert changed.prediction_fingerprint == baseline.prediction_fingerprint


def test_row_order_changes_nothing() -> None:
    baseline = _snapshot()

    shuffled = (
        _panel()
        .sort_values(["gameweek", "player_id"], ascending=[False, False])
        .reset_index(drop=True)
    )

    changed = _snapshot(shuffled)

    assert changed.prediction_fingerprint == baseline.prediction_fingerprint


def test_altering_visible_history_does_change_the_snapshot() -> None:
    """The converse: the tests above would pass trivially if nothing mattered."""

    baseline = _snapshot()

    altered = _panel()
    mask = (altered["season"] == TARGET_SEASON) & (altered["gameweek"] < TARGET_GAMEWEEK)
    altered.loc[mask, "minutes"] = 0

    changed = _snapshot(altered)

    assert changed.prediction_fingerprint != baseline.prediction_fingerprint


def test_the_training_fingerprint_ignores_the_future() -> None:
    baseline = _snapshot()

    tampered = _panel()
    mask = (tampered["season"] == TARGET_SEASON) & (tampered["gameweek"] > TARGET_GAMEWEEK)
    tampered.loc[mask, "total_points"] = -50

    changed = _snapshot(tampered)

    assert (
        changed.provenance.training_data_fingerprint
        == baseline.provenance.training_data_fingerprint
    )


def test_the_same_input_produces_the_same_fingerprint() -> None:
    assert _snapshot().prediction_fingerprint == _snapshot().prediction_fingerprint


def test_the_input_panel_is_not_modified() -> None:
    panel = _panel()
    before = panel.copy(deep=True)

    _snapshot(panel)

    assert panel.equals(before)


# --- the calendar -----------------------------------------------------------


def test_a_double_gameweek_raises_the_projection() -> None:
    single = _snapshot()
    double = _snapshot(fixtures=_fixtures(doubles=(TARGET_GAMEWEEK,)))

    single_total = single.table["expected_points"].astype("float64").sum()
    double_total = double.table["expected_points"].astype("float64").sum()
    assert double_total > single_total


def test_the_diagnostics_count_calendar_cases() -> None:
    snapshot = _snapshot(fixtures=_fixtures(doubles=(TARGET_GAMEWEEK,)))

    assert snapshot.diagnostics["double_gameweek_players"] == len(PLAYERS)
    assert snapshot.diagnostics["blank_gameweek_players"] == 0


def test_the_diagnostics_report_which_rungs_fired() -> None:
    """A squad built from fallbacks should be visibly that."""

    snapshot = _snapshot()

    routes = [key for key in snapshot.diagnostics if key.startswith("points_source:")]
    assert routes
    assert sum(int(snapshot.diagnostics[key]) for key in routes) == len(PLAYERS)


# --- the price prior --------------------------------------------------------


def test_the_price_prior_is_refitted_on_completed_seasons() -> None:
    snapshot = _snapshot()

    assert snapshot.diagnostics["opening_price_prior_origin"] == "refit_expanding_window"


def test_a_first_season_falls_back_to_the_frozen_constant_and_says_so() -> None:
    """That fold's opening behaviour is then not a product of its own history."""

    panel = _panel(seasons=("2024-25",))
    decision = DecisionPoint(season="2024-25", gameweek=5)

    snapshot = _snapshot(panel, decision=decision)

    assert (
        snapshot.diagnostics["opening_price_prior_origin"] == "frozen_constant_no_completed_seasons"
    )


# --- the builder ------------------------------------------------------------


def test_the_builder_matches_the_walk_forward_signature() -> None:
    builder = make_production_projection_builder(
        fixtures=_fixtures(), team_codes=TEAM_CODES, config=CONFIG
    )

    snapshot = builder(_panel(), _decision())

    assert len(snapshot.table) == len(PLAYERS)


def test_the_builder_agrees_with_a_direct_call() -> None:
    """The cache must not change the answer, only the cost of getting it."""

    builder = make_production_projection_builder(
        fixtures=_fixtures(), team_codes=TEAM_CODES, config=CONFIG
    )

    built = builder(_panel(), _decision())
    direct = _snapshot()

    assert built.prediction_fingerprint == direct.prediction_fingerprint


def test_the_builder_is_reusable_across_folds() -> None:
    builder = make_production_projection_builder(
        fixtures=_fixtures(), team_codes=TEAM_CODES, config=CONFIG
    )

    first = builder(_panel(), _decision(4))
    second = builder(_panel(), _decision(5))

    assert first.prediction_fingerprint != second.prediction_fingerprint


def test_a_decision_with_no_target_rows_is_rejected() -> None:
    with pytest.raises(BacktestConfigurationError, match="No target rows"):
        _snapshot(decision=_decision(99))


def test_a_wrong_config_type_is_rejected() -> None:
    with pytest.raises(BacktestConfigurationError, match="ProductionProjectionConfig"):
        _snapshot(config="two-stage")
