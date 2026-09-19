"""The chip forecast states the weekly rule on typed inputs, and nothing beyond them.

Every input here is synthetic. Nothing in this file is a measurement, and nothing reads
a capture: the forecast is a pure function, and these tests hold it to the rule as
``docs/chip_forecast_prereg.md`` writes it.
"""

import copy
import json
import re
from collections.abc import Iterator, Mapping, Sequence
from pathlib import Path
from typing import Any

import jsonschema
import pytest

from squadopt.application.chip_forecast import (
    CHIP_FORECAST_CONTRACT_VERSION,
    CHIP_FORECAST_SCHEMA_PATH,
    HOLD_REASONS,
    LATER_WEEK_BASIS,
    MEASURED_RESERVATION,
    MEASURED_THRESHOLD_POLICY,
    PROTOCOL_HOLDING_VALUES,
    THRESHOLD_DECAYING,
    THRESHOLD_POLICIES,
    VERDICTS,
    ChipForecastError,
    ChipForecastInputs,
    GameweekFixtures,
    HeldChip,
    SquadRow,
    chip_forecast,
    chip_forecast_schema,
    holding_threshold,
    scaled_expected_points,
    write_chip_forecast_schema,
)
from squadopt.application.strategies.catalog import (
    FORBIDDEN_FIELD_PATTERN,
    FORBIDDEN_TEXT_PATTERN,
)
from squadopt.experiments.season_chain import ChipWindowRule, decayed_holding_value
from squadopt.live.rules import CHIP_NAMES

REPOSITORY = Path(__file__).resolve().parents[2]
CLUBS = tuple(range(1, 21))

#: Fifteen players, one per club 1 to 15. The eleven: the captain projects 8.0, the
#: other ten 4.0. The bench, in order: 3.0, 3.0, 2.0, 2.0, so it sums to 10.0.
CAPTAIN = 101
BENCH = (112, 113, 114, 115)


def _squad(overrides: Mapping[int, float] | None = None) -> tuple[SquadRow, ...]:
    positions = ("GK", "DEF", "DEF", "DEF", "MID", "MID", "MID", "MID", "FWD", "FWD", "FWD")
    points = {CAPTAIN: 8.0, **dict.fromkeys(range(102, 112), 4.0)}
    points.update({112: 3.0, 113: 3.0, 114: 2.0, 115: 2.0})
    points.update(overrides or {})
    eleven = [
        SquadRow(100 + slot, slot, position, points[100 + slot], None, slot == 1)
        for slot, position in enumerate(positions, start=1)
    ]
    bench = [
        SquadRow(player, player - 100, "GK" if order == 1 else "DEF", points[player], order)
        for order, player in enumerate(BENCH, start=1)
    ]
    return (*eleven, *bench)


def _calendar(
    first: int, last: int, counts: Mapping[int, Mapping[int, int]] | None = None
) -> tuple[GameweekFixtures, ...]:
    """Every club once in every gameweek, except where ``counts`` says otherwise."""

    special = counts or {}
    return tuple(
        GameweekFixtures(week, {club: special.get(week, {}).get(club, 1) for club in CLUBS})
        for week in range(first, last + 1)
    )


def _inputs(
    chips: Sequence[HeldChip],
    *,
    gameweek: int = 10,
    threshold: str = "decaying",
    reserve: bool = True,
    counts: Mapping[int, Mapping[int, int]] | None = None,
    squad: Sequence[SquadRow] | None = None,
    last: int = 19,
) -> ChipForecastInputs:
    return ChipForecastInputs(
        decision_gameweek=gameweek,
        chips=tuple(chips),
        squad=_squad() if squad is None else tuple(squad),
        calendar=_calendar(gameweek, last, counts),
        holding_values=PROTOCOL_HOLDING_VALUES,
        threshold=threshold,
        reserve=reserve,
    )


def _only(document: Mapping[str, Any]) -> dict[str, Any]:
    (chip,) = document["chips"]
    assert isinstance(chip, dict)
    return chip


def _forecast(chips: Sequence[HeldChip], **options: Any) -> dict[str, Any]:
    return _only(chip_forecast(_inputs(chips, **options)))


def _validate(document: Mapping[str, Any]) -> None:
    schema = json.loads((REPOSITORY / CHIP_FORECAST_SCHEMA_PATH).read_text(encoding="utf-8"))
    jsonschema.Draft202012Validator(schema).validate(document)


def _strings(value: object) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _strings(item)
    elif isinstance(value, list):
        for item in value:
            yield from _strings(item)


def _field_names(value: object) -> Iterator[str]:
    if isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _field_names(item)
    elif isinstance(value, list):
        for item in value:
            yield from _field_names(item)


# The threshold.


def test_the_measured_rule_is_named_once_and_the_function_still_prefers_neither() -> None:
    """What `chip_forecast_rule` chose, in one place, for the caller to pass."""

    assert MEASURED_THRESHOLD_POLICY == THRESHOLD_DECAYING
    assert MEASURED_RESERVATION is False
    assert MEASURED_THRESHOLD_POLICY in THRESHOLD_POLICIES
    # The function takes both as inputs and has no default of its own: a document says
    # which rule made it, so a reader never has to know what the caller's default was.
    with pytest.raises(TypeError):
        ChipForecastInputs(  # type: ignore[call-arg]
            decision_gameweek=5,
            chips=(),
            squad=(),
            calendar=(),
            holding_values={},
        )


def test_the_fixed_threshold_is_the_holding_value_to_the_end_of_the_window() -> None:
    assert [holding_threshold("fixed", 18.0, 1, 19, week) for week in (1, 10, 19)] == [18.0] * 3


def test_the_decaying_threshold_starts_at_the_holding_value_and_is_zero_in_the_last_gameweek() -> (
    None
):
    assert holding_threshold("decaying", 18.0, 1, 19, 1) == 18.0
    assert holding_threshold("decaying", 18.0, 1, 19, 10) == pytest.approx(9.0)
    assert holding_threshold("decaying", 18.0, 1, 19, 19) == 0.0
    # The wildcard's first half opens at gameweek 2, so its share is of seventeen weeks.
    assert holding_threshold("decaying", 12.0, 2, 19, 2) == 12.0
    assert holding_threshold("decaying", 12.0, 2, 19, 19) == 0.0


def test_a_window_of_one_gameweek_has_nothing_to_wait_for() -> None:
    assert holding_threshold("decaying", 20.0, 19, 19, 19) == 0.0
    assert holding_threshold("fixed", 20.0, 19, 19, 19) == 20.0


def test_the_threshold_refuses_a_gameweek_outside_the_window_and_an_unnamed_policy() -> None:
    with pytest.raises(ChipForecastError, match="outside the window"):
        holding_threshold("decaying", 18.0, 1, 19, 20)
    with pytest.raises(ChipForecastError, match="Threshold policy"):
        holding_threshold("linear", 18.0, 1, 19, 5)


def test_the_decaying_threshold_agrees_with_the_chain_on_a_grid() -> None:
    # `decayed_holding_value` lives in the laboratory, which the product may not import,
    # so the formula is restated in the product. A test may import both, and this one
    # holds them together: the rule that is measured is the rule that is stated.
    for first, last in ((1, 19), (2, 19), (20, 38), (19, 19)):
        window = ChipWindowRule("3xc", first, last)
        for week in range(first, last + 1):
            for constant in (0.0, 12.0, 18.5):
                assert holding_threshold(
                    "decaying", constant, first, last, week
                ) == decayed_holding_value(constant, window, week)


# Play now, or hold.


def test_play_now_needs_the_gain_to_exceed_the_threshold_strictly() -> None:
    at = _forecast([HeldChip("3xc", 1, 19, 9.0)])
    above = _forecast([HeldChip("3xc", 1, 19, 9.001)])

    assert at["threshold_this_week"] == pytest.approx(9.0)
    assert (at["verdict"], at["hold_reason"]) == ("hold", "gain_not_above_threshold")
    assert (above["verdict"], above["hold_reason"]) == ("play_now", None)
    assert above["points_at_gameweek"] is None
    assert above["gain_this_week"] == 9.001


def test_the_same_gain_plays_under_one_policy_and_holds_under_the_other() -> None:
    chip = HeldChip("wildcard", 2, 19, 10.0)

    assert _forecast([chip], gameweek=15, threshold="decaying")["verdict"] == "play_now"
    assert _forecast([chip], gameweek=15, threshold="fixed")["verdict"] == "hold"


def test_in_the_last_gameweek_the_decaying_threshold_is_zero_and_the_reservation_is_lifted() -> (
    None
):
    # Gameweek 19 has no double and no blank: under the reservation the bench boost and
    # the free hit would be held, were this not the gameweek after which they are lost.
    chips = [HeldChip("bboost", 1, 19, 0.5), HeldChip("freehit", 2, 19, 0.5)]
    document = chip_forecast(_inputs(chips, gameweek=19))

    for chip in document["chips"]:
        assert chip["threshold_this_week"] == 0.0
        assert chip["reservation_allows_this_week"] is True
        assert chip["verdict"] == "play_now"
    _validate(document)


def test_the_reservation_is_lifted_in_the_last_gameweek_under_the_fixed_threshold_too() -> None:
    held = _forecast([HeldChip("bboost", 1, 19, 19.0)], gameweek=19, threshold="fixed")
    played = _forecast([HeldChip("bboost", 1, 19, 21.0)], gameweek=19, threshold="fixed")

    assert held["reservation_allows_this_week"] is True
    assert (held["verdict"], held["hold_reason"]) == ("hold", "gain_not_above_threshold")
    assert played["verdict"] == "play_now"


def test_a_reserved_chip_is_held_outside_a_structured_gameweek_whatever_it_adds() -> None:
    reserved = _forecast([HeldChip("bboost", 1, 19, 40.0)])
    unreserved = _forecast([HeldChip("bboost", 1, 19, 40.0)], reserve=False)
    doubling = _forecast([HeldChip("bboost", 1, 19, 40.0)], counts={10: {3: 2}})

    assert (reserved["verdict"], reserved["hold_reason"]) == (
        "hold",
        "reserved_for_structured_gameweek",
    )
    assert reserved["reservation_allows_this_week"] is False
    assert unreserved["verdict"] == "play_now"
    assert doubling["verdict"] == "play_now"


def test_the_free_hit_is_reserved_for_a_blank_as_well_as_a_double_and_the_bench_boost_is_not() -> (
    None
):
    blank_this_week = {10: {20: 0}}
    free_hit = _forecast([HeldChip("freehit", 2, 19, 30.0)], counts=blank_this_week)
    bench_boost = _forecast([HeldChip("bboost", 1, 19, 30.0)], counts=blank_this_week)

    assert free_hit["verdict"] == "play_now"
    assert bench_boost["hold_reason"] == "reserved_for_structured_gameweek"


def test_the_triple_captain_and_the_wildcard_are_never_reserved() -> None:
    for name, first in (("3xc", 1), ("wildcard", 2)):
        chip = _forecast([HeldChip(name, first, 19, 30.0)])
        assert chip["reservation_allows_this_week"] is True
        assert chip["verdict"] == "play_now"


# Absent is not zero.


def test_a_gain_that_was_not_computed_is_unknown_this_week_and_never_a_zero() -> None:
    document = chip_forecast(_inputs([HeldChip("3xc", 1, 19, None)]))
    chip = _only(document)

    assert chip["verdict"] == "unknown_this_week"
    assert chip["gain_this_week"] is None
    assert chip["hold_reason"] is None
    # A computed gain of nought is a different document: the rule holds it.
    assert _forecast([HeldChip("3xc", 1, 19, 0.0)])["verdict"] == "hold"
    _validate(document)


def test_an_unknown_gain_is_still_unknown_in_the_last_gameweek_where_nought_would_not_play() -> (
    None
):
    chip = _forecast([HeldChip("wildcard", 2, 19, None)], gameweek=19)

    assert chip["threshold_this_week"] == 0.0
    assert chip["verdict"] == "unknown_this_week"


def test_a_reserved_chip_with_no_computed_gain_is_held_by_the_reservation_not_by_a_zero() -> None:
    document = chip_forecast(_inputs([HeldChip("bboost", 1, 19, None)]))
    chip = _only(document)

    assert (chip["verdict"], chip["hold_reason"]) == ("hold", "reserved_for_structured_gameweek")
    assert chip["gain_this_week"] is None
    _validate(document)


def test_a_holding_value_that_was_not_given_is_refused_rather_than_read_as_zero() -> None:
    with pytest.raises(ChipForecastError, match="absent value is not zero"):
        ChipForecastInputs(
            decision_gameweek=10,
            chips=(HeldChip("3xc", 1, 19, 5.0),),
            squad=_squad(),
            calendar=_calendar(10, 19),
            holding_values={"bboost": 20.0},
            threshold="fixed",
            reserve=True,
        )


# The gameweek a hold points at.


def test_a_double_gameweek_ahead_is_the_gameweek_named_for_the_triple_captain() -> None:
    # From gameweek 10 the threshold in w is 18 * (19 - w) / 18 = 19 - w. The captain's
    # club playing twice in gameweek 11 makes 8.0 into 16.0 against 8.0, so gameweek 11
    # is named. A double as late as gameweek 14 is never reached: a single 8.0 is not
    # above 8.0 in gameweek 11 and is above 7.0 in gameweek 12, which comes first.
    early = _forecast([HeldChip("3xc", 1, 19, 1.0)], counts={11: {1: 2}})
    late = _forecast([HeldChip("3xc", 1, 19, 1.0)], counts={14: {1: 2}})

    assert early["verdict"] == "hold"
    assert early["points_at_gameweek"] == {
        "gameweek": 11,
        "estimated_gain": 16.0,
        "threshold": pytest.approx(8.0),
        "player_ids": [CAPTAIN],
    }
    assert late["points_at_gameweek"]["gameweek"] == 12
    assert late["points_at_gameweek"]["estimated_gain"] == 8.0


def test_the_triple_captain_estimate_reads_the_whole_fifteen_not_the_present_captain() -> None:
    # A benched player whose club doubles outscores the captain's single that gameweek.
    squad = _squad({112: 5.0})
    chip = _forecast([HeldChip("3xc", 1, 19, 1.0)], squad=squad, counts={11: {12: 2}})

    assert chip["points_at_gameweek"]["gameweek"] == 11
    assert chip["points_at_gameweek"]["player_ids"] == [112]
    assert chip["points_at_gameweek"]["estimated_gain"] == 10.0


def test_a_double_gameweek_ahead_is_the_gameweek_named_for_the_bench_boost() -> None:
    # Two of the bench's clubs double in gameweek 13: 3 + 3 + 2 + 2 becomes 6 + 6 + 2 + 2.
    chip = _forecast([HeldChip("bboost", 1, 19, 1.0)], counts={13: {12: 2, 13: 2}})

    assert chip["points_at_gameweek"] == {
        "gameweek": 13,
        "estimated_gain": 16.0,
        "threshold": pytest.approx(20.0 * 6 / 18),
        "player_ids": list(BENCH),
    }


def test_a_double_that_does_not_beat_its_threshold_is_passed_over() -> None:
    # A double for a club the bench does not hold opens gameweek 5 to the bench boost,
    # but the bench still sums to 10.0 there against 20 * 14 / 18.
    chip = _forecast([HeldChip("bboost", 1, 19, 1.0)], gameweek=4, counts={5: {20: 2}, 16: {12: 2}})

    assert chip["points_at_gameweek"]["gameweek"] == 16
    assert chip["points_at_gameweek"]["estimated_gain"] == 13.0


def test_with_no_double_before_the_end_the_reserved_bench_boost_points_at_the_last_gameweek() -> (
    None
):
    reserved = _forecast([HeldChip("bboost", 1, 19, 1.0)], reserve=True)
    unreserved = _forecast([HeldChip("bboost", 1, 19, 1.0)], reserve=False)

    assert reserved["points_at_gameweek"] == {
        "gameweek": 19,
        "estimated_gain": 10.0,
        "threshold": 0.0,
        "player_ids": list(BENCH),
    }
    # Without the reservation it is the first later gameweek whose threshold the bench
    # beats, and 20 * (19 - w) / 18 is already below 10.0 at w = 11.
    assert unreserved["points_at_gameweek"]["gameweek"] == 11
    assert unreserved["points_at_gameweek"]["threshold"] == pytest.approx(20.0 * 8 / 18)


def test_under_the_fixed_threshold_no_gameweek_is_named_when_none_beats_the_holding_value() -> None:
    chip = _forecast([HeldChip("bboost", 1, 19, 1.0)], threshold="fixed", reserve=False)

    assert chip["verdict"] == "hold"
    assert chip["points_at_gameweek"] is None


def test_a_chip_held_in_its_last_gameweek_points_nowhere() -> None:
    chip = _forecast([HeldChip("3xc", 1, 19, 8.0)], gameweek=19, threshold="fixed")

    assert chip["verdict"] == "hold"
    assert chip["points_at_gameweek"] is None


def test_a_later_week_is_scaled_relative_to_this_week_so_a_double_now_is_not_counted_twice() -> (
    None
):
    # The captain's 8.0 already holds two fixtures this gameweek. A single later is 4.0
    # and another double is 8.0, not 16.0.
    assert scaled_expected_points(8.0, 2, 1) == 4.0
    assert scaled_expected_points(8.0, 2, 2) == 8.0
    assert scaled_expected_points(8.0, 1, 0) == 0.0
    assert scaled_expected_points(-1.0, 1, 2) == 0.0
    assert scaled_expected_points(0.0, 0, 2) is None

    chip = _forecast([HeldChip("3xc", 1, 19, 1.0)], counts={10: {1: 2}, 13: {2: 2}})
    assert chip["points_at_gameweek"]["gameweek"] == 13
    assert chip["points_at_gameweek"]["player_ids"] == [102]
    assert chip["points_at_gameweek"]["estimated_gain"] == 8.0


def test_a_player_with_no_fixture_this_week_is_left_out_of_the_scaling_and_reported() -> None:
    # Bench player 112's club is blank now and doubles in gameweek 14. He projects
    # nothing this gameweek, so there is nothing to double: the estimate is the other
    # three, and he is not among the players counted.
    squad = _squad({112: 0.0})
    document = chip_forecast(
        _inputs([HeldChip("bboost", 1, 19, 1.0)], squad=squad, counts={10: {12: 0}, 14: {12: 2}})
    )
    chip = _only(document)

    assert document["players_without_fixture_this_week"] == [112]
    assert chip["points_at_gameweek"] == {
        "gameweek": 14,
        "estimated_gain": 7.0,
        "threshold": pytest.approx(20.0 * 5 / 18),
        "player_ids": [113, 114, 115],
    }
    assert any("no fixture this gameweek" in sentence for sentence in document["limits"])
    _validate(document)

    unaffected = chip_forecast(_inputs([HeldChip("bboost", 1, 19, 1.0)]))
    assert unaffected["players_without_fixture_this_week"] == []
    assert not any("no fixture this gameweek" in sentence for sentence in unaffected["limits"])


def test_expected_points_for_a_club_with_no_fixture_this_week_are_refused() -> None:
    with pytest.raises(ChipForecastError, match="disagree"):
        _inputs([HeldChip("bboost", 1, 19, 1.0)], counts={10: {12: 0}})


# Windows.


def test_a_chip_whose_window_has_closed_is_stated_as_expired_with_nothing_beside_it() -> None:
    document = chip_forecast(
        _inputs([HeldChip("freehit", 2, 19, None)], gameweek=20, last=24, counts={22: {4: 2}})
    )
    chip = _only(document)

    assert chip["verdict"] == "expired_window"
    assert chip["window"] == {"first_gameweek": 2, "last_gameweek": 19}
    for name in (
        "hold_reason",
        "gain_this_week",
        "threshold_this_week",
        "reservation_allows_this_week",
        "points_at_gameweek",
        "structured_gameweeks",
    ):
        assert chip[name] is None
    _validate(document)


def test_a_chip_whose_window_has_not_opened_states_no_gain_and_no_threshold() -> None:
    document = chip_forecast(
        _inputs([HeldChip("freehit", 2, 19, None)], gameweek=1, counts={1: {5: 2}, 6: {5: 0}})
    )
    chip = _only(document)

    assert chip["verdict"] == "window_not_open"
    assert chip["threshold_this_week"] is None
    assert [week["gameweek"] for week in chip["structured_gameweeks"]] == [6]
    _validate(document)


def test_a_bench_boost_whose_window_has_not_opened_names_no_later_gameweek() -> None:
    """The weakest number the module could produce, and it does not produce it.

    A second-half chip asked in gameweek 5 would otherwise be answered with this gameweek's
    projection carried fifteen weeks on fixture counts alone, for a chip nobody can play now.
    """

    document = chip_forecast(
        _inputs(
            [HeldChip("bboost", 20, 38, None)],
            gameweek=5,
            last=38,
            # A double gameweek inside the window, which is what would have been named.
            counts={20: {5: 2}},
        )
    )
    chip = _only(document)

    assert chip["verdict"] == "window_not_open"
    assert chip["points_at_gameweek"] is None
    assert chip["gain_this_week"] is None and chip["threshold_this_week"] is None
    _validate(document)

    # And the same chip inside its window does name one, so the test is not passing on a
    # calendar that offered nothing.
    inside = _forecast(
        [HeldChip("bboost", 20, 38, None)], gameweek=19, last=38, counts={20: {5: 2}}
    )
    assert inside["verdict"] == "window_not_open"
    later = _forecast(
        [HeldChip("bboost", 20, 38, 1.0)], gameweek=20, last=38, counts={20: {5: 1}, 21: {5: 2}}
    )
    assert later["points_at_gameweek"] is not None


def test_the_schema_refuses_the_documents_the_module_never_writes() -> None:
    """Four shapes that validated before: the contract is what a publisher writes against."""

    document = chip_forecast(_inputs([HeldChip("bboost", 2, 19, 1.0)], counts={10: {5: 2}}))
    _validate(document)
    chip = _only(document)
    assert chip["verdict"] == "hold" and chip["hold_reason"] == "gain_not_above_threshold"

    def refused(**changes: Any) -> None:
        forged = json.loads(json.dumps(document))
        forged["chips"][0].update(changes)
        with pytest.raises(jsonschema.ValidationError):
            _validate(forged)

    # "The gain did not exceed the threshold", stating no gain.
    refused(gain_this_week=None)
    # The same hold, claiming the reservation refused it.
    refused(reservation_allows_this_week=False)
    # A chip held by the reservation that the reservation allowed.
    refused(hold_reason="reserved_for_structured_gameweek", reservation_allows_this_week=True)

    # A structured gameweek that is not structured by anything.
    free_hit = chip_forecast(_inputs([HeldChip("freehit", 2, 19, None)], counts={12: {5: 2}}))
    _validate(free_hit)
    forged = json.loads(json.dumps(free_hit))
    forged["chips"][0]["structured_gameweeks"] = [
        {"gameweek": 12, "clubs_doubling": 0, "clubs_blank": 0}
    ]
    with pytest.raises(jsonschema.ValidationError):
        _validate(forged)

    # The same chip listed twice.
    twice = json.loads(json.dumps(document))
    twice["chips"] = [twice["chips"][0], json.loads(json.dumps(twice["chips"][0]))]
    with pytest.raises(jsonschema.ValidationError):
        _validate(twice)


def test_a_gain_stated_outside_the_window_is_refused() -> None:
    with pytest.raises(ChipForecastError, match="outside its window"):
        _inputs([HeldChip("wildcard", 2, 19, 4.0)], gameweek=1)


# Free hit and wildcard.


def test_the_free_hit_lists_the_structured_gameweeks_in_order_and_names_no_gain() -> None:
    counts = {10: {1: 2}, 17: {7: 0, 8: 0}, 12: {3: 2}, 19: {4: 2, 5: 0}}
    document = chip_forecast(_inputs([HeldChip("freehit", 2, 19, 3.0)], counts=counts))
    chip = _only(document)

    assert chip["verdict"] == "hold"
    assert chip["points_at_gameweek"] is None
    # This gameweek is the verdict's business; the list is what comes after it.
    assert chip["structured_gameweeks"] == [
        {"gameweek": 12, "clubs_doubling": 1, "clubs_blank": 0},
        {"gameweek": 17, "clubs_doubling": 0, "clubs_blank": 2},
        {"gameweek": 19, "clubs_doubling": 1, "clubs_blank": 1},
    ]
    assert not any("gain" in key for week in chip["structured_gameweeks"] for key in week)
    assert any("Free Hit" in sentence for sentence in document["limits"])
    _validate(document)


def test_the_wildcard_names_no_gameweek_only_its_threshold_and_this_weeks_gain() -> None:
    document = chip_forecast(
        _inputs([HeldChip("wildcard", 2, 19, 3.0)], gameweek=6, counts={9: {1: 2}})
    )
    chip = _only(document)

    assert chip["verdict"] == "hold"
    assert chip["gain_this_week"] == 3.0
    assert chip["threshold_this_week"] == pytest.approx(12.0 * 13 / 17)
    assert chip["points_at_gameweek"] is None
    assert chip["structured_gameweeks"] is None
    _validate(document)


# The document.


def _full_inputs() -> ChipForecastInputs:
    return _inputs(
        [
            HeldChip("3xc", 1, 19, 4.0),
            HeldChip("freehit", 2, 19, None),
            HeldChip("bboost", 1, 19, 6.5),
            HeldChip("wildcard", 2, 19, 11.0),
        ],
        gameweek=8,
        counts={12: {1: 2, 12: 2, 9: 0}, 15: {13: 2}},
    )


def test_the_document_validates_against_the_committed_schema_under_every_policy() -> None:
    for threshold in THRESHOLD_POLICIES:
        for reserve in (True, False):
            inputs = _full_inputs()
            document = chip_forecast(
                ChipForecastInputs(
                    inputs.decision_gameweek,
                    inputs.chips,
                    inputs.squad,
                    inputs.calendar,
                    inputs.holding_values,
                    threshold,
                    reserve,
                )
            )
            _validate(document)
            assert document["contract_version"] == CHIP_FORECAST_CONTRACT_VERSION
            assert document["threshold_policy"] == threshold
            assert document["reserve"] is reserve
            assert document["later_week_basis"] == LATER_WEEK_BASIS
            assert {chip["verdict"] for chip in document["chips"]} <= set(VERDICTS)
            assert {chip["hold_reason"] for chip in document["chips"]} <= {None, *HOLD_REASONS}


def test_the_document_survives_json_and_no_held_chip_is_an_empty_list() -> None:
    document = chip_forecast(_full_inputs())
    assert json.loads(json.dumps(document, allow_nan=False)) == document

    nothing_held = chip_forecast(_inputs([]))
    assert nothing_held["chips"] == []
    _validate(nothing_held)


def test_chips_are_stated_in_the_games_order_whatever_order_they_were_given_in() -> None:
    document = chip_forecast(_full_inputs())

    assert [chip["name"] for chip in document["chips"]] == list(CHIP_NAMES)


def test_the_same_inputs_make_the_identical_document() -> None:
    first = chip_forecast(_full_inputs())
    second = chip_forecast(_full_inputs())
    shuffled = _full_inputs()
    reordered = chip_forecast(
        ChipForecastInputs(
            shuffled.decision_gameweek,
            tuple(reversed(shuffled.chips)),
            tuple(reversed(shuffled.squad)),
            tuple(reversed(shuffled.calendar)),
            dict(reversed(list(shuffled.holding_values.items()))),
            shuffled.threshold,
            shuffled.reserve,
        )
    )

    assert first == second
    assert json.dumps(first, sort_keys=True) == json.dumps(second, sort_keys=True)
    assert reordered == first


def test_the_forecast_does_not_change_what_it_was_given() -> None:
    inputs = _full_inputs()
    before = copy.deepcopy(
        (inputs.chips, inputs.squad, [dict(week.fixture_count_by_club) for week in inputs.calendar])
    )
    chip_forecast(inputs)

    assert (
        inputs.chips,
        inputs.squad,
        [dict(week.fixture_count_by_club) for week in inputs.calendar],
    ) == before


def test_no_string_and_no_field_name_in_the_document_speaks_of_how_sure_anything_is() -> None:
    squad = _squad({112: 0.0})
    inputs = _full_inputs()
    document = chip_forecast(
        ChipForecastInputs(
            inputs.decision_gameweek,
            inputs.chips,
            squad,
            _calendar(8, 19, {8: {12: 0}, 12: {1: 2}}),
            inputs.holding_values,
            inputs.threshold,
            inputs.reserve,
        )
    )

    # Every optional sentence is in this document, so the sweep reads all of them.
    assert len(document["limits"]) == 6
    for text in _strings(document):
        assert FORBIDDEN_TEXT_PATTERN.search(text) is None, text
    for name in _field_names(document):
        assert FORBIDDEN_FIELD_PATTERN.search(name) is None, name
    for name in _field_names(chip_forecast_schema()["properties"]):
        assert FORBIDDEN_FIELD_PATTERN.search(name) is None, name


def test_the_schema_refuses_a_zero_written_where_the_gain_is_unknown() -> None:
    document = chip_forecast(_inputs([HeldChip("3xc", 1, 19, None)]))
    _validate(document)
    forged = copy.deepcopy(document)
    forged["chips"][0]["gain_this_week"] = 0.0

    with pytest.raises(jsonschema.ValidationError):
        _validate(forged)


def test_the_schema_refuses_a_gain_named_for_a_free_hit_gameweek_and_an_unknown_field() -> None:
    document = chip_forecast(_inputs([HeldChip("freehit", 2, 19, 3.0)], counts={12: {3: 2}}))
    with_gain = copy.deepcopy(document)
    with_gain["chips"][0]["structured_gameweeks"][0]["estimated_gain"] = 9.0
    pointed = copy.deepcopy(document)
    pointed["chips"][0]["points_at_gameweek"] = {
        "gameweek": 12,
        "estimated_gain": 9.0,
        "threshold": 1.0,
        "player_ids": [CAPTAIN],
    }
    widened = copy.deepcopy(document)
    widened["confidence"] = "high"

    for forged in (with_gain, pointed, widened):
        with pytest.raises(jsonschema.ValidationError):
            _validate(forged)


def test_the_committed_schema_is_the_generator_output(tmp_path: Path) -> None:
    schema = chip_forecast_schema()
    jsonschema.Draft202012Validator.check_schema(schema)
    committed = REPOSITORY / CHIP_FORECAST_SCHEMA_PATH

    assert json.loads(committed.read_text(encoding="utf-8")) == schema
    first = write_chip_forecast_schema(tmp_path / "a" / "schema.json")
    second = write_chip_forecast_schema(tmp_path / "b" / "schema.json")
    assert first.read_bytes() == second.read_bytes()
    assert schema["properties"]["contract_version"]["const"] == "chip_forecast_v1"


def test_the_holding_values_are_the_ones_the_protocol_names() -> None:
    protocol = (REPOSITORY / "docs" / "chip_forecast_prereg.md").read_text(encoding="utf-8")
    flat = re.sub(r"\s+", " ", protocol)

    assert "bench boost 20, triple captain 18, wildcard 12, free hit 15" in flat
    assert dict(PROTOCOL_HOLDING_VALUES) == {
        "bboost": 20.0,
        "3xc": 18.0,
        "wildcard": 12.0,
        "freehit": 15.0,
    }


# Inputs the rule cannot be stated on.


def test_inputs_that_would_make_the_forecast_guess_are_refused() -> None:
    with pytest.raises(ChipForecastError, match="once in a half"):
        _inputs([HeldChip("3xc", 1, 19, 1.0), HeldChip("3xc", 1, 19, 2.0)])
    with pytest.raises(ChipForecastError, match="not a blank"):
        _inputs([HeldChip("3xc", 1, 19, 1.0)], last=15)
    with pytest.raises(ChipForecastError, match="start at the decision gameweek"):
        ChipForecastInputs(10, (), _squad(), _calendar(11, 19), {}, "fixed", True)
    with pytest.raises(ChipForecastError, match="consecutive"):
        ChipForecastInputs(
            10, (), _squad(), (*_calendar(10, 11), *_calendar(13, 19)), {}, "fixed", True
        )
    with pytest.raises(ChipForecastError, match="stated zero"):
        ChipForecastInputs(
            10,
            (),
            _squad(),
            (*_calendar(10, 10), GameweekFixtures(11, dict.fromkeys(CLUBS[:-1], 1))),
            {},
            "fixed",
            True,
        )
    with pytest.raises(ChipForecastError, match="Threshold policy"):
        _inputs([], threshold="computed")
    with pytest.raises(ChipForecastError, match="finite"):
        HeldChip("3xc", 1, 19, float("nan"))
    with pytest.raises(ChipForecastError, match="Unknown chip"):
        HeldChip("manager", 1, 19, 1.0)
    with pytest.raises(ChipForecastError, match="ends before it starts"):
        HeldChip("3xc", 19, 1, None)


def test_a_squad_that_is_not_a_fifteen_with_a_bench_and_one_captain_is_refused() -> None:
    squad = list(_squad())
    with pytest.raises(ChipForecastError, match="15 distinct"):
        _inputs([], squad=squad[:-1])
    with pytest.raises(ChipForecastError, match="bench"):
        _inputs([], squad=[*squad[:-1], SquadRow(115, 15, "DEF", 2.0, 3)])
    with pytest.raises(ChipForecastError, match="captain"):
        _inputs([], squad=[SquadRow(101, 1, "GK", 8.0, None, False), *squad[1:]])
    with pytest.raises(ChipForecastError, match="does not list"):
        _inputs([], squad=[SquadRow(101, 99, "GK", 8.0, None, True), *squad[1:]])
