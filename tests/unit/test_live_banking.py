"""Tests for the banked free transfers model.

The endpoints never state the count, so it is derived from the history under one model
(docstring of ``banked_free_transfers``); every test here is a case of that model, and
the last one is the real GW3 capture, whose 45 recorded hits the model has to reproduce.
Parsing the history is the data layer's and tested there; the model takes the parsed
rows, and the two rule values it stands on (the cap and the hit) are pinned to their one
definition in ``live/rules.py``.
"""

import json
from types import SimpleNamespace
from typing import Any

import pytest
import tests.unit.test_source_fpl_live as payload_module

from squadopt.application.capture_entries import CapturePicksProvider
from squadopt.data.sources.fpl_live import entry_transfer_history, fpl_entry_picks
from squadopt.live.banking import BankedFreeTransfers, banked_free_transfers
from squadopt.live.rules import TRANSFER_HIT_POINTS, TransferRules, free_transfer_cap
from squadopt.live.transfers import MEMBER_PLANNING_POLICY

_row = payload_module._row
_history_payload = payload_module._history_payload
_picks_payload = payload_module._picks_payload


def _banked(
    rows: list[dict[str, Any]],
    *,
    gameweek: int,
    chips: list[dict[str, Any]] | None = None,
    cap: int | None = 5,
    active_chip: str | None = None,
) -> BankedFreeTransfers:
    return banked_free_transfers(
        entry_transfer_history(_history_payload(current=rows, chips=chips), entry_id=11),
        gameweek=gameweek,
        max_free_transfers=cap,
        active_chip=active_chip,
    )


def test_free_transfers_accrue_one_a_week_from_gameweek_two_up_to_the_cap() -> None:
    rows = [_row(week) for week in range(1, 8)]
    # None at the GW1 deadline, one for GW2, two for GW3 ... five for GW6 and held there.
    assert [_banked(rows, gameweek=week).count for week in range(1, 8)] == [1, 2, 3, 4, 5, 5, 5]
    assert _banked(rows, gameweek=7).known is True


def test_transfers_consume_the_bank_before_any_hit_is_paid() -> None:
    rows = [_row(1), _row(2, transfers=1), _row(3), _row(4, transfers=3, cost=4)]
    assert _banked(rows, gameweek=2) == BankedFreeTransfers(1, True)  # spent the one
    assert _banked(rows, gameweek=3) == BankedFreeTransfers(2, True)
    assert _banked(rows, gameweek=4) == BankedFreeTransfers(1, True)  # two free, one paid


@pytest.mark.parametrize("chip", ["freehit", "wildcard"])
def test_a_transfer_chip_week_consumes_nothing_and_the_bank_keeps_growing(chip: str) -> None:
    rows = [_row(1), _row(2), _row(3, transfers=9), _row(4)]
    chips = [{"name": chip, "event": 3}]
    assert _banked(rows, gameweek=3, chips=chips) == BankedFreeTransfers(3, True)
    assert _banked(rows, gameweek=4, chips=chips) == BankedFreeTransfers(4, True)
    # The captured week's own chip is read from the picks document as well.
    assert _banked(rows, gameweek=3, active_chip=chip) == BankedFreeTransfers(3, True)


def test_bench_boost_and_triple_captain_leave_the_banking_untouched() -> None:
    rows = [_row(1), _row(2, transfers=1), _row(3, transfers=2, cost=4)]
    chips = [{"name": "bboost", "event": 2}, {"name": "3xc", "event": 3}]
    assert _banked(rows, gameweek=3, chips=chips) == BankedFreeTransfers(1, True)


def test_a_late_joiner_and_a_missing_week_are_unknown_not_guessed() -> None:
    late = _banked([_row(2), _row(3)], gameweek=3)
    assert (late.count, late.known) == (1, False)
    assert "gameweek 1" in str(late.reason)
    gap = _banked([_row(1), _row(3)], gameweek=3)
    assert (gap.count, gap.known) == (1, False)
    assert "gameweek 2" in str(gap.reason)
    assert _banked([_row(1), _row(2)], gameweek=3).known is False


def test_a_recorded_hit_the_model_does_not_reproduce_is_unknown_not_trusted() -> None:
    # Two transfers with one free should have cost 4; a zero means the model is wrong.
    result = _banked([_row(1), _row(2, transfers=2)], gameweek=2)
    assert (result.count, result.known) == (1, False)
    assert "gameweek 2" in str(result.reason) and "expects 4" in str(result.reason)
    # A chip week that charged points contradicts the chip rule the same way.
    charged = _banked(
        [_row(1), _row(2, transfers=2, cost=4)],
        gameweek=2,
        chips=[{"name": "wildcard", "event": 2}],
    )
    assert charged.known is False


def test_without_the_seasons_cap_the_count_is_the_floor_and_says_so() -> None:
    result = _banked([_row(1), _row(2)], gameweek=2, cap=None)
    assert (result.count, result.known) == (1, False)
    assert "cap" in str(result.reason)


def test_a_gameweek_before_the_first_is_refused() -> None:
    with pytest.raises(ValueError, match="positive"):
        _banked([_row(1)], gameweek=0)


# --- the two rule values are defined once ---------------------------------------------


def test_the_cap_is_read_from_the_bootstrap_block_the_season_rules_read() -> None:
    both = {"game_config": {"rules": {"max_extra_free_transfers": 4}}}
    assert free_transfer_cap(json.dumps(both).encode("utf-8")) == 5
    settings = {"game_settings": {"max_extra_free_transfers": 1}}
    assert free_transfer_cap(json.dumps(settings).encode("utf-8")) == 2
    assert free_transfer_cap(b"{}") is None


def test_the_cap_is_the_number_the_season_rules_hand_the_planner() -> None:
    rules = TransferRules(
        squad_size=15,
        starting_size=11,
        team_limit=3,
        budget_tenths=1000,
        max_extra_free_transfers=4,
        transfers_cap=None,
        sell_on_fee=0.5,
        sell_at_purchase_price=False,
    )
    bootstrap = {"game_config": {"rules": {"max_extra_free_transfers": 4}}}
    assert free_transfer_cap(json.dumps(bootstrap).encode("utf-8")) == rules.max_free_transfers


def test_the_hit_the_model_checks_is_the_hit_the_member_policy_charges() -> None:
    assert TRANSFER_HIT_POINTS == 4
    assert MEMBER_PLANNING_POLICY["hit_points_charged"] == float(TRANSFER_HIT_POINTS)


# --- the provider carries the derived count -------------------------------------------


def _bootstrap(*, cap: int | None) -> bytes:
    document: dict[str, Any] = {
        "elements": [{"id": element, "code": element + 1000} for element in range(101, 116)]
    }
    if cap is not None:
        document["game_config"] = {"rules": {"max_extra_free_transfers": cap - 1}}
    return json.dumps(document).encode("utf-8")


def _provider(*, cap: int | None) -> CapturePicksProvider:
    payloads = {
        "bootstrap-static.json": _bootstrap(cap=cap),
        "entry-11-picks-gw03.json": _picks_payload(),
        "entry-11-history.json": _history_payload(current=[_row(1), _row(2), _row(3, transfers=1)]),
    }
    return CapturePicksProvider(SimpleNamespace(payloads=payloads), "fpl-live-20260910T190430Z")


def test_the_provider_derives_the_count_the_parser_leaves_at_the_floor() -> None:
    record = fpl_entry_picks(
        _picks_payload(),
        _history_payload(current=[_row(1), _row(2), _row(3, transfers=1)]),
        entry_id=11,
        season="2026-27",
        gameweek=3,
    )
    assert (record.free_transfers, record.free_transfers_known) == (1, False)
    picks = _provider(cap=5).picks(11, "2026-27", 3)
    assert (picks.free_transfers, picks.free_transfers_known) == (2, True)


def test_the_provider_keeps_the_floor_when_the_capture_states_no_cap() -> None:
    picks = _provider(cap=None).picks(11, "2026-27", 3)
    assert (picks.free_transfers, picks.free_transfers_known) == (1, False)


# The fifteen members of the real GW3 capture (fpl-live-20260910T190430Z-369360398135):
# per week (transfers, cost), the chips played, and the count the model derives for the
# GW4 deadline. Every recorded hit, including the two paid ones (7018833 GW3 with two free
# and 8548384 GW2 with one), is reproduced by the model, which is the cross-check that
# earns the flag. Eight of the fifteen held two or three, not the one assumed before.
REAL_GW3_CAPTURE = (
    (2199732, ((0, 0), (1, 0), (0, 0)), (), 2),
    (2281624, ((0, 0), (1, 0), (1, 0)), (("bboost", 1), ("3xc", 3)), 1),
    (313686, ((0, 0), (0, 0), (1, 0)), (("bboost", 1),), 2),
    (3832237, ((0, 0), (0, 0), (0, 0)), (("3xc", 1),), 3),
    (4287206, ((0, 0), (0, 0), (0, 0)), (("freehit", 3),), 3),
    (5081114, ((0, 0), (1, 0), (1, 0)), (), 1),
    (5349883, ((0, 0), (1, 0), (0, 0)), (("bboost", 1),), 2),
    (5662073, ((0, 0), (0, 0), (0, 0)), (("freehit", 3),), 3),
    (6654210, ((0, 0), (0, 0), (2, 0)), (("3xc", 3),), 1),
    (6879786, ((0, 0), (1, 0), (0, 0)), (), 2),
    (6880255, ((0, 0), (0, 0), (2, 0)), (), 1),
    (7018833, ((0, 0), (0, 0), (3, 4)), (("bboost", 3),), 1),
    (7252721, ((0, 0), (0, 0), (2, 0)), (), 1),
    (8548384, ((0, 0), (2, 4), (1, 0)), (("3xc", 3),), 1),
    (8883467, ((0, 0), (0, 0), (0, 0)), (("wildcard", 2), ("3xc", 3)), 3),
)


@pytest.mark.parametrize(("entry", "weeks", "chips", "expected"), REAL_GW3_CAPTURE)
def test_the_model_reproduces_every_hit_of_the_real_gw3_capture(
    entry: int,
    weeks: tuple[tuple[int, int], ...],
    chips: tuple[tuple[str, int], ...],
    expected: int,
) -> None:
    rows = [_row(week, transfers, cost) for week, (transfers, cost) in enumerate(weeks, 1)]
    history = entry_transfer_history(
        _history_payload(
            current=rows,
            chips=[{"name": name, "event": event} for name, event in chips],
        ),
        entry_id=entry,
    )
    result = banked_free_transfers(history, gameweek=3, max_free_transfers=5)
    assert result == BankedFreeTransfers(expected, True)
