"""Synthetic tests for the season-long decision chain.

The chain carries one squad through every decision gameweek. What must hold: the
walk covers the season's decision points in order, state is carried (squad, bank,
free transfers, purchase prices, spent chips), a chip is spent at most once inside its
window and changes what is realized, a blank or a data hole is carried rather than
fatal, and the whole thing is deterministic.
"""

import pandas as pd
import pytest
from tests.fixtures.synthetic_gameweeks import SEASON, TEAM_COUNT, make_canonical_gameweeks

from squadopt.experiments import (
    ChipWindowRule,
    ExperimentConfigurationError,
    MultiGwRehearsal,
    MultiGwRehearsalConfig,
    SeasonChain,
    SeasonChainConfig,
    SeasonChainResult,
)
from squadopt.experiments.multi_gw_rehearsal import WeekRealization
from squadopt.optimization import optimize_squad
from squadopt.planning import InitialSquadState, sell_price_tenths

POOL = {"candidate_pool_per_position": 10, "cheap_pool_per_position": 2}
ALL_CHIPS = (
    ChipWindowRule("bboost", 2, 8),
    ChipWindowRule("3xc", 2, 8),
    ChipWindowRule("wildcard", 2, 4),
    ChipWindowRule("wildcard", 5, 8),
)


def _fixture_counts() -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for gameweek in range(1, 9):
        for team_id in range(1, TEAM_COUNT + 1):
            count = 1
            if gameweek == 4 and team_id == 1:
                count = 2
            if gameweek == 4 and team_id == 6:
                count = 0
            rows.append({"gameweek": gameweek, "team_id": team_id, "fixture_count": count})
    return pd.DataFrame(rows)


def _run(panel: pd.DataFrame | None = None, **overrides: object) -> SeasonChainResult:
    settings = SeasonChainConfig(season=SEASON, **POOL, **overrides)  # type: ignore[arg-type]
    frame = make_canonical_gameweeks() if panel is None else panel
    return SeasonChain(frame, _fixture_counts(), settings).run()


@pytest.fixture(scope="module")
def myopic() -> SeasonChainResult:
    return _run()


@pytest.fixture(scope="module")
def chipped() -> SeasonChainResult:
    return _run(lookahead=2, chip_windows=ALL_CHIPS)


def test_the_chain_walks_every_decision_gameweek_in_order(myopic: SeasonChainResult) -> None:
    assert myopic.gameweeks == tuple(range(2, 9))
    assert myopic.lookahead == 1 and not myopic.chips_enabled
    assert len(myopic.opening_squad_ids) == 15
    assert myopic.net_points == myopic.realized_points - myopic.transfer_hit_points
    assert myopic.chips_played == {} and myopic.chip_realized_gains == {}
    assert all(week.lookahead_gameweeks == 1 for week in myopic.weeks)
    assert all(week.chip is None and week.planned_chips == {} for week in myopic.weeks)
    assert myopic.proven_share == 1.0
    assert myopic.diagnostics["projection_rule"] == "naive_calendar_scaling_v1"


def test_state_is_carried_from_one_week_to_the_next(myopic: SeasonChainResult) -> None:
    previous = myopic.opening_squad_ids
    for week in myopic.weeks:
        assert len(week.squad_player_ids) == 15
        changed = len(set(week.squad_player_ids) ^ set(previous)) // 2
        assert changed == week.transfer_count
        assert week.paid_transfer_count == max(0, week.transfer_count - week.free_transfers_before)
        assert week.transfer_hit_points == 4.0 * week.paid_transfer_count
        assert week.squad_sell_value_tenths > 0
        previous = week.squad_player_ids
    for earlier, later in zip(myopic.weeks, myopic.weeks[1:], strict=False):
        assert later.free_transfers_before == earlier.free_transfers_after


def test_the_chain_is_deterministic(myopic: SeasonChainResult) -> None:
    again = _run()
    assert [week.as_record() for week in again.weeks] == [week.as_record() for week in myopic.weeks]


def test_the_first_chain_week_is_the_rehearsal_myopic_first_week() -> None:
    """Same pool, same opening squad, same decision: the chain starts where the
    rehearsal's myopic baseline starts, before the pool refresh and the sell rule
    make the two walks diverge."""

    rehearsal = MultiGwRehearsal(
        make_canonical_gameweeks(),
        _fixture_counts(),
        MultiGwRehearsalConfig(season=SEASON, horizon_length=2, **POOL),
    )
    pool = rehearsal._candidate_pool(rehearsal._projection_at(3))
    opening = optimize_squad(pool, rehearsal._settings.frozen_optimization_config)
    assert opening.total_cost_tenths is not None
    state = InitialSquadState(
        tuple(opening.selected_squad["player_id"].tolist()),
        bank_tenths=1000 - int(opening.total_cost_tenths),
        free_transfers=1,
    )
    baseline = rehearsal._score_rolling(pool, state, (3,), lookahead=1)

    chain = _run(start_gameweek=3, end_gameweek=4, sell_on_fee_halved=False)

    assert chain.gameweeks == (3, 4)
    assert chain.opening_squad_ids == state.squad_player_ids
    assert chain.weeks[0].realized_points == baseline.realized_points
    assert chain.weeks[0].transfer_hit_points == baseline.hit_points


def test_chips_are_spent_at_most_once_per_window_and_recorded(
    chipped: SeasonChainResult,
) -> None:
    assert chipped.chips_enabled and chipped.lookahead == 2
    played = chipped.chips_played
    names = list(played.values())
    assert names.count("bboost") <= 1 and names.count("3xc") <= 1
    assert names.count("wildcard") <= 2
    assert sum(1 for week, name in played.items() if name == "wildcard" and week <= 4) <= 1
    assert sum(1 for week, name in played.items() if name == "wildcard" and week >= 5) <= 1
    for week in chipped.weeks:
        if week.chip is not None:
            assert week.planned_chips.get(week.gameweek) == week.chip
        if week.chip == "wildcard":
            assert week.paid_transfer_count == 0 and week.transfer_hit_points == 0.0
    assert set(chipped.chip_realized_gains) == set(names)
    used = list(chipped.diagnostics["final_state"]["used_chips"])  # type: ignore[index]
    assert len(used) == len(played)
    assert all(
        week.lookahead_gameweeks == (2 if week.gameweek < 8 else 1) for week in chipped.weeks
    )


def test_a_played_bench_boost_realizes_the_bench(chipped: SeasonChainResult) -> None:
    """Whatever the planner chose, the realized sheet must reflect the chip played."""

    for week in chipped.weeks:
        if week.chip == "bboost":
            assert week.bench_realized_points == chipped.chip_realized_gains["bboost"]
        if week.chip == "3xc":
            assert week.captain_realized_points == chipped.chip_realized_gains["3xc"]


def test_week_realization_applies_chips_to_what_counts() -> None:
    realization = WeekRealization(starters_points=50.0, captain_points=8.0, bench_points=6.0)
    assert realization.total() == 58.0
    assert realization.total("bboost") == 64.0
    assert realization.total("3xc") == 66.0
    assert realization.total("wildcard") == 58.0


def test_a_closed_chip_window_is_not_offered() -> None:
    result = _run(chip_windows=(ChipWindowRule("wildcard", 2, 3),))
    assert all(week <= 3 for week, name in result.chips_played.items() if name == "wildcard")
    for week in result.weeks:
        if week.gameweek > 3:
            assert week.planned_chips == {}


def test_the_reservation_policy_offers_boost_and_captain_only_in_double_gameweeks() -> None:
    """Gameweek 4 is the synthetic season's only double; the wildcard stays free."""

    result = _run(lookahead=2, chip_windows=ALL_CHIPS, chip_policy="double_gameweeks_only")

    for week in result.weeks:
        for planned_week, name in week.planned_chips.items():
            if name in {"bboost", "3xc"}:
                assert planned_week == 4
    assert result.diagnostics["chip_policy"] == "double_gameweeks_only"


def test_free_hit_is_refused_in_chip_windows() -> None:
    with pytest.raises(ExperimentConfigurationError, match="Unknown chip"):
        ChipWindowRule("freehit", 1, 38)
    with pytest.raises(ExperimentConfigurationError, match="may not end before"):
        ChipWindowRule("bboost", 5, 4)


@pytest.mark.parametrize(
    ("current", "purchase", "fee", "expected"),
    [
        (53, 50, 0.5, 51),
        (52, 50, 0.5, 51),
        (51, 50, 0.5, 50),
        (49, 50, 0.5, 49),
        (53, 50, 0.0, 53),
        (53, 50, 1.0, 50),
    ],
)
def test_the_sell_price_rule_halves_a_rise_and_keeps_a_fall(
    current: int, purchase: int, fee: float, expected: int
) -> None:
    assert sell_price_tenths(current, purchase, sell_on_fee=fee) == expected


def test_a_blank_squad_member_is_carried_at_zero(myopic: SeasonChainResult) -> None:
    """The archive holds no row for a blank team; the squad still holds the player."""

    panel = make_canonical_gameweeks()
    absent = panel.loc[~((panel["gameweek"] == 4) & (panel["team_id"] == 6))]
    team_of = dict(zip(panel["player_id"].tolist(), panel["team_id"].tolist(), strict=True))

    result = _run(panel=absent)

    before = next(week for week in result.weeks if week.gameweek == 3)
    at_blank = next(week for week in result.weeks if week.gameweek == 4)
    held_blank = sum(1 for player in before.squad_player_ids if team_of[player] == 6)
    assert at_blank.carried_blank_rows == held_blank
    assert at_blank.carried_unexplained_rows == 0
    assert result.gameweeks == myopic.gameweeks


def test_a_squad_member_missing_without_a_blank_is_carried_and_counted(
    myopic: SeasonChainResult,
) -> None:
    """A hole is not fatal over a season, but it is counted so the reader sees it."""

    before = next(week for week in myopic.weeks if week.gameweek == 3)
    victim = int(before.squad_player_ids[0])
    panel = make_canonical_gameweeks()
    holed = panel.loc[~((panel["gameweek"] == 4) & (panel["player_id"] == victim))]

    result = _run(panel=holed)

    at_hole = next(week for week in result.weeks if week.gameweek == 4)
    assert at_hole.carried_unexplained_rows == 1


def test_a_planning_hit_cost_is_a_threshold_and_the_charge_stays_the_rule(
    myopic: SeasonChainResult,
) -> None:
    from squadopt.planning import TransferPlanningConfig

    strict = _run(transfer_config=TransferPlanningConfig(transfer_hit_cost_points=8.0))

    paid_strict = sum(week.paid_transfer_count for week in strict.weeks)
    paid_rule = sum(week.paid_transfer_count for week in myopic.weeks)
    assert paid_strict <= paid_rule
    assert strict.transfer_hit_points == 4.0 * paid_strict
    assert strict.diagnostics["planning_hit_cost_points"] == 8.0
    assert strict.diagnostics["hit_points_charged"] == 4.0
    assert myopic.diagnostics["max_transfers_per_gameweek"] is None


def test_the_calendar_blind_rule_projects_a_double_like_a_single(myopic: SeasonChainResult) -> None:
    """Gameweek 4 doubles team 1 and blanks team 6: scaled, team 1 projects twice; blind,
    once — and a blank projects zero under both rules."""

    from squadopt.experiments import CALENDAR_BLIND_PROJECTION_RULE

    blind = _run(projection_rule=CALENDAR_BLIND_PROJECTION_RULE)
    assert blind.diagnostics["projection_rule"] == CALENDAR_BLIND_PROJECTION_RULE
    assert myopic.diagnostics["projection_rule"] == "naive_calendar_scaling_v1"

    chain = SeasonChain(
        make_canonical_gameweeks(),
        _fixture_counts(),
        SeasonChainConfig(season=SEASON, projection_rule=CALENDAR_BLIND_PROJECTION_RULE, **POOL),
    )
    pool = chain._candidate_pool(chain._projection_at(4))
    horizon = chain._naive_horizon(pool, (4,)).table
    scaled = SeasonChain(
        make_canonical_gameweeks(), _fixture_counts(), SeasonChainConfig(season=SEASON, **POOL)
    )
    scaled_horizon = scaled._naive_horizon(pool, (4,)).table
    doubles = horizon["team_id"] == 1
    blanks = horizon["team_id"] == 6
    assert (horizon.loc[doubles, "expected_points"] * 2).tolist() == pytest.approx(
        scaled_horizon.loc[doubles, "expected_points"].tolist()
    )
    assert horizon.loc[blanks, "expected_points"].eq(0.0).all()
    assert scaled_horizon.loc[blanks, "expected_points"].eq(0.0).all()
    with pytest.raises(ExperimentConfigurationError):
        SeasonChainConfig(season=SEASON, projection_rule="oracle")


def test_a_lookahead_is_truncated_at_the_last_decision_gameweek() -> None:
    result = _run(lookahead=3, start_gameweek=5)
    assert [week.lookahead_gameweeks for week in result.weeks] == [3, 3, 2, 1]


def test_a_lookahead_stops_at_a_gameweek_the_season_never_played() -> None:
    panel = make_canonical_gameweeks()
    without_gw6 = panel.loc[panel["gameweek"] != 6]
    result = _run(panel=without_gw6, lookahead=3, start_gameweek=4)
    assert result.gameweeks == (4, 5, 7, 8)
    assert [week.lookahead_gameweeks for week in result.weeks] == [2, 1, 2, 1]


@pytest.mark.parametrize(
    "overrides",
    [
        {"lookahead": 0},
        {"start_gameweek": 6, "end_gameweek": 4},
        {"chip_windows": ("bboost",)},
        {"sell_on_fee_halved": "yes"},
        {"chip_policy": "always"},
    ],
)
def test_invalid_chain_configs_are_refused(overrides: dict[str, object]) -> None:
    with pytest.raises(ExperimentConfigurationError):
        SeasonChainConfig(season=SEASON, **overrides)  # type: ignore[arg-type]


def test_a_range_outside_the_season_is_refused() -> None:
    with pytest.raises(Exception, match="No decision gameweek"):
        SeasonChain(
            make_canonical_gameweeks(),
            _fixture_counts(),
            SeasonChainConfig(season=SEASON, start_gameweek=20, **POOL),
        ).run()
