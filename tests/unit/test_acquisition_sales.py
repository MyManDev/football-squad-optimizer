"""Hand-accounted purchase lots across complete multiweek decisions."""

from dataclasses import replace

import pandas as pd
import pytest

from squadopt.planning import ChipAvailability, InitialSquadState, PlanningHorizon
from squadopt.planning.models import TransferPlanningConfig, TransferPlanningConfigurationError
from squadopt.planning.optimizer import optimize_transfer_plan

BASE = ("GK_A", "DEF_A", "MID_A")


def _solve(
    players,
    config,
    prices,
    forwards,
    *,
    fee=0.5,
    freehit=None,
    wildcard=None,
    bank=20,
    original="FWD_A",
    supplied=None,
):
    parts = []
    for week, price in enumerate(prices, 1):
        frame = players.assign(gameweek=week, buy_price_tenths=50, sell_price_tenths=50)
        frame.loc[frame.player_id.eq("FWD_B"), ["buy_price_tenths", "sell_price_tenths"]] = price
        if supplied is not None:
            frame.loc[frame.player_id.eq("FWD_B"), "sell_price_tenths"] = supplied[week - 1]
        parts.append(frame)
    forced = {w: chip for w, chip in ((freehit, "freehit"), (wildcard, "wildcard")) if w}
    chips = ChipAvailability(
        available={chip: frozenset({w}) for w, chip in forced.items()}, forced=forced
    )
    return optimize_transfer_plan(
        PlanningHorizon(pd.concat(parts, ignore_index=True)),
        InitialSquadState((*BASE, original), bank, 1),
        replace(config, solver_time_limit_seconds=30),
        TransferPlanningConfig(acquisition_sell_on_fee=fee),
        chips=chips,
        fixed_week_squads={w: (*BASE, f) for w, f in enumerate(forwards, 1)},
    )


@pytest.mark.parametrize(
    ("fee", "expected"),
    [
        (None, [20, 23, 17, 26, 26]),
        (0.5, [20, 21, 15, 22, 22]),
        (0.0, [20, 23, 17, 26, 26]),
        (1.0, [20, 20, 14, 20, 20]),
    ],
)
def test_repurchase_resets_sale_basis(known_optimum_players, small_config, fee, expected):
    result = _solve(
        known_optimum_players,
        small_config,
        [50, 53, 56, 59, 62],
        ["FWD_B", "FWD_A", "FWD_B", "FWD_A", "FWD_A"],
        fee=fee,
    )
    assert result.solver_status.name == "OPTIMAL"
    assert [w.bank_after_tenths for w in result.weeks] == expected
    if fee is not None:
        assert result.weeks[1].transfers_out.iloc[0].sell_price_tenths == 50 + int(3 * (1 - fee))
        assert result.weeks[3].transfers_out.iloc[0].sell_price_tenths == 56 + int(3 * (1 - fee))


@pytest.mark.parametrize("chip", ["freehit", "wildcard"])
def test_rebuild_restores_or_retains_the_correct_lot(known_optimum_players, small_config, chip):
    # Week 2 temporarily/permanently replaces the player bought in week 1.
    # FH returns that purchase lot; WC starts week 3 from A and buys B anew.
    result = _solve(
        known_optimum_players,
        small_config,
        [50, 53, 56, 59, 62],
        ["FWD_B", "FWD_A", "FWD_B", "FWD_A", "FWD_A"],
        **{chip: 2},
    )
    assert result.solver_status.name == "OPTIMAL"
    expected = [20, 21, 20, 24, 24] if chip == "freehit" else [20, 21, 15, 22, 22]
    assert [w.bank_after_tenths for w in result.weeks] == expected
    assert result.weeks[2].bank_before_tenths == (20 if chip == "freehit" else 21)
    assert result.weeks[2].free_transfers_before == result.weeks[1].free_transfers_before


def test_price_fall_is_borne_in_full(known_optimum_players, small_config):
    result = _solve(known_optimum_players, small_config, [50, 47, 45], ["FWD_B", "FWD_A", "FWD_A"])
    assert [w.bank_after_tenths for w in result.weeks] == [20, 17, 17]


def test_false_affordability_is_rejected(known_optimum_players, small_config):
    # Sell B after a rise, then buy it back. Supplied prices invent two tenths.
    args = (known_optimum_players, small_config, [50, 53, 53], ["FWD_B", "FWD_A", "FWD_B"])
    assert _solve(*args, fee=None, bank=0).has_solution
    assert _solve(*args, bank=0).solver_status.name == "INFEASIBLE"


@pytest.mark.parametrize("fee", [-0.01, 1.01, float("nan"), True])
def test_bad_fee_rejected(fee):
    with pytest.raises(TransferPlanningConfigurationError, match="acquisition_sell_on_fee"):
        TransferPlanningConfig(acquisition_sell_on_fee=fee)


def test_configuration_distinguishes_the_acquisition_policy():
    base = TransferPlanningConfig()
    assert (
        base.configuration_fingerprint
        == TransferPlanningConfig(acquisition_sell_on_fee=None).configuration_fingerprint
    )
    assert (
        base.configuration_fingerprint
        != TransferPlanningConfig(acquisition_sell_on_fee=0.5).configuration_fingerprint
    )


def test_original_unknown_lot_is_preserved_until_repurchase(known_optimum_players, small_config):
    result = _solve(
        known_optimum_players,
        small_config,
        [60, 63, 66, 69, 72],
        ["FWD_B", "FWD_A", "FWD_B", "FWD_A", "FWD_A"],
        original="FWD_B",
        supplied=[52, 53, 55, 56, 58],
    )
    # Original lot sells for supplied 53. Rebuy costs 66, later sells for 67.
    assert [w.bank_after_tenths for w in result.weeks] == [20, 23, 7, 24, 24]
    assert result.weeks[1].transfers_out.iloc[0].sell_price_tenths == 53
    assert result.weeks[3].transfers_out.iloc[0].sell_price_tenths == 67


def test_temporary_freehit_purchase_does_not_become_permanent(known_optimum_players, small_config):
    result = _solve(
        known_optimum_players,
        small_config,
        [50, 53, 56, 59, 62],
        ["FWD_B", "FWD_A", "FWD_B", "FWD_A", "FWD_A"],
        freehit=1,
    )
    # FH buys at 50, but the permanent purchase is week 3 at 56.
    assert [w.bank_after_tenths for w in result.weeks] == [20, 20, 14, 21, 21]
    assert result.weeks[3].transfers_out.iloc[0].sell_price_tenths == 57


@pytest.mark.parametrize("fee,expected", [(0.0, 53), (0.5, 51), (1.0, 50)])
def test_observed_continuation_rebases_with_the_supplied_fee(
    known_optimum_players, small_config, fee, expected
):
    from squadopt.planning.recourse import ObservationNode, _continuation_horizon

    result = _solve(
        known_optimum_players, small_config, [50, 53, 56], ["FWD_B", "FWD_B", "FWD_A"], fee=fee
    )
    frame = known_optimum_players.assign(gameweek=2, buy_price_tenths=50, sell_price_tenths=50)
    frame.loc[frame.player_id.eq("FWD_B"), "buy_price_tenths"] = 53
    node = ObservationNode("news", 1.0, PlanningHorizon(frame))
    horizon = _continuation_horizon(node, result.weeks[0], sell_on_fee=fee)
    assert (
        horizon.table.loc[horizon.table.player_id.eq("FWD_B"), "sell_price_tenths"].item()
        == expected
    )
