"""Paired explicit-tail lookahead on one rebuilt forecast; development evidence, no promotion.

Three policies are scored on the same supplied forecast: the window solve continued
over the tail it never saw, one lookahead solve over window and tail together, and the
rolling one-week control. A positive difference is in-forecast points on one capture,
never realized points. The protocol is written before the first solve and does not move.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from scripts.measure_shortlist_matrix import audit_plan

from squadopt.application.football_live import produce_football_forecast
from squadopt.contracts.preferences import DecisionPreferences
from squadopt.data.snapshots import read_snapshot
from squadopt.live import infer_season, read_inputs
from squadopt.live.football_artifact import football_artifact_path, read_football_forecast
from squadopt.live.rules import read_season_rules
from squadopt.optimization import OptimizationConfig, SolverStatus, optimize_squad
from squadopt.optimization.optimizer import wall_clock_stopped_the_search
from squadopt.planning import (
    ChipAvailability,
    InitialSquadState,
    PlanningHorizon,
    PlanningWeekResult,
    TransferPlanningConfig,
    TransferPlanResult,
    optimize_transfer_plan,
    to_planning_horizon,
)
from squadopt.planning.lookahead import optimize_with_lookahead
from squadopt.planning.recourse_chips import net_week_points
from squadopt.prediction.availability import apply_availability

#: The production rate: twenty deterministic units per forecast week in the solve
#: (`application/advice.py`, WINDOW_DETERMINISTIC_UNITS_PER_WEEK). Every solve here gets
#: this rate, so a control's two solves and the lookahead's one solve sum to equal units.
UNITS_PER_WEEK = 20.0
#: A protected solve's hold probe has its own one-unit cap outside the main search
#: (`planning/optimizer.py`). Each solve reserves it inside its share, so a declared total
#: is what an arm may spend, probes included. The measured run did not: its control's two
#: probes and the lookahead's one ran outside the shares (#904 review).
HOLD_PROBE_UNITS = 1.0
#: A safety stop, not a budget. Where a clock stops a search is a function of the machine,
#: so a solve it stops is FAILED and never read.
WALL_CEILING_SECONDS = 7200.0
#: Constructed squads: budget, total funds and free transfers, as the matrix runner built
#: them. The third profile runs only when asked; the observed rollout used the first two.
PROFILES = ((1000, 1000, 1), (900, 900, 0), (950, 1000, 2))
WINDOWS = (3, 5)
#: A first-week action difference that includes a held player the capture prices below
#: one is availability-driven: the tail holds him at that multiplier for every week.
AVAILABILITY_LABEL = "availability_driven"
TRANSFER = TransferPlanningConfig()


@dataclass(frozen=True)
class Case:
    profile: int
    window: int
    tail: str
    last_week: int


def cases(first: int, expiry: int, profiles: Sequence[int]) -> list[Case]:
    """The declared cases: the served five-week tail for three weeks, chip expiry for both."""
    served_last = min(first + 4, 38)
    out = []
    for profile in profiles:
        out.append(Case(profile, 3, "served", served_last))
        for window in WINDOWS:
            out.append(Case(profile, window, "expiry", expiry))
    return out


def solver_config(weeks: int) -> OptimizationConfig:
    """One protected solve's main search, with its hold probe's unit reserved from its share."""
    return OptimizationConfig(
        bench_weight=0,
        solver_time_limit_seconds=WALL_CEILING_SECONDS,
        solver_deterministic_time_limit=UNITS_PER_WEEK * weeks - HOLD_PROBE_UNITS,
    )


#: The solver's objective rounds each player-week's points half up to
#: 1/expected_points_scale, once (`optimization/coefficients.py`). With no bench weight a
#: week's lineup carries eleven starter terms and the captain's term again, so a path's
#: scaled objective and its unrounded rescore differ by at most this much per forecast week.
ROUNDING_PER_WEEK = 12 * 0.5 / solver_config(1).expected_points_scale


def budget_arithmetic(case: Case, first: int) -> dict[str, float]:
    """Each arm's total, main-search caps and probe caps; the totals are equal by construction.

    The control is two protected solves, so two probes; the lookahead is one. Each probe is
    reserved inside its solve's share, so the totals are what each arm may spend.
    """
    total = case.last_week - first + 1
    shares = (UNITS_PER_WEEK * case.window, UNITS_PER_WEEK * (total - case.window))
    control_main = sum(share - HOLD_PROBE_UNITS for share in shares)
    lookahead_main = UNITS_PER_WEEK * total - HOLD_PROBE_UNITS
    control = control_main + HOLD_PROBE_UNITS * len(shares)
    lookahead = lookahead_main + HOLD_PROBE_UNITS
    if not math.isclose(control, lookahead):
        raise ValueError("Control and lookahead deterministic budgets must be equal.")
    return {
        "control_units": control,
        "lookahead_units": lookahead,
        "control_main_search_units": control_main,
        "lookahead_main_search_units": lookahead_main,
        "control_probe_units": HOLD_PROBE_UNITS * len(shares),
        "lookahead_probe_units": HOLD_PROBE_UNITS,
        "forecast_weeks": total,
    }


def self_parity(served: pd.DataFrame, extended: pd.DataFrame) -> None:
    """The extension must reproduce the served weeks; it proves week-range invariance only."""
    keys = ["gameweek", "player_id"]
    weeks = sorted(set(served.gameweek))
    left = served.sort_values(keys).reset_index(drop=True)
    right = extended.loc[extended.gameweek.isin(weeks)].sort_values(keys).reset_index(drop=True)
    if len(left) != len(right) or not left[keys].equals(right[keys]):
        raise ValueError("Self-parity failed: the extension does not carry the served rows.")
    # The reader's horizon carries the base projection columns only; compare what both hold.
    shared = [
        c
        for c in ("expected_points", "fixture_count", "price_tenths", "appearance_probability")
        if c in left.columns and c in right.columns
    ]
    if "expected_points" not in shared:
        raise ValueError("Self-parity failed: no expected points to compare.")
    for column in shared:
        if not np.allclose(
            left[column].to_numpy(dtype=float),
            right[column].to_numpy(dtype=float),
            atol=1e-10,
            rtol=0,
        ):
            raise ValueError(f"Self-parity failed on {column}.")


def flagged_players(availability: pd.DataFrame) -> frozenset[int]:
    """Players the capture prices below one: not available, or a stated chance under 100."""
    chance = pd.to_numeric(availability.chance_of_playing, errors="coerce")
    mask = availability.status.ne("a") | (chance.notna() & chance.lt(100))
    return frozenset(int(p) for p in availability.loc[mask, "player_id"])


def handoff(week: PlanningWeekResult) -> InitialSquadState:
    """The recourse handoff: squad, bank and carried free transfers after the decided week."""
    return InitialSquadState(
        tuple(int(p) for p in week.selected_squad.player_id),
        week.bank_after_tenths,
        week.free_transfers_for_next_gameweek,
    )


def first_action(week: PlanningWeekResult) -> dict[str, Any]:
    return {
        "squad": sorted(int(p) for p in week.selected_squad.player_id),
        "in": sorted(int(p) for p in week.transfers_in.player_id),
        "out": sorted(int(p) for p in week.transfers_out.player_id),
        "hit_points": week.transfer_hit_points,
        "chip": week.chip,
        "bank_after": week.bank_after_tenths,
        "free_next": week.free_transfers_for_next_gameweek,
    }


def path_summary(weeks: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """Transfers, paid transfers, reversals and net points of one path, reported apart.

    A reversal is a player bought back after this path sold him, or sold after it bought
    him: the churn a re-planning policy pays for without the forecast having moved.
    """
    sold: set[int] = set()
    bought: set[int] = set()
    reversals = 0
    transfers = 0
    for week in weeks:
        for player in week["in"]:
            reversals += player in sold
            bought.add(player)
        for player in week["out"]:
            reversals += player in bought
            sold.add(player)
        transfers += len(week["in"])
    hits = sum(float(w.get("hit_points", 0.0)) for w in weeks)
    return {
        "transfer_count": transfers,
        "paid_transfer_count": round(hits / TRANSFER.hit_points_charged) if hits else 0,
        "reversals": reversals,
        "hit_points": hits,
        "net_points": sum(float(w["net_points"]) for w in weeks)
        if all("net_points" in w for w in weeks)
        else None,
    }


def solve_record(plan: TransferPlanResult, horizon: PlanningHorizon, wall: float) -> dict[str, Any]:
    """One solve, read the way the record reads it; a clock-stopped search is FAILED."""
    diagnostics = plan.diagnostics
    if wall_clock_stopped_the_search(plan.solver_status, diagnostics):
        return {"valid": False, "status": "FAILED", "error": "wall clock stopped the search"}
    audited = audit_plan(plan, horizon, horizon, DecisionPreferences(), ChipAvailability())
    hold = diagnostics.get("hold_protection")
    probe: Mapping[str, Any] = hold if isinstance(hold, Mapping) else {}
    net = sum(net_week_points(w) for w in plan.weeks)
    if not math.isclose(net, audited["base_net_points"], abs_tol=1e-7):
        raise ValueError("Net points disagree with the independent rescore.")
    return {
        "valid": True,
        "status": plan.solver_status.name,
        "net_points": net,
        "hit_points": plan.total_transfer_hit_points,
        "objective_value": plan.objective_value,
        "best_objective_bound": diagnostics.get("best_objective_bound"),
        "relative_optimality_gap": diagnostics.get("relative_optimality_gap"),
        "deterministic_time_used": diagnostics.get("deterministic_time_used"),
        "deterministic_time_limit": diagnostics.get("solver_deterministic_time_limit"),
        # The probe's work is its own, outside the main search's usage above.
        "hold_probe_deterministic_time_used": probe.get("deterministic_time"),
        "hold_probe_deterministic_time_limit": probe.get("deterministic_time_limit"),
        "deterministic_time_budget_exhausted": diagnostics.get(
            "deterministic_time_budget_exhausted"
        ),
        "wall_seconds": wall,
        "first_action": first_action(plan.weeks[0]),
        "weeks": [
            week | {"hit_points": result.transfer_hit_points, "net_points": net_week_points(result)}
            for week, result in zip(audited["weeks"], plan.weeks, strict=True)
        ],
        **{
            k: v
            for k, v in path_summary(
                [
                    week | {"hit_points": result.transfer_hit_points}
                    for week, result in zip(audited["weeks"], plan.weeks, strict=True)
                ]
            ).items()
            if k in ("transfer_count", "paid_transfer_count", "reversals")
        },
    }


def label_pair(
    window: Mapping[str, Any],
    continuation: Mapping[str, Any],
    lookahead: Mapping[str, Any],
    flagged: frozenset[int],
) -> dict[str, Any]:
    """Read one pair by the declared rule; the gain is defined only under proved controls.

    A proof certifies the solver's rounded objective, not the unrounded rescore the deltas
    are taken on. Two paths can tie on the first and differ on the second, by at most the
    rounding envelope: ``ROUNDING_PER_WEEK`` for each path in every forecast week. So a
    proved lookahead below a proved control within that envelope is a tie, and only a
    shortfall beyond it is a code defect. The solver's bound is likewise on its rounded
    objective, so the gain's upper bound on the rescore adds the lookahead's own envelope.
    """
    arms = (window, continuation, lookahead)
    if not all(arm.get("valid") for arm in arms):
        return {"valid": False, "labels": ["failed"]}
    control_total = window["net_points"] + continuation["net_points"]
    total = lookahead["net_points"]
    delta = total - control_total
    weeks = len(lookahead["weeks"])
    envelope = 2 * ROUNDING_PER_WEEK * weeks
    labels = []
    controls_proved = window["status"] == "OPTIMAL" and continuation["status"] == "OPTIMAL"
    proved = controls_proved and lookahead["status"] == "OPTIMAL"
    if delta < -envelope and proved:
        raise ValueError(
            "A proved lookahead below a proved feasible path beyond the rounding envelope "
            "is a code defect."
        )
    if delta < -1e-6:
        labels.append("tie_within_rounding" if proved else "unproved_shortfall")
    changed = window["first_action"]["squad"] != lookahead["first_action"]["squad"]
    if changed:
        labels.append("first_week_changed")
        moved = set(window["first_action"]["squad"]) ^ set(lookahead["first_action"]["squad"])
        if moved & flagged:
            labels.append(AVAILABILITY_LABEL)
    if not lookahead["first_action"]["in"]:
        labels.append("hold_equal")
    if controls_proved and delta >= -1e-6:
        labels.append("gain_defined")
    bound = lookahead.get("best_objective_bound")
    return {
        "valid": True,
        "control_total": control_total,
        "lookahead_total": total,
        "delta": delta if "gain_defined" in labels else None,
        "delta_unread": None if "gain_defined" in labels else delta,
        "rounding_envelope": envelope,
        "rounded_bound_minus_control": None if bound is None else float(bound) - control_total,
        "gain_upper_bound": (
            None if bound is None else float(bound) + ROUNDING_PER_WEEK * weeks - control_total
        ),
        "labels": labels,
        "free_next_window_end": window["weeks"][-1]["free_next"],
        "free_next_lookahead_window_end": lookahead["weeks"][len(window["weeks"]) - 1]["free_next"],
        "hits_control": window["hit_points"] + continuation["hit_points"],
        "hits_lookahead": lookahead["hit_points"],
    }


def summarize(records: Sequence[Mapping[str, Any]], rolling: Mapping[str, Any]) -> dict[str, Any]:
    pairs = [r["pair"] for r in records if r["pair"].get("valid")]
    defined = [p for p in pairs if p["delta"] is not None]
    return {
        "cases": len(records),
        "valid_pairs": len(pairs),
        "failed_pairs": len(records) - len(pairs),
        "first_week_changed": sum("first_week_changed" in p["labels"] for p in pairs),
        AVAILABILITY_LABEL: sum(AVAILABILITY_LABEL in p["labels"] for p in pairs),
        "gain_defined": len(defined),
        "gains_over_0_1": sum(p["delta"] > 0.1 for p in defined),
        "unproved_shortfall": sum("unproved_shortfall" in p["labels"] for p in pairs),
        "hold_equal": sum("hold_equal" in p["labels"] for p in pairs),
        "rolling_one_week": {
            k: {"net_points": v.get("net_points"), "valid": v.get("valid")}
            for k, v in rolling.items()
        },
        "promotion": False,
        "realized_returns": False,
        "independent_future_performance": False,
    }


def compact(records: Sequence[Mapping[str, Any]], rolling: Mapping[str, Any]) -> dict[str, Any]:
    """What the committed record keeps: statuses, units, totals, labels and each path's moves.

    Per week: incoming, outgoing, bank, carried transfers, chip, hits and net points. The
    squads follow from the initial state and those moves, so they stay in the local results.
    """

    def arm(a: Mapping[str, Any]) -> dict[str, Any]:
        out = {k: v for k, v in a.items() if k != "weeks"}
        if "weeks" in a:
            out["weeks"] = [
                {k: v for k, v in week.items() if k not in ("squad", "starters", "captain")}
                for week in a["weeks"]
            ]
        return out

    return {
        "cases": [
            {
                **{k: r[k] for k in ("profile", "window", "tail", "last_week", "budget")},
                "arms": {name: arm(a) for name, a in r["arms"].items()},
                "pair": r["pair"],
            }
            for r in records
        ],
        "rolling_one_week": {k: arm(v) for k, v in rolling.items()},
    }


def render_markdown(compacted: Mapping[str, Any]) -> str:
    """The record's table, derived from the JSON so the two cannot disagree."""
    lines = [
        "| Profile | Window | Tail | Control (window + continuation) | Lookahead | Statuses "
        "(window/continuation/lookahead) | Delta | Gain upper bound, on the rescore | Labels |",
        "| --- | --- | --- | ---: | ---: | --- | ---: | ---: | --- |",
    ]
    for case in compacted["cases"]:
        pair, arms = case["pair"], case["arms"]
        statuses = "/".join(
            str(arms[a].get("status")) for a in ("window", "continuation", "lookahead")
        )
        delta = pair.get("delta")
        unread = pair.get("delta_unread")
        shown = (
            "not read"
            if not pair.get("valid")
            else f"{delta:+.6f}"
            if delta is not None
            else f"({unread:+.6f}, not read)"
        )
        bound = pair.get("gain_upper_bound")
        lines.append(
            f"| {case['profile']} | {case['window']} | {case['tail']} to GW{case['last_week']} | "
            f"{pair.get('control_total', float('nan')):.6f} | "
            f"{pair.get('lookahead_total', float('nan')):.6f} | {statuses} | {shown} | "
            f"{'none' if bound is None else f'{bound:+.3f}'} | "
            f"{', '.join(pair.get('labels', []))} |"
        )
    return "\n".join(lines)


def _plain(value: Any) -> Any:
    if isinstance(value, np.integer | np.floating):
        return value.item()
    return str(value)


def run(
    snapshot_root: Path,
    archive_root: Path,
    snapshot_id: str,
    output: Path,
    profiles: Sequence[int],
) -> None:
    output.mkdir(parents=True, exist_ok=False)
    root = Path(__file__).resolve().parents[1]

    def write(name: str, value: Any) -> None:
        (output / name).write_text(
            json.dumps(value, indent=2, default=_plain, allow_nan=False) + "\n", encoding="utf-8"
        )

    snapshot = read_snapshot(snapshot_root, snapshot_id)
    season = infer_season(snapshot)
    inputs = read_inputs(snapshot, season=season, gameweek=None)
    first = int(inputs.deadline.gameweek)
    rules = read_season_rules(snapshot, season=season)
    expiry = max(p.stop_event for p in rules.chips if p.covers(first))
    if (
        TRANSFER.horizon_discount_factor != 1
        or TRANSFER.banked_transfer_value_points != 0
        or TRANSFER.chip_holding_value_points
        or TRANSFER.transfer_hit_cost_points != TRANSFER.hit_points_charged
    ):
        raise ValueError("Net-points comparison requires actual hit costs and no terminal terms.")

    print("FORECAST served five weeks", flush=True)
    served_document = produce_football_forecast(snapshot, archive_root)
    served_path = football_artifact_path(output / "artifacts", snapshot_id)
    served_path.parent.mkdir(parents=True)
    served_path.write_text(json.dumps(served_document, sort_keys=True, allow_nan=False))
    forecast = read_football_forecast(served_path, inputs)
    print(f"FORECAST extended GW{first}-{expiry}", flush=True)
    extended_document = produce_football_forecast(
        snapshot, archive_root, gameweeks=range(first, expiry + 1)
    )
    (output / "extended-forecast.json").write_text(
        json.dumps(extended_document, sort_keys=True, allow_nan=False)
    )
    adjusted = [
        apply_availability(frame, inputs.availability).table
        for _, frame in pd.DataFrame(extended_document["rows"]).groupby("gameweek", sort=True)
    ]
    extended_table = pd.concat(adjusted, ignore_index=True)
    self_parity(forecast.horizon.table, extended_table)
    extended = replace(forecast.horizon, table=extended_table)
    planning = to_planning_horizon(extended)
    flagged = flagged_players(inputs.availability)

    sources = [
        Path(__file__),
        root / "scripts/measure_shortlist_matrix.py",
        root / "src/squadopt/application/football_live.py",
        root / "src/squadopt/live/football_horizon.py",
        root / "src/squadopt/live/football_artifact.py",
        root / "src/squadopt/prediction/football.py",
        root / "src/squadopt/prediction/availability.py",
        *sorted((root / "src/squadopt/planning").glob("*.py")),
    ]
    declared = cases(first, expiry, profiles)
    write(
        "protocol.json",
        {
            "analysis_at": datetime.now(UTC).isoformat(),
            "snapshot": snapshot_id,
            "snapshot_fingerprint": snapshot.metadata.fingerprint,
            "target_gameweek": first,
            "calendar_weeks": list(range(first, expiry + 1)),
            "chip_expiry_week": expiry,
            "forecast_identity": (
                "Rebuilt from archive plus capture through produce_football_forecast, "
                "the served football_team_share_v1 pipeline. No served artifact was read. "
                "Weeks beyond the fifth are not live_football_forecast_v1 and are never "
                "written under a football artifact root."
            ),
            "served_forecast_fingerprint": served_document["fingerprint"],
            "served_forecast_sha256": hashlib.sha256(served_path.read_bytes()).hexdigest(),
            "extended_forecast_fingerprint": extended_document["fingerprint"],
            "archive_hashes": served_document["archive_hashes"],
            "self_parity": (
                "served weeks equal in the extension at atol 1e-10; week-range invariance only"
            ),
            "availability": (
                "captured state held in every week; a first-week difference moving a held "
                f"player priced below one is labelled {AVAILABILITY_LABEL}"
            ),
            "flagged_player_count": len(flagged),
            "prices": (
                "buy equals sell at captured prices; purchase rebasing is inert; the opt-in "
                "acquisition accounting stays at its default None in every arm"
            ),
            "transfer_policy": TRANSFER.configuration_fingerprint,
            "squads": (
                "Constructed by optimize_squad on the availability-applied first week at "
                "60 deterministic units, linearization 2, proof required; budgets/funds/FT "
                + str([p for p in PROFILES if p[0] in profiles])
                + "; not owner holdings, not the squads of earlier records"
            ),
            "cases": [c.__dict__ for c in declared],
            "budget": {
                "units_per_forecast_week": UNITS_PER_WEEK,
                "wall_ceiling_seconds": WALL_CEILING_SECONDS,
                "arithmetic": {
                    f"{c.profile}/{c.window}/{c.tail}": budget_arithmetic(c, first)
                    for c in declared
                },
                "rolling_one_week": UNITS_PER_WEEK * (expiry - first + 1),
                "hold_probe": (
                    f"{HOLD_PROBE_UNITS} unit per protected solve, reserved inside its share; "
                    "each solve's probe usage is recorded beside its main-search usage"
                ),
                "wall_stopped": "FAILED, never read; no budget is raised after a result",
            },
            "arms": {
                "window_then_continue": (
                    "window solve blind to the tail, then a continuation over the tail "
                    "from its end state"
                ),
                "lookahead": (
                    "planning.lookahead.optimize_with_lookahead over window and tail together"
                ),
                "rolling_one_week": (
                    "sequential one-week solves with the same handoff, the canonical control; "
                    "transfer counts, paid transfers, reversals and net points reported apart"
                ),
            },
            "reading_rule": (
                "delta is defined only when window and continuation are OPTIMAL; a negative "
                "delta is unproved_shortfall, never a loss; the lookahead bound gives an upper "
                "bound on the in-forecast gain; the primary finding is how often the first-week "
                "action changed; a proof certifies the objective rounded to 0.001 points per "
                f"player-week, so a proved lookahead within {ROUNDING_PER_WEEK} points per path "
                "per forecast week of a proved control is tie_within_rounding, a shortfall beyond "
                "twice that is a code defect, and the bound adds the lookahead's envelope"
            ),
            "dropped": {
                "tail_plus_three": "no declared reason; the served tail replaces it",
                "chips": (
                    "an unpriced right is spent inside any window solve, so the control is "
                    "degenerate"
                ),
            },
            "order": "per case, control arms first on even indices and lookahead first on odd",
            "sources": {
                str(p.relative_to(root)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in sources
            },
            "historical_decision_replay": False,
            "authored_after_capture": True,
            "outcomes_read": False,
            "tuning": False,
            "promotion": False,
            "realized_returns": False,
        },
    )

    construction = OptimizationConfig(
        bench_weight=0, solver_time_limit_seconds=120, solver_deterministic_time_limit=60
    )
    first_week = forecast.horizon.table.loc[forecast.horizon.table.gameweek.eq(first)].copy()
    states: dict[int, InitialSquadState] = {}
    for budget, funds, free in PROFILES:
        if budget not in profiles:
            continue
        solved = optimize_squad(
            first_week, replace(construction, budget_tenths=budget), linearization_level=2
        )
        if solved.solver_status is not SolverStatus.OPTIMAL:
            raise ValueError("Squad construction must be proved before paired comparisons.")
        states[budget] = InitialSquadState(
            tuple(int(p) for p in solved.selected_squad.player_id),
            funds - int(solved.selected_squad.price_tenths.sum()),
            free,
        )
    write(
        "initial-states.json",
        {
            str(k): {
                "ids": v.squad_player_ids,
                "bank": v.bank_tenths,
                "ft": v.free_transfers,
                "flagged_held": sorted(set(v.squad_player_ids) & flagged),
            }
            for k, v in states.items()
        },
    )

    def slice_weeks(start: int, stop: int) -> PlanningHorizon:
        table = planning.table
        return PlanningHorizon(table.loc[table.gameweek.between(start, stop)].copy())

    def failed(error: Exception, started: float) -> dict[str, Any]:
        return {
            "valid": False,
            "status": "FAILED",
            "error": str(error),
            "wall_seconds": time.perf_counter() - started,
        }

    def planned(horizon: PlanningHorizon, state: InitialSquadState) -> dict[str, Any]:
        started = time.perf_counter()
        try:
            result = optimize_transfer_plan(
                horizon,
                state,
                solver_config(len(horizon.gameweeks)),
                TRANSFER,
                protect_hold=True,
                linearization_level=2,
            )
            return solve_record(result, horizon, time.perf_counter() - started)
        except Exception as error:  # every failure is a recorded row
            return failed(error, started)

    def continued(case: Case, window: Mapping[str, Any]) -> dict[str, Any]:
        if not window.get("valid"):
            return {"valid": False, "status": "FAILED", "error": "no window plan"}
        end = window["weeks"][-1]
        return planned(
            slice_weeks(first + case.window, case.last_week),
            InitialSquadState(tuple(end["squad"]), end["bank"], end["free_next"]),
        )

    def looked_ahead(case: Case, state: InitialSquadState) -> dict[str, Any]:
        horizon = slice_weeks(first, case.last_week)
        started = time.perf_counter()
        try:
            result = optimize_with_lookahead(
                horizon,
                state,
                solver_config(len(horizon.gameweeks)),
                window=case.window,
                transfer=TRANSFER,
            )
            record = solve_record(result.plan, horizon, time.perf_counter() - started)
            if record["valid"]:
                record["window_net_points"] = result.window_net_points
                record["tail_net_points"] = result.tail_net_points
            return record
        except Exception as error:  # every failure is a recorded row
            return failed(error, started)

    windows: dict[tuple[int, int], dict[str, Any]] = {}
    records: list[dict[str, Any]] = []
    rolling: dict[str, Any] = {}
    for index, case in enumerate(declared):
        state = states[case.profile]
        print(f"START {case}", flush=True)
        key = (case.profile, case.window)
        if key not in windows:
            windows[key] = planned(slice_weeks(first, first + case.window - 1), state)
        window = windows[key]
        arms: dict[str, Any] = {"window": window}
        order = ("continuation", "lookahead") if index % 2 == 0 else ("lookahead", "continuation")
        for name in order:
            arms[name] = (
                continued(case, window) if name == "continuation" else looked_ahead(case, state)
            )
            print(f"ARM {name}: {arms[name].get('status')}", flush=True)
        records.append(
            {
                "profile": case.profile,
                "window": case.window,
                "tail": case.tail,
                "last_week": case.last_week,
                "budget": budget_arithmetic(case, first),
                "arms": arms,
                "pair": label_pair(window, arms["continuation"], arms["lookahead"], flagged),
            }
        )
        write("results.json", {"cases": records, "rolling_one_week": rolling})
        print(
            f"DONE {len(records)}/{len(declared)} {records[-1]['pair'].get('labels')}", flush=True
        )

    for profile, state in states.items():
        print(f"START rolling {profile}", flush=True)
        current = state
        weeks: list[dict[str, Any]] = []
        statuses = []
        valid = True
        started = time.perf_counter()
        for week in range(first, expiry + 1):
            record = planned(slice_weeks(week, week), current)
            statuses.append(record.get("status"))
            if not record.get("valid"):
                valid = False
                weeks.append(record)
                break
            step = record["weeks"][0]
            weeks.append(step | {"status": record["status"], "net_points": record["net_points"]})
            current = InitialSquadState(tuple(step["squad"]), step["bank"], step["free_next"])
        rolling[str(profile)] = {
            "valid": valid,
            "statuses": statuses,
            "wall_seconds": time.perf_counter() - started,
            "weeks": weeks,
            **(path_summary(weeks) if valid else {}),
        }
        write("results.json", {"cases": records, "rolling_one_week": rolling})
    write("summary.json", summarize(records, rolling))
    compacted = compact(records, rolling)
    compacted["full_local_results_sha256"] = hashlib.sha256(
        (output / "results.json").read_bytes()
    ).hexdigest()
    write("compact.json", compacted)
    (output / "table.md").write_text(render_markdown(compacted) + "\n", encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("snapshot-root", "archive-root", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--snapshot-id", required=True)
    parser.add_argument(
        "--profiles", type=int, nargs="+", default=[1000, 900], choices=[p[0] for p in PROFILES]
    )
    args = parser.parse_args()
    run(args.snapshot_root, args.archive_root, args.snapshot_id, args.output, args.profiles)
