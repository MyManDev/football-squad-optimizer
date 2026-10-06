"""HiGHS against CP-SAT on the member window model, as the #984 protocol declares.

The protocol is written before any solve and this runner does what it declares and nothing
more (#984). It rebuilds the fifteen GW6 members' one-week problems and their three- and
five-week windows from the committed publication inputs of one capture, runs the planner's
own code (``optimize_transfer_plan`` on the plain path the member-menu windows take) and
records the CP-SAT models it solves: the hold probe and the primary. A generic exporter
writes each as MPS, linearising the maximum, minimum, element and enforced constraints with
bounds taken from the model's own domains, and two checks hold the exporter to the model:

1. CP-SAT's solution, mapped onto the MPS columns, satisfies every row within 1e-6 and gives
   the same primary value;
2. a MILP solution, rounded and fixed in the CP-SAT model, is feasible there and gives the
   same primary value.

``check`` builds the instances, runs the one-week rebuild gate, writes the MPS files under
``artifacts/window_solver_highs/`` with their sha256 and runs check 1. It makes no timing
claim. ``measure`` runs the declared solves and refuses unless the heavy-test slot is held,
both HiGHS builds report core 1.15.3 and Node is 22; it writes
``docs/research/window_solver_highs.json`` and its markdown twin only at the end. In both
commands no solve starts on 9 or 10 October (UTC), nor one whose wall stops could carry it
into either day.

    python -m scripts.measure_window_solver_highs check [--member ENTRY_ID]
    python -m scripts.measure_window_solver_highs measure --i-have-the-slot --node <node22>
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import importlib
import json
import math
import os
import platform
import subprocess
import sys
from collections.abc import Callable, Iterator, Mapping, Sequence
from contextlib import contextmanager
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from time import perf_counter
from typing import Any, Final, cast

import pandas as pd
from ortools.sat.python import cp_model
from scripts._provenance import REPOSITORY_ROOT, _git_revision, write_json, write_text

from squadopt.application.advice import (
    WINDOW_DETERMINISTIC_UNITS_PER_WEEK,
    WINDOW_LINEARIZATION_LEVEL,
    WINDOW_WALL_CEILING_SECONDS,
)
from squadopt.live.transfers import MEMBER_PLANNING_POLICY, MEMBER_PLANNING_POLICY_ID
from squadopt.optimization import OptimizationConfig
from squadopt.optimization.coefficients import (
    objective_coefficients,
    round_half_up,
    scale_expected_points,
)
from squadopt.optimization.optimizer import MIN_TIEBREAK_DETERMINISTIC_TIME
from squadopt.planning import (
    InitialSquadState,
    PlanningHorizon,
    TransferPlanningConfig,
    TransferPlanResult,
    optimize_transfer_plan,
)
from squadopt.planning.optimizer import PLAN_WALL_CEILING_SECONDS

CONTRACT_VERSION: Final = "window_solver_highs_v1"
PROTOCOL: Final = "docs/window_solver_highs_prereg.md"
ISSUE: Final = 984
#: The one capture every input must carry (the protocol's "Instances").
CAPTURE: Final = "fpl-live-20261002T104314Z-8b70515b9b31"
WINDOWS: Final = (3, 5)
HIGHS_CORE_VERSION: Final = "1.15.3"
NODE_MAJOR: Final = 22
#: The game's sell-on fee. The three input documents do not publish it, and at the flat
#: captured prices it does not enter the model: a lot bought inside the window sells at its
#: buy price for any fee, so the fee reaches only the configuration fingerprint.
SELL_ON_FEE: Final = 0.5
ROW_TOLERANCE: Final = 1e-6
#: Two primary values agree when they differ by at most this many integer units.
AGREEMENT_UNITS: Final = 1000
DEVICE_PROOF_SECONDS: Final = 15.0
MIP_REL_GAP: Final = 0.0
MIP_ABS_GAP: Final = 0.5
#: (month, day) in UTC on which no solve runs.
BLOCKED_DAYS: Final = ((10, 9), (10, 10))
#: Check 2 fixes every variable, so CP-SAT only propagates; this is a stop, not a budget.
FIXED_CHECK_SECONDS: Final = 120.0
#: The hold probe's wall stop: ``planning/optimizer.py`` configures it with
#: ``min(wall_limit, 30.0)``.
HOLD_PROBE_WALL_SECONDS: Final = 30.0
#: Time beyond the solvers' own wall stops that a solve may take: the model build, the
#: process start, the MPS read and the answer's write.
SOLVE_MARGIN_SECONDS: Final = 900.0
#: A driver's stop on the toy model it must prove before any timed run.
PREFLIGHT_TIMEOUT_SECONDS: Final = 900.0
#: Both HiGHS builds are set to this many threads.
HIGHS_THREADS: Final = 1

LEAGUE_DIR: Final = REPOSITORY_ROOT / "web" / "public" / "data" / "league"
FIXTURES_PATH: Final = REPOSITORY_ROOT / "web" / "public" / "data" / "fixtures.json"
WEB_DIR: Final = REPOSITORY_ROOT / "web"
ARTIFACT_DIR: Final = REPOSITORY_ROOT / "artifacts" / "window_solver_highs"
RECORD_JSON: Final = REPOSITORY_ROOT / "docs" / "research" / "window_solver_highs.json"
RECORD_MARKDOWN: Final = REPOSITORY_ROOT / "docs" / "research" / "window_solver_highs.md"

INT64_MIN: Final = -(2**63)
INT64_MAX: Final = 2**63 - 1
#: Every number the exporter writes is an integer a double holds exactly.
EXACT_LIMIT: Final = 2**53

#: HiGHS model status codes, shared by the native library and the wasm package.
HIGHS_MODEL_STATUS: Final = {
    0: "Not set",
    1: "Load error",
    2: "Model error",
    3: "Presolve error",
    4: "Solve error",
    5: "Postsolve error",
    6: "Empty",
    7: "Optimal",
    8: "Infeasible",
    9: "Primal infeasible or unbounded",
    10: "Unbounded",
    11: "Bound on objective reached",
    12: "Target for objective reached",
    13: "Time limit reached",
    14: "Iteration limit reached",
    15: "Unknown",
    16: "Solution limit reached",
    17: "Interrupted",
    18: "Memory limit reached",
}
HIGHS_OPTIMAL: Final = 7
HIGHS_PRIMAL_FEASIBLE: Final = 2

#: The narrow readings this runner takes where the protocol leaves a choice, recorded with
#: the result so a reader can see them beside the numbers.
READINGS: Final = (
    "The primary MPS omits CP-SAT's hold floor. Each HiGHS run floors its own primary at the "
    "value of its own hold solution, rounded to integers and recomputed exactly, when its hold "
    "solve returned a solution; without one its primary runs unfloored.",
    "A run's time is its hold solve plus its primary solve. The wall-matched budget is "
    "CP-SAT's hold probe plus primary solve time on the reference run, and a HiGHS primary "
    "gets what its own hold solve left of the budget.",
    "A HiGHS run whose primary returns no solution keeps its own hold plan as its value, as "
    "the planner keeps CP-SAT's hold plan, and is not proved.",
    "CP-SAT proves an instance when the reference run's primary solve is OPTIMAL. The "
    "five-week instances CP-SAT's rerun leaves FEASIBLE are those whose reference plan is "
    "FEASIBLE.",
    "A HiGHS native run that ends the 1,800 s run with no solution counts, for the server's "
    "third condition, as ending below CP-SAT's value.",
    "Check 2 compares CP-SAT's objective at the fixed point with the MPS objective evaluated "
    "exactly at the same rounded point; the objective HiGHS reports is recorded beside them.",
    "The sell-on fee is the game's 0.5. The three input documents do not publish it; at the "
    "flat captured prices it does not enter the model.",
    "CP-SAT's primary starts from its hold solution: the planner floors the primary at the "
    "hold value and also hints every variable with the probe's solution "
    "(planning/optimizer.py). Each HiGHS primary gets the floor row only and no starting "
    "solution, because the protocol declares the floor and not a start. Every HiGHS time "
    "stands beside that difference.",
    "CP-SAT's model build time is the planner call's wall time less every captured solve, the "
    "tie-break's included, and less the capture's own model copies; it also holds the "
    "planner's reading of its answer. The tie-break's time counts in no run's time.",
    "Both HiGHS builds are set to one thread. Each solve records the thread count its build "
    "reports back, or none where the build's API reports none.",
)


class ProtocolRefusal(RuntimeError):
    """An input, a guard or a check is not what the protocol declares; nothing goes on."""


class ExportRefused(ValueError):
    """The exporter met something it does not translate; it names it rather than guess."""


# --------------------------------------------------------------------------------------
# The committed inputs.


def _payload(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    payload = document.get("payload", document) if isinstance(document, dict) else None
    if not isinstance(payload, dict):
        raise ProtocolRefusal(f"{path} carries no payload object.")
    return payload


def require_capture(path: Path, payload: Mapping[str, Any]) -> None:
    """Refuse an input from any capture but the protocol's."""

    found = payload.get("source_snapshot_id")
    if found != CAPTURE:
        raise ProtocolRefusal(
            f"{path} is capture {found!r}; the protocol measures {CAPTURE!r} and no other."
        )


@dataclass(frozen=True)
class PublishedInputs:
    """The device table, each member's block and the calendar, as committed."""

    table: Mapping[str, Any]
    members: Mapping[int, Mapping[str, Any]]
    fixture_counts: Mapping[int, Mapping[str, int]]
    league_dir: Path

    @property
    def gameweek(self) -> int:
        return int(self.table["gameweek"])


def fixture_counts(fixtures: Mapping[str, Any]) -> dict[int, dict[str, int]]:
    """Fixtures per club and gameweek, keyed by the club name the device table uses."""

    counts: dict[int, dict[str, int]] = {}
    for week in fixtures["gameweeks"]:
        tally: dict[str, int] = {}
        for fixture in week["fixtures"]:
            for side in ("home", "away"):
                name = str(fixture[side]["name"])
                tally[name] = tally.get(name, 0) + 1
        counts[int(week["gameweek"])] = tally
    return counts


def load_inputs(
    league_dir: Path = LEAGUE_DIR, fixtures_path: Path = FIXTURES_PATH
) -> PublishedInputs:
    """Read the three committed inputs, refusing any from another capture."""

    plan_path = league_dir / "device-plan.json"
    table = _payload(plan_path)
    require_capture(plan_path, table)
    members: dict[int, Mapping[str, Any]] = {}
    for path in sorted((league_dir / "entries").glob("*.json")):
        payload = _payload(path)
        require_capture(path, payload)
        if int(payload.get("gameweek", -1)) != int(table["gameweek"]):
            raise ProtocolRefusal(f"{path} is for another gameweek than the device table.")
        block = payload.get("device_plan")
        if not isinstance(block, dict):
            raise ProtocolRefusal(f"{path} publishes no device_plan block.")
        members[int(path.stem)] = block
    fixtures = _payload(fixtures_path)
    require_capture(fixtures_path, fixtures)
    return PublishedInputs(table, members, fixture_counts(fixtures), league_dir)


def published_advice(inputs: PublishedInputs, entry_id: int, window: int) -> dict[str, Any]:
    """One member's published ``saf-puan`` plan, refused if it is from another capture."""

    path = inputs.league_dir / "advice" / str(entry_id) / "saf-puan" / f"{window}.json"
    payload = _payload(path)
    require_capture(path, payload)
    return payload


# --------------------------------------------------------------------------------------
# The planner's arguments, rebuilt from the published inputs.


@dataclass(frozen=True)
class PlannerCall:
    """The arguments the live path hands ``optimize_transfer_plan`` for one member."""

    horizon: PlanningHorizon
    state: InitialSquadState
    settings: OptimizationConfig
    policy: TransferPlanningConfig
    linearization_level: int | None
    protect_hold: bool

    def solve(self) -> TransferPlanResult:
        return optimize_transfer_plan(
            self.horizon,
            self.state,
            self.settings,
            self.policy,
            chips=None,
            first_week_overlap=None,
            first_week_transfer_cap=None,
            first_week_exclusion=None,
            linearization_level=self.linearization_level,
            preferences=None,
            protect_hold=self.protect_hold,
        )


def _policy_number(name: str) -> float:
    return float(cast(float, MEMBER_PLANNING_POLICY[name]))


def require_rules(table: Mapping[str, Any]) -> None:
    """The published rules and coefficients are the ones this code would solve with."""

    settings = OptimizationConfig()
    rules = table["rules"]
    expected: dict[str, object] = {
        "squad_size": settings.squad_size,
        "starting_size": settings.starting_size,
        "squad_position_limits": dict(settings.squad_position_limits),
        "starting_position_min": dict(settings.starting_position_min),
        "starting_position_max": dict(settings.starting_position_max),
        "max_players_per_team": settings.max_players_per_team,
        "expected_points_scale": settings.expected_points_scale,
        "hit_cost_scaled": scale_expected_points(
            _policy_number("transfer_hit_cost_points"), settings.expected_points_scale
        ),
        "hit_points_charged": _policy_number("hit_points_charged"),
    }
    for key, value in expected.items():
        if rules.get(key) != value:
            raise ProtocolRefusal(f"The device table's {key} is {rules.get(key)!r}, not {value!r}.")
    if table.get("policy_id") != MEMBER_PLANNING_POLICY_ID:
        raise ProtocolRefusal(f"The device table's policy is {table.get('policy_id')!r}.")
    players = table["players"]
    coefficients = objective_coefficients([p["expected_points"] for p in players], settings)
    for player, coefficient in zip(players, coefficients, strict=True):
        if list(coefficient) != list(player["coefficients"]):
            raise ProtocolRefusal(f"Player {player['id']}'s published coefficients differ.")


def member_policy(table: Mapping[str, Any], *, transfer_cap: int | None) -> TransferPlanningConfig:
    """``MEMBER_PLANNING_POLICY`` under the published free-transfer cap."""

    return TransferPlanningConfig(
        max_free_transfers=int(table["rules"]["max_free_transfers"]),
        max_transfers_per_gameweek=transfer_cap,
        transfer_hit_cost_points=_policy_number("transfer_hit_cost_points"),
        hit_points_charged=_policy_number("hit_points_charged"),
        banked_transfer_value_points=_policy_number("banked_transfer_value_points"),
        horizon_discount_factor=_policy_number("horizon_discount_factor"),
        chip_holding_value_points=cast(
            Mapping[str, float], MEMBER_PLANNING_POLICY["chip_holding_value_points"]
        ),
    )


def _players_frame(table: Mapping[str, Any]) -> pd.DataFrame:
    players = table["players"]
    return pd.DataFrame(
        {
            "player_id": pd.Series([int(p["id"]) for p in players], dtype="int64"),
            "name": [str(p["name"]) for p in players],
            "team_id": [str(p["team"]) for p in players],
            "position": [str(p["position"]) for p in players],
            "price_tenths": pd.Series([int(p["buy_tenths"]) for p in players], dtype="int64"),
            "expected_points": pd.Series(
                [float(p["expected_points"]) for p in players], dtype="float64"
            ),
        }
    )


def _sell_prices(frame: pd.DataFrame, block: Mapping[str, Any]) -> list[int]:
    sell = {int(player): int(price) for player, price in block["sell_tenths"].items()}
    return [
        sell.get(int(player), int(price))
        for player, price in zip(
            frame["player_id"].tolist(), frame["price_tenths"].tolist(), strict=True
        )
    ]


def _state(block: Mapping[str, Any], policy: TransferPlanningConfig) -> InitialSquadState:
    return InitialSquadState(
        tuple(int(player) for player in block["held"]),
        bank_tenths=int(block["bank_tenths"]),
        free_transfers=min(int(block["free_transfers"]), policy.max_free_transfers),
    )


def one_week_call(inputs: PublishedInputs, entry_id: int) -> PlannerCall:
    """The one-week problem, as ``plan_transfers`` states it (``live/transfers.py``)."""

    require_rules(inputs.table)
    block = inputs.members[entry_id]
    frame = _players_frame(inputs.table)
    horizon = pd.DataFrame(
        {
            "gameweek": inputs.gameweek,
            "player_id": frame["player_id"].astype("int64"),
            "name": frame["name"],
            "team_id": frame["team_id"],
            "position": frame["position"],
            "buy_price_tenths": frame["price_tenths"].astype("int64"),
            "sell_price_tenths": _sell_prices(frame, block),
            "expected_points": frame["expected_points"].astype("float64"),
        }
    )
    policy = member_policy(inputs.table, transfer_cap=None)
    return PlannerCall(
        horizon=PlanningHorizon(horizon),
        state=_state(block, policy),
        settings=OptimizationConfig(),
        policy=policy,
        linearization_level=None,
        protect_hold=False,
    )


def window_call(inputs: PublishedInputs, entry_id: int, window: int) -> PlannerCall:
    """A member's window, as ``solve_window_plan`` hands it to ``plan_transfer_horizon``.

    The later weeks repeat the first week's points scaled by each club's fixture count
    relative to its first-week count (``live/horizon.py``); the policy is the member policy
    with one transfer a week and the season's sale fee (``live/transfers.py``); the budget
    and the linearization level are the member window's (``application/advice.py``).
    """

    if window not in WINDOWS:
        raise ProtocolRefusal(f"Window {window} is not one of the protocol's {WINDOWS}.")
    require_rules(inputs.table)
    block = inputs.members[entry_id]
    first = inputs.gameweek
    weeks = tuple(range(first, first + window))
    missing = [week for week in weeks if week not in inputs.fixture_counts]
    if missing:
        raise ProtocolRefusal(f"The calendar publishes no gameweeks {missing!r}.")
    frame = _players_frame(inputs.table)
    points = frame["expected_points"].astype("float64")
    decision = frame["team_id"].map(inputs.fixture_counts[first]).fillna(0).astype("int64")
    if bool(((decision == 0) & (points > 0.0)).any()):
        raise ProtocolRefusal("A player with no first-week fixture carries positive points.")
    sell = _sell_prices(frame, block)
    frames = []
    for week in weeks:
        if week == first:
            expected = points.clip(lower=0.0)
        else:
            count = frame["team_id"].map(inputs.fixture_counts[week]).fillna(0).astype("int64")
            scale = count.astype("float64").div(decision.clip(lower=1).astype("float64"))
            expected = points.mul(scale).clip(lower=0.0)
        frames.append(
            pd.DataFrame(
                {
                    "gameweek": week,
                    "player_id": frame["player_id"].astype("int64"),
                    "name": frame["name"],
                    "team_id": frame["team_id"],
                    "position": frame["position"],
                    "expected_points": expected,
                    "buy_price_tenths": frame["price_tenths"].astype("int64"),
                    "sell_price_tenths": sell,
                }
            )
        )
    policy = replace(
        member_policy(inputs.table, transfer_cap=1), acquisition_sell_on_fee=SELL_ON_FEE
    )
    return PlannerCall(
        horizon=PlanningHorizon(pd.concat(frames, ignore_index=True)),
        state=_state(block, policy),
        settings=OptimizationConfig(
            solver_time_limit_seconds=WINDOW_WALL_CEILING_SECONDS,
            solver_deterministic_time_limit=WINDOW_DETERMINISTIC_UNITS_PER_WEEK * window,
        ),
        policy=policy,
        linearization_level=WINDOW_LINEARIZATION_LEVEL,
        protect_hold=True,
    )


def objective_divisor(call: PlannerCall) -> int:
    """Integer objective units per point: the weight scale times the points scale."""

    return int(call.policy.objective_weight_scale) * int(call.settings.expected_points_scale)


def cp_sat_wall_bound(call: PlannerCall) -> float:
    """The longest the planner's CP-SAT solves of ``call`` can run by their wall stops.

    The hold probe stops at 30 s or the ceiling; the primary and the tie-break each stop at
    the ceiling, which the planner raises to its own default when the caller sets no
    deterministic budget (``planning/optimizer.py``).
    """

    wall = float(call.settings.solver_time_limit_seconds)
    if call.settings.solver_deterministic_time_limit is None:
        wall = max(wall, float(PLAN_WALL_CEILING_SECONDS))
    hold = min(wall, HOLD_PROBE_WALL_SECONDS) if call.protect_hold else 0.0
    return hold + 2.0 * wall


def refuse_blocked_day_for(call: PlannerCall) -> None:
    """Refuse a CP-SAT run of ``call`` that could start on or run into a blocked day."""

    refuse_blocked_date(datetime.now(UTC), cp_sat_wall_bound(call) + SOLVE_MARGIN_SECONDS)


def rebuild_check(inputs: PublishedInputs, entry_id: int) -> dict[str, Any]:
    """Solve the rebuilt one-week problem and hold it to the published ``saf-puan/1.json``."""

    call = one_week_call(inputs, entry_id)
    refuse_blocked_day_for(call)
    plan = call.solve()
    published = published_advice(inputs, entry_id, 1)
    week = plan.weeks[0]
    ours = {
        "in": sorted(int(v) for v in week.transfers_in["player_id"]),
        "out": sorted(int(v) for v in week.transfers_out["player_id"]),
        "eleven": sorted(int(v) for v in week.starting_xi["player_id"]),
        "captain": int(week.captain["player_id"]),
    }
    theirs = {
        "in": sorted(
            int(m["player_in"]["player_id"]) for m in published["moves"] if m.get("player_in")
        ),
        "out": sorted(
            int(m["player_out"]["player_id"]) for m in published["moves"] if m.get("player_out")
        ),
        "eleven": sorted(int(p["player_id"]) for p in published["starting_xi"]),
        "captain": int(published["captain"]["player_id"]),
    }
    moves = ours["in"] == theirs["in"] and ours["out"] == theirs["out"]
    eleven = ours["eleven"] == theirs["eleven"]
    captain = ours["captain"] == theirs["captain"]
    return {
        "entry_id": entry_id,
        "solver_status": plan.solver_status.name,
        "moves_equal": moves,
        "eleven_equal": eleven,
        "captain_equal": captain,
        "passed": moves and eleven and captain,
    }


# --------------------------------------------------------------------------------------
# Capturing the CP-SAT models the planner solves.


@dataclass(frozen=True)
class CapturedSolve:
    """One ``CpSolver.solve`` call: the model as solved, the parameters and the answer."""

    order: int
    proto: Any
    parameters: Mapping[str, float | int]
    parameters_text: str
    status: str
    objective_value: float | None
    best_bound: float | None
    solution: tuple[int, ...]
    seconds: float
    deterministic_time: float
    #: The capture's own copy of the model before the solve, outside ``seconds``.
    copy_seconds: float = 0.0

    @property
    def has_solution(self) -> bool:
        return self.status in ("OPTIMAL", "FEASIBLE")


def _parameters(solver: cp_model.CpSolver) -> dict[str, float | int]:
    parameters = solver.parameters
    return {
        "max_time_in_seconds": float(parameters.max_time_in_seconds),
        "max_deterministic_time": float(parameters.max_deterministic_time),
        "num_search_workers": int(parameters.num_search_workers),
        "random_seed": int(parameters.random_seed),
        "linearization_level": int(parameters.linearization_level),
    }


@contextmanager
def capture_cp_sat_solves() -> Iterator[list[CapturedSolve]]:
    """Record every CP-SAT solve inside the block, without changing what is solved.

    ``CpSolver.Solve`` delegates to ``CpSolver.solve``, so wrapping the latter sees both. The
    model is copied before the solve; the clock is ``perf_counter`` around the solve alone.
    """

    solves: list[CapturedSolve] = []
    original = cp_model.CpSolver.solve

    def recording(
        solver: cp_model.CpSolver, model: cp_model.CpModel, solution_callback: Any = None
    ) -> Any:
        copied = perf_counter()
        proto = copy.deepcopy(model.proto)
        parameters = _parameters(solver)
        parameters_text = str(solver.parameters)
        started = perf_counter()
        status = original(solver, model, solution_callback)
        seconds = perf_counter() - started
        response = solver.response_proto
        name = str(getattr(status, "name", status))
        found = name in ("OPTIMAL", "FEASIBLE")
        solves.append(
            CapturedSolve(
                order=len(solves),
                proto=proto,
                parameters=parameters,
                parameters_text=parameters_text,
                status=name,
                objective_value=float(response.objective_value) if found else None,
                best_bound=float(response.best_objective_bound) if found else None,
                solution=tuple(int(v) for v in response.solution) if found else (),
                seconds=seconds,
                deterministic_time=float(response.deterministic_time),
                copy_seconds=started - copied,
            )
        )
        return status

    setattr(cp_model.CpSolver, "solve", recording)  # noqa: B010
    try:
        yield solves
    finally:
        setattr(cp_model.CpSolver, "solve", original)  # noqa: B010


def _constraint_text(proto: Any, index: int) -> str:
    return str(proto.constraints[index])


def user_objective(proto: Any) -> tuple[dict[int, int | float], int | float, bool]:
    """The objective as the caller stated it: coefficients, constant, and whether maximised."""

    if proto.has_floating_point_objective():
        raise ExportRefused("The model has a floating-point objective.")
    if not proto.has_objective():
        return {}, 0, False
    objective = proto.objective
    if len(objective.domain) > 0:
        raise ExportRefused("The objective carries a domain.")
    scaling = float(objective.scaling_factor) or 1.0
    terms: dict[int, int] = {}
    for var, coeff in zip(objective.vars, objective.coeffs, strict=True):
        if var < 0:
            raise ExportRefused("The objective names a negated variable reference.")
        terms[int(var)] = terms.get(int(var), 0) + int(coeff)
    offset = float(objective.offset)
    if scaling in (1.0, -1.0):
        sign = int(scaling)
        integral = offset.is_integer()
        return (
            {var: sign * coeff for var, coeff in terms.items() if coeff != 0},
            sign * int(offset) if integral else sign * offset,
            scaling < 0,
        )
    return (
        {var: scaling * coeff for var, coeff in terms.items() if coeff != 0},
        scaling * offset,
        scaling < 0,
    )


@dataclass(frozen=True)
class WindowSolves:
    """The solves of one window: the hold probe, the primary and, if run, the tie-break."""

    hold: CapturedSolve
    primary: CapturedSolve
    tiebreak: CapturedSolve | None
    base_constraints: int
    floor_value: int | None

    @property
    def export_primary(self) -> Any:
        """The primary model without CP-SAT's hold floor and without its hints."""

        return proto_prefix(self.primary.proto, self.base_constraints)

    @property
    def primary_value(self) -> int | None:
        """The plan's value: the primary's incumbent, or the hold plan the planner keeps."""

        if self.primary.has_solution and self.primary.objective_value is not None:
            value = round(self.primary.objective_value)
            if self.floor_value is None or value >= self.floor_value:
                return value
        return self.floor_value


def _is_fixed_to_zero(proto: Any, index: int) -> bool:
    constraint = proto.constraints[index]
    if not constraint.has_linear() or len(constraint.enforcement_literal) > 0:
        return False
    linear = constraint.linear
    return list(linear.coeffs) == [1] and list(linear.domain) == [0, 0] and len(linear.vars) == 1


def _floor(proto: Any, index: int) -> int | None:
    """The hold floor's value if constraint ``index`` is ``objective >= value``."""

    constraint = proto.constraints[index]
    if not constraint.has_linear() or len(constraint.enforcement_literal) > 0:
        return None
    linear = constraint.linear
    domain = list(linear.domain)
    if len(domain) != 2 or domain[1] != INT64_MAX:
        return None
    terms: dict[int, int] = {}
    for var, coeff in zip(linear.vars, linear.coeffs, strict=True):
        terms[int(var)] = terms.get(int(var), 0) + int(coeff)
    objective, _, maximize = user_objective(proto)
    if not maximize or {k: v for k, v in terms.items() if v != 0} != objective:
        return None
    return int(domain[0])


def identify_window_solves(solves: Sequence[CapturedSolve], window: int) -> WindowSolves:
    """Name the hold probe and the primary, by order and by the hold floor, or refuse.

    The planner clones its model into the hold probe and fixes each week's transfer count to
    zero; the original then gains ``objective >= hold value`` when the probe found a plan.
    So the hold model is the base plus ``window`` fixings, the primary is the base plus at
    most that floor, and both share one objective.
    """

    if len(solves) not in (2, 3):
        raise ProtocolRefusal(f"The window solved {len(solves)} models; expected two or three.")
    hold, primary = solves[0], solves[1]
    if hold.parameters["max_deterministic_time"] != 1.0:
        raise ProtocolRefusal("The first solve is not the hold probe's one-unit budget.")
    if len(hold.proto.variables) != len(primary.proto.variables):
        raise ProtocolRefusal("The hold probe and the primary have different variables.")
    if user_objective(hold.proto) != user_objective(primary.proto):
        raise ProtocolRefusal("The hold probe and the primary have different objectives.")
    base = len(hold.proto.constraints) - window
    fixings = range(base, len(hold.proto.constraints))
    if base < 0 or not all(_is_fixed_to_zero(hold.proto, index) for index in fixings):
        raise ProtocolRefusal("The hold probe's last constraints are not the week fixings.")
    extra = len(primary.proto.constraints) - base
    floor_value: int | None = None
    if extra == 1:
        floor_value = _floor(primary.proto, base)
        if floor_value is None:
            raise ProtocolRefusal("The primary's extra constraint is not the hold floor.")
    elif extra != 0:
        raise ProtocolRefusal(f"The primary has {extra} constraints beyond the base.")
    # The planner floors the primary when the probe proved the hold plan, or found one
    # with its whole unit spent (``planning/optimizer.py``); otherwise it adds nothing.
    floored = hold.status == "OPTIMAL" or (
        hold.status == "FEASIBLE"
        and hold.deterministic_time >= 1.0 - MIN_TIEBREAK_DETERMINISTIC_TIME
    )
    if (floor_value is not None) != floored:
        raise ProtocolRefusal("The hold floor does not follow the hold probe's result.")
    if floor_value is not None and floor_value != round(hold.objective_value or 0):
        raise ProtocolRefusal("The hold floor is not the hold probe's value.")
    for index in range(base):
        if _constraint_text(hold.proto, index) != _constraint_text(primary.proto, index):
            raise ProtocolRefusal(f"Constraint {index} differs between hold and primary.")
    return WindowSolves(
        hold=hold,
        primary=primary,
        tiebreak=solves[2] if len(solves) == 3 else None,
        base_constraints=base,
        floor_value=floor_value,
    )


def proto_prefix(proto: Any, constraints: int) -> Any:
    """A copy of ``proto`` keeping its first ``constraints`` constraints, without hints."""

    target = type(proto)()
    for variable in proto.variables:
        target.variables.add().copy_from(variable)
    for index, constraint in enumerate(proto.constraints):
        if index >= constraints:
            break
        target.constraints.add().copy_from(constraint)
    if proto.has_objective():
        target.objective.copy_from(proto.objective)
    if proto.has_floating_point_objective():
        target.floating_point_objective.copy_from(proto.floating_point_objective)
    target.clear_solution_hint()
    return target


# --------------------------------------------------------------------------------------
# The exporter: a CpModelProto as a MILP, written as free-format MPS.


@dataclass(frozen=True)
class Column:
    name: str
    lower: int
    upper: int


@dataclass(frozen=True)
class Row:
    name: str
    terms: Mapping[int, int]
    lower: int | None
    upper: int | None


@dataclass(frozen=True)
class Auxiliary:
    """A column the exporter added, and how a CP-SAT assignment decides its value."""

    column: int
    kind: str
    constraint: int
    position: int


@dataclass
class Milp:
    """An all-integer MILP whose first ``variables`` columns are the CP-SAT variables."""

    name: str
    columns: list[Column]
    rows: list[Row]
    objective: dict[int, int | float]
    objective_offset: int | float
    maximize: bool
    variables: int
    auxiliaries: list[Auxiliary] = field(default_factory=list)
    kinds: dict[str, int] = field(default_factory=dict)


Expr = tuple[dict[int, int], int]

HANDLED_KINDS: Final = (
    "linear",
    "bool_or",
    "bool_and",
    "at_most_one",
    "exactly_one",
    "lin_max",
    "element",
)
REFUSED_KINDS: Final = (
    "bool_xor",
    "int_div",
    "int_mod",
    "int_prod",
    "all_diff",
    "table",
    "automaton",
    "inverse",
    "reservoir",
    "interval",
    "no_overlap",
    "no_overlap_2d",
    "cumulative",
    "circuit",
    "routes",
    "dummy_constraint",
)


def constraint_kind(constraint: Any) -> str:
    """The constraint's kind, by the field it sets."""

    for kind in (*HANDLED_KINDS, *REFUSED_KINDS):
        if getattr(constraint, f"has_{kind}")():
            return kind
    raise ExportRefused("A constraint sets no kind this exporter knows.")


def _add(left: Expr, right: Expr, factor: int = 1) -> Expr:
    terms = dict(left[0])
    for var, coeff in right[0].items():
        terms[var] = terms.get(var, 0) + factor * coeff
    return {var: coeff for var, coeff in terms.items() if coeff != 0}, left[1] + factor * right[1]


def _exact(value: int, what: str) -> int:
    if abs(value) >= EXACT_LIMIT:
        raise ExportRefused(f"{what} is {value}, beyond what a double holds exactly.")
    return value


class _Exporter:
    def __init__(self, proto: Any, name: str) -> None:
        self.proto = proto
        self.columns: list[Column] = []
        self.rows: list[Row] = []
        self.auxiliaries: list[Auxiliary] = []
        self.kinds: dict[str, int] = {}
        self.name = name

    def bounds_of(self, var: int) -> tuple[int, int]:
        column = self.columns[var]
        return column.lower, column.upper

    def range_of(self, expr: Expr) -> tuple[int, int]:
        low = high = expr[1]
        for var, coeff in expr[0].items():
            lower, upper = self.bounds_of(var)
            low += coeff * (lower if coeff > 0 else upper)
            high += coeff * (upper if coeff > 0 else lower)
        return low, high

    def literal(self, literal: int) -> Expr:
        var = literal if literal >= 0 else -literal - 1
        if self.bounds_of(var)[0] < 0 or self.bounds_of(var)[1] > 1:
            raise ExportRefused(f"Literal {literal} names variable {var}, which is not Boolean.")
        return ({var: 1}, 0) if literal >= 0 else ({var: -1}, 1)

    def linear_expr(self, message: Any) -> Expr:
        terms: dict[int, int] = {}
        for var, coeff in zip(message.vars, message.coeffs, strict=True):
            if var < 0:
                raise ExportRefused("A linear term names a negated variable reference.")
            terms[int(var)] = terms.get(int(var), 0) + int(coeff)
        offset = int(getattr(message, "offset", 0))
        return {var: coeff for var, coeff in terms.items() if coeff != 0}, offset

    def row(
        self, name: str, terms: Mapping[int, int], lower: int | None, upper: int | None
    ) -> None:
        if lower is None and upper is None:
            return
        for coeff in terms.values():
            _exact(coeff, f"A coefficient of row {name}")
        for bound in (lower, upper):
            if bound is not None:
                _exact(bound, f"A bound of row {name}")
        self.rows.append(Row(name, dict(terms), lower, upper))

    def auxiliary(self, kind: str, constraint: int, position: int) -> int:
        column = len(self.columns)
        self.columns.append(Column(f"a{len(self.auxiliaries)}", 0, 1))
        self.auxiliaries.append(Auxiliary(column, kind, constraint, position))
        return column

    def bounded(
        self,
        name: str,
        expr: Expr,
        lower: int | None,
        upper: int | None,
        enforcement: Sequence[int],
    ) -> None:
        """``lower <= expr <= upper``, holding only when every enforcement literal is true."""

        terms, constant = expr
        if not enforcement:
            self.row(
                name,
                terms,
                None if lower is None else lower - constant,
                None if upper is None else upper - constant,
            )
            return
        literals: Expr = ({}, 0)
        for literal in enforcement:
            literals = _add(literals, self.literal(literal))
        count = len(enforcement)
        low, high = self.range_of(expr)
        if upper is not None and upper < high:
            big = high - upper
            row_terms, row_constant = _add(expr, literals, big)
            self.row(f"{name}_up", row_terms, None, upper + big * count - row_constant)
        if lower is not None and lower > low:
            big = lower - low
            row_terms, row_constant = _add(expr, literals, -big)
            self.row(f"{name}_lo", row_terms, lower - big * count - row_constant, None)

    def count(self, kind: str) -> None:
        self.kinds[kind] = self.kinds.get(kind, 0) + 1

    def constraint(self, index: int, constraint: Any) -> None:
        kind = constraint_kind(constraint)
        enforcement = [int(literal) for literal in constraint.enforcement_literal]
        self.count(f"{kind} (enforced)" if enforcement else kind)
        name = f"c{index}"
        if kind == "linear":
            domain = [int(value) for value in constraint.linear.domain]
            if len(domain) != 2:
                raise ExportRefused(f"Linear constraint {index} has a domain with holes.")
            lower = None if domain[0] <= INT64_MIN else domain[0]
            upper = None if domain[1] >= INT64_MAX else domain[1]
            self.bounded(name, self.linear_expr(constraint.linear), lower, upper, enforcement)
        elif kind in ("bool_or", "at_most_one", "exactly_one"):
            literals = getattr(constraint, kind).literals
            total: Expr = ({}, 0)
            for literal in literals:
                total = _add(total, self.literal(int(literal)))
            lower = 1 if kind in ("bool_or", "exactly_one") else None
            upper = 1 if kind in ("at_most_one", "exactly_one") else None
            self.bounded(name, total, lower, upper, enforcement)
        elif kind == "bool_and":
            for position, literal in enumerate(constraint.bool_and.literals):
                self.bounded(f"{name}_{position}", self.literal(int(literal)), 1, None, enforcement)
        elif enforcement:
            raise ExportRefused(f"Constraint {index} is an enforced {kind}.")
        elif kind == "lin_max":
            self.lin_max(index, constraint.lin_max)
        elif kind == "element":
            self.element(index, constraint.element)
        else:
            raise ExportRefused(f"Constraint {index} is a {kind} constraint, which is not handled.")

    def lin_max(self, index: int, message: Any) -> None:
        target = self.linear_expr(message.target)
        exprs = [self.linear_expr(expr) for expr in message.exprs]
        name = f"c{index}"
        if not exprs:
            raise ExportRefused(f"Maximum constraint {index} has no expressions.")
        if len(exprs) == 1:
            terms, constant = _add(target, exprs[0], -1)
            self.row(f"{name}_eq", terms, -constant, -constant)
            return
        chosen = [self.auxiliary("lin_max", index, position) for position in range(len(exprs))]
        for position, expr in enumerate(exprs):
            terms, constant = _add(target, expr, -1)
            self.row(f"{name}_ge{position}", terms, -constant, None)
            big = max(0, self.range_of((terms, constant))[1])
            with_choice = dict(terms)
            with_choice[chosen[position]] = big
            self.row(f"{name}_le{position}", with_choice, None, big - constant)
        self.row(f"{name}_one", dict.fromkeys(chosen, 1), 1, 1)

    def element(self, index: int, message: Any) -> None:
        name = f"c{index}"
        if message.has_linear_index() or len(message.exprs) > 0:
            selector = self.linear_expr(message.linear_index)
            target = self.linear_expr(message.linear_target)
            exprs = [self.linear_expr(expr) for expr in message.exprs]
        else:
            if message.index < 0 or message.target < 0 or any(v < 0 for v in message.vars):
                raise ExportRefused(f"Element constraint {index} names a negated reference.")
            selector = ({int(message.index): 1}, 0)
            target = ({int(message.target): 1}, 0)
            exprs = [({int(var): 1}, 0) for var in message.vars]
        low, high = self.range_of(selector)
        positions = [k for k in range(len(exprs)) if low <= k <= high]
        if not positions:
            raise ExportRefused(f"Element constraint {index} has no index its domain allows.")
        chosen = {k: self.auxiliary("element", index, k) for k in positions}
        self.row(f"{name}_one", dict.fromkeys(chosen.values(), 1), 1, 1)
        terms = dict(selector[0])
        for k, column in chosen.items():
            terms[column] = terms.get(column, 0) - k
        self.row(f"{name}_index", terms, -selector[1], -selector[1])
        if all(not exprs[k][0] for k in positions):
            terms = dict(target[0])
            for k, column in chosen.items():
                terms[column] = terms.get(column, 0) - exprs[k][1]
            self.row(f"{name}_target", terms, -target[1], -target[1])
            return
        for k, column in chosen.items():
            difference = _add(target, exprs[k], -1)
            low_d, high_d = self.range_of(difference)
            above = max(0, high_d)
            below = max(0, -low_d)
            terms_d, constant = difference
            up = dict(terms_d)
            up[column] = up.get(column, 0) + above
            self.row(f"{name}_up{k}", up, None, above - constant)
            down = dict(terms_d)
            down[column] = down.get(column, 0) - below
            self.row(f"{name}_lo{k}", down, -below - constant, None)

    def build(self) -> Milp:
        proto = self.proto
        if len(proto.assumptions) > 0:
            raise ExportRefused("The model carries assumptions.")
        for index, variable in enumerate(proto.variables):
            domain = [int(value) for value in variable.domain]
            if len(domain) != 2:
                raise ExportRefused(
                    f"Variable {index} ({variable.name!r}) has a domain with holes: {domain}."
                )
            lower = _exact(domain[0], f"Variable {index}'s lower bound")
            upper = _exact(domain[1], f"Variable {index}'s upper bound")
            self.columns.append(Column(f"x{index}", lower, upper))
        variables = len(self.columns)
        objective, offset, maximize = user_objective(proto)
        for var, coeff in objective.items():
            # A coefficient is written as it is and read by HiGHS as a double, so it is
            # held to the same limit as every row coefficient, bound and domain.
            if abs(coeff) >= EXACT_LIMIT:
                raise ExportRefused(
                    f"The objective coefficient of variable {var} is {coeff}, beyond what a "
                    "double holds exactly."
                )
        for index, constraint in enumerate(proto.constraints):
            self.constraint(index, constraint)
        return Milp(
            name=self.name,
            columns=self.columns,
            rows=self.rows,
            objective=dict(objective),
            objective_offset=offset,
            maximize=maximize,
            variables=variables,
            auxiliaries=self.auxiliaries,
            kinds=dict(sorted(self.kinds.items())),
        )


def export_milp(proto: Any, name: str = "model") -> Milp:
    """Translate a CP-SAT model into an equivalent all-integer MILP, or refuse."""

    return _Exporter(proto, name).build()


def _number(value: int | float) -> str:
    if isinstance(value, int):
        return str(value)
    if value.is_integer() and abs(value) < EXACT_LIMIT:
        return str(int(value))
    return repr(value)


def write_mps(milp: Milp) -> str:
    """Free-format MPS: every column integer, every bound explicit, no objective constant."""

    lines = [f"NAME {milp.name}", "OBJSENSE", "    MAX" if milp.maximize else "    MIN"]
    lines += ["ROWS", " N  OBJ"]
    ranges: list[tuple[str, int]] = []
    rhs: list[tuple[str, int]] = []
    for row in milp.rows:
        if row.lower is not None and row.upper is not None and row.lower == row.upper:
            lines.append(f" E  {row.name}")
            rhs.append((row.name, row.lower))
        elif row.lower is None:
            lines.append(f" L  {row.name}")
            rhs.append((row.name, cast(int, row.upper)))
        else:
            lines.append(f" G  {row.name}")
            rhs.append((row.name, row.lower))
            if row.upper is not None:
                ranges.append((row.name, row.upper - row.lower))
    entries: list[list[tuple[str, int | float]]] = [[] for _ in milp.columns]
    for var, coeff in milp.objective.items():
        if coeff != 0:
            entries[var].append(("OBJ", coeff))
    for row in milp.rows:
        for var, coeff in row.terms.items():
            if coeff != 0:
                entries[var].append((row.name, coeff))
    lines += ["COLUMNS", "    MARKER  'MARKER'  'INTORG'"]
    for column, column_entries in zip(milp.columns, entries, strict=True):
        if not column_entries:
            lines.append(f"    {column.name}  OBJ  0")
        for row_name, coeff in column_entries:
            lines.append(f"    {column.name}  {row_name}  {_number(coeff)}")
    lines.append("    MARKER  'MARKER'  'INTEND'")
    lines.append("RHS")
    lines += [f"    RHS  {name}  {_number(value)}" for name, value in rhs if value != 0]
    if ranges:
        lines.append("RANGES")
        lines += [f"    RNG  {name}  {_number(value)}" for name, value in ranges]
    lines.append("BOUNDS")
    for column in milp.columns:
        if (column.lower, column.upper) == (0, 1):
            lines.append(f" BV BND  {column.name}")
        else:
            lines.append(f" LI BND  {column.name}  {column.lower}")
            lines.append(f" UI BND  {column.name}  {column.upper}")
    lines.append("ENDATA")
    return "\n".join(lines) + "\n"


@dataclass
class ParsedMps:
    """What an MPS file states, read back by name."""

    name: str
    maximize: bool
    column_names: list[str]
    lower: list[float]
    upper: list[float]
    integer: list[bool]
    row_names: list[str]
    row_lower: list[float]
    row_upper: list[float]
    rows: list[dict[int, int | float]]
    objective: dict[int, int | float]

    def column(self, name: str) -> int:
        return self.column_names.index(name)


def _parse_number(text: str) -> int | float:
    try:
        return int(text)
    except ValueError:
        return float(text)


def read_mps(text: str) -> ParsedMps:
    """Read the free-format MPS this module writes (and the common subset around it)."""

    name = ""
    maximize = False
    section = ""
    objective_row = ""
    row_types: dict[str, str] = {}
    row_order: list[str] = []
    rhs: dict[str, int | float] = {}
    ranges: dict[str, int | float] = {}
    columns: dict[str, int] = {}
    column_names: list[str] = []
    lower: list[float] = []
    upper: list[float] = []
    integer: list[bool] = []
    entries: dict[str, dict[int, int | float]] = {}
    objective: dict[int, int | float] = {}
    in_integer_block = False
    for raw in text.splitlines():
        if not raw.strip() or raw.startswith("*"):
            continue
        tokens = raw.split()
        if not raw[0].isspace():
            section = tokens[0]
            if section == "NAME":
                name = tokens[1] if len(tokens) > 1 else ""
            elif section == "OBJSENSE" and len(tokens) > 1:
                maximize = tokens[1].upper() in ("MAX", "MAXIMIZE")
            elif section == "ENDATA":
                break
            continue
        if section == "OBJSENSE":
            maximize = tokens[0].upper() in ("MAX", "MAXIMIZE")
        elif section == "ROWS":
            kind, row = tokens[0].upper(), tokens[1]
            if kind == "N":
                objective_row = objective_row or row
                continue
            row_types[row] = kind
            row_order.append(row)
            entries[row] = {}
        elif section == "COLUMNS":
            if len(tokens) >= 3 and tokens[1] == "'MARKER'":
                in_integer_block = tokens[2] == "'INTORG'"
                continue
            column = tokens[0]
            if column not in columns:
                columns[column] = len(column_names)
                column_names.append(column)
                lower.append(0.0)
                upper.append(math.inf)
                integer.append(in_integer_block)
            j = columns[column]
            for row, text in zip(tokens[1::2], tokens[2::2], strict=True):
                number = _parse_number(text)
                if row == objective_row:
                    objective[j] = number
                elif row in entries:
                    entries[row][j] = number
                else:
                    raise ExportRefused(f"Column {column} names an undeclared row {row}.")
        elif section in ("RHS", "RANGES"):
            target = rhs if section == "RHS" else ranges
            pairs = tokens[1:] if len(tokens) % 2 == 1 else tokens
            for row, text in zip(pairs[0::2], pairs[1::2], strict=True):
                target[row] = _parse_number(text)
        elif section == "BOUNDS":
            kind, column = tokens[0].upper(), tokens[2]
            j = columns[column]
            bound = float(tokens[3]) if len(tokens) > 3 else 0.0
            if kind in ("LO", "LI"):
                lower[j] = bound
            elif kind in ("UP", "UI"):
                upper[j] = bound
            elif kind == "FX":
                lower[j] = upper[j] = bound
            elif kind == "FR":
                lower[j], upper[j] = -math.inf, math.inf
            elif kind == "MI":
                lower[j] = -math.inf
            elif kind == "PL":
                upper[j] = math.inf
            elif kind == "BV":
                lower[j], upper[j] = 0.0, 1.0
            else:
                raise ExportRefused(f"Bound type {kind} is not read.")
            if kind in ("LI", "UI", "BV"):
                integer[j] = True
    row_lower: list[float] = []
    row_upper: list[float] = []
    for row in row_order:
        kind = row_types[row]
        level = float(rhs.get(row, 0))
        span = ranges.get(row)
        if kind == "E":
            low = high = level
            if span is not None:
                low, high = (
                    (level, level + float(span)) if span > 0 else (level + float(span), level)
                )
        elif kind == "L":
            low, high = -math.inf, level
            if span is not None:
                low = level - abs(float(span))
        else:
            low, high = level, math.inf
            if span is not None:
                high = level + abs(float(span))
        row_lower.append(low)
        row_upper.append(high)
    return ParsedMps(
        name=name,
        maximize=maximize,
        column_names=column_names,
        lower=lower,
        upper=upper,
        integer=integer,
        row_names=row_order,
        row_lower=row_lower,
        row_upper=row_upper,
        rows=[entries[row] for row in row_order],
        objective=objective,
    )


# --------------------------------------------------------------------------------------
# The two checks.


def _expr_value(expr: Expr, values: Sequence[int]) -> int:
    return expr[1] + sum(coeff * values[var] for var, coeff in expr[0].items())


def cp_sat_assignment(milp: Milp, proto: Any, solution: Sequence[int]) -> list[int] | None:
    """A CP-SAT solution on the MILP's columns, each auxiliary derived; None if one cannot be."""

    if len(solution) != milp.variables:
        raise ProtocolRefusal("The solution does not name every CP-SAT variable.")
    values = [int(value) for value in solution]
    exporter = _Exporter(proto, milp.name)
    for auxiliary in milp.auxiliaries:
        constraint = proto.constraints[auxiliary.constraint]
        if auxiliary.kind == "lin_max":
            target = exporter.linear_expr(constraint.lin_max.target)
            exprs = [exporter.linear_expr(e) for e in constraint.lin_max.exprs]
            achieved = _expr_value(target, values)
            first = next(
                (k for k, expr in enumerate(exprs) if _expr_value(expr, values) == achieved), None
            )
            if first is None:
                return None
            values.append(int(first == auxiliary.position))
        else:
            element = constraint.element
            if element.has_linear_index() or len(element.exprs) > 0:
                selector = exporter.linear_expr(element.linear_index)
            else:
                selector = ({int(element.index): 1}, 0)
            values.append(int(_expr_value(selector, values) == auxiliary.position))
    return values


@dataclass(frozen=True)
class Evaluation:
    violations: tuple[str, ...]
    worst: float
    objective: int | float


def evaluate(parsed: ParsedMps, values: Sequence[int | float], tolerance: float) -> Evaluation:
    """Every column bound and row of ``parsed`` at ``values``, and the objective there."""

    violations: list[str] = []
    worst = 0.0
    for j, value in enumerate(values):
        excess = max(parsed.lower[j] - value, value - parsed.upper[j], 0.0)
        worst = max(worst, float(excess))
        if excess > tolerance:
            violations.append(f"column {parsed.column_names[j]} = {value}")
    for r, terms in enumerate(parsed.rows):
        activity = sum(coeff * values[j] for j, coeff in terms.items())
        excess = max(parsed.row_lower[r] - activity, activity - parsed.row_upper[r], 0.0)
        worst = max(worst, float(excess))
        if excess > tolerance:
            violations.append(f"row {parsed.row_names[r]}: activity {activity}")
    objective = sum(coeff * values[j] for j, coeff in parsed.objective.items())
    return Evaluation(tuple(violations[:20]), worst, objective)


def _values_by_name(parsed: ParsedMps, milp: Milp, values: Sequence[int]) -> list[int]:
    by_name = {column.name: values[j] for j, column in enumerate(milp.columns)}
    return [by_name[name] for name in parsed.column_names]


def check_one(
    milp: Milp,
    parsed: ParsedMps,
    proto: Any,
    solution: Sequence[int],
    objective_value: float,
) -> dict[str, Any]:
    """Check 1: CP-SAT's solution satisfies every row of the MPS and gives its value."""

    assignment = cp_sat_assignment(milp, proto, solution)
    if assignment is None:
        return {"passed": False, "reason": "an auxiliary could not be derived"}
    evaluation = evaluate(parsed, _values_by_name(parsed, milp, assignment), ROW_TOLERANCE)
    value = evaluation.objective + milp.objective_offset
    same = _same_value(value, objective_value)
    return {
        "passed": not evaluation.violations and same,
        "rows": len(parsed.rows),
        "columns": len(parsed.column_names),
        "worst_violation": evaluation.worst,
        "violations": list(evaluation.violations),
        "mps_value": value,
        "cp_sat_value": objective_value,
        "same_value": same,
    }


def _same_value(left: int | float, right: int | float) -> bool:
    if float(left).is_integer() and float(right).is_integer():
        return round(left) == round(right)
    return abs(left - right) <= 1e-6 * max(1.0, abs(left), abs(right))


def cp_sat_value(proto: Any, values: Sequence[int]) -> int | float:
    """The model's own objective at ``values``, exactly."""

    objective, offset, _ = user_objective(proto)
    return offset + sum(coeff * values[var] for var, coeff in objective.items())


def check_two(
    milp: Milp,
    parsed: ParsedMps,
    proto: Any,
    column_values: Sequence[float],
    *,
    reported_objective: float | None = None,
) -> dict[str, Any]:
    """Check 2: a MILP solution, rounded and fixed in the CP-SAT model, is feasible there
    and gives the value the MPS objective gives at the same rounded point."""

    rounded = [round(value) for value in column_values]
    distance = max((abs(v - r) for v, r in zip(column_values, rounded, strict=True)), default=0.0)
    by_name = dict(zip(parsed.column_names, rounded, strict=True))
    cp_values = [by_name[milp.columns[var].name] for var in range(milp.variables)]
    model = cp_model.CpModel()
    model.proto.copy_from(proto)
    model.proto.clear_solution_hint()
    for var, value in enumerate(cp_values):
        domain = model.proto.variables[var].domain
        domain.clear()
        domain.extend([value, value])
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    solver.parameters.max_time_in_seconds = FIXED_CHECK_SECONDS
    status = solver.solve(model)
    name = str(getattr(status, "name", status))
    feasible = name in ("OPTIMAL", "FEASIBLE")
    mps_value = (
        sum(coeff * rounded[j] for j, coeff in parsed.objective.items()) + milp.objective_offset
    )
    exact = cp_sat_value(proto, cp_values)
    same = feasible and _same_value(exact, mps_value) and _same_value(solver.objective_value, exact)
    return {
        "passed": feasible and same,
        "cp_sat_status": name,
        "rounding_distance": float(distance),
        "value": exact,
        "mps_value": mps_value,
        "reported_objective": reported_objective,
    }


# --------------------------------------------------------------------------------------
# One instance: the planner's solves, the export, check 1.


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


@dataclass
class Instance:
    entry_id: int
    window: int
    call: PlannerCall
    plan: TransferPlanResult
    solves: WindowSolves
    hold_milp: Milp | None = None
    primary_milp: Milp | None = None
    hold_mps: Path | None = None
    primary_mps: Path | None = None
    primary_proto: Any = None
    export: dict[str, Any] = field(default_factory=dict)
    #: The planner call's wall time, its solves and the capture's copies included.
    call_seconds: float | None = None

    @property
    def model_build_seconds(self) -> float | None:
        """The call's time outside its captured solves and the capture's model copies."""

        if self.call_seconds is None:
            return None
        solves = self.solves
        captured = [solves.hold, solves.primary]
        if solves.tiebreak is not None:
            captured.append(solves.tiebreak)
        return self.call_seconds - sum(solve.seconds + solve.copy_seconds for solve in captured)


def solve_instance(inputs: PublishedInputs, entry_id: int, window: int) -> Instance:
    """Run the planner's own path on one window and name its solves."""

    call = window_call(inputs, entry_id, window)
    refuse_blocked_day_for(call)
    with capture_cp_sat_solves() as solves:
        started = perf_counter()
        plan = call.solve()
        call_seconds = perf_counter() - started
    instance = Instance(entry_id, window, call, plan, identify_window_solves(solves, window))
    instance.call_seconds = call_seconds
    return instance


def cp_sat_record(instance: Instance, *, with_time: bool) -> dict[str, Any]:
    """The CP-SAT side of an instance, on the integer scale and in points."""

    solves = instance.solves
    divisor = objective_divisor(instance.call)
    primary = solves.primary
    limit = float(primary.parameters["max_deterministic_time"])
    stopped_by_wall = (
        primary.status != "OPTIMAL"
        and primary.deterministic_time < limit - MIN_TIEBREAK_DETERMINISTIC_TIME
    )
    value = solves.primary_value
    bound = None if primary.best_bound is None else round(primary.best_bound)
    record: dict[str, Any] = {
        "plan_status": instance.plan.solver_status.name,
        "hold_status": solves.hold.status,
        "hold_value": solves.floor_value,
        "primary_status": primary.status,
        "proved": primary.status == "OPTIMAL",
        "stopped_by_wall_ceiling": stopped_by_wall,
        "value": value,
        "value_points": None if value is None else value / divisor,
        "bound": bound,
        "gap_units": None if bound is None or value is None else bound - value,
        "gap_points": None if bound is None or value is None else (bound - value) / divisor,
        "hold_deterministic_time": solves.hold.deterministic_time,
        "primary_deterministic_time": primary.deterministic_time,
        "primary_parameters": dict(primary.parameters),
        "tiebreak_status": None if solves.tiebreak is None else solves.tiebreak.status,
    }
    if with_time:
        record["hold_seconds"] = solves.hold.seconds
        record["primary_seconds"] = primary.seconds
        record["seconds"] = solves.hold.seconds + primary.seconds
        record["model_build_seconds"] = instance.model_build_seconds
    return record


def wall_matched_budget(cp_sat: Mapping[str, Any]) -> float:
    """The wall-matched HiGHS budget: CP-SAT's hold and primary time on the reference run,
    or the 1,800 s ceiling when the wall ceiling stopped CP-SAT (the protocol's "Time")."""

    if cp_sat["stopped_by_wall_ceiling"]:
        return float(WINDOW_WALL_CEILING_SECONDS)
    return float(cp_sat["seconds"])


def export_instance(instance: Instance, out_dir: Path) -> dict[str, Any]:
    """Write the hold and primary models as MPS, read them back and run check 1 on both."""

    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{instance.entry_id}-w{instance.window}"
    solves = instance.solves
    primary_proto = solves.export_primary
    record: dict[str, Any] = {}
    for part, proto, solve in (
        ("hold", solves.hold.proto, solves.hold),
        ("primary", primary_proto, solves.primary if solves.primary.has_solution else solves.hold),
    ):
        milp = export_milp(proto, f"{stem}-{part}")
        path = out_dir / f"{stem}-{part}.mps"
        path.write_text(write_mps(milp), encoding="utf-8")
        parsed = read_mps(path.read_text(encoding="utf-8"))
        if not solve.has_solution or solve.objective_value is None:
            check: dict[str, Any] = {"passed": False, "reason": "CP-SAT returned no solution"}
        else:
            check = check_one(milp, parsed, proto, solve.solution, solve.objective_value)
        check["solution_from"] = "hold probe" if solve is solves.hold else "primary"
        record[part] = {
            "mps": path.relative_to(REPOSITORY_ROOT).as_posix()
            if path.is_relative_to(REPOSITORY_ROOT)
            else str(path),
            "sha256": _sha256(path),
            "columns": len(milp.columns),
            "cp_sat_variables": milp.variables,
            "auxiliary_columns": len(milp.auxiliaries),
            "rows": len(milp.rows),
            "objective_offset": milp.objective_offset,
            "maximize": milp.maximize,
            "constraint_kinds": milp.kinds,
            "check_1": check,
        }
        if part == "hold":
            instance.hold_milp, instance.hold_mps = milp, path
        else:
            instance.primary_milp, instance.primary_mps = milp, path
    instance.primary_proto = primary_proto
    assert instance.hold_milp is not None and instance.primary_milp is not None
    if instance.hold_milp.columns != instance.primary_milp.columns:
        raise ProtocolRefusal("The hold and primary MPS do not share their columns.")
    record["hold_floor_dropped"] = solves.floor_value is not None
    record["check_1_passed"] = bool(record["hold"]["check_1"]["passed"]) and bool(
        record["primary"]["check_1"]["passed"]
    )
    instance.export = record
    return record


# --------------------------------------------------------------------------------------
# The published three-week plans, valued on the measured model (a comparison, not a gate).


def _best_lineup(rows: Sequence[tuple[str, int, int]], settings: OptimizationConfig) -> int:
    """The best eleven's starter value plus its captain, over every legal formation."""

    by_position: dict[str, list[tuple[int, int]]] = {}
    for position, starter, captain in rows:
        by_position.setdefault(position, []).append((starter, captain))
    for players in by_position.values():
        players.sort(reverse=True)
    positions = sorted(settings.starting_position_min)
    best: int | None = None

    def choose(index: int, chosen: dict[str, int]) -> None:
        nonlocal best
        if index == len(positions):
            if sum(chosen.values()) != settings.starting_size:
                return
            eleven = [p for position, n in chosen.items() for p in by_position[position][:n]]
            value = sum(s for s, _ in eleven) + max(c for _, c in eleven)
            best = value if best is None else max(best, value)
            return
        position = positions[index]
        available = len(by_position.get(position, []))
        low = settings.starting_position_min[position]
        high = min(settings.starting_position_max[position], available)
        for count in range(low, high + 1):
            choose(index + 1, {**chosen, position: count})

    choose(0, {})
    if best is None:
        raise ProtocolRefusal("A published squad admits no legal eleven.")
    return best


def published_plan_value(call: PlannerCall, published: Mapping[str, Any]) -> dict[str, Any]:
    """The published plan's transfers, valued under the measured model's objective."""

    settings = OptimizationConfig()
    table = call.horizon.table
    weeks = sorted(int(week) for week in table["gameweek"].unique())
    plan_weeks = published["plan_weeks"]
    if [int(row["gameweek"]) for row in plan_weeks] != weeks:
        raise ProtocolRefusal("The published plan covers other gameweeks than the window.")
    hit = scale_expected_points(
        call.policy.transfer_hit_cost_points, settings.expected_points_scale
    )
    squad = set(call.state.squad_player_ids)
    free = call.state.free_transfers
    total = 0
    paid_total = 0
    for offset, (week, row) in enumerate(zip(weeks, plan_weeks, strict=True)):
        incoming = {int(p["player_id"]) for p in row["transfers_in"]}
        outgoing = {int(p["player_id"]) for p in row["transfers_out"]}
        squad = (squad - outgoing) | incoming
        count = len(incoming)
        paid = max(count - free, 0)
        free = min(
            max(free - count, 0) + call.policy.free_transfer_accrual, call.policy.max_free_transfers
        )
        frame = table.loc[(table["gameweek"] == week) & table["player_id"].isin(squad)]
        if len(frame) != settings.squad_size:
            raise ProtocolRefusal(f"The published GW{week} squad is not fifteen known players.")
        coefficients = objective_coefficients(frame["expected_points"].tolist(), settings)
        bench = sum(c[0] for c in coefficients)
        lineup = _best_lineup(
            [
                (str(position), c[1], c[2])
                for position, c in zip(frame["position"].tolist(), coefficients, strict=True)
            ],
            settings,
        )
        weight = round_half_up(
            Decimal(str(call.policy.horizon_discount_factor)) ** offset
            * Decimal(call.policy.objective_weight_scale)
        )
        total += weight * (bench + lineup) - weight * hit * paid
        paid_total += paid
    return {
        "value": total,
        "value_points": total / objective_divisor(call),
        "paid_transfers_under_measured_model": paid_total,
        "published_status": published.get("solver_status"),
    }


# --------------------------------------------------------------------------------------
# Guards.


def refuse_blocked_date(now: datetime, seconds: float = 0.0) -> None:
    """No solve runs on 9 or 10 October (UTC): none starts on either day, and none starts
    whose ``seconds`` of wall stops could carry it into either."""

    start = now.astimezone(UTC)
    end = start + timedelta(seconds=max(float(seconds), 0.0))
    day = start.date()
    while day <= end.date():
        if (day.month, day.day) in BLOCKED_DAYS:
            if day == start.date():
                raise ProtocolRefusal(
                    f"It is {day.isoformat()} UTC; the protocol runs no solve on 9 or 10 October."
                )
            raise ProtocolRefusal(
                f"A solve started at {start.isoformat(timespec='seconds')} may run until "
                f"{end.isoformat(timespec='seconds')}, into {day.isoformat()} UTC; the "
                "protocol runs no solve on 9 or 10 October."
            )
        day += timedelta(days=1)


def native_core_version() -> str:
    """The HiGHS core version the native build reports."""

    highspy = importlib.import_module("highspy")
    return _native_version(highspy)


def _native_version(highspy: Any) -> str:
    highs = highspy.Highs()
    try:
        return str(highs.version())
    except AttributeError:
        return f"{highs.versionMajor()}.{highs.versionMinor()}.{highs.versionPatch()}"


def wasm_report(node: str, web_dir: Path = WEB_DIR) -> dict[str, Any]:
    """What the wasm build reports when loaded as the device's tests load it."""

    return _run_wasm_driver(node, {"mode": "version"}, web_dir, timeout=300.0)


def measure_guards(
    *,
    have_slot: bool,
    now: datetime,
    native_version: Callable[[], str],
    wasm_version: Callable[[], Mapping[str, Any]],
) -> dict[str, Any]:
    """Refuse to measure unless every condition the protocol sets holds; else the versions."""

    if not have_slot:
        raise ProtocolRefusal(
            "Measuring needs the heavy-test slot on #632; claim it and pass --i-have-the-slot."
        )
    refuse_blocked_date(now)
    native = native_version()
    if native != HIGHS_CORE_VERSION:
        raise ProtocolRefusal(f"highspy reports HiGHS {native}; the protocol pins 1.15.3.")
    wasm = dict(wasm_version())
    if wasm.get("core_version") != HIGHS_CORE_VERSION:
        raise ProtocolRefusal(
            f"The highs package reports HiGHS {wasm.get('core_version')}; the protocol pins 1.15.3."
        )
    if wasm.get("core_version") != native:
        raise ProtocolRefusal("The native and wasm builds report different HiGHS versions.")
    node_version = str(wasm.get("node_version", ""))
    if not node_version.startswith(f"v{NODE_MAJOR}."):
        raise ProtocolRefusal(f"Node is {node_version or 'unknown'}; the protocol runs Node 22.")
    return {"native_core": native, "wasm": wasm}


# --------------------------------------------------------------------------------------
# HiGHS runs: native in a child Python process, wasm in Node. Neither takes CP-SAT's value.


def highs_options(time_limit: float) -> dict[str, float | bool | int]:
    return {
        "output_flag": False,
        "threads": HIGHS_THREADS,
        "mip_rel_gap": MIP_REL_GAP,
        "mip_abs_gap": MIP_ABS_GAP,
        "time_limit": max(float(time_limit), 0.0),
    }


def _option_value(highs: Any, name: str) -> Any:
    """An option as the native build reports it (older bindings return a status first)."""

    value = highs.getOptionValue(name)
    return value[-1] if isinstance(value, tuple) else value


def _native_solve(
    highspy: Any,
    path: str,
    budget: float,
    floor: tuple[int, Mapping[int, int | float]] | None,
) -> dict[str, Any]:
    numpy = importlib.import_module("numpy")
    highs = highspy.Highs()
    # Set before anything runs: the native build starts its scheduler on the first run.
    highs.setOptionValue("threads", HIGHS_THREADS)
    started = perf_counter()
    read_status = int(highs.readModel(path))
    read_seconds = perf_counter() - started
    if read_status < 0:
        raise RuntimeError(f"HiGHS could not read {path}.")
    for name, value in highs_options(budget).items():
        highs.setOptionValue(name, value)
    floor_seconds = 0.0
    if floor is not None:
        value, costs = floor
        started = perf_counter()
        indices = numpy.array(sorted(costs), dtype=numpy.int32)
        values = numpy.array([float(costs[j]) for j in sorted(costs)], dtype=numpy.float64)
        added = int(highs.addRow(float(value), highspy.kHighsInf, len(indices), indices, values))
        floor_seconds = perf_counter() - started
        if added < 0:
            raise RuntimeError("HiGHS refused the hold floor row.")
    started = perf_counter()
    highs.run()
    seconds = perf_counter() - started
    status = int(highs.getModelStatus())
    info = highs.getInfo()
    primal = int(info.primal_solution_status)
    result: dict[str, Any] = {
        "model_status": status,
        "read_seconds": read_seconds,
        "floor_seconds": floor_seconds,
        "seconds": seconds,
        "primal_solution_status": primal,
        "bound": float(info.mip_dual_bound),
        "threads": int(_option_value(highs, "threads")),
    }
    if primal == HIGHS_PRIMAL_FEASIBLE:
        result["objective"] = float(info.objective_function_value)
        result["solution"] = [float(value) for value in highs.getSolution().col_value]
    return result


def floor_value(solution: Sequence[float], costs: Mapping[int, int | float]) -> int:
    """The primary objective at a rounded hold solution: the floor a HiGHS primary gets."""

    return int(sum(cost * round(solution[j]) for j, cost in costs.items()))


def native_run(job: Mapping[str, Any]) -> dict[str, Any]:
    """One native HiGHS run of one instance: the hold model, then the floored primary."""

    budget = float(job["budget_seconds"])
    refuse_blocked_date(datetime.now(UTC), budget)
    started = perf_counter()
    highspy = importlib.import_module("highspy")
    load_seconds = perf_counter() - started
    costs = {int(j): cost for j, cost in job["objective"].items()}
    hold = _native_solve(highspy, str(job["hold_mps"]), budget, None)
    result: dict[str, Any] = {
        "build": "native",
        "core_version": _native_version(highspy),
        "load_seconds": load_seconds,
        "hold": {key: value for key, value in hold.items() if key != "solution"},
        "hold_solution": hold.get("solution"),
        "floor": None,
        "primary": None,
        "primary_solution": None,
    }
    if hold.get("solution") is not None:
        result["floor"] = floor_value(hold["solution"], costs)
    remaining = budget - float(hold["seconds"])
    if remaining <= 0:
        return result
    floor = None if result["floor"] is None else (int(result["floor"]), costs)
    primary = _native_solve(highspy, str(job["primary_mps"]), remaining, floor)
    result["primary"] = {key: value for key, value in primary.items() if key != "solution"}
    result["primary_solution"] = primary.get("solution")
    return result


#: The wasm driver. It loads the package from ``web/node_modules`` as the device's parity
#: tests do (the ESM entry and the wasm binary the package exports), reads each MPS through
#: the persistent API so the read is timed apart from the run, and floors the primary at
#: its own hold solution. It prints nothing; its answer is the JSON file it writes.
WASM_DRIVER: Final = r"""
import { readFileSync, writeFileSync } from "node:fs";
import { join } from "node:path";
import { pathToFileURL } from "node:url";
import { performance } from "node:perf_hooks";

const [, , webDir, jobPath, outPath] = process.argv;
const job = JSON.parse(readFileSync(jobPath, "utf8"));
const packageDir = join(webDir, "node_modules", "highs");
const manifest = JSON.parse(readFileSync(join(packageDir, "package.json"), "utf8"));
const started = performance.now();
const wasmBinary = readFileSync(join(packageDir, manifest.exports["./runtime"]));
const entry = pathToFileURL(join(packageDir, manifest.exports["."].import)).href;
const load = (await import(entry)).default;
const highs = await load({ wasmBinary });
const result = {
  build: "wasm",
  package_version: manifest.version,
  core_version: highs.version.string,
  node_version: process.version,
  load_seconds: (performance.now() - started) / 1000,
};

function info(model, name) {
  try { return Number(model.info.get(name)); } catch { return null; }
}

function option(model, name) {
  try {
    const value = Number(model.options.get(name));
    return Number.isFinite(value) ? value : null;
  } catch {
    return null;
  }
}

function solve(path, budget, floor) {
  const text = readFileSync(path, "utf8");
  const model = highs.createModel();
  try {
    let clock = performance.now();
    model.readModel({ format: "mps", data: text });
    const readSeconds = (performance.now() - clock) / 1000;
    model.options.set({ ...job.options, time_limit: Math.max(budget, 0) });
    let floorSeconds = 0;
    if (floor !== null) {
      clock = performance.now();
      const columns = Object.keys(job.objective).map(Number).sort((a, b) => a - b);
      const values = columns.map((j) => job.objective[String(j)]);
      model.addRow(floor, highs.infinity, { indices: columns, values });
      floorSeconds = (performance.now() - clock) / 1000;
    }
    clock = performance.now();
    model.run();
    const seconds = (performance.now() - clock) / 1000;
    const out = {
      model_status: model.getModelStatus(),
      read_seconds: readSeconds,
      floor_seconds: floorSeconds,
      seconds,
      primal_solution_status: info(model, "primal_solution_status"),
      bound: info(model, "mip_dual_bound"),
      threads: option(model, "threads"),
    };
    if (out.primal_solution_status === 2) {
      out.objective = model.getObjectiveValue();
      out.solution = Array.from(model.getSolution().colValue);
    }
    return out;
  } finally {
    model.dispose();
  }
}

if (job.mode === "solve") {
  const budget = job.budget_seconds;
  const hold = solve(job.hold_mps, budget, null);
  result.hold_solution = hold.solution ?? null;
  delete hold.solution;
  result.hold = hold;
  let floor = null;
  if (result.hold_solution !== null) {
    floor = 0;
    for (const [j, cost] of Object.entries(job.objective)) {
      floor += cost * Math.round(result.hold_solution[Number(j)]);
    }
  }
  result.floor = floor;
  result.primary = null;
  result.primary_solution = null;
  const remaining = budget - hold.seconds;
  if (remaining > 0) {
    const primary = solve(job.primary_mps, remaining, floor);
    result.primary_solution = primary.solution ?? null;
    delete primary.solution;
    result.primary = primary;
  }
}
writeFileSync(outPath, JSON.stringify(result));
"""


class DriverFailed(Exception):
    """A HiGHS child process ended without an answer: an error or a crash, not a proof."""


def _child(command: Sequence[str], out_path: Path, *, timeout: float) -> dict[str, Any]:
    out_path.unlink(missing_ok=True)
    try:
        completed = subprocess.run(
            list(command),
            timeout=timeout,
            capture_output=True,
            text=True,
            cwd=REPOSITORY_ROOT,
            check=False,
        )
    except (subprocess.SubprocessError, OSError) as error:
        raise DriverFailed(f"{type(error).__name__}: {error}") from error
    if completed.returncode != 0 or not out_path.is_file():
        raise DriverFailed(f"exit {completed.returncode}: {completed.stderr.strip()[-2000:]}")
    try:
        result: dict[str, Any] = json.loads(out_path.read_text(encoding="utf-8"))
    except ValueError as error:
        raise DriverFailed(f"unreadable answer: {error}") from error
    return result


def _run_wasm_driver(
    node: str, job: Mapping[str, Any], web_dir: Path, *, timeout: float
) -> dict[str, Any]:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    driver = ARTIFACT_DIR / "wasm_driver.mjs"
    driver.write_text(WASM_DRIVER, encoding="utf-8")
    job_path = ARTIFACT_DIR / "wasm_job.json"
    out_path = ARTIFACT_DIR / "wasm_result.json"
    job_path.write_text(json.dumps(job), encoding="utf-8")
    command = [node, str(driver), str(web_dir), str(job_path), str(out_path)]
    return _child(command, out_path, timeout=timeout)


def _run_native_child(job: Mapping[str, Any], *, timeout: float) -> dict[str, Any]:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    job_path = ARTIFACT_DIR / "native_job.json"
    out_path = ARTIFACT_DIR / "native_result.json"
    job_path.write_text(json.dumps(job), encoding="utf-8")
    command = [
        sys.executable,
        "-m",
        "scripts.measure_window_solver_highs",
        "native-run",
        "--job",
        str(job_path),
        "--out",
        str(out_path),
    ]
    return _child(command, out_path, timeout=timeout)


def solve_job(
    hold_mps: Path, primary_mps: Path, objective: Mapping[int, int | float], budget: float
) -> dict[str, Any]:
    """What a HiGHS driver is told: the two models, the budget, the options, the objective.

    The objective's coefficients by column are the floor row's; the MPS order is the
    exporter's column order, so a column index means the same column in both builds.
    """

    return {
        "mode": "solve",
        "hold_mps": str(hold_mps),
        "primary_mps": str(primary_mps),
        "budget_seconds": float(budget),
        "options": {k: v for k, v in highs_options(budget).items() if k != "time_limit"},
        "objective": {str(j): c for j, c in sorted(objective.items())},
    }


#: What a HiGHS driver reports about itself on every run, kept in the run's record.
REPORTED_KEYS: Final = ("build", "core_version", "package_version", "node_version")


def require_run_version(build: str, raw: Mapping[str, Any], versions: Mapping[str, Any]) -> None:
    """A run's own report of its build must be the one the guards read before any run."""

    if build == "native":
        expected = {"core_version": versions["native_core"]}
    else:
        wasm = versions["wasm"]
        expected = {key: wasm.get(key) for key in REPORTED_KEYS[1:]}
    for key, value in expected.items():
        if raw.get(key) != value:
            raise ProtocolRefusal(
                f"The {build} run reports {key} {raw.get(key)!r}, not the {value!r} the guards "
                "read; no verdict."
            )


def child_timeout(budget: float) -> float:
    """A HiGHS child's stop: twice its budget and the margin; it is killed there."""

    return 2.0 * float(budget) + SOLVE_MARGIN_SECONDS


def interpret_run(
    instance: Instance, raw: Mapping[str, Any] | None, error: str | None
) -> dict[str, Any]:
    """One HiGHS run read on the integer scale, with check 2 on every solution it returned.

    The value is the primary's rounded solution recomputed exactly; a run whose primary
    found nothing keeps its own hold plan, as the planner keeps CP-SAT's, and is not proved.
    """

    if raw is None:
        return {"status": "error", "error": error, "value": None, "seconds": None, "check_2": []}
    assert instance.hold_milp is not None and instance.primary_milp is not None
    assert instance.hold_mps is not None and instance.primary_mps is not None
    divisor = objective_divisor(instance.call)
    hold = dict(raw.get("hold") or {})
    primary = raw.get("primary")
    seconds = float(hold.get("seconds", 0.0)) + float((primary or {}).get("seconds", 0.0))
    hold["model_status_name"] = HIGHS_MODEL_STATUS.get(int(hold.get("model_status", -1)))
    record: dict[str, Any] = {
        "reported": {key: raw[key] for key in REPORTED_KEYS if key in raw},
        "load_seconds": raw.get("load_seconds"),
        "hold": hold,
        "floor": raw.get("floor"),
        "seconds": seconds,
        "status": "no_solution",
        "value_from": None,
    }
    checks: list[dict[str, Any]] = []
    hold_value: int | None = None
    if raw.get("hold_solution") is not None:
        parsed = read_mps(instance.hold_mps.read_text(encoding="utf-8"))
        check = check_two(
            instance.hold_milp,
            parsed,
            instance.solves.hold.proto,
            raw["hold_solution"],
            reported_objective=hold.get("objective"),
        )
        checks.append({"model": "hold", **check})
        hold_value = round(check["value"])
    value: int | None = None
    record["primary"] = None
    if primary is not None:
        name = HIGHS_MODEL_STATUS.get(int(primary.get("model_status", -1)), "Unknown")
        record["primary"] = {**primary, "model_status_name": name}
        if raw.get("primary_solution") is not None:
            parsed = read_mps(instance.primary_mps.read_text(encoding="utf-8"))
            check = check_two(
                instance.primary_milp,
                parsed,
                instance.primary_proto,
                raw["primary_solution"],
                reported_objective=primary.get("objective"),
            )
            checks.append({"model": "primary", **check})
            value = round(check["value"])
            optimal = int(primary["model_status"]) == HIGHS_OPTIMAL
            record["status"] = "proved_optimal" if optimal else "feasible"
            record["value_from"] = "primary"
        bound = primary.get("bound")
        if bound is not None and value is not None and math.isfinite(float(bound)):
            gap = float(bound) + float(instance.primary_milp.objective_offset) - value
            record["gap_units"] = gap
            record["gap_points"] = gap / divisor
    if value is None and hold_value is not None:
        value = hold_value
        record["status"] = "feasible"
        record["value_from"] = "hold"
    record["value"] = value
    record["value_points"] = None if value is None else value / divisor
    record["check_2"] = checks
    record["check_2_passed"] = all(bool(check["passed"]) for check in checks)
    reference = instance.solves.primary_value
    record["agrees_with_cp_sat"] = (
        None if value is None or reference is None else abs(value - reference) <= AGREEMENT_UNITS
    )
    return record


def _toy_model(hold: bool) -> cp_model.CpModel:
    model = cp_model.CpModel()
    picks = [model.new_bool_var(f"pick{i}") for i in range(4)]
    spare = model.new_int_var(0, 3, "spare")
    lot = model.new_int_var(0, 2, "lot")
    price = model.new_int_var(3, 9, "price")
    model.add(sum(picks) <= 2)
    model.add_max_equality(spare, [picks[0] + picks[1] - 1, 0])
    model.add_element(lot, [3, 5, 9], price)
    model.add(lot == 2).only_enforce_if(picks[3])
    if hold:
        model.add(picks[2] == 0)
    model.maximize(3 * picks[0] + 2 * picks[1] + 4 * picks[2] + 9 * picks[3] + spare - price)
    return model


def preflight_driver(build: Callable[[Mapping[str, Any]], Mapping[str, Any]], name: str) -> None:
    """A driver must solve a toy model to CP-SAT's optimum before any timed run counts."""

    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    milps: dict[str, Milp] = {}
    paths: dict[str, Path] = {}
    for part, hold in (("hold", True), ("primary", False)):
        milps[part] = export_milp(_toy_model(hold).proto, f"preflight-{part}")
        paths[part] = ARTIFACT_DIR / f"preflight-{part}.mps"
        paths[part].write_text(write_mps(milps[part]), encoding="utf-8")
    primary = _toy_model(False)
    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = 1
    if solver.solve(primary) != cp_model.OPTIMAL:
        raise ProtocolRefusal("CP-SAT does not prove the toy model.")
    raw = build(solve_job(paths["hold"], paths["primary"], milps["primary"].objective, 60.0))
    answer = raw.get("primary") or {}
    solution = raw.get("primary_solution")
    if int(answer.get("model_status", -1)) != HIGHS_OPTIMAL or solution is None:
        raise ProtocolRefusal(f"The {name} driver does not prove the toy model; no run.")
    parsed = read_mps(paths["primary"].read_text(encoding="utf-8"))
    check = check_two(milps["primary"], parsed, primary.proto, solution)
    if not check["passed"] or round(check["value"]) != round(solver.objective_value):
        raise ProtocolRefusal(f"The {name} driver's toy answer is not CP-SAT's optimum; no run.")


# --------------------------------------------------------------------------------------
# Verdicts.


def _proved(run: Mapping[str, Any]) -> bool:
    return run.get("status") == "proved_optimal"


def verdicts(instances: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """The protocol's device and server verdicts, or "the models disagree"."""

    disagreements = [
        {"entry_id": i["entry_id"], "window": i["window"], "build": build}
        for i in instances
        for build in ("native", "wasm")
        if i["cp_sat"]["proved"]
        and _proved(i["highs"][build]["ceiling"])
        and i["highs"][build]["ceiling"]["agrees_with_cp_sat"] is not True
    ]
    if disagreements:
        return {
            "verdict": "the models disagree",
            "device": None,
            "server": None,
            "disagreements": disagreements,
        }

    def device_proofs(window: int) -> int:
        return sum(
            1
            for i in instances
            if i["window"] == window
            and _proved(i["highs"]["wasm"]["ceiling"])
            and float(i["highs"]["wasm"]["ceiling"]["seconds"]) <= DEVICE_PROOF_SECONDS
        )

    three = [i for i in instances if i["window"] == 3]
    five = [i for i in instances if i["window"] == 5]
    device_ok = (
        len(three) == 15 and len(five) == 15 and device_proofs(3) == 15 and device_proofs(5) >= 14
    )
    native = [(i, i["highs"]["native"]) for i in instances]
    first = all(
        _proved(runs["wall_matched"]) and runs["wall_matched"]["agrees_with_cp_sat"] is True
        for i, runs in native
        if i["cp_sat"]["proved"]
    )
    left_feasible = [
        runs for i, runs in native if i["window"] == 5 and i["cp_sat"]["plan_status"] == "FEASIBLE"
    ]
    second = bool(left_feasible) and 2 * sum(
        1 for runs in left_feasible if _proved(runs["ceiling"])
    ) >= len(left_feasible)
    third = all(
        runs["ceiling"]["value"] is not None
        and i["cp_sat"]["value"] is not None
        and runs["ceiling"]["value"] >= i["cp_sat"]["value"] - AGREEMENT_UNITS
        for i, runs in native
    )
    return {
        "verdict": None,
        "device": (
            "Device can carry windows on a flat calendar"
            if device_ok
            else "windows stay on the server"
        ),
        "device_counts": {
            "three_week_proved_within_15s": device_proofs(3),
            "five_week_proved_within_15s": device_proofs(5),
        },
        "server": "A switch is supported"
        if first and second and third
        else "the server stays on CP-SAT",
        "server_conditions": {
            "wall_matched_proves_every_cp_sat_proof": first,
            "ceiling_proves_half_of_feasible_five_week": second,
            "five_week_left_feasible_by_cp_sat": len(left_feasible),
            "ceiling_never_below_cp_sat": third,
        },
        "disagreements": [],
    }


# --------------------------------------------------------------------------------------
# The commands.


def _members(inputs: PublishedInputs, member: int | None) -> list[int]:
    if member is None:
        return sorted(inputs.members)
    if member not in inputs.members:
        raise ProtocolRefusal(f"Entry {member} is not one of the published members.")
    return [member]


def run_check(member: int | None, out_dir: Path) -> dict[str, Any]:
    """Build the instances, run the rebuild gate, export, run check 1. No timing claims."""

    inputs = load_inputs()
    members = _members(inputs, member)
    rebuild = [rebuild_check(inputs, entry) for entry in members]
    record: dict[str, Any] = {
        "contract_version": CONTRACT_VERSION,
        "command": "check",
        "capture": CAPTURE,
        "members": members,
        "rebuild": {"passed": all(row["passed"] for row in rebuild), "rows": rebuild},
        "instances": [],
    }
    if not record["rebuild"]["passed"]:
        return record
    for entry in members:
        for window in WINDOWS:
            instance = solve_instance(inputs, entry, window)
            export = export_instance(instance, out_dir)
            row: dict[str, Any] = {
                "entry_id": entry,
                "window": window,
                "cp_sat": cp_sat_record(instance, with_time=False),
                "export": export,
            }
            if window == 3:
                published = published_plan_value(
                    instance.call, published_advice(inputs, entry, window)
                )
                reference = row["cp_sat"]["value"]
                published["difference_units"] = (
                    None if reference is None else reference - published["value"]
                )
                row["published"] = published
            record["instances"].append(row)
    record["passed"] = record["rebuild"]["passed"] and all(
        row["export"]["check_1_passed"] for row in record["instances"]
    )
    kinds: dict[str, int] = {}
    for row in record["instances"]:
        for part in ("hold", "primary"):
            for kind, count in row["export"][part]["constraint_kinds"].items():
                kinds[kind] = kinds.get(kind, 0) + count
    record["constraint_kinds"] = dict(sorted(kinds.items()))
    return record


def machine_record() -> dict[str, Any]:
    return {
        "operating_system": platform.platform(),
        "processor": os.environ.get("PROCESSOR_IDENTIFIER") or platform.processor(),
        "machine": platform.machine(),
        "logical_cores": os.cpu_count(),
        "python": platform.python_version(),
    }


def _highs_run(
    build: str, instance: Instance, budget: float, node: str
) -> tuple[Mapping[str, Any] | None, str | None]:
    assert instance.hold_mps is not None and instance.primary_mps is not None
    assert instance.primary_milp is not None
    job = solve_job(
        instance.hold_mps, instance.primary_mps, instance.primary_milp.objective, budget
    )
    timeout = child_timeout(budget)
    try:
        if build == "native":
            return _run_native_child(job, timeout=timeout), None
        return _run_wasm_driver(node, job, WEB_DIR, timeout=timeout), None
    except DriverFailed as error:
        return None, str(error)


def run_measure(node: str, versions: Mapping[str, Any], out_dir: Path) -> dict[str, Any]:
    """The declared runs, in order, one solve at a time; the record is returned, not written."""

    inputs = load_inputs()
    members = sorted(inputs.members)
    preflight_horizon = PREFLIGHT_TIMEOUT_SECONDS + SOLVE_MARGIN_SECONDS
    refuse_blocked_date(datetime.now(UTC), preflight_horizon)
    preflight_driver(
        lambda job: _run_native_child(job, timeout=PREFLIGHT_TIMEOUT_SECONDS), "native"
    )
    refuse_blocked_date(datetime.now(UTC), preflight_horizon)
    preflight_driver(
        lambda job: _run_wasm_driver(node, job, WEB_DIR, timeout=PREFLIGHT_TIMEOUT_SECONDS),
        "wasm",
    )
    # ``rebuild_check`` and ``solve_instance`` each refuse a CP-SAT run that could reach a
    # blocked day; the HiGHS runs are guarded here, up to their child's stop.
    rebuild = [rebuild_check(inputs, entry) for entry in members]
    if not all(row["passed"] for row in rebuild):
        raise ProtocolRefusal("The one-week rebuild differs from the publication; no verdict.")
    progress = out_dir / "progress.jsonl"
    out_dir.mkdir(parents=True, exist_ok=True)
    progress.unlink(missing_ok=True)
    instances: list[dict[str, Any]] = []
    for entry in members:
        for window in WINDOWS:
            reference = solve_instance(inputs, entry, window)
            repeat = solve_instance(inputs, entry, window)
            first = cp_sat_record(reference, with_time=True)
            second = cp_sat_record(repeat, with_time=True)
            if (first["primary_status"], first["value"]) != (
                second["primary_status"],
                second["value"],
            ):
                raise ProtocolRefusal(f"CP-SAT's two runs of {entry} w{window} differ; no verdict.")
            export = export_instance(reference, out_dir)
            if not export["check_1_passed"]:
                raise ProtocolRefusal(f"Check 1 failed on {entry} w{window}; no verdict.")
            matched = wall_matched_budget(first)
            runs: dict[str, dict[str, Any]] = {}
            for build in ("native", "wasm"):
                runs[build] = {}
                for name, budget in (
                    ("wall_matched", matched),
                    ("ceiling", float(WINDOW_WALL_CEILING_SECONDS)),
                ):
                    refuse_blocked_date(datetime.now(UTC), child_timeout(budget))
                    raw, error = _highs_run(build, reference, budget, node)
                    if raw is not None:
                        require_run_version(build, raw, versions)
                    run = interpret_run(reference, raw, error)
                    run["budget_seconds"] = budget
                    if not run.get("check_2_passed", True):
                        raise ProtocolRefusal(
                            f"Check 2 failed on {entry} w{window} {build} {name}; no verdict."
                        )
                    runs[build][name] = run
            row: dict[str, Any] = {
                "entry_id": entry,
                "window": window,
                "cp_sat": {**first, "repeat": second},
                "export": export,
                "highs": runs,
            }
            if window == 3:
                published = published_plan_value(reference.call, published_advice(inputs, entry, 3))
                published["difference_units"] = (
                    None if first["value"] is None else first["value"] - published["value"]
                )
                row["published"] = published
            instances.append(row)
            with progress.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(row, default=str) + "\n")
    revision, dirty = _git_revision()
    return {
        "contract_version": CONTRACT_VERSION,
        "protocol": PROTOCOL,
        "issue": ISSUE,
        "capture": CAPTURE,
        "repository_commit": revision,
        "working_tree_dirty": dirty,
        "machine": machine_record(),
        "versions": {
            "ortools": importlib.import_module("ortools").__version__,
            "highs_native_core": versions["native_core"],
            "highs_wasm": versions["wasm"],
        },
        "budgets": {
            "cp_sat_units_per_week": WINDOW_DETERMINISTIC_UNITS_PER_WEEK,
            "cp_sat_wall_ceiling_seconds": WINDOW_WALL_CEILING_SECONDS,
            "cp_sat_linearization_level": WINDOW_LINEARIZATION_LEVEL,
            "highs_mip_rel_gap": MIP_REL_GAP,
            "highs_mip_abs_gap": MIP_ABS_GAP,
            "highs_threads_set": HIGHS_THREADS,
            "agreement_units": AGREEMENT_UNITS,
        },
        "readings": list(READINGS),
        "rebuild": {"passed": True, "rows": rebuild},
        "instances": instances,
        "verdicts": verdicts(instances),
    }


def markdown(record: Mapping[str, Any]) -> str:
    """The record's twin for reading."""

    result = record["verdicts"]
    lines = [
        "# HiGHS on the member window model",
        "",
        f"Protocol `{record['protocol']}`, issue #{record['issue']}, capture "
        f"`{record['capture']}`, commit `{record['repository_commit']}`. One week of one "
        "season with a flat calendar; nothing here claims more.",
        "",
        "## Verdicts",
        "",
    ]
    if result["verdict"] is not None:
        lines.append(f"**{result['verdict']}**: {len(result['disagreements'])} disagreement(s).")
    else:
        lines += [f"- Device: **{result['device']}**", f"- Server: **{result['server']}**"]
    lines += [
        "",
        "## Instances",
        "",
        "| Entry | Window | CP-SAT | CP-SAT s | Native matched | Native 1,800 s | "
        "Wasm matched | Wasm 1,800 s |",
        "| ---: | ---: | --- | ---: | --- | --- | --- | --- |",
    ]

    def cell(run: Mapping[str, Any]) -> str:
        seconds = run.get("seconds")
        shown = "" if seconds is None else f", {seconds:.1f} s"
        agree = run.get("agrees_with_cp_sat")
        mark = "" if agree is None else (", agrees" if agree else ", differs")
        return f"{run['status']}{shown}{mark}"

    for row in record["instances"]:
        cp = row["cp_sat"]
        highs = row["highs"]
        lines.append(
            f"| {row['entry_id']} | {row['window']} | {cp['primary_status']} | "
            f"{cp['seconds']:.1f} | {cell(highs['native']['wall_matched'])} | "
            f"{cell(highs['native']['ceiling'])} | {cell(highs['wasm']['wall_matched'])} | "
            f"{cell(highs['wasm']['ceiling'])} |"
        )
    lines += ["", "## Readings", ""]
    lines += [f"- {reading}" for reading in record["readings"]]
    machine = record["machine"]
    lines += [
        "",
        "## Machine and versions",
        "",
        f"{machine['operating_system']}, {machine['processor']}, "
        f"{machine['logical_cores']} logical cores. OR-Tools {record['versions']['ortools']}, "
        f"HiGHS native {record['versions']['highs_native_core']}, wasm "
        f"{record['versions']['highs_wasm'].get('core_version')} under Node "
        f"{record['versions']['highs_wasm'].get('node_version')}.",
    ]
    return "\n".join(lines) + "\n"


def _parse(argv: Sequence[str] | None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    check = commands.add_parser("check", help="build, gate, export and run check 1; no timing")
    check.add_argument("--member", type=int, default=None, help="one entry id instead of all")
    check.add_argument("--artifacts", type=Path, default=ARTIFACT_DIR)
    measure = commands.add_parser("measure", help="the declared runs; needs the slot")
    measure.add_argument("--i-have-the-slot", dest="have_slot", action="store_true")
    measure.add_argument("--node", default=os.environ.get("SQUADOPT_NODE", "node"))
    native = commands.add_parser("native-run", help=argparse.SUPPRESS)
    native.add_argument("--job", type=Path, required=True)
    native.add_argument("--out", type=Path, required=True)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse(argv)
    try:
        if arguments.command == "check":
            record = run_check(arguments.member, arguments.artifacts)
            write_json(arguments.artifacts / "check.json", record)
            summary = {
                "passed": record.get("passed", False),
                "rebuild_passed": record["rebuild"]["passed"],
                "instances": [
                    {
                        "entry_id": row["entry_id"],
                        "window": row["window"],
                        "cp_sat": row["cp_sat"]["primary_status"],
                        "check_1": row["export"]["check_1_passed"],
                    }
                    for row in record["instances"]
                ],
                "constraint_kinds": record.get("constraint_kinds"),
            }
            print(json.dumps(summary, indent=2))
            return 0 if record.get("passed") else 1
        if arguments.command == "native-run":
            job = json.loads(arguments.job.read_text(encoding="utf-8"))
            write_json(arguments.out, native_run(job))
            return 0
        versions = measure_guards(
            have_slot=arguments.have_slot,
            now=datetime.now(UTC),
            native_version=native_core_version,
            wasm_version=lambda: wasm_report(arguments.node),
        )
        record = run_measure(arguments.node, versions, ARTIFACT_DIR)
        write_json(RECORD_JSON, record)
        write_text(RECORD_MARKDOWN, markdown(record))
        return 0
    except (ProtocolRefusal, DriverFailed, ExportRefused) as refusal:
        # A driver that fails its version report or its toy model, or a model the exporter
        # does not translate, stops the run as a refusal does: no verdict, and a reason.
        if arguments.command == "measure" and arguments.have_slot:
            # A run that stopped leaves its reason beside its evidence, never in docs/.
            write_json(
                ARTIFACT_DIR / "stopped.json",
                {
                    "kind": type(refusal).__name__,
                    "reason": str(refusal),
                    "at_utc": datetime.now(UTC).isoformat(),
                },
            )
        print(f"refused ({type(refusal).__name__}): {refusal}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
