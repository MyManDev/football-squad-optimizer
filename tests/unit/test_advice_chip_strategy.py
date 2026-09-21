"""Real joint chip advice: rule rights, raw scoring and switched identity."""

import json
import math
from dataclasses import replace

import pytest
import tests.unit.test_advice_variants as variants
import tests.unit.test_member_windows as windows
from tests.unit.test_advice_menu import _collaborators, _request
from tests.unit.test_league_views import _Provider
from tests.unit.test_member_windows import ENTRY, SEASON

from squadopt.application.advice import NO_CHIP_LIMIT
from squadopt.application.advice_menu import advise_menu_entry
from squadopt.live.chip_strategy import strategy_chip_availability
from squadopt.live.rules import ChipWindow
from squadopt.platform.advice_documents import validate_advice_document

world = variants._world
window_world = windows._window_world


def prepared(world):
    picks = world["provider"].picks(ENTRY, SEASON, 1)
    rules = replace(
        world["rules"],
        chips=tuple(
            ChipWindow(name, 1, start, stop, "team")
            for name in ("3xc", "bboost", "wildcard", "freehit")
            for start, stop in ((1, 19), (20, 38))
        ),
    )
    return {**world, "rules": rules, "provider": _Provider({ENTRY: replace(picks, chips_used={})})}


@pytest.mark.parametrize(
    "window,chip,weight",
    [
        (1, "auto", 0),
        (3, "auto", 20),
        (5, "auto", 50),
        (3, "3xc", 20),
        (5, "bboost", 50),
        (3, "wildcard", 0),
        (3, "freehit", 20),
    ],
)
def test_joint_advice_scores_chips_in_raw_points(world, window, chip, weight):
    w = prepared(world)
    payload = advise_menu_entry(
        _request(window=window, chip=chip, top100_weight=weight),
        **_collaborators(w),
        top100_counts=w["counts"],
    )
    validate_advice_document(
        json.dumps(
            {
                "contract_version": "provisional_league_ui_v1",
                "generated_at_utc": "2026-08-27T08:00:00Z",
                "source_kind": "example",
                "payload": payload,
            }
        ).encode()
    )
    strategy = payload["chip_strategy"]
    assert strategy["requested_chip"] == chip
    assert strategy["selected_chip"] == payload["chip"]
    assert strategy["top100_weight"] == weight
    assert len(payload["plan_weeks"]) == window
    assert NO_CHIP_LIMIT not in payload["stated_limits"]
    total = math.fsum(p["expected_points"] for p in payload["starting_xi"])
    total += payload["captain"]["expected_points"] * (2 if payload["chip"] == "3xc" else 1)
    if payload["chip"] == "bboost":
        total += math.fsum(p["expected_points"] for p in payload["bench"])
    assert payload["expected_own_points"] == pytest.approx(total)
    assert payload["plan_weeks"][0]["expected_points"] == pytest.approx(total)
    if chip != "auto":
        assert payload["chip"] == chip
        assert all(row["chip"] is None for row in payload["plan_weeks"][1:])
    if weight and payload["moves"]:
        from squadopt.application.advice_variants import weighted_horizon
        from squadopt.application.lineup_publication import best_eleven_basis

        picks = w["provider"].picks(ENTRY, SEASON, 1)
        collaborators = _collaborators(w)
        base = collaborators["horizon_builder"](tuple(range(1, window + 1)))
        weighted = weighted_horizon(base, w["counts"].counts, weight)
        raw = base.table.loc[base.table.gameweek.eq(1)].set_index("player_id")
        utility = weighted.table.loc[weighted.table.gameweek.eq(1)].set_index("player_id")
        hold = best_eleven_basis(
            (
                (
                    str(raw.loc[p, "position"]),
                    float(utility.loc[p, "expected_points"]),
                    float(raw.loc[p, "expected_points"]),
                    True,
                    True,
                    p,
                )
                for p in picks.squad
            ),
            chip=payload["chip"],
        )
        assert payload["expected_gain_vs_hold"] == pytest.approx(total - hold)
        assert sum(m["expected_points_delta"] for m in payload["moves"]) == pytest.approx(
            total - hold
        )
    assert payload["optimality_gap"] is None  # reserve/Top100 objective is not match points


def test_rule_adapter_keeps_renewals_and_historical_free_hit_separate(world):
    w = prepared(world)
    chips = strategy_chip_availability(w["rules"], (19, 20, 21), {"freehit": (19,), "3xc": (4,)})
    assert len(chips.windows_for("bboost")) == 2
    assert len(chips.windows_for("3xc")) == 1
    assert 20 not in chips.gameweeks_for("freehit")
    assert 21 in chips.gameweeks_for("freehit")
    with pytest.raises(ValueError, match="history"):
        strategy_chip_availability(w["rules"], (19, 20, 21), None)
