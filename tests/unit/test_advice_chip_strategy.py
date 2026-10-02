"""Real joint chip advice: rule rights, raw scoring and switched identity."""

import json
import math
from dataclasses import replace
from datetime import datetime, timedelta

import pytest
import tests.unit.test_advice_variants as variants
import tests.unit.test_member_windows as windows
from tests.unit.test_advice_menu import _collaborators, _request
from tests.unit.test_league_views import _Provider
from tests.unit.test_member_windows import ENTRY, SEASON

from squadopt.application.advice import NO_CHIP_LIMIT
from squadopt.application.advice_capabilities import AUTOMATIC_CHIP
from squadopt.application.advice_chip_strategy import advise_chip_strategy
from squadopt.application.advice_menu import advise_menu_entry
from squadopt.application.entries import EntryError
from squadopt.contracts.preferences import NO_PREFERENCES, DecisionPreferences
from squadopt.data.errors import DataSourceError
from squadopt.live.chip_strategy import strategy_chip_availability
from squadopt.live.rules import ChipWindow
from squadopt.platform.advice_documents import validate_advice_document

world = variants._world
window_world = windows._window_world


def _advise(w, *, window, chip, weight, preferences=NO_PREFERENCES, chip_tail_forecast=None):
    """The member menu, or the planner itself for the automatic strategy the menu refuses.

    The automatic strategy is off the member menu (audit 2026-09-25, H3) but stays in the
    code for research, so its accounting is still checked here, one call below the menu.
    """

    request = _request(window=window, chip=chip, top100_weight=weight, preferences=preferences)
    if chip != AUTOMATIC_CHIP:
        return advise_menu_entry(request, **_collaborators(w), top100_counts=w["counts"])
    return advise_chip_strategy(
        request.entry_request(),
        chip=chip,
        top100_weight=weight,
        **_collaborators(w),
        counts=w["counts"],
        preferences=preferences,
        chip_tail_forecast=chip_tail_forecast,
    )


@pytest.mark.parametrize("window", [1, 3, 5])
def test_the_member_menu_refuses_the_automatic_chip_strategy(world, window):
    with pytest.raises(EntryError, match="automatic chip strategy is not offered"):
        advise_menu_entry(
            _request(window=window, chip=AUTOMATIC_CHIP),
            **_collaborators(prepared(world)),
        )


@pytest.mark.parametrize(
    ("length", "weight", "chip"), [(1, 0, None), (3, 20, None), (5, 50, None), (3, 0, "auto")]
)
def test_preferences_are_applied_and_identified_by_real_menu(world, length, weight, chip):
    # No continuation estimate is invented: these synthetic rights expire in the window.
    w = prepared(world, expires=length + 1) if chip == "auto" else prepared(world)
    picks = w["provider"].picks(ENTRY, SEASON, 1)
    keep = tuple(picks.squad)[:2]
    preferences = DecisionPreferences(keep_players=keep, no_hits=True, save_chips=chip is None)
    payload = _advise(w, window=length, chip=chip, weight=weight, preferences=preferences)
    assert payload["preferences"] == preferences.payload()
    assert payload["preferences_scope"] == "all_selected_weeks"
    selected = {p["player_id"] for p in payload["starting_xi"] + payload["bench"]}
    assert set(keep) <= selected
    assert all(w["transfer_hit_points"] == 0 for w in payload["plan_weeks"])
    if chip is None:
        assert all(w["chip"] is None for w in payload["plan_weeks"])
        assert payload.get("selection_top100_weight", 0) == weight


def prepared(world, *, expires=None):
    picks = world["provider"].picks(ENTRY, SEASON, 1)
    rules = replace(
        world["rules"],
        chips=tuple(
            ChipWindow(name, 1, start, stop, "team")
            for name in ("3xc", "bboost", "wildcard", "freehit")
            for start, stop in (((1, expires),) if expires is not None else ((1, 19), (20, 38)))
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
    w = prepared(world, expires=window + 1) if chip == "auto" else prepared(world)
    payload = _advise(w, window=window, chip=chip, weight=weight)
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
        start = payload["gameweek"]
        base = collaborators["horizon_builder"](tuple(range(start, start + window)))
        weighted = weighted_horizon(base, w["counts"].counts, weight)
        raw = base.table.loc[base.table.gameweek.eq(start)].set_index("player_id")
        utility = weighted.table.loc[weighted.table.gameweek.eq(start)].set_index("player_id")
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


@pytest.mark.parametrize("window", [1, 3, 5])
def test_automatic_advice_requires_declared_future_values(world, window):
    with pytest.raises(ValueError, match="validated dated future"):
        _advise(prepared(world), window=window, chip="auto", weight=0)


def test_bound_future_values_reach_the_real_chip_planner(world, monkeypatch):
    """A supplied calendar survives both adapters and cannot cross a user preference."""
    from tests.unit.test_chip_tail import for_decision

    import squadopt.live.transfers as transfers

    class ContextCaptured(Exception):
        pass

    calls = []

    def capture_context(*args, **kwargs):
        calls.append((args, kwargs))
        raise ContextCaptured

    w = prepared(world)
    preferences = DecisionPreferences(no_hits=True)
    # Record the native state for a synthetic calendar without running a solver or
    # duplicating the adapters' purchase-price, bank, FT and score-basis conversion.
    with monkeypatch.context() as patch:
        patch.setattr(transfers, "optimize_chip_strategy", capture_context)
        with pytest.raises(ContextCaptured):
            _advise(w, window=3, chip="auto", weight=20, preferences=preferences)
    assert len(calls) == 1
    args, kwargs = calls[0]
    forecast = for_decision(
        *args,
        value=1000,
        expected=kwargs["expected_lineups"],
        preferences=kwargs["preferences"],
    )
    capture = datetime.fromisoformat(w["inputs"].captured_at_utc.replace("Z", "+00:00"))
    deadline = datetime.fromisoformat(w["inputs"].deadline.deadline_utc.replace("Z", "+00:00"))
    forecast = replace(
        forecast,
        as_of=capture,
        opportunities=tuple(
            replace(item, deadline=deadline + timedelta(weeks=item.gameweek - 2))
            for item in forecast.opportunities
        ),
    )
    payload = _advise(
        w,
        window=3,
        chip="auto",
        weight=20,
        preferences=preferences,
        chip_tail_forecast=forecast,
    )
    assert payload["chip"] is None  # Each declared future use dominates current gain.
    assert payload["chip_strategy"]["mode"] == "auto"
    assert payload["preferences"] == preferences.payload()
    # Changing the human objective invalidates the old calendar before a solve.
    with pytest.raises(ValueError, match="context differs"):
        _advise(
            w,
            window=3,
            chip="auto",
            weight=50,
            preferences=preferences,
            chip_tail_forecast=forecast,
        )
    for invalid, reason in (
        (replace(forecast, as_of=capture + timedelta(seconds=1)), "known by the decision capture"),
        (
            replace(
                forecast,
                opportunities=(replace(forecast.opportunities[0], deadline=deadline),),
            ),
            "follow the current decision deadline",
        ),
    ):
        with pytest.raises(DataSourceError, match=reason):
            _advise(
                w,
                window=3,
                chip="auto",
                weight=20,
                preferences=preferences,
                chip_tail_forecast=invalid,
            )
