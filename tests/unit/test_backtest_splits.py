"""Tests for time-ordered splitting of a canonical panel."""

from itertools import pairwise

import pytest
from pandas.testing import assert_frame_equal
from tests.fixtures.synthetic_gameweeks import (
    GAMEWEEK_COUNT,
    PREVIOUS_SEASON,
    SEASON,
    make_canonical_gameweeks,
    make_two_season_gameweeks,
)

from squadopt.backtest import (
    BacktestConfigurationError,
    DecisionPoint,
    realized_points_at,
    rows_before,
    rows_through,
    season_ranks,
    walk_forward_decision_points,
)

# --- decision points --------------------------------------------------------


def test_fold_id_is_stable_and_sorts_chronologically_within_a_season() -> None:
    early = DecisionPoint(season=SEASON, gameweek=2)
    late = DecisionPoint(season=SEASON, gameweek=10)

    assert early.fold_id == f"{SEASON}-gw02"
    assert early.fold_id < late.fold_id


@pytest.mark.parametrize("season", ["", "   ", 2025, None])
def test_decision_point_rejects_a_blank_or_non_text_season(season: object) -> None:
    with pytest.raises(BacktestConfigurationError, match="season"):
        DecisionPoint(season=season, gameweek=1)  # type: ignore[arg-type]


@pytest.mark.parametrize("gameweek", [0, -1, 1.5, True, "3"])
def test_decision_point_rejects_an_unusable_gameweek(gameweek: object) -> None:
    with pytest.raises(BacktestConfigurationError, match="gameweek"):
        DecisionPoint(season=SEASON, gameweek=gameweek)  # type: ignore[arg-type]


def test_decision_point_is_frozen_and_hashable() -> None:
    point = DecisionPoint(season=SEASON, gameweek=3)

    assert point == DecisionPoint(season=SEASON, gameweek=3)
    assert len({point, DecisionPoint(season=SEASON, gameweek=3)}) == 1


# --- season ordering --------------------------------------------------------


def test_seasons_are_ranked_by_sorted_label_by_default() -> None:
    ranks = season_ranks(make_two_season_gameweeks())

    assert ranks[PREVIOUS_SEASON] < ranks[SEASON]


def test_an_explicit_season_order_overrides_the_default() -> None:
    """Unconventional labels must not depend on lexical sorting being right."""

    ranks = season_ranks(make_two_season_gameweeks(), season_order=[SEASON, PREVIOUS_SEASON])

    assert ranks[SEASON] < ranks[PREVIOUS_SEASON]


def test_an_incomplete_season_order_is_rejected() -> None:
    with pytest.raises(BacktestConfigurationError, match="does not cover seasons"):
        season_ranks(make_two_season_gameweeks(), season_order=[SEASON])


def test_a_duplicated_season_order_is_rejected() -> None:
    with pytest.raises(BacktestConfigurationError, match="duplicates"):
        season_ranks(make_two_season_gameweeks(), season_order=[SEASON, SEASON, PREVIOUS_SEASON])


# --- walk-forward decision points -------------------------------------------


def test_decision_points_are_chronological_across_seasons() -> None:
    points = walk_forward_decision_points(make_two_season_gameweeks())
    seasons = [point.season for point in points]

    assert seasons == sorted(seasons)
    assert seasons[0] == PREVIOUS_SEASON
    assert seasons[-1] == SEASON
    for earlier, later in pairwise(points):
        if earlier.season == later.season:
            assert earlier.gameweek < later.gameweek


def test_the_opening_gameweek_is_skipped_by_default() -> None:
    """Gameweek 1 has no season-scoped history, so a fold there measures the fallback."""

    points = walk_forward_decision_points(make_canonical_gameweeks())

    assert min(point.gameweek for point in points) == 2
    assert len(points) == GAMEWEEK_COUNT - 1


def test_the_opening_gameweek_can_be_included_deliberately() -> None:
    points = walk_forward_decision_points(
        make_canonical_gameweeks(), min_prior_gameweeks_in_season=0
    )

    assert min(point.gameweek for point in points) == 1
    assert len(points) == GAMEWEEK_COUNT


def test_history_is_counted_from_rows_present_not_from_gameweek_numbers() -> None:
    """A panel that starts at gameweek 5 has no history at gameweek 5."""

    panel = make_canonical_gameweeks()
    truncated = panel.loc[panel["gameweek"] >= 5].reset_index(drop=True)

    points = walk_forward_decision_points(truncated)

    assert min(point.gameweek for point in points) == 6


@pytest.mark.parametrize("minimum", [2, 3])
def test_a_larger_minimum_history_skips_more_opening_gameweeks(minimum: int) -> None:
    points = walk_forward_decision_points(
        make_canonical_gameweeks(), min_prior_gameweeks_in_season=minimum
    )

    assert min(point.gameweek for point in points) == minimum + 1


def test_restricting_seasons_keeps_a_holdout_out_of_the_decisions() -> None:
    """The holdout stays in the panel as history but produces no decisions."""

    points = walk_forward_decision_points(make_two_season_gameweeks(), seasons=[PREVIOUS_SEASON])

    assert {point.season for point in points} == {PREVIOUS_SEASON}


def test_requesting_an_absent_season_is_rejected() -> None:
    with pytest.raises(BacktestConfigurationError, match="not present in the panel"):
        walk_forward_decision_points(make_canonical_gameweeks(), seasons=["1999-00"])


@pytest.mark.parametrize("minimum", [-1, 1.5, True, "1"])
def test_an_unusable_minimum_history_is_rejected(minimum: object) -> None:
    with pytest.raises(BacktestConfigurationError, match="min_prior_gameweeks_in_season"):
        walk_forward_decision_points(
            make_canonical_gameweeks(),
            min_prior_gameweeks_in_season=minimum,  # type: ignore[arg-type]
        )


# --- the split itself -------------------------------------------------------


def test_rows_before_excludes_the_decision_gameweek_and_everything_later() -> None:
    panel = make_canonical_gameweeks()
    decision = DecisionPoint(season=SEASON, gameweek=5)

    history = rows_before(panel, decision)

    assert history["gameweek"].max() == 4
    assert not (history["gameweek"] >= 5).any()


def test_rows_through_includes_the_decision_gameweek_but_nothing_later() -> None:
    panel = make_canonical_gameweeks()
    decision = DecisionPoint(season=SEASON, gameweek=5)

    visible = rows_through(panel, decision)

    assert visible["gameweek"].max() == 5
    assert not (visible["gameweek"] > 5).any()


def test_the_split_carries_earlier_seasons_as_history() -> None:
    panel = make_two_season_gameweeks()
    decision = DecisionPoint(season=SEASON, gameweek=2)

    history = rows_before(panel, decision)

    assert set(history["season"].unique()) == {PREVIOUS_SEASON, SEASON}
    assert history.loc[history["season"] == SEASON, "gameweek"].max() == 1
    assert history.loc[history["season"] == PREVIOUS_SEASON, "gameweek"].max() == GAMEWEEK_COUNT


def test_the_split_excludes_later_seasons_entirely() -> None:
    panel = make_two_season_gameweeks()
    decision = DecisionPoint(season=PREVIOUS_SEASON, gameweek=GAMEWEEK_COUNT)

    visible = rows_through(panel, decision)

    assert set(visible["season"].unique()) == {PREVIOUS_SEASON}


def test_an_explicit_season_order_changes_which_rows_count_as_history() -> None:
    """Proves the ordering is genuinely applied rather than assumed from labels."""

    panel = make_two_season_gameweeks()
    decision = DecisionPoint(season=PREVIOUS_SEASON, gameweek=1)

    reversed_history = rows_before(panel, decision, season_order=[SEASON, PREVIOUS_SEASON])

    assert set(reversed_history["season"].unique()) == {SEASON}


def test_the_split_is_chronologically_ordered_with_a_reset_index() -> None:
    panel = make_two_season_gameweeks().iloc[::-1].reset_index(drop=True)
    decision = DecisionPoint(season=SEASON, gameweek=4)

    visible = rows_through(panel, decision)
    keys = visible.loc[:, ["season", "gameweek", "player_id"]]

    assert_frame_equal(keys, keys.sort_values(["season", "gameweek", "player_id"]))
    assert visible.index.tolist() == list(range(len(visible)))


def test_the_split_does_not_depend_on_input_row_order() -> None:
    panel = make_two_season_gameweeks()
    decision = DecisionPoint(season=SEASON, gameweek=4)

    shuffled = panel.sort_values(["player_id", "gameweek"]).reset_index(drop=True)

    assert_frame_equal(rows_through(shuffled, decision), rows_through(panel, decision))


def test_the_input_panel_is_not_mutated() -> None:
    panel = make_two_season_gameweeks()
    original = panel.copy(deep=True)

    rows_before(panel, DecisionPoint(season=SEASON, gameweek=3))
    rows_through(panel, DecisionPoint(season=SEASON, gameweek=3))
    realized_points_at(panel, DecisionPoint(season=SEASON, gameweek=3))

    assert_frame_equal(panel, original)


def test_mutating_future_rows_cannot_change_the_history_view() -> None:
    panel = make_canonical_gameweeks()
    decision = DecisionPoint(season=SEASON, gameweek=5)
    baseline = rows_before(panel, decision)

    mutated = panel.copy(deep=True)
    mutated.loc[mutated["gameweek"] >= 5, "total_points"] = 999

    assert_frame_equal(rows_before(mutated, decision), baseline)


def test_deleting_future_rows_cannot_change_the_history_view() -> None:
    panel = make_canonical_gameweeks()
    decision = DecisionPoint(season=SEASON, gameweek=5)
    baseline = rows_before(panel, decision)

    truncated = panel.loc[panel["gameweek"] < 5].reset_index(drop=True)

    assert_frame_equal(rows_before(truncated, decision), baseline)


# --- realized outcomes ------------------------------------------------------


def test_realized_points_returns_only_the_decision_gameweek() -> None:
    panel = make_canonical_gameweeks()
    decision = DecisionPoint(season=SEASON, gameweek=6)

    realized = realized_points_at(panel, decision)
    expected = (
        panel.loc[
            (panel["season"] == SEASON) & (panel["gameweek"] == 6),
            ["player_id", "total_points"],
        ]
        .sort_values("player_id")
        .reset_index(drop=True)
    )

    assert list(realized.columns) == ["player_id", "total_points"]
    assert_frame_equal(realized, expected)


def test_realized_points_are_ordered_by_player_with_a_reset_index() -> None:
    realized = realized_points_at(
        make_canonical_gameweeks(), DecisionPoint(season=SEASON, gameweek=6)
    )

    assert realized["player_id"].tolist() == sorted(realized["player_id"].tolist())
    assert realized.index.tolist() == list(range(len(realized)))


def test_realized_points_for_an_absent_gameweek_are_refused() -> None:
    with pytest.raises(BacktestConfigurationError, match="cannot score a gameweek that is absent"):
        realized_points_at(make_canonical_gameweeks(), DecisionPoint(season=SEASON, gameweek=99))


# --- guards -----------------------------------------------------------------


def test_a_panel_missing_canonical_columns_is_rejected() -> None:
    panel = make_canonical_gameweeks().drop(columns=["total_points"])

    with pytest.raises(BacktestConfigurationError, match="missing required columns"):
        walk_forward_decision_points(panel)


def test_an_empty_panel_is_rejected() -> None:
    panel = make_canonical_gameweeks().iloc[:0]

    with pytest.raises(BacktestConfigurationError, match="at least one row"):
        walk_forward_decision_points(panel)


def test_a_non_dataframe_panel_is_rejected() -> None:
    with pytest.raises(BacktestConfigurationError, match="pandas DataFrame"):
        walk_forward_decision_points([{"season": SEASON}])  # type: ignore[arg-type]


def test_a_decision_in_an_absent_season_is_rejected() -> None:
    with pytest.raises(BacktestConfigurationError, match="not present in the panel"):
        rows_before(make_canonical_gameweeks(), DecisionPoint(season="1999-00", gameweek=2))


def test_a_non_decision_point_argument_is_rejected() -> None:
    with pytest.raises(BacktestConfigurationError, match="must be a DecisionPoint"):
        rows_before(make_canonical_gameweeks(), (SEASON, 2))  # type: ignore[arg-type]


def test_the_api_exposes_no_random_split_option() -> None:
    """A random split must not be expressible: no seed, shuffle, or fraction anywhere."""

    import inspect

    from squadopt import backtest

    forbidden = {"seed", "shuffle", "random_state", "test_size", "train_size", "frac"}
    checked = 0
    for name in backtest.__all__:
        member = getattr(backtest, name)
        # Plain functions only: type aliases report as callable but have no signature.
        if not inspect.isfunction(member):
            continue
        checked += 1
        parameters = set(inspect.signature(member).parameters)
        assert not (parameters & forbidden), f"{name} exposes {parameters & forbidden}"

    assert checked >= 5, "the public surface was not actually inspected"


def test_split_views_are_disjoint_and_complete_around_the_boundary() -> None:
    """rows_before plus the decision gameweek must equal rows_through, with no overlap."""

    panel = make_two_season_gameweeks()
    decision = DecisionPoint(season=SEASON, gameweek=4)

    history = rows_before(panel, decision)
    visible = rows_through(panel, decision)
    at_decision = panel.loc[
        (panel["season"] == decision.season) & (panel["gameweek"] == decision.gameweek)
    ]

    assert len(history) + len(at_decision) == len(visible)
    assert not (
        (history["season"] == decision.season) & (history["gameweek"] == decision.gameweek)
    ).any()


def test_a_single_gameweek_panel_yields_no_decisions() -> None:
    panel = make_canonical_gameweeks()
    one_gameweek = panel.loc[panel["gameweek"] == 1].reset_index(drop=True)

    assert walk_forward_decision_points(one_gameweek) == ()


def test_repeated_calls_are_deterministic() -> None:
    panel = make_two_season_gameweeks()

    assert walk_forward_decision_points(panel) == walk_forward_decision_points(panel)
