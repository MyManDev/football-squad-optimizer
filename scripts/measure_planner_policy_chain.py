"""The planner policy chain's weekly step.

``docs/research/planner_policy_chain_prereg.md`` fixes every rule this script applies.

``check`` prints, from the first chain week on, the decision capture the protocol selects for each
gameweek and whether its served football forecast can be read. It writes nothing.

``decide`` writes every arm's decision for each gameweek not yet decided, in order, from the frozen
source. Neither command reads an outcome; the scorer is a separate script, run only at the
protocol's readings.

Run from a clean checkout at the runner's merge commit, with S the capture root, A the
artifact root and O the chain's own output directory:

    python -m scripts.measure_planner_policy_chain check --snapshot-root S --artifact-root A
    python -m scripts.measure_planner_policy_chain decide --snapshot-root S --artifact-root A
        --output O --through-gameweek N
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from importlib import metadata as package_metadata
from pathlib import Path
from typing import Any, cast

import pandas as pd
from scripts._experiment_cli import repository_provenance

import squadopt
from squadopt.application.advice import (
    WINDOW_DETERMINISTIC_UNITS_PER_WEEK,
    WINDOW_LINEARIZATION_LEVEL,
    WINDOW_WALL_CEILING_SECONDS,
)
from squadopt.application.lineup_publication import lineup_fields
from squadopt.data.atomic import write_bytes_once, write_document_once
from squadopt.data.snapshots import list_snapshot_ids, read_snapshot
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, FPL_LIVE_SOURCE, gameweek_deadlines
from squadopt.live.football_artifact import (
    FootballForecast,
    football_artifact_path,
    read_football_forecast,
)
from squadopt.live.recommendation import RecommendationInputs, read_inputs
from squadopt.live.rules import SeasonRules, read_season_rules
from squadopt.live.transfers import (
    HeldSquad,
    _transfer_config,
    plan_transfer_horizon,
    plan_transfers,
)
from squadopt.optimization import SolverStatus, optimize_squad
from squadopt.optimization.config import OptimizationConfig
from squadopt.optimization.optimizer import wall_clock_stopped_the_search
from squadopt.planning.horizon import ProjectionHorizon
from squadopt.planning.models import (
    InitialSquadState,
    PlanningHorizon,
    PlanningWeekResult,
    TransferPlanningConfig,
    TransferPlanResult,
)
from squadopt.planning.optimizer import (
    PLAN_DETERMINISTIC_TIME_LIMIT,
    PLAN_WALL_CEILING_SECONDS,
    optimize_transfer_plan,
)
from squadopt.planning.pricing import sell_price_tenths, spending_power

REPOSITORY = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = REPOSITORY / "docs" / "research" / "planner_policy_chain_prereg.md"
RUNNER_PATH = Path(__file__).resolve()

PROTOCOL_ID = "planner_policy_chain_v1"
SEASON = "2026-27"
LAST_GAMEWEEK = 38

#: Squad budget, total funds and free transfers, by the rule of measure_shortlist_matrix.py.
PROFILES: tuple[tuple[int, int, int], ...] = ((1000, 1000, 1), (950, 1000, 2), (900, 900, 0))
#: The arms in the order they are solved, every week, for every squad.
ARMS: tuple[str, ...] = ("served_3", "served_5", "hold_3", "hold_5", "one_week")
#: Deterministic units per forecast week, the member window's rate, for every arm.
UNITS_PER_WEEK = WINDOW_DETERMINISTIC_UNITS_PER_WEEK
#: The standard path's hold probe runs outside the primary limit, so the hold arm's primary
#: limit is one unit short of the others' total.
HOLD_PROBE_UNITS = 1.0
#: The configuration measure_shortlist_matrix.py builds its squads under.
SQUAD_CONFIG = OptimizationConfig(
    bench_weight=0, solver_time_limit_seconds=120, solver_deterministic_time_limit=60
)
#: Packages whose versions decide what the solver returns; a later run must match them.
PINNED_PACKAGES: tuple[str, ...] = ("ortools", "numpy", "pandas")


class ChainError(RuntimeError):
    """A refusal the protocol requires: the run stops rather than write a wrong record."""


@dataclass(frozen=True)
class ChainState:
    """One arm's squad going into a deadline: what the protocol carries week to week."""

    squad: tuple[int, ...]
    purchase_prices: Mapping[int, int]
    bank_tenths: int
    free_transfers: int
    decided_gameweek: int

    def to_json(self) -> dict[str, object]:
        return {
            "squad": list(self.squad),
            "purchase_prices": {str(k): int(v) for k, v in sorted(self.purchase_prices.items())},
            "bank_tenths": int(self.bank_tenths),
            "free_transfers": int(self.free_transfers),
            "decided_gameweek": int(self.decided_gameweek),
        }

    @classmethod
    def from_json(cls, document: Mapping[str, Any]) -> ChainState:
        return cls(
            squad=tuple(int(p) for p in document["squad"]),
            purchase_prices={int(k): int(v) for k, v in document["purchase_prices"].items()},
            bank_tenths=int(document["bank_tenths"]),
            free_transfers=int(document["free_transfers"]),
            decided_gameweek=int(document["decided_gameweek"]),
        )

    def held(self) -> HeldSquad:
        return HeldSquad(
            season=SEASON,
            decided_gameweek=self.decided_gameweek,
            squad_player_ids=self.squad,
            purchase_prices=dict(self.purchase_prices),
            bank_tenths=self.bank_tenths,
            free_transfers=self.free_transfers,
            chips_used={},
        )


# ---------------------------------------------------------------------------------------------
# What each week reads (protocol rules 4 to 7)


@dataclass(frozen=True)
class CaptureIndexEntry:
    snapshot_id: str
    captured_at_utc: datetime
    target: int | None


def _instant(text: str) -> datetime:
    value = datetime.fromisoformat(text.replace("Z", "+00:00"))
    if value.tzinfo is None:
        raise ChainError(f"Timestamp {text!r} names no time zone.")
    return value.astimezone(UTC)


def capture_index(snapshot_root: Path) -> tuple[CaptureIndexEntry, ...]:
    """Every live capture with its instant and its own target, read once per run."""

    entries = []
    for snapshot_id in list_snapshot_ids(snapshot_root, source=FPL_LIVE_SOURCE):
        snapshot = read_snapshot(snapshot_root, snapshot_id)
        try:
            target: int | None = int(read_inputs(snapshot, season=SEASON).deadline.gameweek)
        except Exception:  # a capture whose inputs cannot be read targets no gameweek
            target = None
        entries.append(
            CaptureIndexEntry(snapshot_id, _instant(snapshot.metadata.captured_at_utc), target)
        )
    return tuple(entries)


@dataclass(frozen=True)
class Selection:
    snapshot_id: str | None
    reason: str | None


def decision_capture(index: Sequence[CaptureIndexEntry], gameweek: int) -> Selection:
    """Rule 4: the last capture, by instant, whose own target is the gameweek; a tie is missing."""

    own = [entry for entry in index if entry.target == gameweek]
    if not own:
        return Selection(None, "no_own_target_capture")
    latest = max(entry.captured_at_utc for entry in own)
    at_latest = [entry for entry in own if entry.captured_at_utc == latest]
    if len(at_latest) > 1:
        return Selection(None, "tied_latest_captures")
    return Selection(at_latest[0].snapshot_id, None)


@dataclass(frozen=True)
class WeekInputs:
    inputs: RecommendationInputs
    rules: SeasonRules
    forecast: FootballForecast
    artifact: Path
    artifact_sha256: str


def week_inputs(snapshot_root: Path, artifact_root: Path, snapshot_id: str) -> WeekInputs | str:
    """Rules 5 and 6: the served forecast and the season rules for one capture, or a reason."""

    snapshot = read_snapshot(snapshot_root, snapshot_id)
    inputs = read_inputs(snapshot, season=SEASON)
    artifact = football_artifact_path(artifact_root, snapshot_id)
    if not artifact.is_file():
        return "no_artifact"
    written = datetime.fromtimestamp(artifact.stat().st_mtime, tz=UTC)
    if written >= _instant(inputs.deadline.deadline_utc):
        return "artifact_written_at_or_after_deadline"
    try:
        forecast = read_football_forecast(artifact, inputs)
    except ValueError:
        return "artifact_unreadable_or_unbound"
    try:
        rules = read_season_rules(snapshot, season=SEASON)
    except Exception as error:
        raise ChainError(f"The season rules of {snapshot_id} cannot be read: {error}") from error
    return WeekInputs(
        inputs=inputs,
        rules=rules,
        forecast=forecast,
        artifact=artifact,
        artifact_sha256=hashlib.sha256(artifact.read_bytes()).hexdigest(),
    )


# ---------------------------------------------------------------------------------------------
# States (rules 8 and 9)


def initial_states(forecast: FootballForecast, gameweek: int) -> dict[str, ChainState]:
    """Rule 8: each profile's squad, proved OPTIMAL from the first chain week's table."""

    first = forecast.horizon.table.loc[forecast.horizon.table.gameweek.eq(gameweek)].copy()
    prices = {int(p): int(c) for p, c in zip(first.player_id, first.price_tenths, strict=True)}
    states = {}
    for budget, funds, free_transfers in PROFILES:
        solved = optimize_squad(
            first, replace(SQUAD_CONFIG, budget_tenths=budget), linearization_level=2
        )
        if solved.solver_status is not SolverStatus.OPTIMAL:
            raise ChainError(f"Squad {budget} was not proved OPTIMAL; the chain stops (rule 8).")
        squad = tuple(sorted(int(p) for p in solved.selected_squad.player_id))
        cost = sum(prices[p] for p in squad)
        states[f"p{budget}"] = ChainState(
            squad=squad,
            purchase_prices={p: prices[p] for p in squad},
            bank_tenths=funds - cost,
            free_transfers=free_transfers,
            decided_gameweek=gameweek - 1,
        )
    return states


# ---------------------------------------------------------------------------------------------
# Arms (rules 10 to 13)


@dataclass(frozen=True)
class PreparedWindow:
    planning_table: pd.DataFrame
    state: InitialSquadState
    policy: TransferPlanningConfig


def prepare_window(
    inputs: RecommendationInputs,
    horizon: ProjectionHorizon,
    held: HeldSquad,
    rules: SeasonRules,
) -> PreparedWindow:
    """The preparation ``plan_transfer_horizon`` performs before it routes a window.

    The hold arm runs this preparation and then the standard path, so it is checked against
    ``plan_transfer_horizon`` on a horizon that takes the standard path, plan for plan.
    """

    horizon.assert_fingerprint()
    first_gameweek = horizon.target_gameweeks[0]
    if (inputs.season, inputs.snapshot_id, inputs.deadline.gameweek) != (
        horizon.season,
        horizon.source_snapshot_id,
        first_gameweek,
    ):
        raise ChainError("The horizon does not bind to the capture it is planned from.")
    if held.decided_gameweek != first_gameweek - 1:
        raise ChainError("The held squad was not decided for the week before this horizon.")
    table = horizon.table
    if bool((table.groupby("player_id", sort=False)["price_tenths"].nunique() > 1).any()):
        raise ChainError("Captured prices must stay fixed across the horizon.")
    first = table.loc[table["gameweek"] == first_gameweek]
    current = {int(p): int(c) for p, c in zip(first.player_id, first.price_tenths, strict=True)}
    fee = float(rules.transfers.sell_on_fee)
    budget = spending_power(
        bank_tenths=held.bank_tenths,
        sell_prices_tenths={
            player: sell_price_tenths(
                current[player], held.purchase_prices[player], sell_on_fee=fee
            )
            for player in held.squad_player_ids
        },
        stated_squad_sell_value_tenths=held.squad_sell_value_tenths,
    )
    held_sell_prices = dict(budget.sell_prices_tenths)
    planning_table = table.loc[
        :, ["gameweek", "player_id", "name", "team_id", "position", "expected_points"]
    ].copy(deep=True)
    if "appearance_probability" in table:
        planning_table["appearance_probability"] = table["appearance_probability"]
    planning_table["buy_price_tenths"] = table["price_tenths"].astype("int64")
    planning_table["sell_price_tenths"] = [
        held_sell_prices.get(int(player), int(price))
        for player, price in zip(table["player_id"], table["price_tenths"], strict=True)
    ]
    weeks = len(horizon.target_gameweeks)
    policy = _transfer_config(rules, transfer_cap=None if weeks == 1 else 1)
    if weeks > 1:
        policy = replace(policy, acquisition_sell_on_fee=fee)
    state = InitialSquadState(
        held.squad_player_ids,
        bank_tenths=budget.bank_tenths,
        free_transfers=min(held.free_transfers, policy.max_free_transfers),
    )
    return PreparedWindow(planning_table, state, policy)


def window_weeks(arm: str, gameweek: int) -> tuple[int, ...]:
    """Rule 11: a window of w weeks, truncated at the season's end."""

    width = int(arm.rsplit("_", 1)[1])
    return tuple(range(gameweek, min(gameweek + width, LAST_GAMEWEEK + 1)))


@dataclass
class ArmOutcome:
    plan: TransferPlanResult | None
    route: str
    route_version: str | None
    deterministic_units: float
    wall_ceiling_seconds: float
    weeks: tuple[int, ...]
    configuration_fingerprint: str | None
    failure: str | None = None
    work: dict[str, object] = field(default_factory=dict)


def _route(plan: TransferPlanResult) -> tuple[str, str | None]:
    for route, key in (("observed", "observed_window"), ("guarded", "sequential_incumbent")):
        block = plan.diagnostics.get(key)
        if isinstance(block, dict):
            version = block.get("version")
            return route, str(version) if version is not None else None
    return "standard", None


def _work(plan: TransferPlanResult) -> dict[str, object]:
    diagnostics = plan.diagnostics
    used = diagnostics.get("deterministic_time_used")
    hold = diagnostics.get("hold_protection")
    guarded = diagnostics.get("sequential_incumbent")
    total: object = used
    if isinstance(guarded, dict):
        total = guarded.get("actual_total")
    elif isinstance(hold, dict) and isinstance(used, int | float):
        total = float(used) + float(hold.get("deterministic_time") or 0)
    return {"deterministic_time_used": total, "wall_seconds": diagnostics.get("wall_time_seconds")}


def run_arm(arm: str, week: WeekInputs, held: HeldSquad) -> ArmOutcome:
    """Rule 10: one arm's plan for one squad at one deadline, or the reason it failed."""

    gameweek = int(week.inputs.deadline.gameweek)
    if arm == "one_week":
        weeks: tuple[int, ...] = (gameweek,)
        units, wall = PLAN_DETERMINISTIC_TIME_LIMIT, PLAN_WALL_CEILING_SECONDS
    else:
        weeks = window_weeks(arm, gameweek)
        units, wall = UNITS_PER_WEEK * len(weeks), WINDOW_WALL_CEILING_SECONDS
    outcome = ArmOutcome(None, arm.split("_")[0], None, units, wall, weeks, None)
    try:
        if arm == "one_week":
            plan, _decision, policy = plan_transfers(
                week.inputs,
                week.forecast.projection,
                held,
                week.rules,
                optimization=OptimizationConfig(
                    solver_time_limit_seconds=PLAN_WALL_CEILING_SECONDS,
                    solver_deterministic_time_limit=PLAN_DETERMINISTIC_TIME_LIMIT,
                ),
            )
        elif arm.startswith("served_"):
            plan, policy = plan_transfer_horizon(
                week.inputs,
                week.forecast.build_horizon(weeks),
                held,
                week.rules,
                optimization=OptimizationConfig(
                    solver_time_limit_seconds=WINDOW_WALL_CEILING_SECONDS,
                    solver_deterministic_time_limit=units,
                ),
                linearization_level=WINDOW_LINEARIZATION_LEVEL,
            )
        else:
            prepared = prepare_window(
                week.inputs, week.forecast.build_horizon(weeks), held, week.rules
            )
            policy = prepared.policy
            plan = optimize_transfer_plan(
                PlanningHorizon(prepared.planning_table),
                prepared.state,
                OptimizationConfig(
                    solver_time_limit_seconds=WINDOW_WALL_CEILING_SECONDS,
                    solver_deterministic_time_limit=units - HOLD_PROBE_UNITS,
                ),
                policy,
                linearization_level=WINDOW_LINEARIZATION_LEVEL,
                protect_hold=True,
            )
    except Exception as error:  # rule 19: a failure is recorded, never retried
        outcome.failure = f"{type(error).__name__}: {error}"
        return outcome
    outcome.plan = plan
    outcome.configuration_fingerprint = policy.configuration_fingerprint
    outcome.work = _work(plan)
    if arm.startswith("served_"):
        outcome.route, outcome.route_version = _route(plan)
    if wall_clock_stopped_the_search(plan.solver_status, plan.diagnostics):
        outcome.failure = "wall_clock_stopped_the_search"
    elif not plan.has_solution or not plan.weeks:
        outcome.failure = "no_plan"
    return outcome


# ---------------------------------------------------------------------------------------------
# Each week (rules 14 to 17) and missing weeks (rule 18)


def advance(
    state: ChainState, week: PlanningWeekResult, current: Mapping[int, int], fee: float
) -> ChainState:
    """Rule 15: the state after playing the first week, with the bank derived a second way."""

    outgoing = [int(p) for p in week.transfers_out["player_id"]]
    incoming = [int(p) for p in week.transfers_in["player_id"]]
    purchase = dict(state.purchase_prices)
    for player in outgoing:
        purchase.pop(player)
    for player in incoming:
        purchase[player] = int(current[player])
    squad = tuple(sorted(int(p) for p in week.selected_squad["player_id"]))
    if set(purchase) != set(squad):
        raise ChainError("The played squad does not match the carried purchase prices.")
    proceeds = sum(
        sell_price_tenths(int(current[p]), int(state.purchase_prices[p]), sell_on_fee=fee)
        for p in outgoing
    )
    cost = sum(int(current[p]) for p in incoming)
    if int(week.bank_before_tenths) != state.bank_tenths or (
        state.bank_tenths + proceeds - cost != int(week.bank_after_tenths)
    ):
        raise ChainError("The plan's bank does not match the bank derived from its moves.")
    return ChainState(
        squad=squad,
        purchase_prices=purchase,
        bank_tenths=int(week.bank_after_tenths),
        free_transfers=int(week.free_transfers_for_next_gameweek),
        decided_gameweek=int(week.gameweek),
    )


def hold(state: ChainState, gameweek: int, max_free_transfers: int) -> ChainState:
    """Rules 18 and 19: no transfer, one more free transfer up to the captured maximum."""

    return replace(
        state,
        free_transfers=min(state.free_transfers + 1, max_free_transfers),
        decided_gameweek=gameweek,
    )


# ---------------------------------------------------------------------------------------------
# Records (rules 21, 32 and 33)


def _ids(frame: pd.DataFrame) -> list[int]:
    return [int(p) for p in frame["player_id"]]


def _player_id(player: object) -> int:
    return int(cast(Mapping[str, Any], player)["player_id"])


def scoring_block(week: PlanningWeekResult) -> dict[str, object]:
    """Rule 16 and 23: the lineup in the advice record's field names, for the scorer."""

    lineup = lineup_fields(week)
    return {
        "starting_xi": [_player_id(p) for p in cast(list[object], lineup["starting_xi"])],
        "bench": [_player_id(p) for p in cast(list[object], lineup["bench"])],
        "captain": _player_id(lineup["captain"]),
        "vice_captain": _player_id(lineup["vice_captain"]),
        "chip": lineup["chip"],
        "transfer_hit_points": float(week.transfer_hit_points),
        "scoring_complete": True,
    }


def players_block(table: pd.DataFrame, wanted: Sequence[int]) -> dict[str, dict[str, object]]:
    """The join map the scorer reads, from the decided week's own forecast rows."""

    pool = {int(str(row["player_id"])): row for _, row in table.iterrows()}
    players = {}
    for player in sorted(set(wanted)):
        row = pool[player]
        players[str(player)] = {
            "name": str(row["name"]),
            "position": str(row["position"]),
            "team": str(row["team_id"]),
            "price_tenths": int(str(row["price_tenths"])),
            "expected_points": float(str(row["expected_points"])),
        }
    return players


def _weeks_summary(plan: TransferPlanResult) -> list[dict[str, object]]:
    return [
        {
            "gameweek": int(week.gameweek),
            "squad": sorted(_ids(week.selected_squad)),
            "starting_xi": sorted(_ids(week.starting_xi)),
            "captain": int(week.captain["player_id"]),
            "transfers_in": _ids(week.transfers_in),
            "transfers_out": _ids(week.transfers_out),
            "bank_after_tenths": int(week.bank_after_tenths),
            "free_transfers_for_next_gameweek": int(week.free_transfers_for_next_gameweek),
            "paid_transfer_count": int(week.paid_transfer_count),
            "projected_score": float(week.projected_score),
            "chip": week.chip,
        }
        for week in plan.weeks
    ]


def replay_identity(document: Mapping[str, object]) -> object:
    """Rule 21: work and clock fields are outside what two writes must agree on."""

    return {key: value for key, value in document.items() if key != "work"}


# ---------------------------------------------------------------------------------------------
# Preflight and the frozen source (rule 3)


def _git(*arguments: str) -> str:
    return subprocess.run(
        ["git", *arguments], cwd=REPOSITORY, check=True, capture_output=True, text=True
    ).stdout.strip()


def source_identity() -> dict[str, object]:
    """Rule 3: the commit, the protocol and runner blobs and the pinned package versions."""

    provenance = repository_provenance()
    if provenance.get("working_tree_dirty") is not False:
        raise ChainError("The checkout is not clean; the frozen source cannot be named.")
    if not Path(squadopt.__file__).resolve().is_relative_to(REPOSITORY / "src"):
        raise ChainError("squadopt does not resolve into this checkout's src/.")
    return {
        "protocol": PROTOCOL_ID,
        "repository_commit": provenance["repository_commit"],
        "protocol_blob": _git("rev-parse", "HEAD:docs/research/planner_policy_chain_prereg.md"),
        "runner_blob": _git("rev-parse", "HEAD:scripts/measure_planner_policy_chain.py"),
        "versions": {name: package_metadata.version(name) for name in PINNED_PACKAGES},
    }


def binding_instant() -> datetime:
    """Rule 2: the later of the commits that brought this protocol and this runner in."""

    instants = []
    for path in (
        "docs/research/planner_policy_chain_prereg.md",
        "scripts/measure_planner_policy_chain.py",
    ):
        added = _git("log", "--diff-filter=A", "--format=%cI", "-1", "--", path)
        if not added:
            raise ChainError(f"{path} has no commit; the protocol has not merged.")
        instants.append(_instant(added))
    return max(instants)


def first_chain_week(
    index: Sequence[CaptureIndexEntry], snapshot_root: Path, bound: datetime
) -> int:
    """Rule 2: the first gameweek whose deadline, as the latest capture states it, is later."""

    if not index:
        raise ChainError("No live capture to read the deadlines from.")
    latest = max(index, key=lambda entry: entry.captured_at_utc)
    snapshot = read_snapshot(snapshot_root, latest.snapshot_id)
    for deadline in gameweek_deadlines(snapshot.payloads[BOOTSTRAP_PAYLOAD]):
        if _instant(deadline.deadline_utc) > bound:
            return int(deadline.gameweek)
    raise ChainError("No gameweek deadline falls after the protocol bound.")


def refuse_output(output: Path, artifact_root: Path) -> None:
    resolved = output.resolve()
    for forbidden in (REPOSITORY / "data", artifact_root.resolve() / "football"):
        if resolved == forbidden or resolved.is_relative_to(forbidden):
            raise ChainError(f"The chain never writes under {forbidden}.")


def bind_protocol(output: Path, identity: Mapping[str, object], first_week: int) -> int:
    """Rule 3: write the run's identity once; refuse a later run whose identity differs."""

    document = {**identity, "first_chain_week": first_week, "season": SEASON}
    path = output / "protocol.json"
    if path.exists():
        recorded = json.loads(path.read_text(encoding="utf-8"))
        for key, value in identity.items():
            if recorded.get(key) != value:
                raise ChainError(f"This run's {key} differs from the frozen source's.")
        return int(recorded["first_chain_week"])
    write_document_once(document, path)
    return first_week


# ---------------------------------------------------------------------------------------------
# Commands


def check(snapshot_root: Path, artifact_root: Path, *, emit: Callable[[str], None] = print) -> None:
    """List each week's selected capture and whether its forecast is usable; write nothing."""

    index = capture_index(snapshot_root)
    first = first_chain_week(index, snapshot_root, binding_instant())
    for gameweek in range(first, LAST_GAMEWEEK + 1):
        selection = decision_capture(index, gameweek)
        if selection.snapshot_id is None:
            emit(f"GW{gameweek:02d} missing {selection.reason}")
            continue
        loaded = week_inputs(snapshot_root, artifact_root, selection.snapshot_id)
        status = loaded if isinstance(loaded, str) else "ready"
        emit(f"GW{gameweek:02d} {selection.snapshot_id} {status}")


def _record(**fields: object) -> dict[str, object]:
    return {"protocol": PROTOCOL_ID, "season": SEASON, "outcome_read": False, **fields}


def decide_week(
    output: Path,
    gameweek: int,
    week: WeekInputs | str,
    capture_id: str | None,
    states: dict[tuple[str, str], ChainState],
    blocked: set[tuple[str, str]],
    commit: object,
    last_max_free_transfers: int,
) -> tuple[dict[tuple[str, str], ChainState], int]:
    """Rules 14 to 21 for one gameweek, every squad and arm.

    Returns the states after the week and the free-transfer maximum the latest readable rules
    state, which a missing week, with no capture to read, holds to (rule 18).
    """

    directory = output / f"gw{gameweek:02d}"
    directory.mkdir(parents=True, exist_ok=True)
    records: dict[str, str] = {}
    after: dict[tuple[str, str], ChainState] = {}
    missing = isinstance(week, str)
    max_free = last_max_free_transfers
    if not missing:
        loaded = cast(WeekInputs, week)
        write_bytes_once(loaded.artifact.read_bytes(), directory / "forecast.json")
        current = {
            int(p): int(c)
            for p, c in zip(
                loaded.inputs.players.player_id, loaded.inputs.players.price_tenths, strict=True
            )
        }
        fee = float(loaded.rules.transfers.sell_on_fee)
        max_free = int(loaded.rules.transfers.max_free_transfers)
    for (profile, arm), state in sorted(states.items()):
        chain = (profile, arm)
        base: dict[str, object] = {
            "gameweek": gameweek,
            "profile": profile,
            "arm": arm,
            "capture_snapshot_id": capture_id,
            "state_before": state.to_json(),
            "provenance": {"repository_commit": commit},
        }
        if missing:
            new_state = hold(state, gameweek, max_free)
            document = _record(**base, status="held", reason=week, state_after=new_state.to_json())
        elif chain in blocked or not set(state.squad) <= set(current):
            blocked.add(chain)
            new_state = replace(state, decided_gameweek=gameweek)
            document = _record(**base, status="blocked", reason="held_player_absent")
        else:
            outcome = run_arm(arm, loaded, state.held())
            policy = {
                "route": outcome.route,
                "route_version": outcome.route_version,
                "weeks": list(outcome.weeks),
                "deterministic_units": outcome.deterministic_units,
                "wall_ceiling_seconds": outcome.wall_ceiling_seconds,
                "configuration_fingerprint": outcome.configuration_fingerprint,
            }
            if outcome.failure is not None or outcome.plan is None:
                new_state = hold(state, gameweek, max_free)
                document = _record(
                    **base,
                    status="failed",
                    reason=outcome.failure,
                    policy=policy,
                    state_after=new_state.to_json(),
                    work=outcome.work,
                )
            else:
                first = outcome.plan.weeks[0]
                new_state = advance(state, first, current, fee)
                document = _record(
                    **base,
                    status="decided",
                    forecast={
                        "sha256": loaded.artifact_sha256,
                        "fingerprint": loaded.forecast.fingerprint,
                        "model_version": loaded.forecast.horizon.model_version,
                    },
                    policy=policy,
                    plan={
                        "solver_status": outcome.plan.solver_status.name,
                        "weeks": _weeks_summary(outcome.plan),
                    },
                    advice=scoring_block(first),
                    players=players_block(
                        loaded.forecast.projection.table, _ids(first.selected_squad)
                    ),
                    state_after=new_state.to_json(),
                    work=outcome.work,
                )
        name = f"{profile}-{arm}.json"
        write_document_once(document, directory / name, replay_identity=replay_identity)
        records[name] = hashlib.sha256((directory / name).read_bytes()).hexdigest()
        after[chain] = new_state
    manifest = _record(
        gameweek=gameweek,
        capture_snapshot_id=capture_id,
        max_free_transfers=max_free,
        records=records,
    )
    write_document_once(manifest, directory / "manifest.json")
    return after, max_free


def decide(
    snapshot_root: Path,
    artifact_root: Path,
    output: Path,
    through_gameweek: int,
    *,
    emit: Callable[[str], None] = print,
) -> None:
    """Write every undecided gameweek through ``through_gameweek``, in order, from the source."""

    refuse_output(output, artifact_root)
    identity = source_identity()
    index = capture_index(snapshot_root)
    output.mkdir(parents=True, exist_ok=True)
    first = bind_protocol(
        output, identity, first_chain_week(index, snapshot_root, binding_instant())
    )
    states: dict[tuple[str, str], ChainState] = {}
    blocked: set[tuple[str, str]] = set()
    max_free = 0
    for gameweek in range(first, min(through_gameweek, LAST_GAMEWEEK) + 1):
        directory = output / f"gw{gameweek:02d}"
        if (directory / "manifest.json").exists():
            manifest = json.loads((directory / "manifest.json").read_text(encoding="utf-8"))
            max_free = int(manifest["max_free_transfers"])
            states = {}
            for name in manifest["records"]:
                record = json.loads((directory / name).read_text(encoding="utf-8"))
                chain = (str(record["profile"]), str(record["arm"]))
                if record["status"] == "blocked":
                    blocked.add(chain)
                    states[chain] = replace(
                        ChainState.from_json(record["state_before"]), decided_gameweek=gameweek
                    )
                else:
                    states[chain] = ChainState.from_json(record["state_after"])
            continue
        selection = decision_capture(index, gameweek)
        week: WeekInputs | str = (
            selection.reason or "no_own_target_capture"
            if selection.snapshot_id is None
            else week_inputs(snapshot_root, artifact_root, selection.snapshot_id)
        )
        if not states:
            if isinstance(week, str):
                raise ChainError(
                    f"The first chain week GW{gameweek} has no usable forecast: {week}."
                )
            initial = initial_states(week.forecast, gameweek)
            for profile, state in initial.items():
                write_document_once(
                    _record(profile=profile, state=state.to_json()),
                    output / "initial" / f"{profile}.json",
                )
            states = {(profile, arm): state for profile, state in initial.items() for arm in ARMS}
        states, max_free = decide_week(
            output,
            gameweek,
            week,
            selection.snapshot_id,
            states,
            blocked,
            identity["repository_commit"],
            max_free,
        )
        emit(f"GW{gameweek:02d} decided from {selection.snapshot_id or week}")


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    commands = parser.add_subparsers(dest="command", required=True)
    for name in ("check", "decide"):
        command = commands.add_parser(name)
        command.add_argument("--snapshot-root", type=Path, required=True)
        command.add_argument("--artifact-root", type=Path, required=True)
        if name == "decide":
            command.add_argument("--output", type=Path, required=True)
            command.add_argument("--through-gameweek", type=int, required=True)
    arguments = parser.parse_args(argv)
    try:
        if arguments.command == "check":
            check(arguments.snapshot_root, arguments.artifact_root)
        else:
            decide(
                arguments.snapshot_root,
                arguments.artifact_root,
                arguments.output,
                arguments.through_gameweek,
            )
    except ChainError as error:
        print(f"refused: {error}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
