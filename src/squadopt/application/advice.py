"""One member's advice, as a pure application call: ``advise_entry``.

This is the seam the on-demand backend will stand on. The request is wire-shaped —
primitive fields only, deliberately **no Path anywhere**: ``DecideRequest`` carries
filesystem paths because it is an operator command, and a shape like that must never
travel over a network boundary. Everything else ``advise_entry`` needs — the picks
provider, the capture inputs, the projection, the season rules — is an injected
collaborator, so the function is a pure computation over what it is handed: the same
call from the batch site builder and from a future worker produces the same bytes.

Independence is structural here, as it is in the league builder: the provider reads
the league capture, which contains neither the requesting user's secrets nor our own
paper entry, so nothing a member is told can depend on the system's own squad.
"""

import functools
import logging
import math
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any

import pandas as pd

from squadopt.application.entries import (
    EntryError,
    EntryPicks,
    EntryPicksProvider,
    held_squad_from_picks,
)
from squadopt.application.phase_e import TransferAdviceDiagnostic, run_transfer_advice_diagnostic
from squadopt.application.strategies import STRATEGY_CATALOG
from squadopt.data.errors import DataSourceError
from squadopt.data.snapshots import CapturedSnapshot
from squadopt.live import (
    Projection,
    RecommendationInputs,
    SeasonRules,
    make_projection_horizon_builder,
    plan_transfer_horizon,
    plan_transfers,
    plan_transfers_with_overlap,
)
from squadopt.live.recommendation import InSeasonProjection
from squadopt.live.transfers import HeldSquad, TransferDecision
from squadopt.optimization import OptimizationConfig
from squadopt.planning import (
    FirstWeekOverlap,
    PlanningWeekResult,
    ProjectionHorizon,
    TransferPlanningConfig,
    TransferPlanResult,
)

#: The baseline combination: the deterministic planner's own one-week answer. Every
#: rival strategy is computed at this window only.
COMPUTED_MODE = "saf-puan"
COMPUTED_WINDOW = 1
#: The windows ``saf-puan`` is computed for. A longer window is the multi-week planner
#: over the week-1 projection repeated across the captured calendar — a plan under
#: stated limits, not a forecast of the later weeks.
MEMBER_WINDOWS: tuple[int, ...] = (1, 3, 5)
#: The multi-week solve's budget, as the system's own horizon path spends it: twenty
#: deterministic units per gameweek, under one wall-clock ceiling. A plan the budget
#: cannot prove is published FEASIBLE with its gap, never dropped.
WINDOW_DETERMINISTIC_UNITS_PER_WEEK = 20.0
WINDOW_WALL_CEILING_SECONDS = 300.0

#: Builds the projection horizon for the requested consecutive gameweeks from the one
#: capture the advice is answered from. Bound by the caller (``member_horizon_builder``)
#: so the request stays wire-shaped and the horizon is built once per window, not per
#: member: it depends on the capture and the handoff only, never on whose squad asks.
HorizonBuilder = Callable[[tuple[int, ...]], ProjectionHorizon]

#: Pitch order for the published eleven and the outfield bench.
_POSITION_ORDER: tuple[str, ...] = ("GK", "DEF", "MID", "FWD")


@dataclass(frozen=True, slots=True)
class AdviseEntryRequest:
    """Everything a caller may say about one advice computation — primitives only."""

    season: str
    gameweek: int
    league_id: int
    entry_id: int
    strategy: str = COMPUTED_MODE
    window: int = COMPUTED_WINDOW
    rival_entry_id: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.season, str) or not self.season.strip():
            raise EntryError("season must be non-empty text.")
        for name in ("gameweek", "league_id", "entry_id"):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or value < 1:
                raise EntryError(f"{name} must be a positive integer.")
        if not isinstance(self.strategy, str) or not self.strategy.strip():
            raise EntryError("strategy must be non-empty text.")
        if isinstance(self.window, bool) or not isinstance(self.window, int):
            raise EntryError("window must be an integer.")
        if self.rival_entry_id is not None and (
            isinstance(self.rival_entry_id, bool)
            or not isinstance(self.rival_entry_id, int)
            or self.rival_entry_id < 1
        ):
            raise EntryError("rival_entry_id must be None or a positive integer.")


def _advice_player(row: "pd.Series[Any]") -> dict[str, object]:
    name = str(row["name"])
    return {
        "player_id": int(str(row["player_id"])),
        "name": name,
        "short_name": name.rsplit(" ", 1)[-1],
        "position": str(row["position"]),
        "team": str(row["team_id"]),
    }


def _lineup_player(row: "pd.Series[Any]") -> dict[str, object]:
    return {**_advice_player(row), "expected_points": float(str(row["expected_points"]))}


def _ranking(row: "pd.Series[Any]") -> tuple[float, int]:
    return (-float(str(row["expected_points"])), int(str(row["player_id"])))


def lineup_fields(week: PlanningWeekResult) -> dict[str, object]:
    """The complete decision a member acts on, read from the plan's first week.

    Transfers alone are not a gameweek: the member still has to name a captain, a
    vice-captain, an eleven and a bench order, and decide whether a chip is played.
    The planner decides the eleven, the captain and the chip; the vice-captain and the
    bench order follow the same completion rule the official scorer applies to an
    optimizer decision (highest expected points first, ties by player id, the bench
    goalkeeper first) so what is shown is what would be scored. ``expected_own_points``
    is the eleven plus the captain's double — expected points, nothing else.
    """

    eleven = [row for _, row in week.starting_xi.iterrows()]
    bench = [row for _, row in week.bench.iterrows()]
    captain_id = int(str(week.captain["player_id"]))
    starters = {int(str(row["player_id"])): row for row in eleven}
    if captain_id not in starters:
        raise EntryError("The plan's captain is not in its starting eleven.")
    vice_candidates = sorted(
        (row for row in eleven if int(str(row["player_id"])) != captain_id), key=_ranking
    )
    if not vice_candidates:
        raise EntryError("The plan's eleven has no vice-captain candidate.")
    goalkeepers = [row for row in bench if str(row["position"]) == "GK"]
    outfield = sorted((row for row in bench if str(row["position"]) != "GK"), key=_ranking)
    if len(goalkeepers) != 1:
        raise EntryError("The plan's bench must hold exactly one goalkeeper.")
    ordered_eleven = sorted(
        eleven, key=lambda row: (_POSITION_ORDER.index(str(row["position"])), _ranking(row))
    )
    expected_own = sum(float(str(row["expected_points"])) for row in eleven) + float(
        str(starters[captain_id]["expected_points"])
    )
    return {
        "expected_own_points": expected_own,
        "captain": _lineup_player(starters[captain_id]),
        "vice_captain": _lineup_player(vice_candidates[0]),
        "starting_xi": [_lineup_player(row) for row in ordered_eleven],
        "bench": [_lineup_player(row) for row in (*goalkeepers, *outfield)],
        "chip": week.chip,
    }


#: What a payload carries when the decision it renders came without its plan week.
_NO_LINEUP: dict[str, object] = {
    "expected_own_points": None,
    "captain": None,
    "vice_captain": None,
    "starting_xi": None,
    "bench": None,
    "chip": None,
}


def _moves(
    outs: Sequence[int],
    ins: Sequence[int],
    *,
    hit_points: object,
    by_id: "dict[int, pd.Series[Any]]",
    pool_by_id: "dict[int, pd.Series[Any]]",
    gameweek: int,
    reason_code: str,
) -> list[dict[str, object]]:
    """The published moves: out/in pairs by position, each with its expected-points delta
    and the week's hit points. ``by_id`` resolves the incoming players (the plan's own
    squad rows), ``pool_by_id`` the outgoing ones (the shared projection)."""

    moves: list[dict[str, object]] = []
    for index in range(max(len(outs), len(ins))):
        player_out = outs[index] if index < len(outs) else None
        player_in = ins[index] if index < len(ins) else None
        delta = 0.0
        if player_in is not None and player_in in by_id:
            delta += float(str(by_id[player_in]["expected_points"]))
        if player_out is not None and player_out in pool_by_id:
            delta -= float(str(pool_by_id[player_out]["expected_points"]))
        moves.append(
            {
                "move_id": f"gw{gameweek:02d}-{index + 1}",
                "player_out": (
                    _advice_player(pool_by_id[player_out])
                    if player_out is not None and player_out in pool_by_id
                    else None
                ),
                "player_in": (
                    _advice_player(by_id[player_in])
                    if player_in is not None and player_in in by_id
                    else None
                ),
                "expected_points_delta": delta,
                "expected_points_cost": float(str(hit_points)),
                "reason_code": reason_code,
            }
        )
    return moves


def _missing_fields(picks: EntryPicks) -> list[str]:
    missing: list[str] = []
    if not picks.free_transfers_known:
        missing.append("free_transfers")
    if not picks.purchase_prices_known:
        missing.append("purchase_prices")
    return missing


def member_horizon_builder(
    snapshot: CapturedSnapshot,
    *,
    season: str,
    panel: pd.DataFrame | None = None,
    in_season: InSeasonProjection | None = None,
) -> HorizonBuilder:
    """Bind one capture (and its handoff or panel) into the builder ``advise_entry`` takes.

    The horizon for a window is a function of the capture, the handoff and the target
    gameweeks — nothing about the member — so it is memoised per target tuple: a batch
    of fifteen members builds the three-week horizon once, not fifteen times. Its
    first week is the same ``project`` call the one-week advice reads, so a window's
    opening numbers are the one-week numbers, bit for bit.
    """

    build = make_projection_horizon_builder(panel, season=season, in_season=in_season)

    @functools.cache
    def horizon_for(target_gameweeks: tuple[int, ...]) -> ProjectionHorizon:
        return build(snapshot, tuple(int(week) for week in target_gameweeks))

    return horizon_for


@dataclass(frozen=True, slots=True)
class MemberControl:
    """One member's unconstrained one-week plan: the saf-puan answer and every rival
    strategy's control, solved once and reused.

    The batch renders a member against every other member of the league under every
    computable rival strategy; re-solving the same control for each of them would be
    the same bytes at many times the cost. The picks the control was solved from travel
    with it, so a caller cannot hand one member's control to another's request.
    """

    picks: EntryPicks
    plan: TransferPlanResult
    decision: TransferDecision
    transfer_config: TransferPlanningConfig


def solve_member_control(
    picks: EntryPicks,
    inputs: RecommendationInputs,
    projection: Projection,
    rules: SeasonRules,
    *,
    phase_e_diagnostic: TransferAdviceDiagnostic | None = None,
) -> MemberControl:
    """Solve the member's one-week pure-points plan from their own squad."""

    prices = {
        int(str(row["player_id"])): int(str(row["price_tenths"]))
        for _, row in inputs.players.iterrows()
    }
    held = held_squad_from_picks(picks, current_prices=prices)
    plan, decision, transfer_config = plan_transfers(inputs, projection, held, rules)
    try:
        run_transfer_advice_diagnostic(
            plan,
            held,
            gameweek=int(inputs.deadline.gameweek),
            # The diagnostic scores solved candidates against one another, so it charges
            # what the game charges, not the planner's caution margin.
            transfer_hit_cost_points=transfer_config.hit_points_charged,
            diagnostic=phase_e_diagnostic,
        )
    except Exception:
        # An opt-in internal diagnostic cannot invalidate the already-solved advice.
        logging.getLogger(__name__).warning("Phase E advice diagnostic failed", exc_info=True)
    return MemberControl(picks=picks, plan=plan, decision=decision, transfer_config=transfer_config)


def net_expected_points(plan: TransferPlanResult) -> float:
    """A plan's expected points as the member would score them: the eleven's projected
    points minus the hits the plan pays. A constraint that forces paid transfers is not
    cheap because the gross projection barely moved.

    ``total_transfer_hit_points`` is counted at the game's charge, so this compares two
    already-solved plans at what the member would actually be docked. The planner's
    caution margin belongs inside each solve, where it decides whether a transfer is
    worth making at all; applying it again here would price the same caution twice.
    """

    score = plan.total_projected_score
    hits = plan.total_transfer_hit_points
    if score is None or hits is None or not math.isfinite(score) or not math.isfinite(hits):
        raise EntryError("A solved plan must carry finite projected points and hit points.")
    return float(score) - float(hits)


def _control_for(
    picks: EntryPicks,
    control: MemberControl | None,
    inputs: RecommendationInputs,
    projection: Projection,
    rules: SeasonRules,
    *,
    phase_e_diagnostic: TransferAdviceDiagnostic | None = None,
) -> MemberControl:
    if control is None:
        return solve_member_control(
            picks, inputs, projection, rules, phase_e_diagnostic=phase_e_diagnostic
        )
    if control.picks != picks:
        raise EntryError(
            f"The supplied control was solved for entry {control.picks.entry_id} "
            f"gameweek {control.picks.gameweek}, not for entry {picks.entry_id} "
            f"gameweek {picks.gameweek}."
        )
    return control


def build_advice_payload(
    picks: EntryPicks,
    inputs: RecommendationInputs,
    projection: Projection,
    rules: SeasonRules,
    *,
    league_id: int,
    mode: str = COMPUTED_MODE,
    decision: TransferDecision | None = None,
    expected_points_cost: float = 0.0,
    rival_label: str | None = None,
    solver_status: str | None = None,
    optimality_gap: float | None = None,
    week: PlanningWeekResult | None = None,
    control: MemberControl | None = None,
    phase_e_diagnostic: TransferAdviceDiagnostic | None = None,
) -> dict[str, object]:
    """One member's advice payload — from their squad and the shared projection only.

    Without ``decision`` this solves the one-week pure-points plan itself: the site's
    saf-puan baseline, exactly what the page always showed. With one — a menu entry a
    mode's selector chose — it renders that decision instead, labelled ``mode`` and
    carrying the mode's expected-points price tag together with the solver's own account
    of that plan (``solver_status``, ``optimality_gap``), read from the menu entry it
    chose. A competitive mode without a supplied decision is refused rather than
    silently re-labelled as the baseline.

    The payload carries the whole decision, not only the transfers: captain,
    vice-captain, the eleven, the bench order and the chip, read from the plan's first
    week (``lineup_fields``). A supplied decision without its ``week`` publishes those
    fields as null rather than inventing a lineup.

    A plan the solver found but could not prove optimal is published with
    ``solver_status: "FEASIBLE"`` and the measured bound gap, not discarded: the plan
    it found is real, the missing proof is stated, and the reader decides.

    An optional ``phase_e_diagnostic`` inspects this function's solved saf-puan control
    internally; its result never supplies a member-facing decision or payload field.
    """

    if mode != COMPUTED_MODE and decision is None:
        raise EntryError(f"Mode {mode!r} advice needs the decision its selector chose.")
    pool_by_id = {int(str(row["player_id"])): row for _, row in projection.table.iterrows()}
    if decision is None:
        solved = _control_for(
            picks, control, inputs, projection, rules, phase_e_diagnostic=phase_e_diagnostic
        )
        plan = solved.plan
        transfers: TransferDecision | None = solved.decision
        by_id = {
            int(str(row["player_id"])): row for _, row in plan.weeks[0].selected_squad.iterrows()
        }
        solver_status = plan.solver_status.name
        raw_gap = plan.diagnostics.get("absolute_optimality_gap")
        optimality_gap = float(str(raw_gap)) if raw_gap is not None else None
        week = plan.weeks[0]
    else:
        transfers = decision
        by_id = pool_by_id
    lineup = lineup_fields(week) if week is not None else dict(_NO_LINEUP)
    reason_code = "window_value" if mode == COMPUTED_MODE else "mode_tradeoff"
    moves: list[dict[str, object]] = []
    if transfers is not None:
        record = transfers.as_record()
        outs_raw = record.get("transfers_out", [])
        ins_raw = record.get("transfers_in", [])
        outs = [int(str(v)) for v in outs_raw] if isinstance(outs_raw, list | tuple) else []
        ins = [int(str(v)) for v in ins_raw] if isinstance(ins_raw, list | tuple) else []
        moves = _moves(
            outs,
            ins,
            hit_points=record.get("transfer_hit_points", 0.0),
            by_id=by_id,
            pool_by_id=pool_by_id,
            gameweek=picks.gameweek + 1,
            reason_code=reason_code,
        )
    missing = _missing_fields(picks)
    return {
        "season": picks.season,
        "gameweek": picks.gameweek + 1,
        "entry_id": picks.entry_id,
        "league_id": league_id,
        "mode": mode,
        "window": COMPUTED_WINDOW,
        "source_snapshot_id": picks.source_snapshot_id,
        "moves": moves,
        # The mode's whole-plan price against the pure-points pick, in expected points —
        # the only cross-mode number the site may show (no probability ships, ever).
        "expected_points_cost": float(expected_points_cost),
        "rival_label": rival_label,
        # The solver's own account of the plan: OPTIMAL is a proof, FEASIBLE is a found
        # plan with the measured bound gap beside it. Absent proof is stated, not hidden.
        "solver_status": solver_status,
        "optimality_gap": optimality_gap,
        # The rest of the decision: who wears the armband, who stands in for him, the
        # eleven in pitch order, the bench in the order the game's autosubs walk it,
        # and the chip — all in expected points, none of it a probability.
        **lineup,
        "data_quality": "partial" if missing else "complete",
        "missing_fields": missing,
    }


#: What a three- or five-week window assumes, stated in the payload beside the plan so
#: the reader gets the limits with the answer. Every sentence names a mechanism the code
#: applies; none of them is softened.
WINDOW_STATED_LIMITS: tuple[str, ...] = (
    "The first week's projection is repeated over the later weeks, scaled by each "
    "club's fixture count from the captured calendar; the later weeks are not "
    "projected separately.",
    "Availability is applied once, from the capture: injuries, rotation and "
    "suspensions after it are not seen.",
    "Every week inside the window, the first included, is capped at one transfer "
    "(a wildcard week excepted); the one-week plan has no such cap.",
    "The Top-100 uplift is inside the first week's numbers, and the repetition "
    "carries it into every later week.",
    "Prices are held at the captured values; no price change is modelled.",
    "No chip is offered inside the window. A finite window counts nothing for "
    "holding a chip back, so a planner that could reach one would spend it; chip "
    "timing is a season-long decision this window cannot price.",
)


def build_window_payload(
    picks: EntryPicks,
    inputs: RecommendationInputs,
    projection: Projection,
    rules: SeasonRules,
    *,
    league_id: int,
    window: int,
    horizon_builder: HorizonBuilder | None,
) -> dict[str, object]:
    """One member's ``saf-puan`` advice over a three- or five-week window.

    The horizon is the week-1 projection repeated over the captured calendar
    (``build_projection_horizon``), the plan is the multi-week planner under the system's
    own horizon budget and no chip offered — a finite window counts nothing for holding
    one back, so a planner that could reach a chip would spend it, and the system's own
    horizon path declines them for the same reason — and the payload is the one-week
    shape plus ``plan_weeks``
    — one row per gameweek — and ``stated_limits``. The first week is published through
    the same ``lineup_fields`` and moves as the one-week advice, so the page's existing
    card renders it unchanged; the whole window's transfers live in ``plan_weeks``.

    A per-week component rescoring was measured to move only the venue effect, below the
    solver's proof resolution, so the later weeks are the first week's numbers by
    design and the limits say so. A plan the budget found but could not prove is
    published FEASIBLE with its gap, as the one-week path publishes its own.
    """

    if window not in MEMBER_WINDOWS or window == COMPUTED_WINDOW:
        raise EntryError(f"Window {window} is not a multi-week member window.")
    if horizon_builder is None:
        raise EntryError(
            f"Window {window} needs a projection horizon builder for this capture; none "
            "was supplied."
        )
    gameweek = int(inputs.deadline.gameweek)
    targets = tuple(range(gameweek, gameweek + window))
    # A target the captured calendar does not publish is refused by the builder itself.
    horizon = horizon_builder(targets)
    prices = {
        int(str(row["player_id"])): int(str(row["price_tenths"]))
        for _, row in inputs.players.iterrows()
    }
    held = held_squad_from_picks(picks, current_prices=prices)
    plan, _transfer_config = plan_transfer_horizon(
        inputs,
        horizon,
        held,
        rules,
        optimization=OptimizationConfig(
            solver_time_limit_seconds=WINDOW_WALL_CEILING_SECONDS,
            solver_deterministic_time_limit=WINDOW_DETERMINISTIC_UNITS_PER_WEEK * window,
        ),
    )
    first = plan.weeks[0]
    pool_by_id = {int(str(row["player_id"])): row for _, row in projection.table.iterrows()}
    by_id = {int(str(row["player_id"])): row for _, row in first.selected_squad.iterrows()}
    raw_gap = plan.diagnostics.get("absolute_optimality_gap")
    missing = _missing_fields(picks)
    return {
        "season": picks.season,
        "gameweek": picks.gameweek + 1,
        "entry_id": picks.entry_id,
        "league_id": league_id,
        "mode": COMPUTED_MODE,
        "window": int(window),
        "source_snapshot_id": picks.source_snapshot_id,
        # The first week's moves, in the one-week shape the page already renders.
        "moves": _moves(
            [int(str(v)) for v in first.transfers_out["player_id"].tolist()],
            [int(str(v)) for v in first.transfers_in["player_id"].tolist()],
            hit_points=float(first.transfer_hit_points),
            by_id=by_id,
            pool_by_id=pool_by_id,
            gameweek=picks.gameweek + 1,
            reason_code="window_value",
        ),
        "expected_points_cost": 0.0,
        "rival_label": None,
        # The solver's own account of the whole window: OPTIMAL is a proof, FEASIBLE is
        # the plan it found with the measured bound gap beside it.
        "solver_status": plan.solver_status.name,
        "optimality_gap": float(str(raw_gap)) if raw_gap is not None else None,
        **lineup_fields(first),
        # One row per gameweek. ``expected_points`` is the planner's projected score
        # for that week's eleven with the captain's multiplier, before hits.
        "plan_weeks": [
            {
                "gameweek": int(week.gameweek),
                "transfers_in": [_advice_player(row) for _, row in week.transfers_in.iterrows()],
                "transfers_out": [_advice_player(row) for _, row in week.transfers_out.iterrows()],
                "transfer_hit_points": float(week.transfer_hit_points),
                "chip": week.chip,
                "free_transfers_before": int(week.free_transfers_before),
                "free_transfers_after": int(week.free_transfers_for_next_gameweek),
                "expected_points": float(week.projected_score),
            }
            for week in plan.weeks
        ],
        "stated_limits": list(WINDOW_STATED_LIMITS),
        "data_quality": "partial" if missing else "complete",
        "missing_fields": missing,
    }


def advise_entry(
    request: AdviseEntryRequest,
    *,
    provider: EntryPicksProvider,
    inputs: RecommendationInputs,
    projection: Projection,
    rules: SeasonRules,
    control: MemberControl | None = None,
    phase_e_diagnostic: TransferAdviceDiagnostic | None = None,
    horizon_builder: HorizonBuilder | None = None,
) -> dict[str, object]:
    """Compute one member's advice for a validated request.

    The request is checked against the capture it will be answered from: the season and
    gameweek must be the capture's own, and the strategy and window must be a
    combination that is actually computed — an advice file for a combination nobody
    computed would make the site show an answer where none was measured. ``saf-puan``
    is computed at every window in ``MEMBER_WINDOWS``; a rival strategy at window one
    only, because its band is a first-week constraint and nothing about a later week
    is known that would let it be priced there. The rival parameter is validated
    against the strategy that asks for it: ``saf-puan`` is rival-free and refuses one,
    a catalogue strategy whose overlap band reaches the solver requires one, and
    nobody may name themselves.

    ``control`` is an optional precomputed ``MemberControl`` for this member (the batch
    solves it once and renders the whole rival menu from it); it must have been solved
    from the same picks, and the bytes are identical with or without it.

    ``horizon_builder`` is the collaborator a multi-week window needs — the capture's
    projection horizon for the window's gameweeks (``member_horizon_builder``). A
    window asked for without one is refused, never answered from the one-week plan.

    ``phase_e_diagnostic`` is a local collaborator for saf-puan only, not a request
    field. It is dormant until a reviewed calibration pin exists.
    """

    if request.season != str(inputs.season):
        raise EntryError(
            f"Request season {request.season!r} is not the capture's {inputs.season!r}."
        )
    if request.gameweek != int(inputs.deadline.gameweek):
        raise EntryError(
            f"Request gameweek {request.gameweek} is not the capture's "
            f"{int(inputs.deadline.gameweek)}."
        )
    if rules.season != inputs.season:
        raise EntryError("The advice rules belong to another season.")
    if rules.source_snapshot_id != inputs.snapshot_id:
        raise EntryError("The advice rules belong to another capture.")
    if request.window not in MEMBER_WINDOWS:
        raise EntryError(
            f"Window {request.window} is not computed; {COMPUTED_MODE!r} windows are "
            f"{MEMBER_WINDOWS} and rival strategies are computed at window "
            f"{COMPUTED_WINDOW} only."
        )
    if request.strategy == COMPUTED_MODE:
        if request.rival_entry_id is not None:
            raise EntryError(
                f"{COMPUTED_MODE!r} is rival-free; to name a rival, ask for a rival "
                "strategy from the catalogue."
            )
        picks = _requested_picks(request, request.entry_id, provider=provider, inputs=inputs)
        if request.window != COMPUTED_WINDOW:
            return build_window_payload(
                picks,
                inputs,
                projection,
                rules,
                league_id=request.league_id,
                window=request.window,
                horizon_builder=horizon_builder,
            )
        return build_advice_payload(
            picks,
            inputs,
            projection,
            rules,
            league_id=request.league_id,
            control=control,
            phase_e_diagnostic=phase_e_diagnostic,
        )
    strategy = STRATEGY_CATALOG.get(request.strategy)
    if strategy is None:
        raise EntryError(f"Strategy {request.strategy!r} is not in the catalogue.")
    if request.window != COMPUTED_WINDOW:
        raise EntryError(
            f"Strategy {request.strategy!r} is computed at window {COMPUTED_WINDOW} only; "
            f"windows {MEMBER_WINDOWS[1:]} are {COMPUTED_MODE!r} only."
        )
    floor = strategy.constraints.overlap_floor
    ceiling = strategy.constraints.overlap_ceiling
    if floor is None and ceiling is None:
        raise EntryError(
            f"Strategy {request.strategy!r} is not computed on this path yet; its "
            "constraint is not wired to the solver."
        )
    if request.rival_entry_id is None:
        raise EntryError(f"Strategy {request.strategy!r} needs a rival: pass rival_entry_id.")
    if request.rival_entry_id == request.entry_id:
        raise EntryError("A member cannot be their own rival.")
    return _advise_against_rival(
        request,
        rival_entry_id=request.rival_entry_id,
        floor=floor,
        ceiling=ceiling,
        provider=provider,
        inputs=inputs,
        projection=projection,
        rules=rules,
        control=control,
    )


def _solve_within_free_transfers(
    inputs: RecommendationInputs,
    projection: Projection,
    held: HeldSquad,
    rules: SeasonRules,
    *,
    rival_eleven: frozenset[int],
    floor: int | None,
    ceiling: int | None,
    transfer_cap: int,
) -> tuple[TransferPlanResult, TransferDecision, int] | None:
    """The banded plan under the transfer cap, at the strictest level the cap reaches.

    A floor is relaxed downward (nine, eight, …, one); a ceiling upward (five, six, …,
    eleven). Each level is one solve; an unsatisfiable level is the planner's own
    refusal, not a guess. Returns the plan, its decision and the level applied, or
    ``None`` when no level is reachable.
    """

    levels: list[tuple[int | None, int | None]]
    if floor is not None:
        levels = [(level, None) for level in range(int(floor), 0, -1)]
    elif ceiling is not None:
        levels = [(None, level) for level in range(int(ceiling), len(rival_eleven) + 1)]
    else:
        return None
    for minimum, maximum in levels:
        band = FirstWeekOverlap(player_ids=rival_eleven, minimum=minimum, maximum=maximum)
        try:
            plan, decision, _config = plan_transfers_with_overlap(
                inputs, projection, held, rules, band, transfer_cap=transfer_cap
            )
        except DataSourceError:
            continue
        applied = minimum if minimum is not None else maximum
        assert applied is not None
        return plan, decision, applied
    return None


def _requested_picks(
    request: AdviseEntryRequest,
    entry_id: int,
    *,
    provider: EntryPicksProvider,
    inputs: RecommendationInputs,
) -> EntryPicks:
    """Reject a collaborator's mismatched member or capture before any solve."""

    picks = provider.picks(entry_id, request.season, request.gameweek - 1)
    for name, expected, actual in (
        ("entry_id", entry_id, picks.entry_id),
        ("season", request.season, picks.season),
        ("gameweek", request.gameweek - 1, picks.gameweek),
    ):
        if actual != expected:
            raise EntryError(
                f"Picks {name} {actual!r} does not match requested {name} {expected!r}."
            )
    if picks.source_snapshot_id is not None and picks.source_snapshot_id != inputs.snapshot_id:
        raise EntryError(f"Picks for entry {entry_id} belong to another capture.")
    return picks


def _advise_against_rival(
    request: AdviseEntryRequest,
    *,
    rival_entry_id: int,
    floor: int | None,
    ceiling: int | None,
    provider: EntryPicksProvider,
    inputs: RecommendationInputs,
    projection: Projection,
    rules: SeasonRules,
    control: MemberControl | None = None,
) -> dict[str, object]:
    """One member's plan under a rival strategy's overlap band, priced and labelled.

    The member's own squad is still the only starting point — the rival contributes a
    constraint (their public eleven) and the comparison labels, nothing else, so the
    invariance rule survives: what this member is told is computed from this member's
    squad and the shared projection.

    A rival strategy spends the free transfers and nothing more: one free transfer a
    week, banked up to the rules' limit, and every extra transfer costs four points,
    which no one-week band is worth. So the band is solved under a cap of the free
    transfers the member holds, and a target the free transfers cannot reach is
    relaxed one step at a time — a floor of nine that one transfer cannot reach
    becomes the highest floor it can — and the payload names both the target and the
    band actually applied. The eleven, the captain and the bench are then chosen
    from the resulting fifteen.

    The price tag is the control's expected points minus the banded plan's, both net
    of the hits each plan pays and both from this member's own solves. A control the
    solver found but could not prove is used as it is and published beside the tag as
    ``control_solver_status`` with its measured gap; only a control with no solution
    refuses. Everything added to the payload here is in the strategy's declared
    ``publishes`` set — the mean gap, the overlap count, captain agreement; no spread,
    no probability, ever.
    """

    picks = _requested_picks(request, request.entry_id, provider=provider, inputs=inputs)
    rival_picks = _requested_picks(request, rival_entry_id, provider=provider, inputs=inputs)
    rival_eleven = frozenset(int(value) for value in rival_picks.starting_xi)
    rival_captain = int(rival_picks.captain)
    if rival_captain not in rival_eleven:
        raise EntryError(f"Rival entry {rival_entry_id} captain is not in its starting XI.")
    expected = {
        int(str(row["player_id"])): float(str(row["expected_points"]))
        for _, row in projection.table.iterrows()
    }
    missing_rival = sorted({*rival_eleven, rival_captain} - set(expected))
    if missing_rival:
        raise EntryError(
            f"The projection is missing rival entry {rival_entry_id} players "
            f"{missing_rival[:5]!r}; a rival score cannot treat missing players as zero."
        )
    solved = _control_for(picks, control, inputs, projection, rules)
    control_plan = solved.plan
    if not control_plan.has_solution or not control_plan.weeks:
        raise EntryError(
            "The unconstrained control plan has no solution; nothing can be priced against it."
        )
    prices = {
        int(str(row["player_id"])): int(str(row["price_tenths"]))
        for _, row in inputs.players.iterrows()
    }
    held = held_squad_from_picks(picks, current_prices=prices)
    transfer_cap = max(1, min(int(held.free_transfers), int(rules.transfers.max_free_transfers)))
    target = floor if floor is not None else ceiling
    assert target is not None
    # Two candidates, one decision rule. Within the free transfers: the strictest band
    # level they reach, no hits. With hits: the declared target, every extra transfer
    # charged four points in the objective. The one with the higher net expected points
    # is the advice — a hit is spent only where it pays for itself — and the other is
    # published beside it as the alternative, so the member sees what it would have cost.
    within_free = _solve_within_free_transfers(
        inputs,
        projection,
        held,
        rules,
        rival_eleven=rival_eleven,
        floor=floor,
        ceiling=ceiling,
        transfer_cap=transfer_cap,
    )
    band = FirstWeekOverlap(player_ids=rival_eleven, minimum=floor, maximum=ceiling)
    try:
        with_hits: tuple[TransferPlanResult, TransferDecision, int] | None = (
            *plan_transfers_with_overlap(inputs, projection, held, rules, band)[:2],
            target,
        )
    except DataSourceError:
        with_hits = None
    if within_free is None and with_hits is None:
        raise EntryError(
            f"The {request.strategy!r} band cannot be satisfied from this squad against "
            f"entry {rival_entry_id}: no provable plan exists."
        )
    if within_free is not None and (
        with_hits is None
        or net_expected_points(within_free[0]) >= net_expected_points(with_hits[0])
    ):
        chosen, other, chosen_kind = within_free, with_hits, "within_free_transfers"
    else:
        assert with_hits is not None
        chosen, other, chosen_kind = with_hits, within_free, "with_hits"
    plan, decision, applied = chosen
    raw_gap = plan.diagnostics.get("absolute_optimality_gap")
    raw_control_gap = control_plan.diagnostics.get("absolute_optimality_gap")
    # Net of hits on both sides: a band that forces paid transfers costs those hits.
    control_net = net_expected_points(control_plan)
    strategy_net = net_expected_points(plan)
    payload = build_advice_payload(
        picks,
        inputs,
        projection,
        rules,
        league_id=request.league_id,
        mode=request.strategy,
        decision=decision,
        expected_points_cost=control_net - strategy_net,
        rival_label=f"entry-{rival_entry_id}",
        solver_status=plan.solver_status.name,
        optimality_gap=float(str(raw_gap)) if raw_gap is not None else None,
        week=plan.weeks[0],
    )
    week = plan.weeks[0]
    squad_ids = {int(str(value)) for value in week.selected_squad["player_id"]}
    my_eleven = [int(str(value)) for value in week.starting_xi["player_id"]]
    my_captain = int(str(week.captain["player_id"]))
    missing_plan = sorted({*my_eleven, my_captain} - set(expected))
    if missing_plan:
        raise EntryError(
            f"The solved plan references players absent from its projection: {missing_plan[:5]!r}."
        )
    my_expected = sum(expected[p] for p in my_eleven) + expected[my_captain]
    rival_expected = sum(expected[p] for p in sorted(rival_eleven)) + expected[rival_captain]
    hits = plan.total_transfer_hit_points
    my_hits = float(hits) if hits is not None and math.isfinite(hits) else 0.0
    payload["rival_entry_id"] = rival_entry_id
    payload["overlap_count"] = len(squad_ids & rival_eleven)
    # What the strategy asked for, what the free transfers could reach, and the cap
    # itself: a target a member cannot afford without hits is stated, never bought.
    payload["transfer_cap"] = transfer_cap
    payload["overlap_target"] = target
    payload["overlap_applied"] = applied
    payload["plan_kind"] = chosen_kind
    other_hits = other[0].total_transfer_hit_points if other is not None else None
    payload["alternative_plan"] = (
        None
        if other is None
        else {
            "kind": (
                "with_hits" if chosen_kind == "within_free_transfers" else "within_free_transfers"
            ),
            "overlap_applied": other[2],
            "transfer_hit_points": float(other_hits) if other_hits is not None else None,
            "expected_points_cost": control_net - net_expected_points(other[0]),
        }
    )
    # A mean and only a mean: shared players cancel exactly in the fixed-decision
    # comparison, so this is projection arithmetic over the differentials, net of the
    # hits this plan pays (the rival's future transfers are unknown and not guessed).
    # The spread those same differentials generate is not publishable, and is not
    # computed.
    payload["expected_gap_vs_rival"] = (my_expected - my_hits) - rival_expected
    payload["captain_agreement"] = my_captain == rival_captain
    # The control's own account beside the price it anchors: a FEASIBLE control makes
    # the tag a reading with a stated bound, not a proof.
    payload["control_solver_status"] = control_plan.solver_status.name
    payload["control_optimality_gap"] = (
        float(str(raw_control_gap)) if raw_control_gap is not None else None
    )
    return payload


__all__: tuple[str, ...] = (
    "COMPUTED_MODE",
    "COMPUTED_WINDOW",
    "MEMBER_WINDOWS",
    "WINDOW_STATED_LIMITS",
    "AdviseEntryRequest",
    "HorizonBuilder",
    "MemberControl",
    "advise_entry",
    "build_advice_payload",
    "build_window_payload",
    "lineup_fields",
    "member_horizon_builder",
    "net_expected_points",
    "solve_member_control",
)
