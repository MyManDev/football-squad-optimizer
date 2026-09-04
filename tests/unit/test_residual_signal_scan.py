"""Tests for the residual signal scan: strict lags, correct joins, honest bins.

The one thing that could make this measurement lie is a covariate that peeks at the
gameweek it is scored on, so the lag is the first thing tested, on hand-built rows whose
answers can be checked by eye.
"""

from pathlib import Path

import pandas as pd
import pytest

from squadopt.experiments import ExperimentExecutionError
from squadopt.experiments.residual_signal_scan import (
    RESIDUAL_SIGNAL_SCAN_CONTRACT_VERSION,
    build_lagged_covariates,
    load_enrichment_rows,
    scan_residual_signals,
    scan_to_markdown,
)

SEASON = "2023-24"


def _raw() -> pd.DataFrame:
    """Two players over five gameweeks; player 2 has a double in GW3."""

    rows: list[dict[str, object]] = []
    for gameweek in range(1, 6):
        rows.append(
            {
                "season": SEASON,
                "gameweek": gameweek,
                "player_id": 1,
                "minutes": 90.0,
                "goals_scored": 1.0 if gameweek == 2 else 0.0,
                "assists": 0.0,
                "expected_goal_involvements": 0.5,
                "selected": 100.0 * gameweek,
                "xP": 3.0 + gameweek,
            }
        )
        rows.append(
            {
                "season": SEASON,
                "gameweek": gameweek,
                "player_id": 2,
                "minutes": 180.0 if gameweek == 3 else 90.0,
                "goals_scored": 0.0,
                "assists": 0.0,
                "expected_goal_involvements": 1.0 if gameweek == 3 else 0.2,
                "selected": 50.0,
                "xP": 2.0,
            }
        )
    return pd.DataFrame(rows)


def _panel(team_switch_at: int | None = None) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for gameweek in range(1, 6):
        for player in (1, 2):
            team = "A"
            if player == 1 and team_switch_at is not None and gameweek >= team_switch_at:
                team = "B"
            rows.append(
                {
                    "season": SEASON,
                    "gameweek": gameweek,
                    "player_id": player,
                    "team_id": team,
                    "position": "MID",
                    "minutes": 90,
                    "total_points": 2,
                }
            )
    return pd.DataFrame(rows)


def test_rolling_covariates_use_only_earlier_gameweeks() -> None:
    covariates = build_lagged_covariates(_raw(), _panel(), window=3)
    one = covariates.loc[covariates["player_id"] == 1].set_index("gameweek")

    # GW1 has no history: every lagged rolling quantity is missing.
    assert pd.isna(one.loc[1, "xgi_per_90_last"])
    assert pd.isna(one.loc[1, "luck_last"])
    assert pd.isna(one.loc[1, "ownership_prev"])
    # GW3 sees GW1-2 only: 1.0 xGI over 180 minutes -> 0.5 per 90; one goal against 1.0 xGI.
    assert one.loc[3, "xgi_per_90_last"] == pytest.approx(0.5)
    assert one.loc[3, "luck_last"] == pytest.approx(0.0)
    # GW5 sees GW2-4 (window three): returns 1, xGI 1.5 -> luck -0.5.
    assert one.loc[5, "luck_last"] == pytest.approx(-0.5)
    # Ownership is the previous gameweek's; the source expectation is the current one's.
    assert one.loc[4, "ownership_prev"] == pytest.approx(300.0)
    assert one.loc[4, "source_xp"] == pytest.approx(7.0)


def test_a_double_gameweek_adds_across_fixtures_in_the_rate() -> None:
    covariates = build_lagged_covariates(_raw(), _panel(), window=6)
    two = covariates.loc[covariates["player_id"] == 2].set_index("gameweek")

    # GW4 sees GW1-3: xGI 0.2 + 0.2 + 1.0 = 1.4 over 90 + 90 + 180 minutes.
    assert two.loc[4, "xgi_per_90_last"] == pytest.approx(1.4 / 360.0 * 90.0)


def test_a_club_change_is_flagged_for_the_window_after_it() -> None:
    covariates = build_lagged_covariates(_raw(), _panel(team_switch_at=3), window=2)
    one = covariates.loc[covariates["player_id"] == 1].set_index("gameweek")["recently_moved"]

    assert one.loc[2] == 0
    assert one.loc[3] == 1
    assert one.loc[4] == 1
    assert one.loc[5] == 0
    two = covariates.loc[covariates["player_id"] == 2, "recently_moved"]
    assert (two == 0).all()


def _residuals(covariates: pd.DataFrame) -> pd.DataFrame:
    frame = covariates.loc[:, ["season", "gameweek", "player_id"]].copy()
    frame["position"] = "MID"
    frame["realized_points"] = 2.0
    frame["residual"] = frame["gameweek"].astype("float64") - 3.0
    return frame


def test_the_scan_bins_and_reports_spreads() -> None:
    covariates = build_lagged_covariates(_raw(), _panel(team_switch_at=3), window=2)
    residuals = _residuals(covariates)

    scan = scan_residual_signals(residuals, covariates, window=2, min_rows=2)

    assert scan.contract_version == RESIDUAL_SIGNAL_SCAN_CONTRACT_VERSION
    by_name = {signal.covariate: signal for signal in scan.signals}
    moved = by_name["recently_moved"]
    assert {entry.label for entry in moved.bins} == {"unchanged", "recently_moved"}
    assert moved.rows == len(residuals)
    xp = by_name["source_xp"]
    assert xp.rows == len(residuals)
    assert xp.residual_spread >= 0.0
    markdown = scan_to_markdown(scan)
    assert RESIDUAL_SIGNAL_SCAN_CONTRACT_VERSION in markdown
    assert "`recently_moved`" in markdown


def test_too_few_rows_is_reported_not_binned() -> None:
    covariates = build_lagged_covariates(_raw(), _panel(), window=2)
    residuals = _residuals(covariates)

    scan = scan_residual_signals(residuals, covariates, window=2, min_rows=1_000)

    assert all(signal.bins == () for signal in scan.signals)
    assert "Not measured" in scan_to_markdown(scan)


def test_a_join_that_changes_the_row_count_is_refused() -> None:
    covariates = build_lagged_covariates(_raw(), _panel(), window=2)
    residuals = _residuals(covariates)
    duplicated = pd.concat([covariates, covariates.iloc[[0]]], ignore_index=True)

    with pytest.raises(ExperimentExecutionError, match="row count"):
        scan_residual_signals(residuals, duplicated, window=2, min_rows=2)


def test_the_raw_reader_joins_codes_and_collapses_double_gameweeks(tmp_path: Path) -> None:
    season_dir = tmp_path / "data" / SEASON
    (season_dir / "gws").mkdir(parents=True)
    pd.DataFrame(
        {
            "element": [7, 7, 7, 8],
            "round": [1, 2, 2, 1],
            "fixture": [10, 11, 12, 10],
            "minutes": ["90", "90", "90", "45"],
            "goals_scored": ["1", "0", "1", "0"],
            "assists": ["0", "0", "0", "1"],
            "expected_goal_involvements": ["0.4", "0.3", "0.6", "0.1"],
            "selected": ["1000", "1200", "1200", "50"],
            "xP": ["4.0", "3.5", "3.5", "1.0"],
        }
    ).to_csv(season_dir / "gws" / "merged_gw.csv", index=False)
    pd.DataFrame({"id": [7, 8], "code": [700, 800]}).to_csv(
        season_dir / "players_raw.csv", index=False
    )

    rows = load_enrichment_rows(tmp_path, (SEASON,))

    double = rows.loc[(rows["player_id"] == 700) & (rows["gameweek"] == 2)].iloc[0]
    assert double["minutes"] == 180.0
    assert double["expected_goal_involvements"] == pytest.approx(0.9)
    assert double["selected"] == 1200.0  # per-gameweek, taken once
    assert double["xP"] == 3.5
    assert set(rows["player_id"]) == {700, 800}
