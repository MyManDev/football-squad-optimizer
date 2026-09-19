"""The chip forecast runner's rule of two sets, its count of what expired, and its rereading."""

import json

import pytest
from scripts.measure_chip_forecast_rule import (
    ARMS,
    COMPARISONS,
    DERIVED_CHAIN_KEYS,
    HISTORY_SEASONS,
    _expiries,
    expired_chips,
    max_relative_gap,
    recompute,
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


def _chain(variant: str, gaps: list[float | None]) -> dict[str, object]:
    return {
        "season": "2021-22",
        "variant": variant,
        "net_points": 2000.0,
        "transfer_hit_points": 100.0,
        "proven_share": 1.0,
        "mean_relative_gap": 0.0,
        "gameweeks": [2, 3, 4],
        "chips_played": {},
        "weeks": [
            {"gameweek": week, "net_points": 50.0, "relative_gap": gap}
            for week, gap in enumerate(gaps, start=2)
        ],
    }


def test_the_widest_weekly_gap_is_the_one_a_reader_needs() -> None:
    """The mean counts proved weeks as zeros, so a bad week hides inside it."""

    assert max_relative_gap(_chain("fixed", [0.0, 0.0, 0.3])) == pytest.approx(0.3)
    assert max_relative_gap(_chain("fixed", [0.0, 0.0, 0.0])) == 0.0
    # A week that states no gap at all is absent, never a zero.
    assert max_relative_gap(_chain("fixed", [None, None, None])) is None
    assert max_relative_gap({"weeks": []}) is None


def test_recomputing_reads_the_chains_again_and_never_changes_one() -> None:
    record = {
        "contract_version": "chip_forecast_rule_v1",
        "created_utc": "2026-09-19T12:41:35+00:00",
        "chains": [_chain("fixed", [0.0, 0.2, 0.0]), _chain("decaying", [0.0, 0.0, 0.0])],
        "comparisons": [],
    }
    before = json.loads(json.dumps(record))
    again = recompute(record, resamples=50, block_length=2)

    # The walk keeps its own identity and the reading says it came later.
    assert again["created_utc"] == before["created_utc"]
    assert "recomputed_utc" in again and "recomputed_utc" not in before
    # Every chain is the one that was walked, plus the derived gap and nothing else.
    for walked, read in zip(before["chains"], again["chains"], strict=True):
        assert {k: v for k, v in read.items() if k not in DERIVED_CHAIN_KEYS} == walked
    assert again["chains"][0]["max_relative_gap"] == pytest.approx(0.2)
    assert again["bootstrap"] == {
        "resamples": 50,
        "block_length": 2,
        "interval_level": 0.90,
        "unit": "gameweek, resampled in blocks within season",
    }
    # Reading a record twice reads the same chains twice.
    twice = recompute(again, resamples=50, block_length=2)
    assert [{k: v for k, v in c.items()} for c in twice["chains"]] == [
        {k: v for k, v in c.items()} for c in again["chains"]
    ]


def test_the_adopted_arm_is_compared_with_the_arm_it_displaces() -> None:
    """Without this pair the rule the verdicts adopt is never read against the highest net."""

    assert ("threshold_only", "fixed") in COMPARISONS
    assert COMPARISONS[0] == ("decaying", "fixed")
    assert ("decaying", "threshold_only") in COMPARISONS


def test_an_arm_that_was_never_offered_a_chip_does_not_read_as_one_that_lost_none() -> None:
    """`off` runs with no windows, so `none` would put it beside the arms that played all eight."""

    assert _expiries({"variant": "off", "chip_windows_offered": False, "expired_chips": []}) == (
        "n/a, no chip was offered"
    )
    assert _expiries({"chip_windows_offered": True, "expired_chips": []}) == "none"
    assert (
        _expiries({"chip_windows_offered": True, "expired_chips": ["bboost:1-19"]}) == "bboost:1-19"
    )
    # A record walked before the field existed still reads correctly after a rereading.
    record = {
        "contract_version": "chip_forecast_rule_v1",
        "created_utc": "2026-09-19T12:41:35+00:00",
        "chains": [_chain("off", [0.0]), _chain("decaying", [0.0])],
        "comparisons": [],
    }
    again = recompute(record, resamples=10, block_length=2)
    assert again["chains"][0]["chip_windows_offered"] is False
    assert again["chains"][1]["chip_windows_offered"] is True
    assert set(DERIVED_CHAIN_KEYS) == {"max_relative_gap", "chip_windows_offered"}
