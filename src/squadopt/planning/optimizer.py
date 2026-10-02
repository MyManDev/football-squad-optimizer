"""Deterministic CP-SAT optimizer for multi-gameweek transfer planning."""

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from decimal import Decimal
from itertools import pairwise
from numbers import Integral
from time import perf_counter
from typing import Final

import pandas as pd
from ortools.sat.python import cp_model

from squadopt.contracts.preferences import DecisionPreferences
from squadopt.optimization import (
    InvalidConfigurationError,
    OptimizationConfig,
    SolverExecutionError,
    SolverStatus,
)
from squadopt.optimization.coefficients import (
    objective_coefficients,
    round_half_up,
    scale_expected_points,
    sort_players_by_id,
)
from squadopt.optimization.config import POSITIONS
from squadopt.optimization.decisions import (
    add_decision_constraints as _add_decision_constraints,
)
from squadopt.optimization.decisions import (
    selected_indices as _selected_indices,
)
from squadopt.optimization.decisions import (
    verify_solution as _verify_solution,
)
from squadopt.optimization.optimizer import (
    CP_SAT_SAFE_INTEGER_MAX,
    MIN_TIEBREAK_DETERMINISTIC_TIME,
    _deterministic_time_used,
    _map_solver_status,
    _raw_status_name,
    _remaining_deterministic_time,
    _solve,
    configure_solver,
)
from squadopt.optimization.validation import validate_players
from squadopt.planning.acquisition import AcquisitionSales
from squadopt.planning.chip_tail import ChipTailTable
from squadopt.planning.models import (
    ChipAvailability,
    FirstWeekExclusion,
    FirstWeekOverlap,
    InitialSquadState,
    PlanningHorizon,
    PlanningWeekResult,
    TransferPlanningConfig,
    TransferPlanningConfigurationError,
    TransferPlanningValidationError,
    TransferPlanResult,
)
from squadopt.planning.pricing import sell_price_tenths

# The wall ceiling bounds each phase rather than being divided between them, so a solve
# that reached it in both phases would stop at twice this value. That is the shape
# `optimization/optimizer.py` has had since #192.
#
# A wall-clock budget only decides anything when it is what stops the search -- and then
# the answer is a function of the CPU share the process happened to receive. Fifteen
# members solved back to back inherit exactly that: which of them proves its plan optimal
# depends on the machine and its load, not on the problem (#247, measured for the rank
# objective as #239). CP-SAT's deterministic time is the budget that gives a truncated
# search a reproducible stopping point, so it is the default budget here, as it already
# is for the rank objective (#244). These limits apply only when the caller has not
# chosen a deterministic budget of their own.
#
# The budget is measured, not guessed: on the GW2 capture the hardest of the fifteen
# registered members proves its primary plan optimal at 16.25 deterministic units, so
# the default covers that with headroom. A member that still exhausts it returns
# FEASIBLE with ``deterministic_time_budget_exhausted`` set -- deterministically, on
# every machine.
#
# The wall ceiling is not a second budget: it is high enough never to bind a normal
# solve, and exists only so a pathological run still ends. If it ever binds, determinism
# is gone again and the diagnostics say so.
PLAN_DETERMINISTIC_TIME_LIMIT: Final = 20.0
PLAN_WALL_CEILING_SECONDS: Final = 300.0


@dataclass(frozen=True, slots=True)
class _PlanArtifacts:
    model: cp_model.CpModel
    players_by_week: list[pd.DataFrame]
    squad_vars: list[list[cp_model.IntVar]]
    starter_vars: list[list[cp_model.IntVar]]
    captain_vars: list[list[cp_model.IntVar]]
    transfer_in_vars: list[list[cp_model.IntVar]]
    transfer_out_vars: list[list[cp_model.IntVar]]
    bank_after_vars: list[cp_model.IntVar]
    free_before_vars: list[cp_model.IntVar]
    free_unused_vars: list[cp_model.IntVar]
    free_next_vars: list[cp_model.IntVar]
    transfer_count_vars: list[cp_model.IntVar]
    paid_transfer_vars: list[cp_model.IntVar]
    primary_objective: cp_model.LinearExpr
    discount_weights: list[int]
    hit_cost_scaled: int
    chip_vars: list[dict[str, cp_model.IntVar]]
    chips: ChipAvailability
    chip_tail: ChipTailTable | None


def _validated_week_tables(
    horizon: PlanningHorizon,
    config: OptimizationConfig,
) -> list[pd.DataFrame]:
    tables: list[pd.DataFrame] = []
    expected_order: list[object] | None = None
    for gameweek in horizon.gameweeks:
        week = horizon.table.loc[horizon.table["gameweek"] == gameweek].copy(deep=True)
        week.loc[:, "price_tenths"] = week["buy_price_tenths"]
        validated = sort_players_by_id(validate_players(week, config))
        player_order = validated["player_id"].tolist()
        if expected_order is None:
            expected_order = player_order
        elif player_order != expected_order:
            raise TransferPlanningValidationError(
                "Stable player ordering must align across every planning gameweek."
            )
        tables.append(validated)
    return tables


def _validate_initial_state(
    initial_state: InitialSquadState,
    players: pd.DataFrame,
    optimization_config: OptimizationConfig,
    transfer_config: TransferPlanningConfig,
) -> set[object]:
    player_ids = players["player_id"].tolist()
    initial_ids = set(initial_state.squad_player_ids)
    if len(initial_state.squad_player_ids) != optimization_config.squad_size:
        raise TransferPlanningValidationError(
            "Initial squad size must equal optimization_config.squad_size."
        )
    missing = sorted(initial_ids - set(player_ids), key=str)
    if missing:
        raise TransferPlanningValidationError(
            f"Initial squad contains players outside the planning horizon: {missing[:10]!r}."
        )
    if initial_state.free_transfers > transfer_config.max_free_transfers:
        raise TransferPlanningValidationError(
            "Initial free_transfers may not exceed max_free_transfers."
        )
    initial_rows = players.loc[players["player_id"].isin(initial_ids)]
    position_counts = Counter(initial_rows["position"])
    for position in POSITIONS:
        if position_counts[position] != optimization_config.squad_position_limits[position]:
            raise TransferPlanningValidationError(
                f"Initial squad violates the {position} position quota."
            )
    # The club limit is not checked on the held squad: a player who moved clubs after he
    # was bought can leave a manager holding four from one club, which the game allows
    # until the next transfer. Every planned squad still satisfies the limit, so such a
    # start forces a sale rather than a refusal.
    return initial_ids


def _discount_weights(
    horizon_length: int,
    transfer_config: TransferPlanningConfig,
) -> list[int]:
    base = Decimal(str(transfer_config.horizon_discount_factor))
    scale = Decimal(transfer_config.objective_weight_scale)
    weights = [round_half_up((base**offset) * scale) for offset in range(horizon_length)]
    if any(weight < 1 for weight in weights):
        raise TransferPlanningConfigurationError(
            "Discounted horizon weights rounded to zero; increase objective_weight_scale or "
            "shorten the horizon."
        )
    return weights


def _validate_integer_bounds(
    players_by_week: list[pd.DataFrame],
    initial_state: InitialSquadState,
    optimization_config: OptimizationConfig,
    transfer_config: TransferPlanningConfig,
    discount_weights: list[int],
    hit_cost_scaled: int,
    banked_value_scaled: int,
    chips: ChipAvailability,
    chip_tail: ChipTailTable | None = None,
) -> int:
    objective_bound = 0
    bank_bound = initial_state.bank_tenths
    for players, discount_weight in zip(players_by_week, discount_weights, strict=True):
        coefficients = objective_coefficients(
            players["expected_points"].tolist(), optimization_config
        )
        objective_bound += discount_weight * sum(
            abs(squad) + abs(starter) + abs(captain) for squad, starter, captain in coefficients
        )
        # A bench boost adds every squad member's unweighted remainder; a triple
        # captain adds the captain's points once more. Both bounded by the sums below.
        objective_bound += discount_weight * sum(
            abs(starter) + abs(captain) for _, starter, captain in coefficients
        )
        objective_bound += discount_weight * abs(hit_cost_scaled) * optimization_config.squad_size
        objective_bound += (
            discount_weight * abs(banked_value_scaled) * transfer_config.max_free_transfers
        )
        largest_sell_prices = sorted(
            (
                int(value)
                for value in players[
                    "buy_price_tenths"
                    if transfer_config.acquisition_sell_on_fee is not None
                    else "sell_price_tenths"
                ]
            ),
            reverse=True,
        )[: optimization_config.squad_size]
        bank_bound += sum(largest_sell_prices)
    objective_bound += discount_weights[-1] * sum(
        abs(
            scale_expected_points(
                (
                    transfer_config.chip_holding_value_points.get(name, 0.0)
                    if p.holding_value_points is None
                    else p.holding_value_points
                ),
                optimization_config.expected_points_scale,
            )
        )
        for name in chips.available
        for p in chips.windows_for(name)
    )
    if chip_tail is not None:
        objective_bound += discount_weights[-1] * max(
            (
                scale_expected_points(value, optimization_config.expected_points_scale)
                for _, _, value in chip_tail.values
            ),
            default=0,
        )
    if objective_bound > CP_SAT_SAFE_INTEGER_MAX:
        raise SolverExecutionError(
            "Transfer-plan objective exceeds the safe CP-SAT integer range; reduce the horizon, "
            "expected_points_scale, or objective_weight_scale."
        )
    if bank_bound > CP_SAT_SAFE_INTEGER_MAX:
        raise SolverExecutionError(
            "Transfer-plan price accounting exceeds the safe CP-SAT integer range."
        )
    return bank_bound


def _build_model(
    players_by_week: list[pd.DataFrame],
    initial_ids: set[object],
    initial_state: InitialSquadState,
    optimization_config: OptimizationConfig,
    transfer_config: TransferPlanningConfig,
    chips: ChipAvailability,
    chip_tail: ChipTailTable | None = None,
) -> _PlanArtifacts:
    model = cp_model.CpModel()
    player_count = len(players_by_week[0])
    week_count = len(players_by_week)
    horizon_gameweeks = [int(players.iloc[0]["gameweek"]) for players in players_by_week]
    # A chip is a variable only in the gameweeks it is available in; a chip available
    # only outside this horizon simply has no variable here.
    chip_vars: list[dict[str, cp_model.IntVar]] = []
    for gameweek in horizon_gameweeks:
        week_chips: dict[str, cp_model.IntVar] = {}
        for name in chips.available:
            if gameweek in chips.gameweeks_for(name):
                week_chips[name] = model.new_bool_var(f"chip_{name}_gw{gameweek}")
        if len(week_chips) > 1:
            model.add(cp_model.LinearExpr.sum(list(week_chips.values())) <= 1)
        forced = chips.forced.get(gameweek)
        if forced is not None:
            model.add(week_chips[forced] == 1)
        chip_vars.append(week_chips)
    for name in chips.available:
        for period in chips.windows_for(name):
            plays = [
                week[name]
                for gw, week in zip(horizon_gameweeks, chip_vars, strict=True)
                if name in week and gw in period.gameweeks
            ]
            if len(plays) > 1:
                model.add(cp_model.LinearExpr.sum(plays) <= 1)
    # Two separate Free Hit rights still cannot be used in consecutive gameweeks.
    for left, right in pairwise(chip_vars):
        if "freehit" in left and "freehit" in right:
            model.add(left["freehit"] + right["freehit"] <= 1)
    discount_weights = _discount_weights(week_count, transfer_config)
    hit_cost_scaled = scale_expected_points(
        transfer_config.transfer_hit_cost_points,
        optimization_config.expected_points_scale,
    )
    banked_value_scaled = scale_expected_points(
        transfer_config.banked_transfer_value_points,
        optimization_config.expected_points_scale,
    )
    bank_bound = _validate_integer_bounds(
        players_by_week,
        initial_state,
        optimization_config,
        transfer_config,
        discount_weights,
        hit_cost_scaled,
        banked_value_scaled,
        chips,
        chip_tail,
    )

    squad_vars: list[list[cp_model.IntVar]] = []
    base_squad_vars: list[list[cp_model.LinearExpr | int]] = []
    base_bank_vars: list[cp_model.LinearExpr | int] = []
    starter_vars: list[list[cp_model.IntVar]] = []
    captain_vars: list[list[cp_model.IntVar]] = []
    transfer_in_vars: list[list[cp_model.IntVar]] = []
    transfer_out_vars: list[list[cp_model.IntVar]] = []
    bank_after_vars: list[cp_model.IntVar] = []
    free_before_vars: list[cp_model.IntVar] = []
    free_unused_vars: list[cp_model.IntVar] = []
    free_next_vars: list[cp_model.IntVar] = []
    transfer_count_vars: list[cp_model.IntVar] = []
    paid_transfer_vars: list[cp_model.IntVar] = []
    objective_terms: list[cp_model.LinearExpr] = []
    acquisition = (
        AcquisitionSales(players_by_week, transfer_config.acquisition_sell_on_fee)
        if transfer_config.acquisition_sell_on_fee is not None
        else None
    )

    for week_index, players in enumerate(players_by_week):
        gameweek = int(players.iloc[0]["gameweek"])
        squads = [
            model.new_bool_var(f"squad_gw{gameweek}_{index}") for index in range(player_count)
        ]
        starters = [
            model.new_bool_var(f"starter_gw{gameweek}_{index}") for index in range(player_count)
        ]
        captains = [
            model.new_bool_var(f"captain_gw{gameweek}_{index}") for index in range(player_count)
        ]
        transfers_in = [
            model.new_bool_var(f"transfer_in_gw{gameweek}_{index}") for index in range(player_count)
        ]
        transfers_out = [
            model.new_bool_var(f"transfer_out_gw{gameweek}_{index}")
            for index in range(player_count)
        ]
        _add_decision_constraints(
            model,
            players,
            optimization_config,
            squads,
            starters,
            captains,
            enforce_budget=False,
        )
        free_hit = chip_vars[week_index].get("freehit")
        bases: list[cp_model.LinearExpr | int] = []
        for player_index, player_id in enumerate(players["player_id"]):
            previous: cp_model.LinearExpr | int
            if week_index == 0:
                previous = int(player_id in initial_ids)
            else:
                previous = base_squad_vars[week_index - 1][player_index]
            model.add(
                squads[player_index]
                == previous + transfers_in[player_index] - transfers_out[player_index]
            )
            # The squad the next week starts from: this week's squad, or — under a free
            # hit, which makes this week's squad temporary — the squad this week started
            # from. A Boolean base variable pinned to one or the other by the chip.
            base: cp_model.LinearExpr | int
            if free_hit is None:
                base = squads[player_index]
            else:
                base_var = model.new_bool_var(f"base_gw{gameweek}_{player_index}")
                model.add(base_var >= squads[player_index] - free_hit)
                model.add(base_var <= squads[player_index] + free_hit)
                model.add(base_var >= previous - (1 - free_hit))
                model.add(base_var <= previous + (1 - free_hit))
                base = base_var
            bases.append(base)
            model.add(transfers_in[player_index] + transfers_out[player_index] <= 1)

        transfer_count = model.new_int_var(
            0,
            optimization_config.squad_size,
            f"transfer_count_gw{gameweek}",
        )
        model.add(transfer_count == cp_model.LinearExpr.sum(transfers_in))
        free_before = model.new_int_var(
            0,
            transfer_config.max_free_transfers,
            f"free_before_gw{gameweek}",
        )
        if week_index == 0:
            model.add(free_before == initial_state.free_transfers)
        else:
            model.add(free_before == free_next_vars[week_index - 1])
        wildcard = chip_vars[week_index].get("wildcard")
        # A free hit rebuilds for one week as a wildcard does; both lift the cap, cost
        # no hits, and (per the flag) leave the free-transfer bank alone.
        rebuild_vars = [chip for chip in (wildcard, free_hit) if chip is not None]
        rebuild: cp_model.LinearExpr | int = (
            cp_model.LinearExpr.sum(rebuild_vars) if rebuild_vars else 0
        )
        # Transfer discipline: a hard cap on moves per gameweek, lifted under a rebuild.
        cap = transfer_config.max_transfers_per_gameweek
        if cap is not None:
            effective_cap: cp_model.IntVar | int = cap
            if cap == 1 and transfer_config.allow_two_free_transfers:
                two_free = model.new_bool_var(f"two_free_transfers_gw{gameweek}")
                model.add(free_before >= 2).only_enforce_if(two_free)
                model.add(free_before <= 1).only_enforce_if(two_free.Not())
                effective_cap = model.new_int_var(1, 2, f"transfer_cap_gw{gameweek}")
                model.add(effective_cap == 1 + two_free)
            if rebuild_vars:
                model.add(
                    transfer_count <= effective_cap + optimization_config.squad_size * rebuild
                )
            else:
                model.add(transfer_count <= effective_cap)
        # Transfers that draw on the free-transfer bank this week. Under a wildcard
        # (when the rule preserves the bank) none of them do. The value is pinned in
        # both directions — count without the chip, zero with it — because the bank it
        # feeds is not always in the objective (a horizon's last week, a full bank), and
        # a free variable there would let the solver leave the accounting inconsistent.
        consumed = model.new_int_var(
            0,
            optimization_config.squad_size,
            f"free_consumed_gw{gameweek}",
        )
        if rebuild_vars and transfer_config.wildcard_preserves_free_transfers:
            model.add(consumed >= transfer_count - optimization_config.squad_size * rebuild)
            model.add(consumed <= transfer_count)
            model.add(consumed <= optimization_config.squad_size * (1 - rebuild))
        else:
            model.add(consumed == transfer_count)
        free_unused = model.new_int_var(
            0,
            transfer_config.max_free_transfers,
            f"free_unused_gw{gameweek}",
        )
        model.add_max_equality(free_unused, [free_before - consumed, 0])
        free_next = model.new_int_var(
            0,
            transfer_config.max_free_transfers,
            f"free_next_gw{gameweek}",
        )
        # The chip consumes this week's new entitlement: retaining the entering total
        # already includes the next deadline's replacement. Adding one again invents
        # a free move. The non-preserving alternative keeps its configured accounting.
        accrual = transfer_config.free_transfer_accrual
        earned = (
            accrual * (1 - rebuild)
            if transfer_config.wildcard_preserves_free_transfers
            else accrual
        )
        model.add_min_equality(
            free_next,
            [
                free_unused + earned,
                transfer_config.max_free_transfers,
            ],
        )
        paid_transfers = model.new_int_var(
            0,
            optimization_config.squad_size,
            f"paid_transfers_gw{gameweek}",
        )
        # Accounting must be exact even with a zero hit weight or a merely feasible
        # incumbent. A rebuild makes the expression nonpositive because the number
        # of transfers is bounded by squad_size, so WC/FH always pay zero hits.
        model.add_max_equality(
            paid_transfers,
            [transfer_count - free_before - optimization_config.squad_size * rebuild, 0],
        )

        bank_after = model.new_int_var(0, bank_bound, f"bank_after_gw{gameweek}")
        bank_before: cp_model.LinearExpr | int
        if week_index == 0:
            bank_before = initial_state.bank_tenths
        else:
            bank_before = base_bank_vars[week_index - 1]
        sell_prices = [int(value) for value in players["sell_price_tenths"]]
        buy_prices = [int(value) for value in players["buy_price_tenths"]]
        proceeds = (
            cp_model.LinearExpr.weighted_sum(transfers_out, sell_prices)
            if acquisition is None
            else acquisition.add_week(
                model, week_index, players, transfers_in, transfers_out, free_hit
            )
        )
        model.add(
            bank_after
            == bank_before + proceeds - cp_model.LinearExpr.weighted_sum(transfers_in, buy_prices)
        )

        coefficients = objective_coefficients(
            players["expected_points"].tolist(),
            optimization_config,
        )
        discount_weight = discount_weights[week_index]
        for player_index, (
            squad_coefficient,
            starter_coefficient,
            captain_coefficient,
        ) in enumerate(coefficients):
            objective_terms.extend(
                (
                    discount_weight * squad_coefficient * squads[player_index],
                    discount_weight * starter_coefficient * starters[player_index],
                    discount_weight * captain_coefficient * captains[player_index],
                )
            )
        objective_terms.append(-discount_weight * hit_cost_scaled * paid_transfers)

        bench_boost = chip_vars[week_index].get("bboost")
        if bench_boost is not None:
            # Under a bench boost every squad member scores in full: add each bench
            # player's unweighted remainder. Upper bounds suffice because the remainder
            # is non-negative and the objective is maximised.
            for player_index, (_, starter_coefficient, _) in enumerate(coefficients):
                if starter_coefficient == 0:
                    continue
                boosted = model.new_bool_var(f"bboost_gw{gameweek}_{player_index}")
                model.add(boosted <= bench_boost)
                model.add(boosted <= squads[player_index])
                model.add(boosted <= 1 - starters[player_index])
                objective_terms.append(discount_weight * starter_coefficient * boosted)
        triple_captain = chip_vars[week_index].get("3xc")
        if triple_captain is not None:
            for player_index, (_, _, captain_coefficient) in enumerate(coefficients):
                if captain_coefficient == 0:
                    continue
                tripled = model.new_bool_var(f"tripled_gw{gameweek}_{player_index}")
                model.add(tripled <= triple_captain)
                model.add(tripled <= captains[player_index])
                objective_terms.append(discount_weight * captain_coefficient * tripled)

        # The bank the next week starts from reverts with the squad under a free hit.
        base_bank: cp_model.LinearExpr | int
        if free_hit is None:
            base_bank = bank_after
        else:
            base_bank_var = model.new_int_var(0, bank_bound, f"base_bank_gw{gameweek}")
            model.add(base_bank_var >= bank_after - bank_bound * free_hit)
            model.add(base_bank_var <= bank_after + bank_bound * free_hit)
            model.add(base_bank_var >= bank_before - bank_bound * (1 - free_hit))
            model.add(base_bank_var <= bank_before + bank_bound * (1 - free_hit))
            base_bank = base_bank_var
        base_squad_vars.append(bases)
        base_bank_vars.append(base_bank)
        squad_vars.append(squads)
        starter_vars.append(starters)
        captain_vars.append(captains)
        transfer_in_vars.append(transfers_in)
        transfer_out_vars.append(transfers_out)
        bank_after_vars.append(bank_after)
        free_before_vars.append(free_before)
        free_unused_vars.append(free_unused)
        free_next_vars.append(free_next)
        transfer_count_vars.append(transfer_count)
        paid_transfer_vars.append(paid_transfers)

    if banked_value_scaled != 0:
        # Terminal value of free transfers banked past the horizon: what the plan is
        # giving up by spending one now on a small gain, which a finite horizon cannot
        # otherwise see.
        objective_terms.append(discount_weights[-1] * banked_value_scaled * free_next_vars[-1])
    for name in sorted(chips.available):
        for period in chips.windows_for(name):
            holding_value = (
                transfer_config.chip_holding_value_points.get(name, 0.0)
                if period.holding_value_points is None
                else period.holding_value_points
            )
            if holding_value == 0.0:
                continue
            holding_scaled = scale_expected_points(
                holding_value, optimization_config.expected_points_scale
            )
            plays = [
                week[name]
                for gw, week in zip(horizon_gameweeks, chip_vars, strict=True)
                if name in week and gw in period.gameweeks
            ]
            held = 1 - cp_model.LinearExpr.sum(plays)
            objective_terms.append(discount_weights[-1] * holding_scaled * held)
    primary_objective = cp_model.LinearExpr.sum(objective_terms)
    if chip_tail is not None:
        # Each row is an exact joint future assignment for the used-right subset.
        # The FH boundary bit prevents adjacent uses across the horizon boundary.
        used_vars = []
        for i, (name, dates) in enumerate(chip_tail.rights):
            used = model.new_bool_var(f"tail_right_used_{i}")
            model.add(
                used
                == cp_model.LinearExpr.sum(
                    [
                        week[name]
                        for gw, week in zip(horizon_gameweeks, chip_vars, strict=True)
                        if name in week and gw in dates
                    ]
                )
            )
            used_vars.append(used)
        last_fh = chip_vars[-1].get("freehit")
        if last_fh is None:
            last_fh = model.new_bool_var("tail_last_fh")
            model.add(last_fh == 0)
        rows = [
            [int(bool(mask & (1 << i))) for i in range(len(used_vars))]
            + [fh, scale_expected_points(value, optimization_config.expected_points_scale)]
            for mask, fh, value in chip_tail.values
        ]
        maximum = max((row[-1] for row in rows), default=0)
        tail_value = model.new_int_var(0, maximum, "joint_chip_tail_value")
        model.add_allowed_assignments([*used_vars, last_fh, tail_value], rows)
        primary_objective += discount_weights[-1] * tail_value
    model.maximize(primary_objective)
    return _PlanArtifacts(
        model=model,
        players_by_week=players_by_week,
        squad_vars=squad_vars,
        starter_vars=starter_vars,
        captain_vars=captain_vars,
        transfer_in_vars=transfer_in_vars,
        transfer_out_vars=transfer_out_vars,
        bank_after_vars=bank_after_vars,
        free_before_vars=free_before_vars,
        free_unused_vars=free_unused_vars,
        free_next_vars=free_next_vars,
        transfer_count_vars=transfer_count_vars,
        paid_transfer_vars=paid_transfer_vars,
        primary_objective=primary_objective,
        discount_weights=discount_weights,
        hit_cost_scaled=hit_cost_scaled,
        chip_vars=chip_vars,
        chips=chips,
        chip_tail=chip_tail,
    )


def _add_tiebreak(
    artifacts: _PlanArtifacts,
    optimization_config: OptimizationConfig,
    primary_value: int,
) -> None:
    flat_count = len(artifacts.players_by_week) * len(artifacts.players_by_week[0])
    largest_rank = max(0, flat_count - 1)
    max_squad_rank_sum = (
        len(artifacts.players_by_week) * optimization_config.squad_size * largest_rank
    )
    max_starter_rank_sum = (
        len(artifacts.players_by_week) * optimization_config.starting_size * largest_rank
    )
    starter_weight = max_squad_rank_sum + 1
    captain_weight = starter_weight * (max_starter_rank_sum + 1)
    conservative_bound = (
        captain_weight * len(artifacts.players_by_week) * largest_rank
        + starter_weight * max_starter_rank_sum
        + max_squad_rank_sum
    )
    chip_count = sum(len(week) for week in artifacts.chip_vars)
    week_count = len(artifacts.players_by_week)
    # Two chip tiers sit above every rank term. First: among plans with equal objective,
    # keep chips unplayed — a chip that buys nothing on paper is worth more later.
    # Second: among plans that play the same number of chips, play them later — a
    # rolling planner re-decides a deferred chip next week with fresher information,
    # and committing it early buys nothing on paper. The tiers are weighted so the
    # count always decides before the timing, and the timing before any rank term.
    later_weight = conservative_bound + 1
    later_bound = later_weight * max(0, week_count - 1) * chip_count + conservative_bound
    count_weight = later_bound + 1
    if count_weight * chip_count + later_bound > CP_SAT_SAFE_INTEGER_MAX:
        raise SolverExecutionError(
            "Transfer-plan deterministic tie-break exceeds the safe CP-SAT integer range."
        )
    artifacts.model.add(artifacts.primary_objective == primary_value)
    terms: list[cp_model.LinearExpr] = []
    player_count = len(artifacts.players_by_week[0])
    for week_index, week_chips in enumerate(artifacts.chip_vars):
        weight = count_weight + later_weight * (week_count - 1 - week_index)
        for name in sorted(week_chips):
            terms.append(weight * week_chips[name])
    for week_index in range(len(artifacts.players_by_week)):
        for player_index in range(player_count):
            rank = week_index * player_count + player_index
            terms.extend(
                (
                    rank * artifacts.squad_vars[week_index][player_index],
                    starter_weight * rank * artifacts.starter_vars[week_index][player_index],
                    captain_weight * rank * artifacts.captain_vars[week_index][player_index],
                )
            )
    artifacts.model.minimize(cp_model.LinearExpr.sum(terms))


def _empty_result(
    status: SolverStatus,
    horizon: PlanningHorizon,
    diagnostics: dict[str, object],
) -> TransferPlanResult:
    return TransferPlanResult(
        solver_status=status,
        weeks=(),
        horizon_fingerprint=horizon.horizon_fingerprint,
        total_projected_score=None,
        total_projected_bench_points=None,
        total_transfer_hit_points=None,
        objective_value=None,
        diagnostics=diagnostics,
    )


def _extract_plan(
    solver: cp_model.CpSolver,
    status: SolverStatus,
    artifacts: _PlanArtifacts,
    horizon: PlanningHorizon,
    initial_state: InitialSquadState,
    optimization_config: OptimizationConfig,
    transfer_config: TransferPlanningConfig,
    diagnostics: dict[str, object],
) -> TransferPlanResult:
    weeks: list[PlanningWeekResult] = []
    chips_played: dict[int, str] = {}
    previous_squad = set(initial_state.squad_player_ids)
    bank_before = initial_state.bank_tenths
    total_score = 0.0
    total_bench = 0.0
    total_hits = 0.0
    total_objective = 0.0
    purchases: dict[object, int] = {}
    fee = transfer_config.acquisition_sell_on_fee
    if fee is not None:
        diagnostics["sale_price_policy"] = "known_horizon_acquisitions_v1"
        diagnostics["acquisition_sell_on_fee"] = fee

    for week_index, players in enumerate(artifacts.players_by_week):
        if fee is not None:
            # Independent numerical replay of the CP acquisition-week variables.
            players = players.copy(deep=True)
            for row_index, row in players.iterrows():
                if row.player_id in purchases:
                    players.at[row_index, "sell_price_tenths"] = sell_price_tenths(
                        int(row.buy_price_tenths), purchases[row.player_id], sell_on_fee=fee
                    )
        squad_indices = _selected_indices(solver, artifacts.squad_vars[week_index])
        starter_indices = _selected_indices(solver, artifacts.starter_vars[week_index])
        captain_indices = _selected_indices(solver, artifacts.captain_vars[week_index])
        transfer_in_indices = _selected_indices(solver, artifacts.transfer_in_vars[week_index])
        transfer_out_indices = _selected_indices(solver, artifacts.transfer_out_vars[week_index])
        _verify_solution(
            players,
            optimization_config,
            squad_indices,
            starter_indices,
            captain_indices,
            enforce_budget=False,
        )
        squad_ids = set(players.iloc[squad_indices]["player_id"])
        transfer_in_ids = set(players.iloc[transfer_in_indices]["player_id"])
        transfer_out_ids = set(players.iloc[transfer_out_indices]["player_id"])
        if transfer_in_ids != squad_ids - previous_squad:
            raise SolverExecutionError("Transfer-in decisions failed continuity verification.")
        if transfer_out_ids != previous_squad - squad_ids:
            raise SolverExecutionError("Transfer-out decisions failed continuity verification.")

        sold = sum(int(players.iloc[index]["sell_price_tenths"]) for index in transfer_out_indices)
        bought = sum(int(players.iloc[index]["buy_price_tenths"]) for index in transfer_in_indices)
        bank_after = int(solver.value(artifacts.bank_after_vars[week_index]))
        if bank_after != bank_before + sold - bought or bank_after < 0:
            raise SolverExecutionError("Transfer-plan bank accounting failed verification.")
        base_squad = previous_squad
        base_bank = bank_before
        transfer_count = int(solver.value(artifacts.transfer_count_vars[week_index]))
        paid_count = int(solver.value(artifacts.paid_transfer_vars[week_index]))
        free_before = int(solver.value(artifacts.free_before_vars[week_index]))
        free_unused = int(solver.value(artifacts.free_unused_vars[week_index]))
        free_next = int(solver.value(artifacts.free_next_vars[week_index]))
        played = [
            name
            for name, variable in sorted(artifacts.chip_vars[week_index].items())
            if solver.value(variable) == 1
        ]
        if len(played) > 1:
            raise SolverExecutionError("More than one chip was played in a single gameweek.")
        chip = played[0] if played else None
        wildcard_played = chip in {"wildcard", "freehit"}
        expected_paid = 0 if wildcard_played else max(0, transfer_count - free_before)
        if transfer_count != len(transfer_in_indices) or paid_count != expected_paid:
            raise SolverExecutionError("Transfer counts failed verification.")
        consumed = (
            0
            if wildcard_played and transfer_config.wildcard_preserves_free_transfers
            else transfer_count
        )
        if free_unused != max(0, free_before - consumed):
            raise SolverExecutionError("Unused free transfers failed verification.")
        expected_next = min(
            transfer_config.max_free_transfers,
            free_unused
            + (
                0
                if wildcard_played and transfer_config.wildcard_preserves_free_transfers
                else transfer_config.free_transfer_accrual
            ),
        )
        if free_next != expected_next:
            raise SolverExecutionError("Free-transfer carry failed verification.")

        if fee is not None:
            # A newly bought player's sale basis is this week's purchase, including
            # a former original holding bought again after a sale.
            for index in transfer_in_indices:
                players.at[index, "sell_price_tenths"] = int(players.iloc[index].buy_price_tenths)
            if chip != "freehit":
                for player in transfer_out_ids:
                    purchases.pop(player, None)
                purchases.update(
                    {
                        players.iloc[index].player_id: int(players.iloc[index].buy_price_tenths)
                        for index in transfer_in_indices
                    }
                )
        squad_set = set(squad_indices)
        starter_set = set(starter_indices)
        bench_indices = sorted(squad_set - starter_set)
        selected_squad = players.iloc[squad_indices].reset_index(drop=True).copy(deep=True)
        starting_xi = players.iloc[starter_indices].reset_index(drop=True).copy(deep=True)
        bench = players.iloc[bench_indices].reset_index(drop=True).copy(deep=True)
        captain = players.iloc[captain_indices[0]].copy(deep=True)
        captain.name = None
        projected_score = float(starting_xi["expected_points"].sum() + captain["expected_points"])
        if chip == "3xc":
            projected_score += float(captain["expected_points"])
        projected_bench = float(bench["expected_points"].sum())
        # Two different hit numbers, and the difference is the whole point. The
        # objective priced this week's paid transfers at ``transfer_hit_cost_points``
        # (that is what ``hit_cost_scaled`` was built from), so the contribution — which
        # must reconstruct ``objective_value`` — is charged at that price. What the game
        # takes off the sheet is ``hit_points_charged``, and that is the only one
        # reported: the week's ``transfer_hit_points`` and the plan's total. When a
        # caller sets a planning cost above the charge, the margin filters marginal
        # transfers inside the solve and never appears in a number anyone is shown.
        objective_hit_points = paid_count * transfer_config.transfer_hit_cost_points
        hit_points = paid_count * transfer_config.hit_points_charged
        discount = transfer_config.horizon_discount_factor**week_index
        bench_weight = 1.0 if chip == "bboost" else optimization_config.bench_weight
        contribution = discount * (
            projected_score + bench_weight * projected_bench - objective_hit_points
        )
        gameweek = int(players.iloc[0]["gameweek"])
        if chip is not None:
            chips_played[gameweek] = chip
        weeks.append(
            PlanningWeekResult(
                gameweek=gameweek,
                selected_squad=selected_squad,
                starting_xi=starting_xi,
                bench=bench,
                captain=captain,
                transfers_in=players.iloc[transfer_in_indices]
                .reset_index(drop=True)
                .copy(deep=True),
                transfers_out=players.iloc[transfer_out_indices]
                .reset_index(drop=True)
                .copy(deep=True),
                bank_before_tenths=bank_before,
                bank_after_tenths=bank_after,
                free_transfers_before=free_before,
                free_transfers_unused=free_unused,
                free_transfers_for_next_gameweek=free_next,
                transfer_count=transfer_count,
                paid_transfer_count=paid_count,
                transfer_hit_points=hit_points,
                projected_score=projected_score,
                projected_bench_points=projected_bench,
                discounted_objective_contribution=contribution,
                chip=chip,
            )
        )
        # A free hit's squad and bank are temporary: the next week starts from the
        # squad and bank this week started from.
        previous_squad = base_squad if chip == "freehit" else squad_ids
        bank_before = base_bank if chip == "freehit" else bank_after
        total_score += projected_score
        total_bench += projected_bench
        total_hits += hit_points
        total_objective += contribution

    for name in artifacts.chips.available:
        for period in artifacts.chips.windows_for(name):
            if (
                sum(
                    1
                    for gw, played in chips_played.items()
                    if played == name and gw in period.gameweeks
                )
                > 1
            ):
                raise SolverExecutionError(
                    f"Chip {name!r} was played more than once in its window."
                )
    diagnostics["chips_played"] = dict(chips_played)
    terminal_value = (
        transfer_config.banked_transfer_value_points
        * weeks[-1].free_transfers_for_next_gameweek
        * transfer_config.horizon_discount_factor ** (len(weeks) - 1)
    )
    diagnostics["terminal_banked_transfer_value"] = terminal_value
    total_objective += terminal_value
    last_discount = transfer_config.horizon_discount_factor ** (len(weeks) - 1)
    holding_value = sum(
        (
            transfer_config.chip_holding_value_points.get(name, 0.0)
            if period.holding_value_points is None
            else period.holding_value_points
        )
        for name in artifacts.chips.available
        for period in artifacts.chips.windows_for(name)
        if not any(played == name and gw in period.gameweeks for gw, played in chips_played.items())
    )
    if artifacts.chip_tail is not None:
        holding_value = artifacts.chip_tail.value(chips_played)
        diagnostics["chip_tail_source_fingerprint"] = artifacts.chip_tail.source_fingerprint
        diagnostics["chip_tail_fingerprint"] = artifacts.chip_tail.fingerprint
    diagnostics["terminal_chip_holding_value"] = holding_value * last_discount
    total_objective += holding_value * last_discount
    return TransferPlanResult(
        solver_status=status,
        weeks=tuple(weeks),
        horizon_fingerprint=horizon.horizon_fingerprint,
        total_projected_score=total_score,
        total_projected_bench_points=total_bench,
        total_transfer_hit_points=total_hits,
        objective_value=total_objective,
        diagnostics=diagnostics,
        chips_played=chips_played,
    )


def _forbid_squads(
    artifacts: _PlanArtifacts,
    first_week: pd.DataFrame,
    excluded_squads: Sequence[frozenset[object]],
    squad_size: int,
) -> None:
    """Rule out squads a caller has already been given, and nothing else.

    A no-good cut per squad: of those fifteen players, at most fourteen may be held in
    the opening week. Players the horizon does not carry are ignored rather than refused —
    an excluded squad from an older capture may name someone since removed, and refusing
    it would turn a stale exclusion into a failed plan.
    """

    if not excluded_squads:
        return
    # Player ids are whatever the horizon carries — codes in production, labels in
    # tests — so they are matched as they are rather than coerced.
    column_of = {player: index for index, player in enumerate(first_week["player_id"])}
    for squad in excluded_squads:
        columns = [column_of[player] for player in squad if player in column_of]
        if len(columns) < squad_size:
            continue
        artifacts.model.add(
            sum(artifacts.squad_vars[0][column] for column in columns) <= squad_size - 1
        )


def _fix_week_squads(
    artifacts: _PlanArtifacts,
    tables: list[pd.DataFrame],
    fixed: Mapping[int, tuple[object, ...]] | None,
    squad_size: int,
) -> None:
    if fixed is None:
        return
    if not isinstance(fixed, Mapping):
        raise TransferPlanningValidationError("Fixed squads must map gameweeks to player tuples.")
    week_index = {int(t.iloc[0].gameweek): i for i, t in enumerate(tables)}
    for week, ids in fixed.items():
        if isinstance(week, bool) or not isinstance(week, Integral) or week not in week_index:
            raise TransferPlanningValidationError("Fixed squad gameweek is outside the horizon.")
        if not isinstance(ids, tuple) or len(ids) != squad_size:
            raise TransferPlanningValidationError("Fixed squads require a full player tuple.")
        if any(isinstance(p, bool) or not isinstance(p, (str, Integral)) for p in ids):
            raise TransferPlanningValidationError("Fixed squads contain invalid player IDs.")
        index = week_index[week]
        columns = {p: i for i, p in enumerate(tables[index].player_id)}
        if len(set(ids)) != squad_size or not set(ids) <= columns.keys():
            raise TransferPlanningValidationError("Fixed squads contain duplicate or absent IDs.")
        for player in ids:
            artifacts.model.add(artifacts.squad_vars[index][columns[player]] == 1)


def _bound_first_week_overlap(
    artifacts: _PlanArtifacts,
    first_week: pd.DataFrame,
    band: FirstWeekOverlap | None,
) -> None:
    """Bound how many of the band's players the first-week fifteen holds.

    Matching mirrors ``_forbid_squads``: ids are whatever the horizon carries, matched
    as they are. A floor above the number of band players the horizon carries leaves
    the constraint unsatisfiable and the solve INFEASIBLE — the honest reading of a
    band the world cannot meet, and the reason a menu builder drops the band instead
    of publishing an unproven entry for it.
    """

    if band is None:
        return
    column_of = {player: index for index, player in enumerate(first_week["player_id"])}
    columns = [
        column_of[player] for player in sorted(band.player_ids, key=str) if player in column_of
    ]
    held = cp_model.LinearExpr.sum([artifacts.squad_vars[0][column] for column in columns])
    if band.minimum is not None:
        artifacts.model.add(held >= band.minimum)
    if band.maximum is not None:
        artifacts.model.add(held <= band.maximum)


def _exclude_first_week_roles(
    artifacts: _PlanArtifacts,
    first_week: pd.DataFrame,
    exclusion: FirstWeekExclusion | None,
) -> None:
    """Fix the excluded players' first-week starter and captain variables to zero.

    Matching mirrors ``_bound_first_week_overlap``: ids are whatever the horizon carries,
    matched as they are, and a player it does not carry is skipped. The squad variable
    is untouched, so an excluded player may still be held (and benched) or sold; only
    starting and captaining him are ruled out, which is exactly what the caller declared.
    """

    if exclusion is None:
        return
    column_of = {player: index for index, player in enumerate(first_week["player_id"])}
    for player in sorted(exclusion.not_starting, key=str):
        if player in column_of:
            artifacts.model.add(artifacts.starter_vars[0][column_of[player]] == 0)
    for player in sorted(exclusion.not_captain, key=str):
        if player in column_of:
            artifacts.model.add(artifacts.captain_vars[0][column_of[player]] == 0)


def _cap_later_week_transfers(
    artifacts: _PlanArtifacts,
    squad_size: int,
    cap: int | None,
) -> None:
    """Cap every gameweek after the first at ``cap`` transfers, first week untouched.

    The form is ``TransferPlanningConfig.max_transfers_per_gameweek``'s, applied to a
    different set of weeks, so the two agree wherever they overlap:

    * **A wildcard or free-hit week is exempt.** A rebuild week lifts the cap by the
      squad size, exactly as the per-week cap does — those chips exist to rebuild, and a
      cap that survived one would make the chip unplayable rather than disciplined.
    * **A cap above the free transfers changes no hit accounting.** This bounds the
      *count* of transfers in a week, never how they are paid for. A week may still
      spend more than its free transfers and be charged, and a week under the cap may
      still decline a move the hit cost does not justify: the cap is a ceiling the
      objective works under, not a budget it is handed.
    * **A cap at or above the squad size cannot bind.** ``transfer_count`` is already
      bounded by the squad size — a week cannot replace more players than it holds — so
      such a cap admits every plan the uncapped planner admits and the result is that
      plan. It is not an error, and it is not reported as one.

    A one-week horizon has no later week, so the cap is inert there by construction.
    """

    if cap is None:
        return
    for week_index in range(1, len(artifacts.transfer_count_vars)):
        week_chips = artifacts.chip_vars[week_index]
        rebuild_vars = [week_chips[name] for name in ("wildcard", "freehit") if name in week_chips]
        transfer_count = artifacts.transfer_count_vars[week_index]
        if rebuild_vars:
            artifacts.model.add(
                transfer_count <= cap + squad_size * cp_model.LinearExpr.sum(rebuild_vars)
            )
        else:
            artifacts.model.add(transfer_count <= cap)


def _hint_incumbent(
    artifacts: _PlanArtifacts,
    incumbent: TransferPlanResult,
    horizon: PlanningHorizon,
    initial: InitialSquadState,
    settings: TransferPlanningConfig,
    config: OptimizationConfig,
    wall_limit: float,
    deterministic_limit: float,
) -> tuple[cp_model.CpSolver, float]:
    """Certify and hint decisions; retain the witness for optional incumbent protection."""
    if (
        not isinstance(incumbent, TransferPlanResult)
        or not incumbent.has_solution
        or incumbent.horizon_fingerprint != horizon.horizon_fingerprint
        or tuple(w.gameweek for w in incumbent.weeks) != horizon.gameweeks
        or incumbent.diagnostics.get("configuration_fingerprint")
        != settings.configuration_fingerprint
        or incumbent.diagnostics.get("chip_availability_fingerprint")
        != artifacts.chips.availability_fingerprint
    ):
        raise TransferPlanningValidationError(
            "Incumbent must match the complete horizon and rules."
        )
    probe_model = artifacts.model.clone()
    probe_model.clear_objective()  # type: ignore[no-untyped-call]
    bank_before = initial.bank_tenths
    for index, week in enumerate(incumbent.weeks):
        universe = set(artifacts.players_by_week[index].player_id)
        groups = []
        for frame in (
            week.selected_squad,
            week.starting_xi,
            week.bench,
            week.transfers_in,
            week.transfers_out,
        ):
            if "player_id" not in frame:
                raise TransferPlanningValidationError("Incumbent is missing player identifiers.")
            ids = frame.player_id.tolist()
            if len(set(ids)) != len(ids) or not set(ids) <= universe:
                raise TransferPlanningValidationError("Incumbent has duplicate or unknown players.")
            groups.append(set(ids))
        squad, starters, bench, incoming, outgoing = groups
        captain = week.captain.get("player_id")
        if starters & bench or starters | bench != squad or captain not in starters:
            raise TransferPlanningValidationError("Incumbent roles do not partition its squad.")
        if week.bank_before_tenths != bank_before:
            raise TransferPlanningValidationError("Incumbent bank continuity is inconsistent.")
        if week.chip != "freehit":
            bank_before = week.bank_after_tenths
        for variables, chosen in (
            (artifacts.squad_vars, squad),
            (artifacts.starter_vars, starters),
            (artifacts.captain_vars, {captain}),
            (artifacts.transfer_in_vars, incoming),
            (artifacts.transfer_out_vars, outgoing),
        ):
            for player_index, player in enumerate(artifacts.players_by_week[index].player_id):
                probe_model.add(variables[index][player_index] == int(player in chosen))
        if week.chip is not None and week.chip not in artifacts.chip_vars[index]:
            raise TransferPlanningValidationError("Incumbent chip is unavailable.")
        for name, variable in artifacts.chip_vars[index].items():
            probe_model.add(variable == int(week.chip == name))
        for resources, value in (
            (artifacts.bank_after_vars, week.bank_after_tenths),
            (artifacts.free_before_vars, week.free_transfers_before),
            (artifacts.free_unused_vars, week.free_transfers_unused),
            (artifacts.free_next_vars, week.free_transfers_for_next_gameweek),
            (artifacts.transfer_count_vars, week.transfer_count),
            (artifacts.paid_transfer_vars, week.paid_transfer_count),
        ):
            if isinstance(value, bool) or not isinstance(value, Integral):
                raise TransferPlanningValidationError("Incumbent resource values must be integers.")
            probe_model.add(resources[index] == int(value))
    probe = cp_model.CpSolver()
    configure_solver(probe, config, min(wall_limit, 30.0), min(1.0, deterministic_limit / 10.0))
    raw = _solve(probe_model, probe)
    if _map_solver_status(raw) not in {SolverStatus.OPTIMAL, SolverStatus.FEASIBLE}:
        raise TransferPlanningValidationError(
            "Incumbent could not be certified against the current constraints."
        )
    # Clone indices include auxiliary purchase-lot and chip variables too.
    for index in range(len(artifacts.model.proto.variables)):
        variable = artifacts.model.get_int_var_from_proto_index(index)
        artifacts.model.add_hint(variable, probe.value(variable))
    return probe, _deterministic_time_used(probe, raw)


def optimize_transfer_plan(
    horizon: PlanningHorizon,
    initial_state: InitialSquadState,
    optimization_config: OptimizationConfig,
    transfer_config: TransferPlanningConfig | None = None,
    chips: ChipAvailability | None = None,
    excluded_squads: Sequence[frozenset[object]] = (),
    first_week_overlap: FirstWeekOverlap | None = None,
    first_week_transfer_cap: int | None = None,
    first_week_exclusion: FirstWeekExclusion | None = None,
    linearization_level: int | None = None,
    preferences: DecisionPreferences | None = None,
    protect_hold: bool = False,
    fixed_week_squads: Mapping[int, tuple[object, ...]] | None = None,
    incumbent_plan: TransferPlanResult | None = None,
    protect_incumbent: bool = False,
    chip_tail: ChipTailTable | None = None,
) -> TransferPlanResult:
    """Optimize squads and transfers over one deterministic projection horizon.

    ``incumbent_plan`` supplies optional decisions, never a claimed score or bound.
    They are certified in a constrained clone before being hinted to the original.
    Certification consumes the same deterministic budget as search. It cannot be
    combined with ``protect_hold``, which supplies a different incumbent and bound.
    ``protect_incumbent`` additionally retains the certified witness after UNKNOWN
    or a worse feasible search. Its value is computed from the current model, never
    read from the supplied result. A retained witness is FEASIBLE, not an optimum.

    ``fixed_week_squads`` is an opt-in temporal neighborhood: named gameweeks keep
    their entire squad, while all bank, transfer, chip and XI constraints still span
    the original horizon. A restricted optimum is not a full-horizon optimum. None
    preserves existing callers, including their diagnostic fingerprints.

    ``linearization_level`` is CP-SAT's own parameter, left at the solver's default
    when ``None`` so every existing caller solves exactly as before. At 2 the solver
    linearizes more of the model (most likely the two-literal rows: starter implies
    squad, captain implies starter; the cause was not isolated), and the effect is
    measured in ``docs/member_window_proofs.md``: on the fifteen members of capture
    ``fpl-live-20260918T122516Z`` it took the three-week windows from 0 to 15 proved
    and the five-week windows from 0 to 12, inside the unchanged deterministic budget.
    It changes how hard the solver works on the bound, never what the model says.

    ``chips`` names the chips that may be played in which gameweeks of this horizon
    (bench boost, triple captain, wildcard); omitted or empty, the planner is exactly
    the chip-less planner. Each available chip is played at most once in the horizon
    and at most one chip is played per gameweek.

    ``excluded_squads`` forbids first-week squads that have already been produced, so a
    caller can ask for the next-best plan rather than the same one. Each entry becomes a
    no-good cut: at most fourteen of those fifteen may be held together, which rules out
    that exact squad and nothing else. This is what lets a mode choose between plans
    instead of re-ranking a menu of one — without it every mode returns the optimizer's
    single answer under a different name.

    ``first_week_overlap`` bounds how many of a named set of players — a rival's known
    eleven — the first-week fifteen holds. It is the strategy catalogue's overlap band
    in solver terms; ``None`` is today's unconstrained planner, bit for bit.

    ``first_week_transfer_cap`` caps every gameweek **after** the first at that many
    transfers and leaves the first week free to spend more. It is what a band over a
    multi-week window needs: the band constrains the decided week, so the later weeks
    must not be charged for it, while leaving every week uncapped reproduces the
    transfer churn ``docs/transfer_discipline_note.md`` measured as losing.
    ``TransferPlanningConfig.max_transfers_per_gameweek`` cannot express this — it is
    one scalar applied to every week, this one deliberately is not.

    It is a parameter here rather than a field on ``TransferPlanningConfig`` because a
    field would enter ``configuration_fingerprint``, and that digest is recorded on
    every plan — including the ledger's own ``transfer_config_fingerprint``. A new
    field would move it for every caller, including the ones that never set the cap.
    A parameter defaulting to ``None`` is invisible to all of them, and the cap that
    was applied is still on the record, in this plan's ``diagnostics``.
    """

    if not isinstance(horizon, PlanningHorizon):
        raise TransferPlanningValidationError("horizon must be a PlanningHorizon.")
    if not isinstance(initial_state, InitialSquadState):
        raise TransferPlanningValidationError("initial_state must be an InitialSquadState.")
    if not isinstance(optimization_config, OptimizationConfig):
        raise InvalidConfigurationError(
            "optimization_config must be an OptimizationConfig instance."
        )
    settings = TransferPlanningConfig() if transfer_config is None else transfer_config
    if not isinstance(settings, TransferPlanningConfig):
        raise TransferPlanningConfigurationError(
            "transfer_config must be a TransferPlanningConfig instance."
        )
    availability = ChipAvailability() if chips is None else chips
    if not isinstance(availability, ChipAvailability):
        raise TransferPlanningValidationError("chips must be a ChipAvailability instance.")

    if not isinstance(protect_incumbent, bool):
        raise TransferPlanningValidationError("protect_incumbent must be boolean.")
    if protect_incumbent and incumbent_plan is None:
        raise TransferPlanningValidationError("Incumbent protection requires an incumbent plan.")
    if incumbent_plan is not None and protect_hold:
        raise TransferPlanningValidationError("Incumbent and hold hints cannot be combined.")
    verified_horizon = horizon.validated_copy()
    if chip_tail is not None and (
        chip_tail.horizon_end != verified_horizon.gameweeks[-1]
        or chip_tail.availability_fingerprint != availability.availability_fingerprint
        or settings.chip_holding_value_points
        or any(
            p.holding_value_points not in (None, 0)
            for n in availability.available
            for p in availability.windows_for(n)
        )
    ):
        raise TransferPlanningValidationError("Joint chip tail does not match unpriced rights.")
    players_by_week = _validated_week_tables(verified_horizon, optimization_config)
    initial_ids = _validate_initial_state(
        initial_state,
        players_by_week[0],
        optimization_config,
        settings,
    )
    artifacts = _build_model(
        players_by_week,
        initial_ids,
        initial_state,
        optimization_config,
        settings,
        availability,
        chip_tail,
    )
    _fix_week_squads(artifacts, players_by_week, fixed_week_squads, optimization_config.squad_size)
    _forbid_squads(artifacts, players_by_week[0], excluded_squads, optimization_config.squad_size)
    if first_week_overlap is not None and not isinstance(first_week_overlap, FirstWeekOverlap):
        raise TransferPlanningValidationError("first_week_overlap must be a FirstWeekOverlap.")
    _bound_first_week_overlap(artifacts, players_by_week[0], first_week_overlap)
    if first_week_exclusion is not None and not isinstance(
        first_week_exclusion, FirstWeekExclusion
    ):
        raise TransferPlanningValidationError("first_week_exclusion must be a FirstWeekExclusion.")
    _exclude_first_week_roles(artifacts, players_by_week[0], first_week_exclusion)
    # The admissible range is ``max_transfers_per_gameweek``'s: at least one transfer, or
    # ``None`` for no cap. A second range for the same quantity would be a second
    # contract to read.
    if first_week_transfer_cap is not None and (
        isinstance(first_week_transfer_cap, bool)
        or not isinstance(first_week_transfer_cap, int)
        or first_week_transfer_cap < 1
    ):
        raise TransferPlanningValidationError(
            "first_week_transfer_cap must be None or an integer of at least 1."
        )
    _cap_later_week_transfers(artifacts, optimization_config.squad_size, first_week_transfer_cap)
    if preferences is not None:
        if not isinstance(preferences, DecisionPreferences):
            raise TransferPlanningValidationError("Invalid decision preferences.")
        universe = set(players_by_week[0].player_id)
        if not set(preferences.keep_players) <= set(initial_state.squad_player_ids):
            raise TransferPlanningValidationError("Only currently held players can be kept.")
        if not set(preferences.avoid_players) <= universe:
            raise TransferPlanningValidationError("Avoided player is outside the forecast roster.")
        for week, table in enumerate(players_by_week):
            for index, player in enumerate(table.player_id):
                if player in preferences.keep_players:
                    artifacts.model.add(artifacts.squad_vars[week][index] == 1)
                if player in preferences.avoid_players:
                    artifacts.model.add(artifacts.squad_vars[week][index] == 0)
            if preferences.no_hits:
                artifacts.model.add(artifacts.paid_transfer_vars[week] == 0)
            if preferences.save_chips:
                for variable in artifacts.chip_vars[week].values():
                    artifacts.model.add(variable == 0)
    started_at = perf_counter()
    wall_limit = optimization_config.solver_time_limit_seconds
    deterministic_limit = optimization_config.solver_deterministic_time_limit
    deterministic_budget_source = "caller"
    if deterministic_limit is None:
        deterministic_limit = PLAN_DETERMINISTIC_TIME_LIMIT
        wall_limit = max(wall_limit, PLAN_WALL_CEILING_SECONDS)
        deterministic_budget_source = "planner_default"
    incumbent_deterministic_time = 0.0
    incumbent_solver: cp_model.CpSolver | None = None
    incumbent_value: int | None = None
    if incumbent_plan is not None:
        incumbent_solver, incumbent_deterministic_time = _hint_incumbent(
            artifacts,
            incumbent_plan,
            verified_horizon,
            initial_state,
            settings,
            optimization_config,
            wall_limit,
            deterministic_limit,
        )
        if protect_incumbent:
            incumbent_value = int(incumbent_solver.value(artifacts.primary_objective))
    search_limit = max(0.0, deterministic_limit - incumbent_deterministic_time)
    search_wall = wall_limit
    if incumbent_plan is not None:
        search_wall = max(0.001, wall_limit - (perf_counter() - started_at))
    primary_solver = cp_model.CpSolver()
    configure_solver(
        primary_solver,
        optimization_config,
        search_wall,
        search_limit,
    )
    if linearization_level is not None:
        primary_solver.parameters.linearization_level = linearization_level
    # Clone after ALL restrictions. A forbidden hold is not a fallback. Variable
    # indices remain identical, so a verified cloned solution is a valid warm start.
    hold_solver: cp_model.CpSolver | None = None
    hold_value: int | None = None
    hold_status: SolverStatus | None = None
    hold_deterministic_time = 0.0
    if protect_hold:
        hold_model = artifacts.model.clone()
        for variable in artifacts.transfer_count_vars:
            hold_model.add(variable == 0)
        probe = cp_model.CpSolver()
        configure_solver(probe, optimization_config, min(wall_limit, 30.0), 1.0)
        if linearization_level is not None:
            probe.parameters.linearization_level = linearization_level
        hold_raw = _solve(hold_model, probe)
        hold_status = _map_solver_status(hold_raw)
        hold_deterministic_time = _deterministic_time_used(probe, hold_raw)
        if hold_status is SolverStatus.OPTIMAL or (
            hold_status is SolverStatus.FEASIBLE
            and hold_deterministic_time >= 1.0 - MIN_TIEBREAK_DETERMINISTIC_TIME
        ):
            hold_solver = probe
            hold_value = int(probe.value(artifacts.primary_objective))
            artifacts.model.add(artifacts.primary_objective >= hold_value)
            for index in range(len(artifacts.model.proto.variables)):
                variable = artifacts.model.get_int_var_from_proto_index(index)
                artifacts.model.add_hint(variable, probe.value(variable))
    raw_primary_status = _solve(artifacts.model, primary_solver)
    primary_status = _map_solver_status(raw_primary_status)
    used_incumbent = False
    if protect_incumbent:
        assert incumbent_solver is not None and incumbent_value is not None
        if primary_status is SolverStatus.INFEASIBLE or (
            primary_status is SolverStatus.OPTIMAL
            and int(primary_solver.value(artifacts.primary_objective)) < incumbent_value
        ):
            raise SolverExecutionError("Full search contradicts its certified incumbent plan.")
        used_incumbent = primary_status is SolverStatus.UNKNOWN or (
            primary_status is SolverStatus.FEASIBLE
            and int(primary_solver.value(artifacts.primary_objective)) < incumbent_value
        )
    used_hold = hold_solver is not None and (
        primary_status is SolverStatus.UNKNOWN
        or (
            primary_status is SolverStatus.FEASIBLE
            and int(primary_solver.value(artifacts.primary_objective)) < int(hold_value or 0)
        )
    )
    if hold_solver is not None and primary_status is SolverStatus.INFEASIBLE:
        raise SolverExecutionError("Full search contradicts its verified feasible hold plan.")
    primary_deterministic_time = _deterministic_time_used(primary_solver, raw_primary_status)
    divisor = settings.objective_weight_scale * optimization_config.expected_points_scale
    diagnostics: dict[str, object] = {
        "solver_backend": "ortools-cp-sat",
        "solver_status_name": _raw_status_name(raw_primary_status),
        "solve_time_seconds": perf_counter() - started_at,
        "best_objective_bound": None,
        "absolute_optimality_gap": None,
        "relative_optimality_gap": None,
        "contract_version": settings.contract_version,
        "configuration_fingerprint": settings.configuration_fingerprint,
        "horizon_contract_version": verified_horizon.contract_version,
        "horizon_fingerprint": verified_horizon.horizon_fingerprint,
        "gameweeks": verified_horizon.gameweeks,
        "horizon_length": len(verified_horizon.gameweeks),
        "chip_availability_fingerprint": availability.availability_fingerprint,
        "first_week_overlap": (
            None
            if first_week_overlap is None
            else {
                "player_count": len(first_week_overlap.player_ids),
                "minimum": first_week_overlap.minimum,
                "maximum": first_week_overlap.maximum,
            }
        ),
        "first_week_transfer_cap": first_week_transfer_cap,
        "first_week_exclusion": (
            None
            if first_week_exclusion is None
            else {
                "not_starting": len(first_week_exclusion.not_starting),
                "not_captain": len(first_week_exclusion.not_captain),
            }
        ),
        "chips_available": {name: sorted(weeks) for name, weeks in availability.available.items()},
        "expected_points_scale": optimization_config.expected_points_scale,
        "objective_weight_scale": settings.objective_weight_scale,
        "discount_weights": artifacts.discount_weights,
        "horizon_discount_factor": settings.horizon_discount_factor,
        "transfer_hit_cost_points": settings.transfer_hit_cost_points,
        "hit_points_charged": settings.hit_points_charged,
        "hit_cost_scaled": artifacts.hit_cost_scaled,
        "max_free_transfers": settings.max_free_transfers,
        "max_transfers_per_gameweek": settings.max_transfers_per_gameweek,
        "allow_two_free_transfers": settings.allow_two_free_transfers,
        "free_transfer_accrual": settings.free_transfer_accrual,
        "budget_policy": "stateful_bank_accounting",
        "rounding_mode": "ROUND_HALF_UP",
        "deterministic_seed": optimization_config.deterministic_seed,
        "num_search_workers": primary_solver.parameters.num_search_workers,
        "solver_time_limit_seconds": optimization_config.solver_time_limit_seconds,
        "wall_time_limit_seconds": wall_limit,
        # ``planner_default`` means this function supplied the deterministic budget;
        # ``caller`` means the configuration carried one.
        "deterministic_budget_source": deterministic_budget_source,
        "solver_deterministic_time_limit": deterministic_limit,
        "primary_deterministic_time": primary_deterministic_time,
        "tiebreak_deterministic_time_limit": None,
        "tiebreak_deterministic_time": None,
        "deterministic_time_used": incumbent_deterministic_time + primary_deterministic_time,
        "deterministic_time_budget_exhausted": (
            primary_status is not SolverStatus.OPTIMAL
            and primary_deterministic_time >= search_limit - MIN_TIEBREAK_DETERMINISTIC_TIME
        ),
        "tiebreak_attempted": False,
        "tiebreak_status": None,
        "tiebreak_completed": False,
    }
    if incumbent_plan is not None:
        diagnostics["incumbent_hint"] = {
            # Runtime work remains in the existing top-level runtime counters.
            # Nested metadata is also used by immutable horizon documents.
            "version": "certified_decisions_v1",
            "validation_deterministic_time_limit": min(1.0, deterministic_limit / 10.0),
            "claimed_objective_used": False,
        }
    if protect_incumbent:
        assert incumbent_value is not None
        diagnostics["incumbent_protection"] = {
            "version": "certified_fallback_v1",
            "selected": used_incumbent,
            "scaled_objective_value": incumbent_value / divisor,
            "claimed_objective_used": False,
        }
    if fixed_week_squads is not None:
        diagnostics["fixed_week_squads"] = dict(fixed_week_squads)
        diagnostics["proof_scope"] = "restricted_week_squads"
    if preferences is not None and preferences.active:
        diagnostics["decision_preferences"] = preferences.payload()
    if protect_hold:
        diagnostics["hold_protection"] = {
            "version": "feasible_hold_v1",
            "status": None if hold_status is None else hold_status.name,
            "objective_value": None if hold_value is None else hold_value / divisor,
            "selected": used_hold,
            "deterministic_time": hold_deterministic_time,
            "deterministic_time_limit": 1.0,
        }
    if used_incumbent:
        assert incumbent_solver is not None and incumbent_value is not None
        # Certification fixes the proposed decisions. Its status cannot prove an
        # unrestricted optimum, even if the input was labelled OPTIMAL.
        diagnostics["solver_status_name"] = "FEASIBLE"
        diagnostics["primary_search_status"] = primary_status.name
        diagnostics["scaled_model_objective_value"] = incumbent_value / divisor
        diagnostics["solve_time_seconds"] = perf_counter() - started_at
        if linearization_level is not None:
            diagnostics["linearization_level"] = linearization_level
        return _extract_plan(
            incumbent_solver,
            SolverStatus.FEASIBLE,
            artifacts,
            verified_horizon,
            initial_state,
            optimization_config,
            settings,
            diagnostics,
        )
    if used_hold:
        assert hold_solver is not None and hold_value is not None
        # The restricted hold optimum is NOT a proof for the unrestricted search.
        diagnostics["solver_status_name"] = "FEASIBLE"
        diagnostics["primary_search_status"] = primary_status.name
        diagnostics["scaled_model_objective_value"] = hold_value / divisor
        diagnostics["solve_time_seconds"] = perf_counter() - started_at
        return _extract_plan(
            hold_solver,
            SolverStatus.FEASIBLE,
            artifacts,
            verified_horizon,
            initial_state,
            optimization_config,
            settings,
            diagnostics,
        )
    if linearization_level is not None:
        # Only when a caller chose one, so every other plan's diagnostics stay as they were.
        diagnostics["linearization_level"] = linearization_level
    if primary_status in {SolverStatus.INFEASIBLE, SolverStatus.UNKNOWN}:
        return _empty_result(primary_status, verified_horizon, diagnostics)

    primary_value = int(primary_solver.value(artifacts.primary_objective))
    model_objective = primary_value / divisor
    best_bound = float(primary_solver.best_objective_bound) / divisor
    if primary_status is SolverStatus.OPTIMAL:
        absolute_gap = 0.0
        relative_gap = 0.0
    else:
        absolute_gap = max(0.0, best_bound - model_objective)
        relative_gap = absolute_gap / max(1.0, abs(model_objective))

    result_solver = primary_solver
    remaining_deterministic_time = _remaining_deterministic_time(
        deterministic_limit,
        incumbent_deterministic_time + primary_deterministic_time,
    )
    deterministic_budget_available = (
        remaining_deterministic_time is None
        or remaining_deterministic_time > MIN_TIEBREAK_DETERMINISTIC_TIME
    )
    # The tie-break is gated and budgeted on deterministic work alone. It used to be handed
    # whatever wall time the primary left over, which made the phase that settles bench order,
    # the captain among equals and the choice between two equal-value fifteens a function of
    # the CPU share the process received: exactly the dependence the deterministic budget was
    # introduced to remove from the primary (#247, #275).
    #
    # `optimization/optimizer.py` settled this the same way for the one-week path in #192,
    # where the tie-break's wall limit is floored at the caller's own budget rather than the
    # leftover. This file was the one that still divided the ceiling between its phases.
    #
    # What this does NOT claim: `member_plan_determinism` cut this phase with the clock 24
    # times on the gameweek 5 capture and the published plan did not move once. The five of
    # fifteen members who read a different plan there had their primary search cut, which is
    # a different phase and is not addressed here. This makes a property guaranteed that was
    # measured to hold anyway.
    #
    # The ceiling keeps the job its comment gives it, a stop so that a pathological run still
    # ends, but it now bounds each phase instead of being divided between them, so the stop
    # is at twice its value. That is the bound `optimization/optimizer.py` has accepted since
    # #192; the budget that decides the answer is deterministic in both phases.
    if primary_status is SolverStatus.OPTIMAL and deterministic_budget_available:
        diagnostics["tiebreak_attempted"] = True
        artifacts.model.clear_hints()  # type: ignore[no-untyped-call]
        # Hint the tie-break with the primary's solution: a known-feasible,
        # objective-optimal start turns most tie-break solves into a fast proof
        # instead of a fresh search that the budget then cuts off arbitrarily (#192).
        for week_vars in (artifacts.squad_vars, artifacts.starter_vars, artifacts.captain_vars):
            for tie_week in week_vars:
                for variable in tie_week:
                    artifacts.model.add_hint(variable, primary_solver.value(variable))
        for week_chips in artifacts.chip_vars:
            for name in sorted(week_chips):
                artifacts.model.add_hint(week_chips[name], primary_solver.value(week_chips[name]))
        _add_tiebreak(artifacts, optimization_config, primary_value)
        tiebreak_solver = cp_model.CpSolver()
        diagnostics["tiebreak_deterministic_time_limit"] = remaining_deterministic_time
        configure_solver(
            tiebreak_solver,
            optimization_config,
            search_wall,
            remaining_deterministic_time,
        )
        if linearization_level is not None:
            tiebreak_solver.parameters.linearization_level = linearization_level
        raw_tiebreak_status = _solve(artifacts.model, tiebreak_solver)
        tiebreak_status = _map_solver_status(raw_tiebreak_status)
        tiebreak_deterministic_time = _deterministic_time_used(
            tiebreak_solver,
            raw_tiebreak_status,
        )
        diagnostics["tiebreak_status"] = _raw_status_name(raw_tiebreak_status)
        diagnostics["tiebreak_deterministic_time"] = tiebreak_deterministic_time
        diagnostics["deterministic_time_used"] = (
            incumbent_deterministic_time + primary_deterministic_time + tiebreak_deterministic_time
        )
        diagnostics["deterministic_time_budget_exhausted"] = (
            remaining_deterministic_time is not None
            and tiebreak_status is not SolverStatus.OPTIMAL
            and tiebreak_deterministic_time
            >= remaining_deterministic_time - MIN_TIEBREAK_DETERMINISTIC_TIME
        )
        if tiebreak_status in {SolverStatus.OPTIMAL, SolverStatus.FEASIBLE}:
            result_solver = tiebreak_solver
            diagnostics["tiebreak_completed"] = tiebreak_status is SolverStatus.OPTIMAL
        elif tiebreak_status is SolverStatus.INFEASIBLE:
            raise SolverExecutionError(
                "Transfer-plan tie-break became infeasible after fixing the primary optimum."
            )

    diagnostics.update(
        {
            "solve_time_seconds": perf_counter() - started_at,
            "best_objective_bound": best_bound,
            "absolute_optimality_gap": absolute_gap,
            "relative_optimality_gap": relative_gap,
            "scaled_model_objective_value": model_objective,
        }
    )
    return _extract_plan(
        result_solver,
        primary_status,
        artifacts,
        verified_horizon,
        initial_state,
        optimization_config,
        settings,
        diagnostics,
    )
