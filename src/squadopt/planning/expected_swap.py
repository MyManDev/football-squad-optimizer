"""One initial-roster swap, ranked cheaply and validated by the full CP model.

The proxy is not exact: a changed q also changes others' autosub/captain weights.
No forecast is transformed and no initial transaction state is rebased.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from math import isfinite
from numbers import Real
from time import perf_counter
from typing import Any, cast

from squadopt.contracts.players import POSITIONS
from squadopt.contracts.preferences import DecisionPreferences
from squadopt.optimization import OptimizationConfig, wall_clock_stopped_the_search
from squadopt.planning.lineup_utility import improve_plan_lineups
from squadopt.planning.models import (
    ChipAvailability,
    InitialSquadState,
    PlanningHorizon,
    PlanningWeekResult,
    TransferPlanningConfig,
    TransferPlanResult,
    _stable_id_key,
)
from squadopt.planning.optimizer import optimize_transfer_plan
from squadopt.scenarios.expected_lineup import expected_lineup_score


def checked_work(value: object, cap: float) -> float:
    """Bad accounting is an error, never permission for fresh solver work."""
    if (
        isinstance(value, bool)
        or not isinstance(value, Real)
        or not isfinite(float(value))
        or not isfinite(cap)
        or cap < 0
        or not 0 <= float(value) <= cap + 0.01
    ):
        raise ValueError("Invalid deterministic-work accounting for expected windows.")
    return float(value)


def propose_expected_swap(
    horizon: PlanningHorizon,
    initial: InitialSquadState,
    optimization: OptimizationConfig,
    transfer: TransferPlanningConfig,
    template: PlanningWeekResult,
    retained_squads: Sequence[frozenset[object]],
    *,
    deterministic_slack: float,
    wall_slack: float,
    chips: ChipAvailability | None = None,
    preferences: DecisionPreferences | None = None,
    not_starting: Iterable[object] = (),
    not_captain: Iterable[object] = (),
) -> tuple[TransferPlanResult | None, dict[str, Any]]:
    """At most one template score, then one cold fixed-first-squad CP solve.

    Exclusions currently route outside the expected-window wrapper. Any nonempty
    role restriction is an explicit no-op, not new exclusion-route support.
    """
    started = perf_counter()
    weeks = horizon.gameweeks
    record: dict[str, Any] = {
        "phase": "initial_single_swap",
        "status": "skipped",
        "reason": None,
        "cap": 0.0,
        "actual": 0.0,
        "solver_calls": 0,
        "cheap_pair_checks": 0,
        "cheap_pair_cap": 0,
        "eligible_positive_pairs": 0,
        "hold_score_calls": 0,
        "hold_score_states": 0,
        "lineup_search": None,
        "proof_scope": "one_fixed_first_squad_full_resource_path",
        "proxy_basis": "original_first_week_multiplier_marginal_minus_selection_hit",
        "proxy_is_exact_gain": False,
    }

    def skip(reason: str) -> tuple[None, dict[str, Any]]:
        record.update(reason=reason, wall_seconds=perf_counter() - started)
        return None, record

    checked_work(deterministic_slack, deterministic_slack)
    if not isfinite(wall_slack):
        raise ValueError("Expected-window wall slack must be finite.")
    if len(weeks) not in (3, 5):
        return skip("unsupported_horizon")
    if tuple(not_starting) or tuple(not_captain):
        return skip("first_week_role_exclusions_not_supported")
    if deterministic_slack <= 1e-9 or wall_slack <= 0:
        return skip("no_remaining_budget")
    if optimization.squad_size != 15 or optimization.starting_size != 11:
        return skip("unsupported_squad_shape")
    if "appearance_probability" not in horizon.table:
        return skip("missing_appearance_probability")
    if template.chip in {"wildcard", "freehit"} or (
        chips is not None and chips.forced.get(weeks[0]) in {"wildcard", "freehit"}
    ):
        return skip("first_week_rebuild")
    preferences = preferences or DecisionPreferences()
    if initial.free_transfers == 0 and preferences.no_hits:
        return skip("no_free_transfer_and_no_hits")
    first = horizon.table.loc[horizon.table.gameweek.eq(weeks[0])].set_index(
        "player_id", drop=False
    )
    held = frozenset(initial.squad_player_ids)
    selected = frozenset(template.selected_squad.player_id)
    if (
        template.gameweek != weeks[0]
        or len(held) != 15
        or not (held | selected) <= set(first.index)
    ):
        return skip("invalid_initial_template")
    replacement: dict[object, object] = {}
    for position in POSITIONS:
        incoming = sorted(
            (p for p in selected - held if first.at[p, "position"] == position),
            key=_stable_id_key,
        )
        missing = sorted(
            (p for p in held - selected if first.at[p, "position"] == position),
            key=_stable_id_key,
        )
        if len(incoming) != len(missing):
            return skip("invalid_initial_template")
        replacement.update(zip(incoming, missing, strict=True))
    xi = tuple(replacement.get(p, p) for p in template.starting_xi.player_id)
    bench = tuple(replacement.get(p, p) for p in template.bench.player_id)
    captain = replacement.get(template.captain.player_id, template.captain.player_id)
    vice = replacement.get(template.vice_captain_id, template.vice_captain_id)
    if (
        len(xi) != 11
        or len(bench) != 4
        or len(set((*xi, *bench))) != 15
        or set((*xi, *bench)) != held
        or captain not in xi
        or vice not in xi
        or captain == vice
    ):
        return skip("invalid_initial_template")
    for position in POSITIONS:
        count = sum(first.at[p, "position"] == position for p in xi)
        if not (
            optimization.starting_position_min[position]
            <= count
            <= optimization.starting_position_max[position]
        ):
            return skip("invalid_initial_template")
    if first.at[bench[0], "position"] != "GK" or any(
        first.at[p, "position"] == "GK" for p in bench[1:]
    ):
        return skip("invalid_initial_template")
    if selected == held and template.lineup_expectation is not None:
        multipliers = template.lineup_expectation["scoring_multipliers"]
        if not isinstance(multipliers, Mapping) or set(multipliers) != held:
            raise ValueError("Saved lineup multipliers do not match the retained squad.")
    else:
        scored = expected_lineup_score(
            first.loc[list(initial.squad_player_ids)],
            xi,
            bench,
            captain,
            vice,
            chip=template.chip,
        )
        multipliers = scored.scoring_multipliers
        record.update(hold_score_calls=1, hold_score_states=scored.states_evaluated)
    if any(
        isinstance(value, bool)
        or not isinstance(value, Real)
        or not isfinite(float(value))
        or float(value) < 0
        for value in multipliers.values()
    ):
        raise ValueError("Expected lineup multipliers must be finite and nonnegative.")
    outsiders = sorted(set(first.index) - held, key=_stable_id_key)
    record["cheap_pair_cap"] = 15 * len(outsiders)
    keep, avoid = set(preferences.keep_players), set(preferences.avoid_players)
    hit = transfer.transfer_hit_cost_points if initial.free_transfers == 0 else 0.0
    best: tuple[float, object, object, tuple[object, ...]] | None = None
    for outgoing in sorted(held, key=_stable_id_key):
        for incoming in outsiders:
            record["cheap_pair_checks"] += 1
            if first.at[outgoing, "position"] != first.at[incoming, "position"]:
                continue
            ids = held - {outgoing} | {incoming}
            if ids in retained_squads or not keep <= ids or ids & avoid:
                continue
            if (
                initial.bank_tenths + int(cast(int, first.at[outgoing, "sell_price_tenths"]))
                < int(cast(int, first.at[incoming, "buy_price_tenths"]))
                or max(Counter(first.loc[list(ids), "team_id"]).values())
                > optimization.max_players_per_team
            ):
                continue
            proxy = (
                float(multipliers[outgoing])
                * (
                    float(cast(float, first.at[incoming, "expected_points"]))
                    - float(cast(float, first.at[outgoing, "expected_points"]))
                )
                - hit
            )
            if proxy <= 0:
                continue
            record["eligible_positive_pairs"] += 1
            if best is None or proxy > best[0]:
                best = (proxy, outgoing, incoming, tuple(sorted(ids, key=_stable_id_key)))
    if best is None:
        return skip("no_distinct_legal_positive_pair")
    remaining_wall = wall_slack - (perf_counter() - started)
    if remaining_wall <= 0:
        return skip("no_remaining_wall_budget")
    # Native primary and tie-break each receive this limit. With no seed/hold
    # solve, two half-ceilings fit the remaining CP wall allowance.
    settings = replace(
        optimization,
        solver_deterministic_time_limit=deterministic_slack,
        solver_time_limit_seconds=remaining_wall / 2,
    )
    record.update(
        cap=deterministic_slack,
        solver_calls=1,
        proxy=best[0],
        outgoing=best[1],
        incoming=best[2],
        fixed_first_squad=list(best[3]),
        solver_wall_cap_seconds=remaining_wall,
        solver_phase_wall_cap_seconds=remaining_wall / 2,
    )
    candidate = optimize_transfer_plan(
        horizon,
        initial,
        settings,
        transfer,
        chips=chips,
        preferences=preferences,
        fixed_week_squads={weeks[0]: best[3]},
        linearization_level=2,
        protect_hold=False,
        incumbent_plan=None,
        protect_incumbent=False,
    )
    record.update(
        status=candidate.solver_status.name,
        actual=checked_work(candidate.diagnostics["deterministic_time_used"], deterministic_slack),
    )
    if wall_clock_stopped_the_search(candidate.solver_status, candidate.diagnostics):
        return skip("optional_wall_clock_truncation")
    if not candidate.has_solution:
        return skip("optional_no_solution")
    if tuple(w.gameweek for w in candidate.weeks) != weeks:
        raise ValueError("A completed optional resource path omitted a planning week.")
    if frozenset(candidate.weeks[0].selected_squad.player_id) != frozenset(best[3]):
        raise ValueError("The optional solve did not preserve its fixed first squad.")
    if candidate.weeks[0].chip in {"wildcard", "freehit"}:
        return skip("optional_first_week_rebuild")
    result = improve_plan_lineups(candidate, settings, transfer, max_evaluations=128)
    record.update(
        reason="retained",
        lineup_search=result.diagnostics["lineup_search"],
        wall_seconds=perf_counter() - started,
    )
    return result, record
