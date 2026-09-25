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
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

import pandas as pd

from squadopt.application.advice_capabilities import (
    COMPUTED_MODE as COMPUTED_MODE,
)
from squadopt.application.advice_capabilities import (
    COMPUTED_WINDOW as COMPUTED_WINDOW,
)
from squadopt.application.advice_capabilities import (
    MEMBER_WINDOWS as MEMBER_WINDOWS,
)
from squadopt.application.advice_capabilities import (
    validate_advice_selection,
)
from squadopt.application.entries import (
    EntryError,
    EntryPicks,
    EntryPicksProvider,
    held_squad_from_picks,
)
from squadopt.application.lineup_publication import advice_player as _advice_player
from squadopt.application.lineup_publication import (
    best_eleven_basis,
    best_eleven_points_under,
)
from squadopt.application.lineup_publication import best_eleven_points as best_eleven_points
from squadopt.application.lineup_publication import lineup_fields as lineup_fields
from squadopt.application.manager_words import ManagerWord, ManagerWords
from squadopt.application.phase_e import TransferAdviceDiagnostic, run_transfer_advice_diagnostic
from squadopt.application.strategies import STRATEGY_CATALOG
from squadopt.application.top100_weight import (
    TOP100_PRICE_BASIS,
    Top100Counts,
    base_net,
    base_points,
    decision_changed,
    rebased_week,
    validate_top100_weight,
    weighted_projection,
)
from squadopt.data.errors import DataError, DataSourceError
from squadopt.data.snapshots import CapturedSnapshot
from squadopt.live import (
    Projection,
    RecommendationInputs,
    SeasonRules,
    make_projection_horizon_builder,
    plan_transfer_horizon,
    plan_transfers,
    plan_transfers_with_exclusion,
    plan_transfers_with_overlap,
)
from squadopt.live.recommendation import InSeasonProjection
from squadopt.live.transfers import HeldSquad, TransferDecision
from squadopt.optimization import (
    OptimizationConfig,
    SolverExecutionError,
    SolverStatus,
    wall_clock_stopped_the_search,
)
from squadopt.planning import (
    FirstWeekExclusion,
    FirstWeekOverlap,
    PlanningWeekResult,
    ProjectionHorizon,
    TransferPlanningConfig,
    TransferPlanningError,
    TransferPlanResult,
)

#: The multi-week solve's budget, as the system's own horizon path spends it: twenty
#: deterministic units per gameweek, under one wall-clock ceiling. A plan the budget
#: cannot prove is published FEASIBLE with its gap, never dropped.
WINDOW_DETERMINISTIC_UNITS_PER_WEEK = 20.0
#: The wall-clock ceiling is a safety stop, never a budget. Only the deterministic budget
#: above may decide where a truncated search stops, because only it is a function of the
#: inputs; ``build_window_payload`` refuses a plan this ceiling cut short rather than
#: publishing one build's answer as though a second build would find it.
#:
#: 300.0 was the previous value and it was too close to the work to be a safety stop. On
#: the GW4 capture ``fpl-live-20260907T131414Z-db9314d00961``, the fifteen registered
#: members' five-week windows spend their full hundred deterministic units in 191.7s to
#: 295.8s of wall clock when the site builder runs them across its own fifteen-worker
#: pool -- the hardest member finished 4.2s inside the ceiling, before the rival menu's
#: own solves are added to the same pool. Any load beyond that measurement and the clock
#: stopped the search instead, which is how two builds of one capture came to publish two
#: different five-week plans. 1800.0 is six times the measured worst case: it cannot bind
#: on work this machine has been seen to do, and still ends a run that is twelve times
#: slower than any measured one.
WINDOW_WALL_CEILING_SECONDS = 1800.0
#: CP-SAT's linearization level for a member window, and for nothing else. At the
#: solver's default every published three- and five-week plan of the GW5 capture was
#: an incumbent with sixteen to fifty-nine points between it and its bound; at 2, under
#: the same deterministic budget, fifteen of fifteen three-week plans and twelve of
#: fifteen five-week plans are proved. The one-week plan, the system's own horizon path
#: and every measurement runner do not pass it and solve as they always did.
WINDOW_LINEARIZATION_LEVEL = 2

#: Builds the projection horizon for the requested consecutive gameweeks from the one
#: capture the advice is answered from. Bound by the caller (``member_horizon_builder``)
#: so the request stays wire-shaped and the horizon is built once per window, not per
#: member: it depends on the capture and the handoff only, never on whose squad asks.
HorizonBuilder = Callable[[tuple[int, ...]], ProjectionHorizon]


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


#: What a payload carries when the decision it renders came without its plan week.
_NO_LINEUP: dict[str, object] = {
    "expected_own_points": None,
    "captain": None,
    "vice_captain": None,
    "starting_xi": None,
    "bench": None,
    "chip": None,
}


def _paired_by_position(
    outs: Sequence[int],
    ins: Sequence[int],
    *,
    by_id: "dict[int, pd.Series[Any]]",
    pool_by_id: "dict[int, pd.Series[Any]]",
) -> list[tuple[int | None, int | None]]:
    """Match each outgoing player with an incoming player of the same pitch position.

    Both lists arrive sorted by player id — the planner sorts its table with
    ``sort_players_by_id`` and the decision keeps that order — and an FPL element code
    says nothing about the player's position, so pairing the two lists by index
    publishes rows naming swaps the game's own transfer screen would refuse. The squad
    quotas hold each position's count fixed across a week, so a position-matched pairing
    always exists for a solved plan.

    A player the projection cannot resolve has no position to match on, and a position
    whose two counts disagree has no such pairing at all; whatever is left over after
    the matched pairs is paired in id order at the end rather than dropped, so the row
    set and the summed delta never change. Those leftovers are the only rows that can
    name two positions.
    """

    def position_of(player: int, table: "dict[int, pd.Series[Any]]") -> str | None:
        row = table.get(player)
        return None if row is None else str(row["position"])

    waiting: dict[str, list[int]] = {}
    spare_ins: list[int] = []
    for player_in in ins:
        position = position_of(player_in, by_id)
        if position is None:
            spare_ins.append(player_in)
        else:
            waiting.setdefault(position, []).append(player_in)
    pairs: list[tuple[int | None, int | None]] = []
    spare_outs: list[int] = []
    for player_out in outs:
        position = position_of(player_out, pool_by_id)
        queue = waiting.get(position) if position is not None else None
        if queue:
            pairs.append((player_out, queue.pop(0)))
        else:
            spare_outs.append(player_out)
    leftover_ins = sorted([*(player for queue in waiting.values() for player in queue), *spare_ins])
    for index in range(max(len(spare_outs), len(leftover_ins))):
        pairs.append(
            (
                spare_outs[index] if index < len(spare_outs) else None,
                leftover_ins[index] if index < len(leftover_ins) else None,
            )
        )
    return pairs


def _attributed_gains(
    pairs: Sequence[tuple[int | None, int | None]],
    *,
    held: Sequence[int],
    lookup: dict[int, tuple[str, float]],
    exclusion: FirstWeekExclusion | None = None,
    choice: Mapping[int, float] | None = None,
    expected_total: float | None = None,
) -> list[float] | None:
    """Each swap's share of what the plan is worth against holding the squad.

    One basis, the published one: the eleven with the captain doubled. The moves are
    applied to the held fifteen in the order the rows are printed, the eleven is re-chosen
    after each of them (``best_eleven_points``), and a row is what that total moved by. So
    the rows add up to the whole plan's gain against doing nothing, exactly, and a swap
    whose outgoing player was never going to start prints what it is really worth rather
    than a difference between two names.

    The order is the rows' own, which makes each row conditional on the ones above it: the
    second of two swaps into the same position is credited only with what it adds on top
    of the first. That is a choice, not a measurement, and it is the only decomposition
    that is exactly additive; the card says the rows are read in order.

    ``None`` when the chain cannot be walked at all: a player neither table names, a row
    with no outgoing or no incoming player, or an intermediate fifteen holding no legal
    eleven. Nothing is then published for any row, because a row whose value was not
    measured is not a row worth zero.
    """

    squad = list(held)
    if any(player not in lookup for player in squad):
        return None

    def value_of(players: Sequence[int]) -> float | None:
        if choice is not None:
            # The eleven a plan chosen on other points would field, stated on these.
            if any(player not in choice for player in players):
                return None
            return best_eleven_basis(
                (
                    lookup[player][0],
                    choice[player],
                    lookup[player][1],
                    exclusion is None or player not in exclusion.not_starting,
                    exclusion is None or player not in exclusion.not_captain,
                    player,
                )
                for player in players
            )
        if exclusion is None:
            return best_eleven_points(lookup[player] for player in players)
        return best_eleven_points_under(
            (
                *lookup[player],
                player not in exclusion.not_starting,
                player not in exclusion.not_captain,
            )
            for player in players
        )

    previous = value_of(squad)
    if previous is None:
        return None
    gains: list[float] = []
    for player_out, player_in in pairs:
        if player_out is None or player_in is None:
            return None
        if player_out not in squad or player_in in squad or player_in not in lookup:
            return None
        squad[squad.index(player_out)] = player_in
        value = value_of(squad)
        if value is None:
            return None
        gains.append(value - previous)
        previous = value
    # Rows are shares of the published total. A chain that ends anywhere else read a
    # different eleven from the one the plan fields (a tie the solver broke another
    # way), so its rows describe nothing the member will see, and none is published.
    if expected_total is not None and abs(previous - expected_total) > 1e-6:
        return None
    return gains


def _moves(
    outs: Sequence[int],
    ins: Sequence[int],
    *,
    by_id: "dict[int, pd.Series[Any]]",
    pool_by_id: "dict[int, pd.Series[Any]]",
    held: Sequence[int],
    gameweek: int,
    reason_code: str,
    exclusion: FirstWeekExclusion | None = None,
    move_reason: Callable[[int | None, int | None], str] | None = None,
    choice: Mapping[int, float] | None = None,
    expected_total: float | None = None,
) -> tuple[list[dict[str, object]], float | None]:
    """The published moves and what the whole set is worth against holding the squad.

    Out/in pairs by pitch position. ``by_id`` resolves the incoming players (the plan's
    own squad rows), ``pool_by_id`` the outgoing ones (the shared projection), and
    ``held`` is the fifteen the member holds, which is where the comparison starts.

    Each row's ``expected_points_delta`` is on the same basis as the payload's
    ``expected_own_points``: the eleven with the captain doubled. A raw difference between
    the two players' own projections is not that, and was not comparable with anything
    else the card prints; see ``_attributed_gains``. Where the decomposition cannot be
    walked, every row publishes ``null`` and so does the total, rather than a zero nobody
    measured.

    A move carries no cost of its own. The week's hit charge is a property of the week —
    the game takes four points once for each transfer beyond the free ones, and nothing
    here measures what share of that belongs to one swap — so it is published once,
    beside ``moves``, as the payload's ``transfer_hit_points``, and the gain returned here
    is before it.
    """

    pairs = _paired_by_position(outs, ins, by_id=by_id, pool_by_id=pool_by_id)
    lookup: dict[int, tuple[str, float]] = {
        player: (str(row["position"]), float(str(row["expected_points"])))
        for table in (pool_by_id, by_id)
        for player, row in table.items()
    }
    gains = _attributed_gains(
        pairs,
        held=held,
        lookup=lookup,
        exclusion=exclusion,
        choice=choice,
        expected_total=expected_total if choice is not None else None,
    )
    moves: list[dict[str, object]] = []
    for index, (player_out, player_in) in enumerate(pairs):
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
                "expected_points_delta": None if gains is None else gains[index],
                "reason_code": (
                    reason_code if move_reason is None else move_reason(player_out, player_in)
                ),
            }
        )
    return moves, (None if gains is None else math.fsum(gains))


def _published_total(lineup: Mapping[str, object]) -> float | None:
    total = lineup.get("expected_own_points")
    return float(str(total)) if total is not None else None


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


def publish_price_ceiling(target: dict[str, object], price: float, *, anchor_proven: bool) -> None:
    """Set ``expected_points_cost_ceiling`` on ``target``: the price itself, under a proof only.

    A price is the net expected points of the plan it is measured against (the anchor: the
    member's own pure-points plan) less the priced plan's, both at the game's hit charge.
    Under ``OPTIMAL`` the anchor is the plan the planner returns with its proof finished,
    so the price is measured against the right plan and the most the priced plan can cost
    is the price: the ceiling is that number. It reads as "at most" where only the priced
    plan's own proof is missing, since a better priced plan could only cost less.

    Without a proof on the anchor, nothing published bounds the price. The solver's gap
    (``absolute_optimality_gap``) is in planner-objective units, not expected points: the
    eleven with the captain doubled, plus a tenth of the bench, less each paid transfer
    at the planning charge. The plan the search did not reach can therefore out-net the
    anchor by the gap, plus a tenth of the bench the anchor carries, plus the planning
    charge less the game's four points for every paid transfer it makes beyond the
    anchor's. The member's own plan is solved under the caution margin of 8, so on an
    uncapped week that last term is bounded by nothing but the squad size. The rival
    price's anchor is solved at the charge and has no such term; it keeps the same rule
    so that the sentence means one thing on every document. So no figure is published:
    the key is left out (and removed if a copied document carried one) rather than
    written as zero, and the page prints no price sentence.
    """

    if anchor_proven:
        target["expected_points_cost_ceiling"] = float(price)
    else:
        target.pop("expected_points_cost_ceiling", None)


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


#: No plan on this path is offered a chip. Every member solve, one week and window alike,
#: is handed an empty chip availability, so a payload's ``chip: null`` says the plan plays
#: none and not that a chip was weighed and declined. Named here because the one-week
#: payload states the same limit the windows state, in the same words, from one place.
NO_CHIP_LIMIT: str = (
    "No chip is offered inside the window. A finite window counts nothing for "
    "holding a chip back, so a planner that could reach one would spend it; chip "
    "timing is a season-long decision this window cannot price."
)

#: What a one-week plan assumes. The windows carry six sentences; the only one of them
#: that is also true here is the chip, and it is the one a reader cannot otherwise tell
#: from the payload: "no chip this week" is what a plan that never considered one looks
#: like, so without this sentence the absence reads as a decision.
ONE_WEEK_STATED_LIMITS: tuple[str, ...] = (NO_CHIP_LIMIT,)


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
    clock_stopped_the_search: bool | None = None,
    week: PlanningWeekResult | None = None,
    control: MemberControl | None = None,
    phase_e_diagnostic: TransferAdviceDiagnostic | None = None,
    reason_code: str | None = None,
    exclusion: FirstWeekExclusion | None = None,
    move_reason: Callable[[int | None, int | None], str] | None = None,
    choice_points: Mapping[int, float] | None = None,
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
        clock_stopped_the_search = wall_clock_stopped_the_search(
            plan.solver_status, plan.diagnostics
        )
        week = plan.weeks[0]
    else:
        transfers = decision
        by_id = pool_by_id
    lineup = lineup_fields(week) if week is not None else dict(_NO_LINEUP)
    # The caption the page prints under a move names why the move is in the plan. A
    # sentence about a longer window belongs only to a payload that solved one
    # (``build_window_payload``); this function solves a single week, so the pure-points
    # baseline gets its own reason and a competitive mode keeps its trade-off.
    reason_code = reason_code or ("points_gain" if mode == COMPUTED_MODE else "mode_tradeoff")
    moves: list[dict[str, object]] = []
    transfer_hit_points = 0.0
    # No transfers is a measured answer, not an absent one: the plan's fifteen is the
    # fifteen already held, so what it gains against holding is exactly nothing.
    gain_vs_hold: float | None = 0.0
    if transfers is not None:
        record = transfers.as_record()
        outs_raw = record.get("transfers_out", [])
        ins_raw = record.get("transfers_in", [])
        outs = [int(str(v)) for v in outs_raw] if isinstance(outs_raw, list | tuple) else []
        ins = [int(str(v)) for v in ins_raw] if isinstance(ins_raw, list | tuple) else []
        transfer_hit_points = float(str(record.get("transfer_hit_points", 0.0)))
        moves, gain_vs_hold = _moves(
            outs,
            ins,
            by_id=by_id,
            pool_by_id=pool_by_id,
            held=picks.squad,
            gameweek=picks.gameweek + 1,
            reason_code=reason_code,
            exclusion=exclusion,
            move_reason=move_reason,
            choice=choice_points,
            expected_total=_published_total(lineup),
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
        # The week's hit charge, stated once because that is what it is: the game takes
        # four points for each transfer beyond the free ones, on the week rather than on
        # any one move, so no move row carries it.
        "transfer_hit_points": transfer_hit_points,
        # What the whole plan is worth against simply keeping the fifteen already held,
        # on the same basis as ``expected_own_points`` and as every move row: the eleven
        # with the captain doubled, before the week's hit charge above. Equal to the sum
        # of the rows by construction. ``null`` where the comparison could not be walked.
        "expected_gain_vs_hold": gain_vs_hold,
        # The mode's whole-plan price against the pure-points pick, in expected points —
        # the only cross-mode number the site may show (no probability ships, ever). It
        # is the measured difference between two solved plans, which is the cost itself
        # only when both were proved. A priced path publishes it again as
        # ``expected_points_cost_ceiling`` when the plan it is measured against was
        # proved, which the page reads as "at most" when the priced plan's own proof is
        # missing, and publishes no ceiling when the anchor's proof is missing
        # (``publish_price_ceiling``).
        "expected_points_cost": float(expected_points_cost),
        "rival_label": rival_label,
        # The solver's own account of the plan: OPTIMAL is a proof, FEASIBLE is a found
        # plan with the measured bound gap beside it. Absent proof is stated, not hidden.
        "solver_status": solver_status,
        "optimality_gap": optimality_gap,
        # Which budget stopped the search, which the status alone does not say, and the
        # two are different facts. Deterministic work is machine independent: the same
        # capture under the same budget spends it again and returns the same plan. A
        # search the wall clock stopped is instead a property of what else the machine
        # was doing that minute, and `member_plan_determinism` measured five of fifteen
        # members reading a different plan where the ceiling bound. `null` on documents
        # published before the producer carried these, which is absent and not false.
        "wall_clock_stopped_the_search": clock_stopped_the_search,
        # The rest of the decision: who wears the armband, who stands in for him, the
        # eleven in pitch order, the bench in the order the game's autosubs walk it,
        # and the chip — all in expected points, none of it a probability.
        **lineup,
        # What this plan assumes, in the producer's own sentence. A one-week solve is
        # handed no chip either, and the payload said nothing about it, so a reader had
        # no way to tell a chip that was weighed and declined from one never offered.
        "stated_limits": list(ONE_WEEK_STATED_LIMITS),
        "data_quality": "partial" if missing else "complete",
        "missing_fields": missing,
        # Which squad the advice stands on: the captured week's own, or the one held
        # before a Free Hit voided it (``pre_free_hit_gwNN``), so the page can say so.
        "squad_basis": picks.squad_basis,
    }


#: The one sentence in ``WINDOW_STATED_LIMITS`` that is not true of every projection.
#: The Top-100 uplift is optional — ``build_projection_handoff`` applies it only when it
#: is given the elite evidence table, and both un-uplifted model versions are promoted —
#: so ``window_stated_limits`` reads the projection instead of asserting it.
WINDOW_TOP100_LIMIT: str = (
    "The Top-100 uplift is inside the first week's numbers, and the repetition "
    "carries it into every later week."
)

#: What a three- or five-week window assumes, stated in the payload beside the plan so
#: the reader gets the limits with the answer. Every sentence names a mechanism the code
#: applies; none of them is softened.
WINDOW_STATED_LIMITS: tuple[str, ...] = (
    "The first week's projection is repeated over the later weeks, rescaled by each "
    "club's fixture count in that week relative to its count in the first week, from "
    "the captured calendar; a club with no fixture in the first week stays at zero all "
    "the way through, and the later weeks are not projected separately.",
    "Availability is applied once, from the capture: injuries, rotation and "
    "suspensions after it are not seen.",
    "Every week inside the window, the first included, is capped at one transfer "
    "(a wildcard week excepted); the one-week plan has no such cap.",
    WINDOW_TOP100_LIMIT,
    "Prices are held at the captured values; no price change is modelled.",
    NO_CHIP_LIMIT,
)


def window_stated_limits(projection: Projection) -> list[str]:
    """``WINDOW_STATED_LIMITS`` minus any sentence this projection does not support.

    The uplift sentence states a mechanism as applied, so it may only be published when
    it *was* applied. The handoff records that itself: an elite projection carries the
    evidence fingerprint it was built from, and the un-uplifted versions are forbidden
    from carrying one (``InSeasonProjection``), so a non-null
    ``projection_evidence_fingerprint`` is the fact rather than an assumption about how
    the operator ran the week. Absent, the sentence is dropped rather than softened:
    what the numbers rest on is stated only where it is true.
    """

    carries_uplift = projection.diagnostics.get("projection_evidence_fingerprint") is not None
    if projection.diagnostics.get("projection_source") == "live_football_artifact":
        return [
            "Each future fixture is forecast separately from captured history; blank weeks "
            "are zero only in that week. No future outcomes or injury updates are assumed.",
            *[sentence for sentence in WINDOW_STATED_LIMITS[1:] if sentence != WINDOW_TOP100_LIMIT],
        ]
    return [
        sentence
        for sentence in WINDOW_STATED_LIMITS
        if carries_uplift or sentence != WINDOW_TOP100_LIMIT
    ]


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

    Publishing an unproven plan is honest only while it is the *same* unproven plan on
    every build, and that holds exactly while the deterministic budget is what stopped
    the search. A plan the wall-clock safety cap cut short instead is refused here rather
    than published: where a clock stops a search is a function of the machine, so two
    builds of one capture would publish two different plans and the advice record could
    describe neither.
    """

    horizon = window_horizon(inputs, window, horizon_builder)
    plan = solve_window_plan(picks, inputs, rules, horizon, window=window)
    return window_payload(picks, projection, plan, league_id=league_id, window=window)


def window_horizon(
    inputs: RecommendationInputs, window: int, horizon_builder: HorizonBuilder | None
) -> ProjectionHorizon:
    """The capture's projection horizon for a three- or five-week member window."""

    if window not in MEMBER_WINDOWS or window == COMPUTED_WINDOW:
        raise EntryError(f"Window {window} is not a multi-week member window.")
    if horizon_builder is None:
        raise EntryError(
            f"Window {window} needs a projection horizon builder for this capture; none "
            "was supplied."
        )
    gameweek = int(inputs.deadline.gameweek)
    # A target the captured calendar does not publish is refused by the builder itself.
    return horizon_builder(tuple(range(gameweek, gameweek + window)))


def solve_window_plan(
    picks: EntryPicks,
    inputs: RecommendationInputs,
    rules: SeasonRules,
    horizon: ProjectionHorizon,
    *,
    window: int,
    first_week_overlap: FirstWeekOverlap | None = None,
) -> TransferPlanResult:
    """The multi-week plan under the member window's budget, or a refusal.

    ``first_week_overlap`` is a rival strategy's band on the decided week; ``None`` is the
    pure-points window exactly as it always was.
    """

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
        first_week_overlap=first_week_overlap,
        linearization_level=WINDOW_LINEARIZATION_LEVEL,
    )
    if wall_clock_stopped_the_search(plan.solver_status, plan.diagnostics):
        raise SolverExecutionError(
            f"The {window}-week window for entry {picks.entry_id} was stopped by the "
            f"{WINDOW_WALL_CEILING_SECONDS}s wall-clock safety cap after "
            f"{plan.diagnostics.get('deterministic_time_used')!r} of its "
            f"{plan.diagnostics.get('solver_deterministic_time_limit')!r} deterministic "
            "units. Where the clock stops a search is a function of the machine, not of "
            "the inputs, so this plan is not the plan a second build would find and may "
            "not be published."
        )
    return plan


def window_payload(
    picks: EntryPicks,
    projection: Projection,
    plan: TransferPlanResult,
    *,
    league_id: int,
    window: int,
    mode: str = COMPUTED_MODE,
    weeks: Sequence[PlanningWeekResult] | None = None,
    optimality_gap_published: bool = True,
    move_reason: Callable[[int | None, int | None], str] | None = None,
    choice_points: Mapping[int, float] | None = None,
) -> dict[str, object]:
    """The published shape of a solved window: the first week as a one-week card, the
    whole window in ``plan_weeks``.

    ``weeks`` replaces the plan's own weeks in everything published (a plan chosen on
    other points, restated on the base model's); ``optimality_gap_published`` is false
    when the solver's gap is on that other scale and may not be printed beside them.
    The defaults are the pure-points window, byte for byte.
    """

    shown = tuple(plan.weeks if weeks is None else weeks)
    first = shown[0]
    pool_by_id = {int(str(row["player_id"])): row for _, row in projection.table.iterrows()}
    by_id = {int(str(row["player_id"])): row for _, row in first.selected_squad.iterrows()}
    raw_gap = plan.diagnostics.get("absolute_optimality_gap") if optimality_gap_published else None
    missing = _missing_fields(picks)
    moves, gain_vs_hold = _moves(
        [int(str(v)) for v in first.transfers_out["player_id"].tolist()],
        [int(str(v)) for v in first.transfers_in["player_id"].tolist()],
        by_id=by_id,
        pool_by_id=pool_by_id,
        held=picks.squad,
        gameweek=picks.gameweek + 1,
        reason_code="window_value" if mode == COMPUTED_MODE else "mode_tradeoff",
        move_reason=move_reason,
        choice=choice_points,
        expected_total=_published_total(lineup_fields(first)),
    )
    return {
        "season": picks.season,
        "gameweek": picks.gameweek + 1,
        "entry_id": picks.entry_id,
        "league_id": league_id,
        "mode": mode,
        "window": int(window),
        "source_snapshot_id": picks.source_snapshot_id,
        # The first week's moves, in the one-week shape the page already renders.
        "moves": moves,
        # The first week's hit charge, once, as the one-week payload carries it; the
        # rest of the window's charges are on their own rows in ``plan_weeks``.
        "transfer_hit_points": float(first.transfer_hit_points),
        # The first week's gain against holding, matching the first week's moves and the
        # first week's lineup total; the later weeks are in ``plan_weeks``.
        "expected_gain_vs_hold": gain_vs_hold,
        "expected_points_cost": 0.0,
        "rival_label": None,
        # The solver's own account of the whole window: OPTIMAL is a proof, FEASIBLE is
        # the plan it found with the measured bound gap beside it.
        "solver_status": plan.solver_status.name,
        "optimality_gap": float(str(raw_gap)) if raw_gap is not None else None,
        # Which budget stopped the search. This path already refuses a plan the clock cut
        # short, so the flag published here is always false; it is published anyway, because
        # a reader comparing a window card with a one-week card should not have to know
        # which of them carries the guard to know what the absence of the field means.
        "wall_clock_stopped_the_search": wall_clock_stopped_the_search(
            plan.solver_status, plan.diagnostics
        ),
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
            for week in shown
        ],
        "stated_limits": window_stated_limits(projection),
        "data_quality": "partial" if missing else "complete",
        "missing_fields": missing,
        # Which squad the advice stands on: the captured week's own, or the one held
        # before a Free Hit voided it (``pre_free_hit_gwNN``), so the page can say so.
        "squad_basis": picks.squad_basis,
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
    pricing: TransferPlanResult | None = None,
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

    ``pricing`` is the rival price tag's anchor (``solve_pricing_control``) already solved
    for this member; it depends on neither the rival nor the strategy, so the batch solves
    it once for the whole rival menu. The bytes are identical with or without it.
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
    validate_advice_selection(
        strategy=request.strategy,
        window=request.window,
        entry_id=request.entry_id,
        rival_entry_id=request.rival_entry_id,
    )
    if request.strategy == COMPUTED_MODE:
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
    strategy = STRATEGY_CATALOG[request.strategy]
    floor = strategy.constraints.overlap_floor
    ceiling = strategy.constraints.overlap_ceiling
    assert request.rival_entry_id is not None  # validated by the shared capability contract
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
        pricing=pricing,
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


def _player_ids(frame: "pd.DataFrame") -> set[int]:
    return {int(str(value)) for value in frame["player_id"]}


def _breaks(week: PlanningWeekResult, exclusion: FirstWeekExclusion) -> bool:
    """Whether a solved week starts a player the exclusion benches or captains one it bars."""

    if _player_ids(week.starting_xi) & set(exclusion.not_starting):
        return True
    return int(str(week.captain["player_id"])) in exclusion.not_captain


def _vice_not_barred(payload: dict[str, object], barred: frozenset[object]) -> None:
    """Re-pick the vice-captain when the published one is barred from the armband.

    The vice-captain takes the armband when the captain does not play, so a player the
    page barred from the armband cannot hold it either. The replacement follows the
    completion rule ``lineup_fields`` applies (highest expected points, ties by id) among
    the other starters the rule allows; ``None`` when no starter is allowed.
    """

    vice = payload.get("vice_captain")
    captain = payload.get("captain")
    eleven = payload.get("starting_xi")
    if not isinstance(vice, dict) or not isinstance(captain, dict) or not isinstance(eleven, list):
        return
    if int(str(vice["player_id"])) not in barred:
        return
    captain_id = int(str(captain["player_id"]))
    candidates = [
        player
        for player in eleven
        if isinstance(player, dict)
        and int(str(player["player_id"])) != captain_id
        and int(str(player["player_id"])) not in barred
    ]
    candidates.sort(
        key=lambda player: (
            -float(str(player.get("expected_points", 0.0))),
            int(str(player["player_id"])),
        )
    )
    payload["vice_captain"] = candidates[0] if candidates else None


def _word_evidence(
    words: ManagerWords,
    projection: Projection,
    applied: tuple[ManagerWord, ...],
    *,
    binding: bool,
) -> dict[str, object]:
    """The ``evidence`` block: where the words came from and every statement shown."""

    table = projection.table
    names = (
        {
            int(str(player)): str(name)
            for player, name in zip(
                table["player_id"].tolist(), table["name"].tolist(), strict=True
            )
        }
        if "name" in table.columns
        else {}
    )
    return {
        **words.as_source_record(),
        "binding": binding,
        "applied": [
            {
                "player_id": word.player_id,
                "name": names.get(word.player_id),
                "disposition": word.disposition,
                "role": word.role,
                "speaker": word.speaker,
                "published_at_utc": word.published_at_utc,
                "published_precision": word.published_precision,
                "club": word.club,
                "source_url": word.source_url,
                "fetched_at_utc": word.fetched_at_utc,
                "words": word.words,
                "words_status": word.words_status,
            }
            for word in applied
        ],
    }


def advise_with_managers_word(
    request: AdviseEntryRequest,
    *,
    words: ManagerWords,
    provider: EntryPicksProvider,
    inputs: RecommendationInputs,
    projection: Projection,
    rules: SeasonRules,
    control: MemberControl | None = None,
) -> dict[str, object]:
    """The one-week pure-points plan with the manager's word switched on, priced.

    The member's own squad is still the only starting point; the club's own page
    contributes a constraint (``manager_words``' declared rule: an absence keeps a player
    out of the eleven, a stated doubt keeps him from the armband) and nothing else. No
    projection number moves.

    **Whether the word binds** is read off the member's own control, the pure-points plan
    solved under the same planning policy: if that plan already starts nobody the rule
    benches and captains nobody it bars, it is also the best plan under the rule, so the
    document is the control's plan at a price of zero. Only when the control breaks the
    rule is a second plan solved under it. **The price** compares two plans solved under
    one policy, the control and the constrained plan, net of the hits each pays at the
    game's charge, and is floored at zero. Either way the ceiling is the price when the
    control is proven and is not published when it is not (``publish_price_ceiling``):
    the control's bound gap is on the planner's objective and bounds no price. Anchoring
    on a plan solved at the charge instead (as the rival band does) would put the caution
    margin's own effect on unrelated transfers into the price of the club's word.

    Either way the rows are measured under the rule, and a vice-captain the rule bars from
    the armband is replaced (``_vice_not_barred``).

    **What the member reads** is every statement about a player in the fifteen they hold,
    the fifteen the control would end with, or the fifteen this plan ends with, so a word
    about a player the control would have bought is shown whenever it moved the plan.
    ``binding`` says whether it did. A move carries ``manager_word`` only when it is not
    one the control makes too; the gain each row publishes is measured under the rule.
    """

    if request.strategy != COMPUTED_MODE or request.window != COMPUTED_WINDOW:
        raise EntryError("The manager's word applies to the one-week pure-points plan only.")
    if (words.season, words.gameweek) != (inputs.season, request.gameweek):
        raise EntryError(
            f"The manager's word is for {words.season} gameweek {words.gameweek}, not "
            f"{inputs.season} gameweek {request.gameweek}."
        )
    picks = _requested_picks(request, request.entry_id, provider=provider, inputs=inputs)
    solved = _control_for(picks, control, inputs, projection, rules)
    if not solved.plan.has_solution or not solved.plan.weeks:
        raise EntryError("The pure-points control has no solution; nothing can be priced.")

    def _evidence(applied: tuple[ManagerWord, ...], *, binding: bool) -> dict[str, object]:
        return _word_evidence(words, projection, applied, binding=binding)

    exclusion = words.exclusion()
    control_week = solved.plan.weeks[0]
    control_squad = _player_ids(control_week.selected_squad)
    if exclusion is None or not _breaks(control_week, exclusion):
        payload = build_advice_payload(
            picks,
            inputs,
            projection,
            rules,
            league_id=request.league_id,
            control=solved,
            exclusion=exclusion,
        )
        if exclusion is not None:
            _vice_not_barred(payload, exclusion.not_captain)
        payload["expected_points_cost"] = 0.0
        publish_price_ceiling(
            payload, 0.0, anchor_proven=solved.plan.solver_status is SolverStatus.OPTIMAL
        )
        payload["evidence"] = _evidence(words.about({*picks.squad, *control_squad}), binding=False)
        return payload

    prices = {
        int(str(row["player_id"])): int(str(row["price_tenths"]))
        for _, row in inputs.players.iterrows()
    }
    held = held_squad_from_picks(picks, current_prices=prices)
    plan, decision, _config = plan_transfers_with_exclusion(
        inputs, projection, held, rules, exclusion
    )
    # Both plans are solved under the member planning policy, so the tag is what the rule
    # costs under the policy that chose the plan, not the policy's own caution on other
    # transfers. Floored at zero: the rule only removes plans.
    constrained_net = net_expected_points(plan)
    control_net = max(net_expected_points(solved.plan), constrained_net)
    raw_gap = plan.diagnostics.get("absolute_optimality_gap")
    raw_control_gap = solved.plan.diagnostics.get("absolute_optimality_gap")
    cost = control_net - constrained_net
    record = solved.decision.as_record()
    outs_raw = record.get("transfers_out", [])
    ins_raw = record.get("transfers_in", [])
    control_outs = {int(str(v)) for v in outs_raw} if isinstance(outs_raw, list | tuple) else set()
    control_ins = {int(str(v)) for v in ins_raw} if isinstance(ins_raw, list | tuple) else set()

    def move_reason(player_out: int | None, player_in: int | None) -> str:
        # A swap the control makes too is the pure-points plan's own; only the rest is
        # there because of what the page said.
        if player_out in control_outs and player_in in control_ins:
            return "points_gain"
        return "manager_word"

    payload = build_advice_payload(
        picks,
        inputs,
        projection,
        rules,
        league_id=request.league_id,
        decision=decision,
        expected_points_cost=cost,
        solver_status=plan.solver_status.name,
        optimality_gap=float(str(raw_gap)) if raw_gap is not None else None,
        # Which budget stopped this solve. A gap may be unpublishable because it is on
        # another scale; the work spent and what ended the search are on no scale and are
        # published whatever the gap does.
        clock_stopped_the_search=wall_clock_stopped_the_search(
            plan.solver_status, plan.diagnostics
        ),
        week=plan.weeks[0],
        exclusion=exclusion,
        move_reason=move_reason,
    )
    publish_price_ceiling(
        payload, cost, anchor_proven=solved.plan.solver_status is SolverStatus.OPTIMAL
    )
    payload["control_solver_status"] = solved.plan.solver_status.name
    payload["control_optimality_gap"] = (
        float(str(raw_control_gap)) if raw_control_gap is not None else None
    )
    _vice_not_barred(payload, exclusion.not_captain)
    plan_squad = _player_ids(plan.weeks[0].selected_squad)
    payload["evidence"] = _evidence(
        words.about({*picks.squad, *control_squad, *plan_squad}), binding=True
    )
    return payload


#: What a weighted document assumes, beside the chip sentence every one-week plan states.
TOP100_LIMIT: str = (
    "The plan was chosen with the Top 100 influence at {weight}; every expected-points "
    "number in this document is the base model's, without it."
)


#: What one Top 100 setting's solve may fail with and still be recorded rather than
#: raised: the menu is an addition to the member's week, so a setting the planner could
#: not solve, verify or render is named in the index and the member note, and every
#: other document the member gets stands.
TOP100_SOLVE_ERRORS: tuple[type[Exception], ...] = (
    EntryError,
    DataError,
    SolverExecutionError,
    TransferPlanningError,
    KeyError,
    ValueError,
)
#: What one member's own solve (the baseline, a rival pair, a window) may fail with and
#: still be recorded against that member rather than raised through the batch: the
#: member's data, the planner refusing, or a window the wall clock cut short
#: (``SolverExecutionError``), so one member's clock does not cost every other member their
#: advice. Unlike a Top 100 setting's set it leaves out ``KeyError`` and ``ValueError``: a
#: programming error would hit every member alike, and it should stop the run rather than
#: publish a league in which every member is quietly refused.
MEMBER_SOLVE_ERRORS: tuple[type[Exception], ...] = (
    EntryError,
    DataError,
    SolverExecutionError,
    TransferPlanningError,
)


@dataclass(frozen=True, slots=True)
class Top100Advice:
    """One weight's documents for one member, and what the operator should hear about them.

    ``word_payload`` is the same weight with the manager's word switched on, ``None`` when
    no words were handed in or they could not be applied, with the reason in
    ``word_unavailable``. ``notes`` are for the run's member note, never the page.
    """

    weight: int
    payload: dict[str, object]
    word_payload: dict[str, object] | None = None
    word_unavailable: str = ""
    notes: tuple[str, ...] = ()


def _setting_rows(payload: dict[str, object]) -> None:
    """A row the base model scores below zero is the setting's, whatever else it is.

    A plan chosen under a setting can start a favoured player over a better-projected
    one, so a swap the pure-points plan also makes can read negative on base points. It
    is then in the plan as it stands because of the setting, and says so.
    """

    moves = payload.get("moves")
    for move in moves if isinstance(moves, list) else []:
        delta = move.get("expected_points_delta")
        if isinstance(delta, float) and delta < -1e-9 and move.get("reason_code") != "manager_word":
            move["reason_code"] = "top100_preference"


def _move_ids(decision: TransferDecision) -> tuple[set[int], set[int]]:
    return set(decision.transfers_out_ids), set(decision.transfers_in_ids)


def solve_word_control(
    control: MemberControl,
    words: ManagerWords,
    inputs: RecommendationInputs,
    projection: Projection,
    rules: SeasonRules,
) -> MemberControl:
    """The plan a member sees with the manager's word on and no Top 100 setting.

    The control itself when the word does not break it; otherwise the control re-solved
    under the word, as ``advise_with_managers_word`` solves it. Solved once per member and
    handed to every weight, which each compare their own plan with it.
    """

    exclusion = words.exclusion()
    if not control.plan.weeks:
        raise EntryError("The pure-points control has no solution; nothing can be compared.")
    if exclusion is None or not _breaks(control.plan.weeks[0], exclusion):
        return control
    prices = {
        int(str(row["player_id"])): int(str(row["price_tenths"]))
        for _, row in inputs.players.iterrows()
    }
    held = held_squad_from_picks(control.picks, current_prices=prices)
    plan, decision, config = plan_transfers_with_exclusion(
        inputs, projection, held, rules, exclusion
    )
    return MemberControl(picks=control.picks, plan=plan, decision=decision, transfer_config=config)


def advise_with_top100(
    request: AdviseEntryRequest,
    *,
    weight: int,
    counts: Top100Counts,
    provider: EntryPicksProvider,
    inputs: RecommendationInputs,
    projection: Projection,
    rules: SeasonRules,
    control: MemberControl | None = None,
    words: ManagerWords | None = None,
    word_control: MemberControl | None = None,
) -> Top100Advice:
    """The one-week pure-points plan chosen on Top 100 weighted points, priced on base ones.

    ``projection`` is the published base; ``control`` is the member's own plan on it, the
    weight-zero answer. The weighted plan is solved here from the member's picks and never
    taken from a caller: a control is matched to its member by picks alone, so a handed-in
    base control would publish the unweighted plan under a weight's name.

    **What is published** is the weighted plan's decision (moves, eleven, captain) with
    every number scored on the base projection: the players' expected points, each move's
    gain, the plan's own total. The vice-captain and the bench order follow the base
    points, by the same completion rule every plan uses.

    **The price** is what choosing on the weight gives up in the base model against the
    control, both net of the game's hit charge, floored at zero; the ceiling is the price
    when the control is proven and is not published when it is not
    (``publish_price_ceiling``). A plan the base model scores above the control (the
    planner's objective also weighs the bench and its caution margin, which this total
    does not) is floored and named in ``notes``.

    **With the manager's word**, the weighted plan is re-solved under the declared rule
    when it breaks it, as ``advise_with_managers_word`` does for the control, and the
    price is the combination's against the same control. ``binding`` is judged against
    the weighted plan. A move the control also makes is ``points_gain``; one the weighted
    plan makes and the control does not is ``top100_preference``; any other is there
    because of the word.
    """

    if request.strategy != COMPUTED_MODE or request.window != COMPUTED_WINDOW:
        raise EntryError("The Top 100 influence applies to the one-week pure-points plan only.")
    weight = validate_top100_weight(weight)
    if weight == 0:
        raise EntryError("Weight zero is the published plan; it has no document of its own.")
    picks = _requested_picks(request, request.entry_id, provider=provider, inputs=inputs)
    solved = _control_for(picks, control, inputs, projection, rules)
    if not solved.plan.has_solution or not solved.plan.weeks:
        raise EntryError("The pure-points control has no solution; nothing can be priced.")
    weighted = weighted_projection(projection, counts.counts, weight)
    preferred = solve_member_control(picks, inputs, weighted, rules)
    if not preferred.plan.has_solution or not preferred.plan.weeks:
        raise EntryError(f"The plan at Top 100 influence {weight} has no solution.")
    points = base_points(projection)
    weighted_points = base_points(weighted)
    control_week = solved.plan.weeks[0]
    control_value = base_net(control_week, points)
    control_proven = solved.plan.solver_status is SolverStatus.OPTIMAL
    raw_control_gap = solved.plan.diagnostics.get("absolute_optimality_gap")
    control_outs, control_ins = _move_ids(solved.decision)
    preferred_outs, preferred_ins = _move_ids(preferred.decision)
    changed = decision_changed(
        control_week, solved.decision, preferred.plan.weeks[0], preferred.decision
    )

    def move_reason(player_out: int | None, player_in: int | None) -> str:
        if player_out in control_outs and player_in in control_ins:
            return "points_gain"
        if player_out in preferred_outs and player_in in preferred_ins:
            return "top100_preference"
        return "manager_word"

    def priced(
        plan: TransferPlanResult,
        decision: TransferDecision,
        exclusion: FirstWeekExclusion | None,
        label: str,
        changed: bool,
    ) -> tuple[dict[str, object], tuple[str, ...]]:
        week = plan.weeks[0]
        selected = base_net(week, points)
        cost = max(control_value, selected) - selected
        notes: list[str] = []
        if selected > control_value:
            notes.append(
                f"Top 100 influence {weight}{label}: price floored at 0, the plan scores "
                f"{selected - control_value:.3f} above the control in base points"
            )
        raw_gap = plan.diagnostics.get("absolute_optimality_gap")
        if plan.solver_status is not SolverStatus.OPTIMAL:
            notes.append(
                f"Top 100 influence {weight}{label}: {plan.solver_status.name}, gap "
                f"{raw_gap} in weighted points (not published)"
            )
        payload = build_advice_payload(
            picks,
            inputs,
            projection,
            rules,
            league_id=request.league_id,
            decision=decision,
            expected_points_cost=cost,
            solver_status=plan.solver_status.name,
            # The planner's gap is on the weighted scale; no base-model bound exists for
            # it, so none is published and the page says the proof did not finish.
            optimality_gap=None,
            # Which budget stopped this solve. A gap may be unpublishable because it is on
            # another scale; the work spent and what ended the search are on no scale and are
            # published whatever the gap does.
            clock_stopped_the_search=wall_clock_stopped_the_search(
                plan.solver_status, plan.diagnostics
            ),
            week=rebased_week(week, points),
            exclusion=exclusion,
            move_reason=move_reason,
            # The rows and the gain describe the eleven this plan fields, which was chosen
            # on the weighted points; they are stated on the base ones.
            choice_points=weighted_points,
        )
        publish_price_ceiling(payload, cost, anchor_proven=control_proven)
        _setting_rows(payload)
        payload["control_solver_status"] = solved.plan.solver_status.name
        payload["control_optimality_gap"] = (
            float(str(raw_control_gap)) if raw_control_gap is not None else None
        )
        limits = payload.get("stated_limits")
        payload["stated_limits"] = [
            *(limits if isinstance(limits, list) else []),
            TOP100_LIMIT.format(weight=weight),
        ]
        payload["top100"] = {
            "weight": weight,
            "changed": changed,
            "price_basis": TOP100_PRICE_BASIS,
            **counts.source_record(),
        }
        return payload, tuple(notes)

    payload, notes = priced(preferred.plan, preferred.decision, None, "", changed)
    if words is None:
        return Top100Advice(weight, payload, notes=notes)
    if (words.season, words.gameweek) != (inputs.season, request.gameweek):
        return Top100Advice(
            weight,
            payload,
            word_unavailable=(
                f"The manager's word is for {words.season} gameweek {words.gameweek}, not "
                f"{inputs.season} gameweek {request.gameweek}."
            ),
            notes=notes,
        )
    exclusion = words.exclusion()
    preferred_week = preferred.plan.weeks[0]
    binding = exclusion is not None and _breaks(preferred_week, exclusion)
    prices = {
        int(str(row["player_id"])): int(str(row["price_tenths"]))
        for _, row in inputs.players.iterrows()
    }
    try:
        held = held_squad_from_picks(picks, current_prices=prices)
        if exclusion is not None and binding:
            plan, decision, _config = plan_transfers_with_exclusion(
                inputs, weighted, held, rules, exclusion
            )
        else:
            plan, decision = preferred.plan, preferred.decision
        # "Changed" on this document is against what the member sees with the word on and
        # the setting at 0 (``hoca-sozu.json``), solved once per member by the caller.
        if word_control is not None and word_control.picks != picks:
            raise EntryError("The word's control was solved for another member's picks.")
        zero = (
            word_control
            if word_control is not None
            else solve_word_control(solved, words, inputs, projection, rules)
        )
        word_changed = decision_changed(zero.plan.weeks[0], zero.decision, plan.weeks[0], decision)
        word_payload, word_notes = priced(plan, decision, exclusion, " with the word", word_changed)
    except TOP100_SOLVE_ERRORS as error:
        return Top100Advice(weight, payload, word_unavailable=str(error), notes=notes)
    if exclusion is not None:
        _vice_not_barred(word_payload, exclusion.not_captain)
    shown = {
        *picks.squad,
        *_player_ids(preferred_week.selected_squad),
        *_player_ids(plan.weeks[0].selected_squad),
    }
    word_payload["evidence"] = _word_evidence(
        words, projection, words.about(shown), binding=binding
    )
    return Top100Advice(weight, payload, word_payload, notes=(*notes, *word_notes))


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


def solve_pricing_control(
    inputs: RecommendationInputs,
    projection: Projection,
    held: HeldSquad,
    rules: SeasonRules,
    control: MemberControl,
) -> TransferPlanResult:
    """The rival price tag's anchor: the member's pure-points plan at the game's charge.

    It depends on the member's squad and the shared projection only, never on the rival or
    the strategy, so a caller pricing many documents for one member may solve it once.
    """

    plan, _decision, _config = plan_transfers(
        inputs,
        projection,
        held,
        rules,
        transfer_hit_cost_points=control.transfer_config.hit_points_charged,
    )
    return plan


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
    choice: Projection | None = None,
    pricing: TransferPlanResult | None = None,
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

    The price tag is the pricing control's expected points minus the banded plan's, both
    net of the hits each plan pays and both from this member's own solves. A control the
    solver found but could not prove is used as it is and published beside the tag as
    ``control_solver_status`` with its measured gap; only a control with no solution
    refuses. The tag is published with ``expected_points_cost_ceiling`` beside it only
    when that control is proven, and then the two are the same number: the page reads it
    as the most the band can cost when the banded plan's own proof is missing. An
    unproven control's gap is on the planner's objective and bounds no price, so no
    ceiling is published and the page prints no price (``publish_price_ceiling``).

    Beyond ``rival_entry_id`` — the identity field naming whose squad the tag was priced
    against, which the request itself carries and the reader's client checks the answer
    against — everything added to the payload here is in the strategy's declared
    ``publishes`` set: the mean gap, the overlap count, captain agreement; no spread, no
    probability, ever.

    ``choice`` is a projection the banded plans are *chosen* on while everything published
    stays on ``projection`` (the Top 100 influence: the member's setting decides the plan,
    the base model states and prices it). ``pricing`` is the pricing control already solved
    for this member on ``projection``, so a menu of settings does not solve it again. Both
    default to ``None``, which is this function exactly as it was.
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
    # charged MEMBER_PLANNING_POLICY's caution margin in the objective. The one with the
    # higher net expected points is the advice — a hit is spent only where it pays for
    # itself — and the other is published beside it as the alternative, so the member
    # sees what it would have cost.
    chosen_on = projection if choice is None else choice
    base = None if choice is None else base_points(projection)

    def priced_net(candidate: TransferPlanResult) -> float:
        # What a candidate is worth where the price is stated: its own net, or, for a
        # plan chosen on other points, the base model's net of the week it fields.
        if base is None:
            return net_expected_points(candidate)
        return base_net(candidate.weeks[0], base)

    within_free = _solve_within_free_transfers(
        inputs,
        chosen_on,
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
            *plan_transfers_with_overlap(inputs, chosen_on, held, rules, band)[:2],
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
    # The price tag anchors on a control solved at the game's own charge, not on the
    # published saf-puan control. Both that control and the banded candidates are solved
    # under MEMBER_PLANNING_POLICY's caution margin, which is what decides whether a
    # transfer is worth making at all; but the tag compares two solved plans at what the
    # game actually docks, and the maximiser of ``score - margin * paid`` is not the
    # maximiser of ``score - charge * paid``. A band that forces a paid transfer the
    # margin made the control decline could therefore out-net the control, and the tag
    # went negative — telling a member a strategy hands them points. Solving the anchor
    # at the charge makes the comparison like-for-like: the caution margin still governs
    # what is recommended (every plan published here is solved under it), only the
    # comparison is between maximisers of the same objective.
    pricing_plan = (
        pricing
        if pricing is not None
        else solve_pricing_control(inputs, projection, held, rules, solved)
    )
    raw_control_gap = pricing_plan.diagnostics.get("absolute_optimality_gap")
    # Net of hits on both sides: a band that forces paid transfers costs those hits.
    strategy_net = priced_net(plan)
    pricing_net = net_expected_points(pricing_plan)
    # The solver's bench weight and its own bound gap sit outside that arithmetic, so
    # the anchor is floored at the best plan solved here: a banded candidate is itself a
    # plan with no strategy constraint required, so a member could always play it. The
    # tag is then a price and can never be published as a discount.
    solved_nets = [pricing_net, strategy_net]
    if other is not None:
        solved_nets.append(priced_net(other[0]))
    control_net = max(solved_nets)
    # --- what the tag may be claimed to be, once a proof is missing ------------------
    #
    # Write C* for the plan the pricing solve returns once its proof finishes and S* for
    # the best plan inside the band. The true cost is C* - S*.
    #
    # With the pricing control proven, C* is that plan, so C* = pricing_net <= control_net;
    # and S* >= strategy_net, because the band plan returned here is one a member could
    # play. The cost is then at most the tag, and the ceiling states exactly that: the
    # same number, which the page reads as "at most" when the band plan is the unproven
    # one.
    #
    # With the pricing control unproven, nothing published bounds C* in points: the
    # solver's gap is on its objective, which also counts a tenth of the bench, so a plan
    # the search did not reach can out-net the anchor by more than the gap. No ceiling is
    # published then, and the page prints no price (``publish_price_ceiling``).
    #
    # A floor is never published beside the ceiling: a floor and a ceiling together read
    # as an interval around a central estimate, which the envelope may never look like.
    control_proven = pricing_plan.solver_status is SolverStatus.OPTIMAL
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
        # A gap measured on other points may not be printed beside base-model numbers.
        optimality_gap=(float(str(raw_gap)) if raw_gap is not None and base is None else None),
        # Which budget stopped this solve. A gap may be unpublishable because it is on
        # another scale; the work spent and what ended the search are on no scale and are
        # published whatever the gap does.
        clock_stopped_the_search=wall_clock_stopped_the_search(
            plan.solver_status, plan.diagnostics
        ),
        week=plan.weeks[0] if base is None else rebased_week(plan.weeks[0], base),
        choice_points=None if choice is None else base_points(choice),
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
    # The most this band can cost (see the arithmetic above): the tag itself, published
    # only under a proven pricing control, and never below zero, so a reader who reads
    # only this number is never told a constrained plan hands them points.
    publish_price_ceiling(payload, control_net - strategy_net, anchor_proven=control_proven)
    payload["overlap_count"] = len(squad_ids & rival_eleven)
    # What the strategy asked for, what the free transfers could reach, and the cap
    # itself: a target a member cannot afford without hits is stated, never bought.
    payload["transfer_cap"] = transfer_cap
    payload["overlap_target"] = target
    payload["overlap_applied"] = applied
    payload["plan_kind"] = chosen_kind
    alternative: dict[str, object] | None = None
    if other is not None:
        other_hits = other[0].total_transfer_hit_points
        other_cost = control_net - priced_net(other[0])
        alternative = {
            "kind": (
                "with_hits" if chosen_kind == "within_free_transfers" else "within_free_transfers"
            ),
            "overlap_applied": other[2],
            "transfer_hit_points": float(other_hits) if other_hits is not None else None,
            "expected_points_cost": other_cost,
        }
        # The same rule: the candidate the member did not get is priced against the same
        # control, so it carries a ceiling exactly when the published plan does.
        publish_price_ceiling(alternative, other_cost, anchor_proven=control_proven)
    payload["alternative_plan"] = alternative
    # A mean and only a mean: shared players cancel exactly in the fixed-decision
    # comparison, so this is projection arithmetic over the differentials, net of the
    # hits this plan pays (the rival's future transfers are unknown and not guessed).
    # The spread those same differentials generate is not publishable, and is not
    # computed.
    payload["expected_gap_vs_rival"] = (my_expected - my_hits) - rival_expected
    payload["captain_agreement"] = my_captain == rival_captain
    # The pricing control's own account beside the price it anchors: a FEASIBLE control
    # makes the tag a reading with no ceiling, not a proof.
    payload["control_solver_status"] = pricing_plan.solver_status.name
    payload["control_optimality_gap"] = (
        float(str(raw_control_gap)) if raw_control_gap is not None else None
    )
    return payload


__all__: tuple[str, ...] = (
    "COMPUTED_MODE",
    "COMPUTED_WINDOW",
    "MEMBER_WINDOWS",
    "NO_CHIP_LIMIT",
    "ONE_WEEK_STATED_LIMITS",
    "WINDOW_STATED_LIMITS",
    "WINDOW_TOP100_LIMIT",
    "AdviseEntryRequest",
    "HorizonBuilder",
    "MemberControl",
    "advise_entry",
    "advise_with_managers_word",
    "best_eleven_points",
    "build_advice_payload",
    "build_window_payload",
    "lineup_fields",
    "member_horizon_builder",
    "net_expected_points",
    "publish_price_ceiling",
    "solve_member_control",
    "window_stated_limits",
)
