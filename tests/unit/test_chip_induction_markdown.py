"""The record states its own verdict, and its threshold table is ordered by the renderer.

Both are failures a reader meets rather than a number being wrong. The verdict lived only in
the index row and the pull request, and the threshold table inherited its order from a mapping
that `write_json` had sorted as text, so a table whose point is a threshold falling across a
window read 1, 10, 11 ... 19, 2, 3 once it was re-rendered from disk.
"""

from typing import Any

from scripts.measure_chip_threshold_induction import (
    _markdown,
    _stage_two_verdict,
    _threshold_table,
)


def _stage_two(lower: float, upper: float, seasons: dict[str, float]) -> dict[str, Any]:
    return {
        "deciding_comparison": "induction_minus_threshold_only",
        "comparisons": [
            {
                "variant": "induction",
                "baseline": "decaying",
                "weekly_advantage_block_bootstrap_interval": [-9.0, 9.0],
                "season_net_advantage_points": seasons,
            },
            {
                "variant": "induction",
                "baseline": "threshold_only",
                "weekly_advantage_block_bootstrap_interval": [lower, upper],
                "season_net_advantage_points": seasons,
            },
        ],
    }


BEHIND = {"2021-22": -11.0, "2022-23": -33.0, "2023-24": 67.0, "2024-25": -2.0}


def test_an_interval_containing_zero_states_the_verdict_the_protocol_fixed() -> None:
    text = "\n".join(_stage_two_verdict(_stage_two(-1.286, 1.252, BEHIND)))
    assert "Verdict: `not separated`" in text
    assert "the linear decay stays" in text
    # It names the comparison that decided, which is not the one the runner once hard-coded.
    assert "`induction` minus `threshold_only`" in text
    assert "decaying - threshold_only" in text


def test_an_interval_above_zero_does_not_state_that_verdict() -> None:
    text = "\n".join(_stage_two_verdict(_stage_two(0.5, 2.0, BEHIND)))
    assert "not separated" not in text
    assert "entirely above zero" in text
    # A bound touching zero is not above it, so the verdict must come back.
    touching = "\n".join(_stage_two_verdict(_stage_two(0.0, 2.0, BEHIND)))
    assert "Verdict: `not separated`" in touching


def test_the_reader_is_sent_to_the_seasons_before_the_mean() -> None:
    text = "\n".join(_stage_two_verdict(_stage_two(-1.286, 1.252, BEHIND)))
    assert "behind in 3 of 4 seasons" in text
    assert "2021-22, 2022-23, 2024-25" in text
    # With every season ahead there is no such caveat to make.
    ahead = _stage_two(0.5, 2.0, {"2021-22": 5.0, "2022-23": 7.0})
    assert "The mean is not what the seasons did" not in "\n".join(_stage_two_verdict(ahead))


def test_the_threshold_table_is_ordered_numerically_whatever_the_mapping_offers() -> None:
    """The record comes back from JSON with its gameweek keys sorted as text."""

    record = {
        "thresholds": {
            "2021-22": [
                {
                    "chip": "bboost",
                    "start_gameweek": 1,
                    "stop_gameweek": 19,
                    "pooled_fallback_kinds": [],
                    "thresholds": {"1": 26.61, "10": 23.94, "2": 26.37, "9": 24.10},
                    "linear_decay": {"1": 18.89, "10": 10.0, "2": 17.89, "9": 11.0},
                }
            ]
        }
    }
    gameweeks = [
        line.split("|")[4].strip() for line in _threshold_table(record) if "bboost" in line
    ]
    assert gameweeks == ["1", "2", "9", "10"]


def test_a_seasons_chips_are_listed_in_the_order_they_were_played() -> None:
    """The same mapping-keyed-by-gameweek trap, in the stage 2 chains table.

    A reader takes a comma-separated list of gameweeks as chronology. Sorted as text it reads
    GW13, GW2, GW20, GW3, which is not one and does not announce that it is not one.
    """

    record = {
        "contract_version": "x",
        "prereg": "y",
        "seasons": ["2021-22"],
        "source_arm": "decaying",
        "source_record": "z",
        "source_created_utc": None,
        "covered_chips": [],
        "gameweek_kinds": {},
        "replay": [],
        "replay_agrees_everywhere": False,
        "unpriced_gameweeks_total": 0,
        "thresholds": {},
        "stage_two": {
            "deciding_comparison": "induction_minus_threshold_only",
            "chains": [
                {
                    "season": "2021-22",
                    "variant": "induction",
                    "net_points": 2045.0,
                    "chips_played": {"13": "freehit", "2": "bboost", "20": "wildcard", "3": "3xc"},
                    "expired_chips": [],
                }
            ],
            "comparisons": [
                {
                    "variant": "induction",
                    "baseline": "threshold_only",
                    "mean_season_net_advantage_points": 5.25,
                    "mean_weekly_advantage_points": 0.14,
                    "weekly_advantage_block_bootstrap_interval": [-1.29, 1.25],
                    "positive_season_share": 0.25,
                    "season_net_advantage_points": {"2021-22": -11.0},
                }
            ],
        },
    }
    (line,) = [
        row for row in _markdown(record).splitlines() if "`induction`" in row and "GW" in row
    ]
    assert "GW2 bboost, GW3 3xc, GW13 freehit, GW20 wildcard" in line
