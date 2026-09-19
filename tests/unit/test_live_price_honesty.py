"""The price-honesty arithmetic on synthetic records; nothing here reads real data."""

from typing import Any

import pandas as pd
import pytest

from squadopt.application.live_price_honesty import (
    FAMILY_COMBINED,
    FAMILY_RIVAL,
    FAMILY_TOP100,
    FAMILY_WORD,
    MINIMUM_GAMEWEEKS_FOR_INTERVAL,
    LivePriceHonestyError,
    PricedPair,
    family_of,
    pairs_for_record,
    reading,
    summarise,
)

STARTERS = [1, 3, 4, 5, 8, 9, 10, 11, 13, 14, 15]
BENCH = [2, 12, 6, 7]
POSITIONS = ["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3


def _document(path: str, **changes: Any) -> dict[str, Any]:
    document: dict[str, Any] = {
        "strategy": "saf-puan",
        "window": 1,
        "rival_entry_id": None,
        "published_path": f"advice/101/{path}.json",
        "starting_xi": STARTERS,
        "bench": BENCH,
        "captain": 8,
        "vice_captain": 9,
        "scoring_complete": True,
        "solver_status": "OPTIMAL",
        "chip": None,
        "transfer_hit_points": 0,
        "expected_own_points": 50.0,
    }
    document.update(changes)
    return document


def _record(*documents: dict[str, Any], gameweek: int = 4) -> dict[str, Any]:
    return {
        "gameweek": gameweek,
        "entry_id": 101,
        "players": {
            str(i): {"name": f"Player {i}", "position": position, "expected_points": 3.5}
            for i, position in enumerate(POSITIONS, start=1)
        },
        "advice": [_document("saf-puan/1"), *documents],
    }


def _outcomes(**points: float) -> pd.DataFrame:
    frame = pd.DataFrame({"player_id": range(1, 16), "total_points": 2.0, "minutes": 90})
    for player, value in points.items():
        frame.loc[frame["player_id"] == int(player.removeprefix("p")), "total_points"] = value
    return frame


def test_the_family_is_read_from_what_was_switched() -> None:
    assert family_of(_document("saf-puan/1")) is None
    assert family_of(_document("ortak-koru/1", strategy="ortak-koru", rival_entry_id=7)) == (
        FAMILY_RIVAL
    )
    assert family_of(_document("saf-puan/1/top100-20", top100_weight=20)) == FAMILY_TOP100
    assert family_of(_document("saf-puan/1/hoca-sozu", managers_word=True)) == FAMILY_WORD
    both = _document("saf-puan/1/top100-20-hoca-sozu", top100_weight=20, managers_word=True)
    assert family_of(both) == FAMILY_COMBINED
    # Chips and the longer windows are another claim and are left out.
    assert family_of(_document("saf-puan/1/chip-bboost", chip="bboost")) is None
    assert family_of(_document("saf-puan/3", window=3)) is None


def test_a_pair_states_the_difference_and_scores_both_arms_with_one_function() -> None:
    # The setting moves the armband from player 8 to player 9 and says that costs 1.5.
    setting = _document(
        "fark-yarat/1",
        strategy="fark-yarat",
        rival_entry_id=7,
        captain=9,
        vice_captain=8,
        expected_own_points=48.5,
    )
    pairs, left_out = pairs_for_record(_record(setting), _outcomes(p8=10.0, p9=4.0))
    assert left_out == {}
    (pair,) = pairs
    assert pair.binding and pair.family == FAMILY_RIVAL
    assert pair.setting == "fark-yarat/rival-7"
    assert pair.stated_cost == pytest.approx(1.5)
    # The control doubles the 10, the setting doubles the 4: six points apart.
    assert pair.realized_cost == pytest.approx(6.0)


def test_the_recorded_price_wins_over_the_difference_and_carries_its_ceiling() -> None:
    setting = _document(
        "saf-puan/1/top100-20",
        top100_weight=20,
        captain=9,
        vice_captain=8,
        expected_own_points=49.0,
        expected_points_cost=0.4,
        expected_points_cost_ceiling=2.0,
    )
    ((pair,), _) = pairs_for_record(_record(setting), _outcomes())
    assert pair.stated_cost == pytest.approx(0.4) and pair.stated_ceiling == pytest.approx(2.0)


def test_the_same_plan_is_counted_and_never_averaged() -> None:
    same = _document("ortak-koru/1", strategy="ortak-koru", rival_entry_id=7)
    moved = _document(
        "ortak-koru/1-b", strategy="ortak-koru", rival_entry_id=9, captain=9, vice_captain=8
    )
    pairs, _ = pairs_for_record(_record(same, moved), _outcomes(p8=10.0))
    assert [pair.binding for pair in pairs] == [False, True]
    summary = summarise(pairs)
    assert summary["pairs"] == 2 and summary["binding_pairs"] == 1
    assert summary["mean_realized_cost"] == pytest.approx(8.0)
    assert summary["interval"] is None


def test_what_is_left_out_is_counted_with_its_reason() -> None:
    rival = {"strategy": "ortak-koru", "rival_entry_id": 7}
    documents = [
        _document("ortak-koru/1", **rival),
        _document("ortak-koru/1-named", **rival),  # the default rival, listed again by name
        _document("saf-puan/3", window=3),
        _document("saf-puan/1/chip-3xc", chip="3xc"),
        _document("fark-yarat/1", strategy="fark-yarat", rival_entry_id=7, scoring_complete=False),
    ]
    pairs, left_out = pairs_for_record(_record(*documents), _outcomes())
    assert len(pairs) == 1
    assert left_out == {"listed_twice": 1, "window_or_chip": 2, "setting_incomplete": 1}


def test_an_unproved_control_prices_nothing() -> None:
    record = _record(_document("ortak-koru/1", strategy="ortak-koru", rival_entry_id=7))
    record["advice"][0]["solver_status"] = "FEASIBLE"
    pairs, left_out = pairs_for_record(record, _outcomes())
    assert pairs == () and left_out == {"control_not_proved_or_incomplete": 1}
    record["advice"].pop(0)
    with pytest.raises(LivePriceHonestyError, match="exactly one control"):
        pairs_for_record(record, _outcomes())


def _pair(gameweek: int, stated: float, realized: float) -> PricedPair:
    return PricedPair(gameweek, 101, FAMILY_RIVAL, "s", True, stated, realized, None)


def test_the_interval_waits_for_enough_gameweeks_and_resamples_them_whole() -> None:
    few = [_pair(week, 1.0, 3.0) for week in range(4, 4 + MINIMUM_GAMEWEEKS_FOR_INTERVAL - 1)]
    assert summarise(few)["interval"] is None
    # Every pair understates by exactly two, so every resample has the same mean.
    enough = [*few, _pair(20, 1.0, 3.0)]
    interval = summarise(enough)["interval"]
    assert isinstance(interval, dict)
    assert interval["low"] == pytest.approx(2.0) and interval["high"] == pytest.approx(2.0)
    assert interval["understates"] is True and interval["gameweeks"] == 6
    # Overstating is reported and is not a failure.
    over = summarise([_pair(week, 5.0, 3.0) for week in range(4, 10)])["interval"]
    assert isinstance(over, dict) and over["understates"] is False
    document = reading(enough)
    assert set(document) == {"pooled", "by_family", "by_gameweek"}
    assert list(document["by_family"]) == [FAMILY_RIVAL]
