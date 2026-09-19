"""The chip forecast runner's rule of two sets, and its count of what expired."""

from scripts.measure_chip_forecast_rule import (
    ARMS,
    COMPARISONS,
    HISTORY_SEASONS,
    expired_chips,
    two_set_windows,
)

from squadopt.experiments.season_chain_runs import LOCKED_HOLDOUT_SEASON


def test_every_chip_has_one_window_per_half_as_this_season_states_them() -> None:
    windows = two_set_windows()
    spans = {(w.name, w.start_gameweek, w.stop_gameweek) for w in windows}
    assert spans == {
        ("wildcard", 2, 19),
        ("wildcard", 20, 38),
        ("freehit", 2, 19),
        ("freehit", 20, 38),
        ("bboost", 1, 19),
        ("bboost", 20, 38),
        ("3xc", 1, 19),
        ("3xc", 20, 38),
    }
    # A gameweek belongs to exactly one window of each chip.
    for name in ("wildcard", "freehit", "bboost", "3xc"):
        for gameweek in range(2, 39):
            assert sum(w.covers(gameweek) for w in windows if w.name == name) == 1


def test_a_window_that_closed_with_its_chip_unplayed_is_counted_once() -> None:
    windows = two_set_windows()
    record = {
        "gameweeks": list(range(2, 39)),
        "chips_played": {"9": "bboost", "25": "bboost", "30": "3xc", "4": "wildcard"},
    }
    assert expired_chips(record, windows) == [
        "wildcard:20-38",
        "freehit:2-19",
        "freehit:20-38",
        "3xc:1-19",
    ]
    # A chain that stopped at gameweek 19 never reached the second half, so nothing of the
    # second half is called expired.
    first_half = {"gameweeks": list(range(2, 20)), "chips_played": {"9": "bboost"}}
    assert expired_chips(first_half, windows) == ["wildcard:2-19", "freehit:2-19", "3xc:1-19"]


def test_the_holdout_is_never_loaded_and_the_arms_are_the_protocols() -> None:
    assert LOCKED_HOLDOUT_SEASON not in HISTORY_SEASONS
    assert ARMS == ("off", "planner", "fixed", "decaying", "threshold_only")
    assert ("decaying", "threshold_only") in COMPARISONS
    assert COMPARISONS[0] == ("decaying", "fixed")
