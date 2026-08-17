"""Deterministic CP-SAT optimizer for multi-gameweek transfer planning."""

from collections import Counter
from dataclasses import dataclass
from decimal import Decimal
from time import perf_counter

import pandas as pd
from ortools.sat.python import cp_model

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
from squadopt.optimization.optimizer import (
    CP_SAT_SAFE_INTEGER_MAX,
    MIN_TIEBREAK_DETERMINISTIC_TIME,
    MIN_TIEBREAK_TIME_SECONDS,
    _add_decision_constraints,
    _configure_solver,
    _deterministic_time_used,
    _map_solver_status,
    _raw_status_name,
    _remaining_deterministic_time,
    _selected_indices,
    _solve,
    _verify_solution,
)
from squadopt.optimization.validation import validate_players
from squadopt.planning.models import (
    ChipAvailability,
    InitialSquadState,
    PlanningHorizon,
    PlanningWeekResult,
    TransferPlanningConfig,
    TransferPlanningConfigurationError,
    TransferPlanningValidationError,
    TransferPlanResult,
)


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
    team_counts = Counter(initial_rows["team_id"])
    if any(count > optimization_config.max_players_per_team for count in team_counts.values()):
        raise TransferPlanningValidationError("Initial squad violates max_players_per_team.")
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
            (int(value) for value in players["sell_price_tenths"]),
            reverse=True,
        )[: optimization_config.squad_size]
        bank_bound += sum(largest_sell_prices)
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
        plays = [week[name] for week in chip_vars if name in week]
        if len(plays) > 1:
            model.add(cp_model.LinearExpr.sum(plays) <= 1)
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
    )

    squad_vars: list[list[cp_model.IntVar]] = []
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
        for player_index, player_id in enumerate(players["player_id"]):
            previous: cp_model.LinearExpr | int
            if week_index == 0:
                previous = int(player_id in initial_ids)
            else:
                previous = squad_vars[week_index - 1][player_index]
            model.add(
                squads[player_index]
                == previous + transfers_in[player_index] - transfers_out[player_index]
            )
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
        # Transfer discipline: a hard cap on moves per gameweek, lifted under a wildcard,
        # which rebuilds by definition.
        cap = transfer_config.max_transfers_per_gameweek
        if cap is not None:
            if wildcard is not None:
                model.add(transfer_count <= cap + optimization_config.squad_size * wildcard)
            else:
                model.add(transfer_count <= cap)
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
        if wildcard is not None and transfer_config.wildcard_preserves_free_transfers:
            model.add(consumed >= transfer_count - optimization_config.squad_size * wildcard)
            model.add(consumed <= transfer_count)
            model.add(consumed <= optimization_config.squad_size * (1 - wildcard))
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
        model.add_min_equality(
            free_next,
            [
                free_unused + transfer_config.free_transfer_accrual,
                transfer_config.max_free_transfers,
            ],
        )
        paid_transfers = model.new_int_var(
            0,
            optimization_config.squad_size,
            f"paid_transfers_gw{gameweek}",
        )
        # Inequality form: paid transfers carry a negative objective weight, so the
        # solver takes the smallest value the bounds allow — max(count - free, 0)
        # without a wildcard, zero under one.
        if wildcard is not None:
            model.add(
                paid_transfers
                >= transfer_count - free_before - optimization_config.squad_size * wildcard
            )
        else:
            model.add(paid_transfers >= transfer_count - free_before)

        bank_after = model.new_int_var(0, bank_bound, f"bank_after_gw{gameweek}")
        bank_before: cp_model.LinearExpr | int
        if week_index == 0:
            bank_before = initial_state.bank_tenths
        else:
            bank_before = bank_after_vars[week_index - 1]
        sell_prices = [int(value) for value in players["sell_price_tenths"]]
        buy_prices = [int(value) for value in players["buy_price_tenths"]]
        model.add(
            bank_after
            == bank_before
            + cp_model.LinearExpr.weighted_sum(transfers_out, sell_prices)
            - cp_model.LinearExpr.weighted_sum(transfers_in, buy_prices)
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
    primary_objective = cp_model.LinearExpr.sum(objective_terms)
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

    for week_index, players in enumerate(artifacts.players_by_week):
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
        wildcard_played = chip == "wildcard"
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
            free_unused + transfer_config.free_transfer_accrual,
        )
        if free_next != expected_next:
            raise SolverExecutionError("Free-transfer carry failed verification.")

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
        hit_points = paid_count * transfer_config.transfer_hit_cost_points
        discount = transfer_config.horizon_discount_factor**week_index
        bench_weight = 1.0 if chip == "bboost" else optimization_config.bench_weight
        contribution = discount * (projected_score + bench_weight * projected_bench - hit_points)
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
        previous_squad = squad_ids
        bank_before = bank_after
        total_score += projected_score
        total_bench += projected_bench
        total_hits += hit_points
        total_objective += contribution

    for name in artifacts.chips.available:
        if sum(1 for played_name in chips_played.values() if played_name == name) > 1:
            raise SolverExecutionError(f"Chip {name!r} was played more than once in the horizon.")
    diagnostics["chips_played"] = dict(chips_played)
    terminal_value = (
        transfer_config.banked_transfer_value_points
        * weeks[-1].free_transfers_for_next_gameweek
        * transfer_config.horizon_discount_factor ** (len(weeks) - 1)
    )
    diagnostics["terminal_banked_transfer_value"] = terminal_value
    total_objective += terminal_value
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


def optimize_transfer_plan(
    horizon: PlanningHorizon,
    initial_state: InitialSquadState,
    optimization_config: OptimizationConfig,
    transfer_config: TransferPlanningConfig | None = None,
    chips: ChipAvailability | None = None,
) -> TransferPlanResult:
    """Optimize squads and transfers over one deterministic projection horizon.

    ``chips`` names the chips that may be played in which gameweeks of this horizon
    (bench boost, triple captain, wildcard); omitted or empty, the planner is exactly
    the chip-less planner. Each available chip is played at most once in the horizon
    and at most one chip is played per gameweek.
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

    verified_horizon = horizon.validated_copy()
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
    )
    started_at = perf_counter()
    deadline = started_at + optimization_config.solver_time_limit_seconds
    primary_solver = cp_model.CpSolver()
    _configure_solver(
        primary_solver,
        optimization_config,
        optimization_config.solver_time_limit_seconds,
        optimization_config.solver_deterministic_time_limit,
    )
    raw_primary_status = _solve(artifacts.model, primary_solver)
    primary_status = _map_solver_status(raw_primary_status)
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
        "chips_available": {name: sorted(weeks) for name, weeks in availability.available.items()},
        "expected_points_scale": optimization_config.expected_points_scale,
        "objective_weight_scale": settings.objective_weight_scale,
        "discount_weights": artifacts.discount_weights,
        "horizon_discount_factor": settings.horizon_discount_factor,
        "transfer_hit_cost_points": settings.transfer_hit_cost_points,
        "hit_cost_scaled": artifacts.hit_cost_scaled,
        "max_free_transfers": settings.max_free_transfers,
        "free_transfer_accrual": settings.free_transfer_accrual,
        "budget_policy": "stateful_bank_accounting",
        "rounding_mode": "ROUND_HALF_UP",
        "deterministic_seed": optimization_config.deterministic_seed,
        "num_search_workers": 1,
        "solver_time_limit_seconds": optimization_config.solver_time_limit_seconds,
        "solver_deterministic_time_limit": (optimization_config.solver_deterministic_time_limit),
        "primary_deterministic_time": primary_deterministic_time,
        "tiebreak_deterministic_time_limit": None,
        "tiebreak_deterministic_time": None,
        "deterministic_time_used": primary_deterministic_time,
        "deterministic_time_budget_exhausted": (
            optimization_config.solver_deterministic_time_limit is not None
            and primary_status is not SolverStatus.OPTIMAL
            and primary_deterministic_time
            >= (
                optimization_config.solver_deterministic_time_limit
                - MIN_TIEBREAK_DETERMINISTIC_TIME
            )
        ),
        "tiebreak_attempted": False,
        "tiebreak_status": None,
        "tiebreak_completed": False,
    }
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
    remaining_time = deadline - perf_counter()
    remaining_deterministic_time = _remaining_deterministic_time(
        optimization_config.solver_deterministic_time_limit,
        primary_deterministic_time,
    )
    deterministic_budget_available = (
        remaining_deterministic_time is None
        or remaining_deterministic_time > MIN_TIEBREAK_DETERMINISTIC_TIME
    )
    if (
        primary_status is SolverStatus.OPTIMAL
        and remaining_time > MIN_TIEBREAK_TIME_SECONDS
        and deterministic_budget_available
    ):
        diagnostics["tiebreak_attempted"] = True
        _add_tiebreak(artifacts, optimization_config, primary_value)
        tiebreak_solver = cp_model.CpSolver()
        diagnostics["tiebreak_deterministic_time_limit"] = remaining_deterministic_time
        _configure_solver(
            tiebreak_solver,
            optimization_config,
            remaining_time,
            remaining_deterministic_time,
        )
        raw_tiebreak_status = _solve(artifacts.model, tiebreak_solver)
        tiebreak_status = _map_solver_status(raw_tiebreak_status)
        tiebreak_deterministic_time = _deterministic_time_used(
            tiebreak_solver,
            raw_tiebreak_status,
        )
        diagnostics["tiebreak_status"] = _raw_status_name(raw_tiebreak_status)
        diagnostics["tiebreak_deterministic_time"] = tiebreak_deterministic_time
        diagnostics["deterministic_time_used"] = (
            primary_deterministic_time + tiebreak_deterministic_time
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
