"""Finite dated opportunity assignment, without stochastic or season extrapolation."""

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from itertools import product

import pytest

from squadopt.planning import ChipAvailability, ChipUseWindow
from squadopt.planning.chip_tail import (
    ChipTailForecast,
    DatedChipOpportunity,
    build_chip_tail_table,
    chip_tail_context_fingerprint,
)

AS_OF = datetime(2026, 1, 1, tzinfo=UTC)


def declared_tail(chips, end, value=10, context="context"):
    return ChipTailForecast(
        context,
        "a" * 64,
        AS_OF,
        tuple(
            DatedChipOpportunity(
                name,
                gw,
                AS_OF + timedelta(days=gw),
                value.get((name, gw), 0) if isinstance(value, dict) else value,
            )
            for name in sorted(chips.available)
            for gw in sorted(chips.available[name])
            if gw > end
        ),
    )


def for_decision(
    horizon, initial, config, transfer, chips, value, expected=False, preferences=None
):
    return declared_tail(
        chips,
        horizon.gameweeks[-1],
        value,
        chip_tail_context_fingerprint(
            horizon, initial, config, transfer, preferences, expected_lineups=expected
        ),
    )


def test_joint_tail_does_not_double_book_date_and_renews_separate_rights():
    chips = ChipAvailability(
        {"3xc": frozenset({1, 2, 3}), "bboost": frozenset({1, 2})},
        use_windows={"3xc": (ChipUseWindow(frozenset({1, 2})), ChipUseWindow(frozenset({3})))},
    )
    forecast = declared_tail(chips, 1, {("3xc", 2): 10, ("bboost", 2): 9, ("3xc", 3): 7})
    table = build_chip_tail_table(chips, 1, forecast, context_fingerprint="context")
    assert table.value({}) == 17  # not 26: TC and BB compete for GW2
    assert table.value({1: "3xc"}) == 16  # renewed TC in GW3 is still available
    assert table.value({1: "bboost"}) == 17


def test_free_hit_boundary_and_later_consecutive_rights_cannot_collide():
    chips = ChipAvailability(
        {"freehit": frozenset({1, 2, 3})},
        use_windows={"freehit": tuple(ChipUseWindow(frozenset({gw})) for gw in (1, 2, 3))},
    )
    table = build_chip_tail_table(
        chips,
        1,
        declared_tail(chips, 1, {("freehit", 2): 20, ("freehit", 3): 7}),
        context_fingerprint="context",
    )
    assert table.value({}) == 20
    assert table.value({1: "freehit"}) == 7


def test_tail_equals_exhaustive_assignment_for_every_current_right_subset():
    chips = ChipAvailability({"3xc": frozenset({1, 2, 3}), "bboost": frozenset({1, 2, 3})})
    gains = {("3xc", 2): 10, ("3xc", 3): 3, ("bboost", 2): 9, ("bboost", 3): 8}
    table = build_chip_tail_table(
        chips, 1, declared_tail(chips, 1, gains), context_fingerprint="context"
    )
    for mask, last_fh, value in table.values:
        assert last_fh in (0, 1)
        used = {name for i, (name, _) in enumerate(table.rights) if mask & (1 << i)}
        valid = []
        for schedule in product((None, "3xc", "bboost"), repeat=2):
            names = [name for name in schedule if name]
            if len(names) != len(set(names)) or set(names) & used:
                continue
            valid.append(
                sum(gains[name, gw] for gw, name in zip((2, 3), schedule, strict=True) if name)
            )
        assert value == max(valid)


def test_forced_future_use_prevents_spending_the_same_right_now():
    chips = ChipAvailability({"3xc": frozenset({1, 2})}, {2: "3xc"})
    table = build_chip_tail_table(chips, 1, declared_tail(chips, 1), context_fingerprint="context")
    assert table.value({}) == 10
    with pytest.raises(ValueError, match="forced future"):
        table.value({1: "3xc"})


@pytest.mark.parametrize(
    "change,match",
    [
        (lambda f: None, "validated dated"),
        (lambda f: replace(f, opportunities=()), "every remaining"),
        (lambda f: replace(f, context_fingerprint="other"), "context differs"),
        (lambda f: replace(f, source_fingerprint="unknown"), "SHA256"),
        (lambda f: replace(f, as_of=f.as_of.replace(tzinfo=None)), "UTC"),
        (
            lambda f: replace(f, opportunities=(replace(f.opportunities[0], deadline=AS_OF),)),
            "future UTC",
        ),
        (lambda f: replace(f, opportunities=f.opportunities * 2), "uniquely"),
        (
            lambda f: replace(
                f, opportunities=(replace(f.opportunities[0], marginal_utility=float("nan")),)
            ),
            "finite",
        ),
    ],
)
def test_missing_unbound_or_invalid_opportunities_are_refused(change, match):
    chips = ChipAvailability({"3xc": frozenset({1, 2})})
    with pytest.raises(ValueError, match=match):
        build_chip_tail_table(
            chips, 1, change(declared_tail(chips, 1)), context_fingerprint="context"
        )


def test_expiring_right_needs_no_tail():
    chips = ChipAvailability({"3xc": frozenset({1})})
    table = build_chip_tail_table(chips, 1, None, context_fingerprint="context")
    assert table.value({}) == table.value({1: "3xc"}) == 0


def test_context_changes_with_resources_objective_and_preferences(
    known_optimum_players, small_config
):
    from tests.unit.test_transfer_planning import OPTIMAL_INITIAL, _horizon_table

    from squadopt.contracts.preferences import DecisionPreferences
    from squadopt.planning import PlanningHorizon, TransferPlanningConfig

    horizon = PlanningHorizon(_horizon_table(known_optimum_players))
    transfer = TransferPlanningConfig()

    def fingerprint(initial=OPTIMAL_INITIAL, config=small_config, prefs=None, expected=False):
        return chip_tail_context_fingerprint(
            horizon, initial, config, transfer, prefs, expected_lineups=expected
        )

    base = fingerprint()
    assert fingerprint(initial=replace(OPTIMAL_INITIAL, bank_tenths=10)) != base
    assert fingerprint(initial=replace(OPTIMAL_INITIAL, free_transfers=2)) != base
    assert fingerprint(prefs=DecisionPreferences(save_chips=True)) != base
    assert fingerprint(expected=True) != base
    assert fingerprint(config=replace(small_config, solver_deterministic_time_limit=60)) == base
