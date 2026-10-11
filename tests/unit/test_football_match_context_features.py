from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd
import pytest
from pandas.testing import assert_frame_equal

from squadopt.prediction.football_match_context_features import (
    CONTEXT_FEATURES,
    CONTEXT_TEAM_FEATURES,
    MATCH_CONTEXT_FEATURE_CONTRACT,
    causal_match_context_features,
    match_context_feature_metadata,
)

CUTOFF = pd.Timestamp("2026-10-09T12:00:00Z")


def _game(
    fixture: int,
    week: int,
    kickoff: pd.Timestamp,
    *,
    home: int = 10,
    score: tuple[int, int] = (2, 1),
    season: str = "2026-27",
    changes: dict[int, dict[str, Any]] | None = None,
) -> pd.DataFrame:
    away = 20 if home == 10 else 10
    rows = []
    for club, opponent, venue, gf, ga in (
        (home, away, 1.0, score[0], score[1]),
        (away, home, 0.0, score[1], score[0]),
    ):
        for offset, minutes, starts, xg in ((1, 90.0, 1.0, 0.8), (2, 0.0, 0.0, 0.2)):
            player = club * 10 + offset
            rows.append(
                {
                    "season": season,
                    "GW": week,
                    "fixture": fixture,
                    "player_code": player,
                    "club": club,
                    "opponent": opponent,
                    "home": venue,
                    "kickoff": kickoff,
                    "minutes": minutes,
                    "starts": starts,
                    "team_goals": float(gf),
                    "team_conceded": float(ga),
                    "expected_goals": xg,
                    **(changes or {}).get(player, {}),
                }
            )
    return pd.DataFrame(rows)


def _target(**changes: Any) -> pd.DataFrame:
    return pd.DataFrame(
        [
            {
                "season": "2026-27",
                "GW": 8,
                "fixture": 999,
                "player_code": 101,
                "club": 10,
                "opponent": 20,
                "home": 1.0,
                **changes,
            }
        ],
        index=pd.Index([43], name="request_row"),
    )


def _history() -> pd.DataFrame:
    return pd.concat(
        [
            _game(71, 7, CUTOFF - pd.Timedelta(days=2), score=(3, 1)),
            _game(
                61,
                6,
                CUTOFF - pd.Timedelta(days=7),
                home=20,
                score=(2, 0),
                changes={101: {"minutes": 45.0, "starts": 0.0, "expected_goals": 0.7}},
            ),
            _game(
                51,
                5,
                CUTOFF - pd.Timedelta(days=9),
                score=(1, 0),
                changes={101: {"minutes": 0.0, "starts": np.nan, "expected_goals": 0.0}},
            ),
            _game(41, 4, CUTOFF - pd.Timedelta(days=16), score=(2, 1)),
        ],
        ignore_index=True,
    )


def test_calendar_day_workload_differs_from_recent_match_counts() -> None:
    result = causal_match_context_features(_history(), _target(), CUTOFF).iloc[0]
    assert result.player_pl_7d_minutes == 135
    assert result.player_pl_7d_appearances == 2
    assert result.player_pl_7d_starts == 1
    assert result.player_pl_7d_observations == 2
    assert result.player_pl_7d_minutes_known_rows == 2
    assert result.player_pl_7d_starts_known_rows == 2
    assert result.player_pl_7d_starts_missing == 0
    assert result.player_pl_14d_minutes == 135
    assert result.player_pl_14d_appearances == 2
    assert result.player_pl_14d_observations == 3
    assert result.player_pl_14d_starts == 1
    assert result.player_pl_14d_starts_known_rows == 2
    assert result.player_pl_14d_starts_missing == 1
    assert result.own_pl_7d_fixtures == result.opp_pl_7d_fixtures == 2
    assert result.own_pl_14d_fixtures == result.opp_pl_14d_fixtures == 3
    assert result.own_pl_observed_fixtures == result.opp_pl_observed_fixtures == 4
    assert result.own_pl_days_since_match == result.opp_pl_days_since_match == 2
    assert result.own_pl_match_history_missing == result.opp_pl_match_history_missing == 0


def test_venue_conditioning_uses_own_venue_and_opponents_opposite_venue() -> None:
    target = pd.concat([_target(), _target(fixture=998, home=0.0)]).set_axis([43, 17])
    result = causal_match_context_features(_history(), target, CUTOFF)
    home, away = result.iloc[0], result.iloc[1]
    assert home.own_venue_matches == home.opp_venue_matches == 3
    assert home.own_venue_gf == 2
    assert home.own_venue_ga == pytest.approx(2 / 3)
    assert home.own_venue_xgf == pytest.approx(2.2 / 3)
    assert home.own_venue_xga == 1
    assert home.opp_venue_gf == pytest.approx(2 / 3)
    assert home.opp_venue_ga == 2
    assert home.opp_venue_xgf == 1
    assert home.opp_venue_xga == pytest.approx(2.2 / 3)
    assert home.own_venue_gf_known_matches == 3
    assert home.own_venue_gf_missing == 0
    assert away.own_venue_matches == away.opp_venue_matches == 1
    assert away.own_venue_gf == away.opp_venue_ga == 0
    assert away.own_venue_ga == away.opp_venue_gf == 2
    assert away.own_venue_xgf == away.opp_venue_xga == pytest.approx(0.9)
    assert away.own_venue_xga == away.opp_venue_xgf == 1
    assert result.index.equals(target.index)


def test_more_player_rows_do_not_multiply_club_fixture_counts() -> None:
    history = _game(71, 7, CUTOFF - pd.Timedelta(days=2))
    extra = history.loc[history.player_code.eq(102)].copy()
    extra["player_code"] = 103
    extra["expected_goals"] = 0.0
    original = causal_match_context_features(history, _target(), CUTOFF)
    expanded = causal_match_context_features(pd.concat([history, extra]), _target(), CUTOFF)
    assert_frame_equal(original, expanded)


def test_target_and_future_outcomes_are_not_inspected() -> None:
    history = _history()
    target = _target(minutes="not a label", starts=object(), total_points=np.inf, kickoff="bad")
    excluded = pd.concat(
        [
            _game(81, 8, CUTOFF - pd.Timedelta(days=1)),
            _game(91, 9, CUTOFF + pd.Timedelta(days=1)),
        ]
    )
    excluded["minutes"] = "not a label"
    excluded.loc[:, "expected_goals"] = np.inf
    expected = causal_match_context_features(history, _target(), CUTOFF)
    actual = causal_match_context_features(pd.concat([history, excluded]), target, CUTOFF)
    assert_frame_equal(actual, expected)


def test_settlement_boundary_is_strict_and_window_start_inclusive() -> None:
    included = _game(71, 7, CUTOFF - pd.Timedelta(hours=3, seconds=1))
    excluded = _game(72, 7, CUTOFF - pd.Timedelta(hours=3))
    excluded["starts"] = "not a label"
    result = causal_match_context_features(pd.concat([included, excluded]), _target(), CUTOFF)
    assert result.iloc[0].own_pl_observed_fixtures == 1
    assert result.iloc[0].player_pl_7d_minutes == 90
    boundary = _game(73, 7, CUTOFF - pd.Timedelta(days=14))
    result = causal_match_context_features(boundary, _target(), CUTOFF).iloc[0]
    assert result.player_pl_14d_observations == 1
    assert result.player_pl_7d_observations == 0
    assert result.own_pl_14d_fixtures == 1
    assert result.own_pl_7d_fixtures == 0
    assert result.own_pl_match_history_missing == 0


def test_other_season_is_not_workload_or_venue_evidence() -> None:
    old = _game(71, 7, CUTOFF - pd.Timedelta(days=1), season="2024-25")
    current = _history()
    actual = causal_match_context_features(pd.concat([current, old]), _target(), CUTOFF)
    expected = causal_match_context_features(current, _target(), CUTOFF)
    assert_frame_equal(actual, expected)


def test_each_target_week_has_its_own_entire_gameweek_exclusion() -> None:
    history = _history()
    target = pd.concat([_target(GW=7), _target(GW=8, fixture=998)]).set_axis([43, 17])
    result = causal_match_context_features(history, target, CUTOFF)
    assert result.iloc[0].own_pl_observed_fixtures == 3
    assert result.iloc[1].own_pl_observed_fixtures == 4
    assert result.iloc[0].player_pl_7d_minutes == 45
    assert result.iloc[1].player_pl_7d_minutes == 135


def test_no_known_start_labels_are_not_inferred_from_full_minutes() -> None:
    history = _game(71, 7, CUTOFF - pd.Timedelta(days=2), changes={101: {"starts": np.nan}})
    result = causal_match_context_features(history, _target(), CUTOFF).iloc[0]
    assert result.player_pl_7d_minutes == 90
    assert result.player_pl_7d_appearances == 1
    assert result.player_pl_7d_starts == 0
    assert result.player_pl_7d_starts_known_rows == 0
    assert result.player_pl_7d_starts_missing == 1


def test_missing_minutes_and_xg_have_separate_counts_and_flags() -> None:
    history = _game(
        71,
        7,
        CUTOFF - pd.Timedelta(days=2),
        changes={101: {"minutes": np.nan}, 102: {"expected_goals": np.nan}},
    )
    result = causal_match_context_features(history, _target(), CUTOFF).iloc[0]
    assert result.player_pl_7d_minutes == result.player_pl_7d_appearances == 0
    assert result.player_pl_7d_minutes_known_rows == 0
    assert result.player_pl_7d_minutes_missing == result.player_pl_7d_appearances_missing == 1
    assert result.player_pl_7d_starts == result.player_pl_7d_starts_known_rows == 1
    assert result.own_venue_matches == 1
    assert result.own_venue_xgf == result.own_venue_xgf_known_matches == 0
    assert result.own_venue_xgf_missing == 1
    assert result.opp_venue_xga_missing == 1
    assert result.own_venue_gf == 2
    assert result.own_venue_gf_known_matches == 1
    assert result.own_venue_gf_missing == 0


def test_partial_score_labels_preserve_known_team_scores_and_unknown_metrics() -> None:
    first = _game(71, 7, CUTOFF - pd.Timedelta(days=2))
    first.loc[first.player_code.eq(102), "team_goals"] = np.nan
    second = _game(61, 6, CUTOFF - pd.Timedelta(days=6))
    second.loc[second.club.eq(10), "team_goals"] = np.nan
    result = causal_match_context_features(pd.concat([first, second]), _target(), CUTOFF).iloc[0]
    assert result.own_venue_matches == 2
    assert result.own_venue_gf == 2
    assert result.own_venue_gf_known_matches == 1
    assert result.own_venue_gf_missing == 1
    assert result.opp_venue_ga_known_matches == 2
    assert result.opp_venue_ga_missing == 0
    assert result.own_venue_ga_known_matches == 2
    assert result.own_venue_ga_missing == 0


def test_transferred_player_workload_uses_player_identity_and_club_context_stays_separate() -> None:
    history = _history()
    old_club = _game(31, 3, CUTOFF - pd.Timedelta(days=3))
    old_club["club"] = old_club.club.replace({10: 30, 20: 40})
    old_club["opponent"] = old_club.opponent.replace({10: 30, 20: 40})
    old_club.loc[old_club.player_code.eq(102), "player_code"] = 302
    old_club.loc[old_club.player_code.eq(201), "player_code"] = 401
    old_club.loc[old_club.player_code.eq(202), "player_code"] = 402
    result = causal_match_context_features(pd.concat([history, old_club]), _target(), CUTOFF)
    assert result.iloc[0].player_pl_7d_minutes == 225
    assert result.iloc[0].own_pl_7d_fixtures == 2
    assert result.iloc[0].own_pl_observed_fixtures == 4


def test_cold_start_has_explicit_missingness_and_finite_output() -> None:
    result = causal_match_context_features(_history().iloc[:0], _target(), CUTOFF)
    row = result.iloc[0]
    assert result.index.equals(_target().index)
    assert tuple(result.columns) == CONTEXT_FEATURES
    assert np.isfinite(result.to_numpy()).all()
    assert row.player_pl_7d_minutes == row.player_pl_7d_observations == 0
    assert row.player_pl_7d_minutes_missing == row.player_pl_7d_starts_missing == 1
    assert row.own_pl_days_since_match == row.own_pl_observed_fixtures == 0
    assert row.own_pl_match_history_missing == row.own_venue_gf_missing == 1
    assert row.own_venue_matches == row.own_venue_gf_known_matches == 0
    assert_frame_equal(result, causal_match_context_features(pd.DataFrame(), _target(), CUTOFF))
    empty_target = _target().iloc[:0]
    empty = causal_match_context_features(pd.DataFrame(), empty_target, CUTOFF)
    assert empty.empty and tuple(empty.columns) == CONTEXT_FEATURES
    assert empty.index.equals(empty_target.index)


def test_duplicate_target_indices_preserve_order_without_sharing_player_context() -> None:
    target = pd.concat([_target(), _target(fixture=998, player_code=102)])
    result = causal_match_context_features(_history(), target, CUTOFF)
    assert result.index.equals(target.index)
    assert result.iloc[0].player_pl_7d_minutes == 135
    assert result.iloc[1].player_pl_7d_minutes == 0


def test_integer_player_identity_is_not_rounded_through_a_float() -> None:
    player = 2**53 + 1
    history = _game(71, 7, CUTOFF - pd.Timedelta(days=2))
    history.loc[history.player_code.eq(101), "player_code"] = player
    history.loc[history.player_code.eq(102), "player_code"] = player - 1
    result = causal_match_context_features(history, _target(player_code=player), CUTOFF)
    assert result.iloc[0].player_pl_7d_minutes == 90


def test_feature_metadata_is_exact_fresh_and_covers_the_emitted_columns() -> None:
    first = match_context_feature_metadata()
    second = match_context_feature_metadata()
    assert first == second
    assert first["contract"] == MATCH_CONTEXT_FEATURE_CONTRACT
    assert first["features"] == list(CONTEXT_FEATURES)
    assert first["team_features"] == list(CONTEXT_TEAM_FEATURES)
    assert len(CONTEXT_FEATURES) == len(set(CONTEXT_FEATURES)) == 56
    assert len(CONTEXT_TEAM_FEATURES) == 36
    assert first["all_competition_coverage"] is False
    assert first["target_outcomes"] == "never_read"
    assert first["gameweek_filter"] == "history_gameweek_strictly_before_target_gameweek"
    assert first["settlement_boundary"] == "kickoff_plus_lag_strictly_before_cutoff"
    first["features"] = []
    first["venue_conditioning"] = {}
    assert match_context_feature_metadata() == second
    for column in CONTEXT_TEAM_FEATURES:
        counterpart = (
            column.replace("own_", "opp_", 1)
            if column.startswith("own_")
            else column.replace("opp_", "own_", 1)
        )
        assert counterpart in CONTEXT_TEAM_FEATURES


@pytest.mark.parametrize("cutoff", [pd.Timestamp("2026-10-09"), pd.NaT, "2026-10-09T12:00Z"])
def test_invalid_cutoff_refuses(cutoff: Any) -> None:
    with pytest.raises(ValueError, match="cutoff"):
        causal_match_context_features(_history(), _target(), cutoff)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("player_code", True),
        ("club", 0),
        ("opponent", np.inf),
        ("fixture", 1.2),
        ("GW", 39),
        ("season", "2026-28"),
        ("season", "2026/27"),
        ("home", True),
        ("home", 0.5),
    ],
)
def test_invalid_target_identity_refuses(field: str, value: Any) -> None:
    with pytest.raises(ValueError, match=field if field != "season" else "season"):
        causal_match_context_features(_history(), _target(**{field: value}), CUTOFF)


@pytest.mark.parametrize("field", ["minutes", "starts", "team_goals", "expected_goals"])
def test_infinite_known_history_labels_refuse(field: str) -> None:
    history = _history()
    history.loc[0, field] = np.inf
    with pytest.raises(ValueError, match=field):
        causal_match_context_features(history, _target(), CUTOFF)


@pytest.mark.parametrize(
    ("field", "value"),
    [("minutes", 121), ("starts", 0.75), ("team_goals", 1.5), ("expected_goals", -1)],
)
def test_unsupported_recorded_labels_refuse(field: str, value: float) -> None:
    history = _history()
    history.loc[0, field] = value
    with pytest.raises(ValueError, match=field):
        causal_match_context_features(history, _target(), CUTOFF)


@pytest.mark.parametrize("kind", ["history", "target"])
def test_duplicate_player_fixture_identity_refuses(kind: str) -> None:
    history, target = _history(), _target()
    if kind == "history":
        history = pd.concat([history, history.iloc[[0]]])
    else:
        target = pd.concat([target, target])
    with pytest.raises(ValueError, match="repeats a player-fixture"):
        causal_match_context_features(history, target, CUTOFF)


@pytest.mark.parametrize(
    ("field", "value", "reason"),
    [
        ("opponent", 30, "opponent"),
        ("home", 0.0, "venues"),
        ("team_goals", 7.0, "scores"),
        ("GW", 6, "fixture identity"),
        ("kickoff", CUTOFF - pd.Timedelta(days=3), "fixture identity"),
    ],
)
def test_inconsistent_club_fixture_rows_refuse(field: str, value: Any, reason: str) -> None:
    history = _game(71, 7, CUTOFF - pd.Timedelta(days=2))
    history.loc[0, field] = value
    with pytest.raises(ValueError, match=reason):
        causal_match_context_features(history, _target(), CUTOFF)


def test_inconsistent_paired_scores_refuse() -> None:
    history = _game(71, 7, CUTOFF - pd.Timedelta(days=2))
    history.loc[history.club.eq(10), "team_goals"] = 7
    with pytest.raises(ValueError, match="paired club scores"):
        causal_match_context_features(history, _target(), CUTOFF)


def test_unpaired_club_history_refuses_instead_of_inventing_opponent_xg() -> None:
    history = _game(71, 7, CUTOFF - pd.Timedelta(days=2))
    with pytest.raises(ValueError, match="paired-club"):
        causal_match_context_features(history.loc[history.club.eq(10)], _target(), CUTOFF)


def test_naive_history_timestamp_refuses() -> None:
    history = _game(71, 7, CUTOFF - pd.Timedelta(days=2))
    history["kickoff"] = pd.Timestamp("2026-10-07T12:00:00")
    with pytest.raises(ValueError, match="kickoff"):
        causal_match_context_features(history, _target(), CUTOFF)


def test_target_fixture_identity_conflict_refuses() -> None:
    target = pd.concat([_target(), _target(player_code=102, opponent=30)])
    with pytest.raises(ValueError, match="target club-fixture"):
        causal_match_context_features(_history(), target, CUTOFF)


def test_inputs_are_not_mutated() -> None:
    history, target = _history(), _target()
    before_history, before_target = history.copy(deep=True), target.copy(deep=True)
    causal_match_context_features(history, target, CUTOFF)
    assert_frame_equal(history, before_history)
    assert_frame_equal(target, before_target)
