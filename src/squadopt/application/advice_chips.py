"""A chip the member chose to play, on the one-week pure-points plan.

No plan on the member path is offered a chip (``NO_CHIP_LIMIT``): a finite window counts
nothing for holding one back, so a planner that could reach a chip would spend it. That
stays true here. The planner still never decides a chip. The **member** declares "play
this chip this gameweek", exactly as they switch on the manager's word or set a Top 100
influence, and the solve is handed that one chip, forced (``plan_transfers(chip=...)``).

What the document states is not a price, because a chip is not a constraint that removes
plans: it is the chip week's expected points minus the member's own no-chip plan's, both
net of the game's hit charge, for this gameweek and no other. What the chip would be
worth in a later gameweek is not measured anywhere in this repository, so the document
says so in the producer's own sentence (``CHIP_CHOICE_LIMIT``) and never reads as advice
to play the chip now.

Which chips a member may choose is read from their own captured chip history and the
season's published windows (``chip_states``). A member whose history was not captured is
offered no chip, and the index says why; nothing is guessed.
"""

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Final

from squadopt.application.advice import (
    COMPUTED_MODE,
    COMPUTED_WINDOW,
    NO_CHIP_LIMIT,
    TOP100_SOLVE_ERRORS,
    WINDOW_DETERMINISTIC_UNITS_PER_WEEK,
    WINDOW_WALL_CEILING_SECONDS,
    AdviseEntryRequest,
    MemberControl,
    _control_for,
    _requested_picks,
    build_advice_payload,
    net_expected_points,
)
from squadopt.application.entries import (
    EntryError,
    EntryPicks,
    EntryPicksProvider,
    chip_states,
    held_squad_from_picks,
)
from squadopt.application.lineup_publication import best_lineup_points_with_chip
from squadopt.live import Projection, RecommendationInputs, SeasonRules, plan_transfers
from squadopt.live.rules import CHIP_NAMES
from squadopt.optimization import (
    OptimizationConfig,
    SolverExecutionError,
    wall_clock_stopped_the_search,
)
from squadopt.planning import PlanningWeekResult

#: How the gain on a chip document was measured: two one-week plans solved from the
#: member's own squad on the shared projection, one with the chip forced and one without
#: a chip, each scored as the week is expected to score and net of the game's hit charge.
CHIP_CHOICE_BASIS: Final = "one_week_expected_points_v1"

#: The sentence every chip document states. The gain beside it is one gameweek's, and the
#: question a chip really asks (is this the week to play it) is a season-long one nothing
#: here measures, so the document may not be read as an answer to it.
CHIP_CHOICE_LIMIT: Final = (
    "The chip is in this plan because the member chose it; the planner did not weigh "
    "it. The gain stated is this gameweek's only: what the chip would be worth in a "
    "later gameweek is not measured, so this is not advice to play it now."
)

#: What a Free Hit document states besides: the squad is this gameweek's only.
FREE_HIT_LIMIT: Final = (
    "A Free Hit squad is held for this gameweek only; the squad held before it "
    "returns at the next deadline."
)

#: The chips whose week scores on another basis than the eleven with the captain doubled.
_RESCORED_CHIPS: Final = frozenset({"3xc", "bboost"})

#: What one chip's solve may fail with and still be recorded rather than raised, as one
#: Top 100 setting's may: the chip documents are an addition to the member's week.
CHIP_SOLVE_ERRORS: Final = TOP100_SOLVE_ERRORS

#: Why a chip is not offered to a member this gameweek, as codes the page translates.
CHIP_ALREADY_PLAYED: Final = "already_played"
CHIP_WINDOW_NOT_OPEN: Final = "window_not_open"
CHIP_FREE_HIT_LAST_WEEK: Final = "free_hit_played_last_gameweek"
CHIP_NOT_SOLVED: Final = "not_solved_for_member"

#: Why a member has no chip documents at all.
CHIP_HISTORY_UNKNOWN: Final = "chip_history_unknown"
NO_CHIP_LEFT: Final = "no_chip_left"

#: A forced Wildcard or Free Hit is a whole-squad problem, larger than the one-week
#: control. It is solved under a deterministic budget, the one a window spends on a single
#: week, with the wall clock as a safety stop only: a plan the budget cut short is the
#: same plan on every build and is published FEASIBLE with its gap, and a plan the clock
#: cut short is refused, as ``solve_window_plan`` refuses it and for the same reason.
CHIP_OPTIMIZATION: Final = OptimizationConfig(
    solver_time_limit_seconds=WINDOW_WALL_CEILING_SECONDS,
    solver_deterministic_time_limit=WINDOW_DETERMINISTIC_UNITS_PER_WEEK,
)


@dataclass(frozen=True, slots=True)
class MemberChipMenu:
    """The chips one member may choose this gameweek, and why not the others.

    ``known`` is false when the member's chip history was not captured; then nothing is
    held and nothing is refused by name, because no history is not the same thing as no
    chips played. ``windows`` is each chip's published windows as the member stands
    before this gameweek, the reading ``chip_states`` gives the squad page.
    """

    known: bool
    held: tuple[str, ...]
    unavailable: tuple[tuple[str, str], ...]
    windows: Mapping[str, Mapping[str, dict[str, object] | None]]


def member_chip_menu(
    rules: SeasonRules, gameweek: int, chips_used: Mapping[str, Sequence[int]] | None
) -> MemberChipMenu:
    """Which chips the member can play in ``gameweek``, from their own history."""

    states = chip_states(rules, gameweek, chips_used)
    windows = {
        name: {
            half: None if window is None else window.to_dict() for half, window in halves.items()
        }
        for name, halves in states.items()
    }
    known = chips_used is not None and all(
        window.state != "unknown"
        for halves in states.values()
        for window in halves.values()
        if window is not None
    )
    if not known:
        return MemberChipMenu(False, (), (), windows)
    held: list[str] = []
    unavailable: list[tuple[str, str]] = []
    for name in CHIP_NAMES:
        current = [
            window
            for window in states[name].values()
            if window is not None and window.start_event <= gameweek <= window.stop_event
        ]
        if any(window.state == "available" for window in current):
            held.append(name)
        elif any(window.state == "used" for window in current):
            unavailable.append((name, CHIP_ALREADY_PLAYED))
        elif any(window.state == "not_yet" for window in current):
            # Open and unspent, and still refused: only the Free Hit's consecutive-week
            # rule reads that way (``chip_states``).
            unavailable.append((name, CHIP_FREE_HIT_LAST_WEEK))
        else:
            unavailable.append((name, CHIP_WINDOW_NOT_OPEN))
    return MemberChipMenu(True, tuple(held), tuple(unavailable), windows)


@dataclass(frozen=True, slots=True)
class ChipAdvice:
    """One chip's document for one member, and what the operator should hear about it.

    ``notes`` are for the run's member note, never the page.
    """

    chip: str
    payload: dict[str, object]
    notes: tuple[str, ...] = ()


def chip_week_points(week: PlanningWeekResult) -> float:
    """What a solved week is expected to score with its chip played.

    The planner's ``projected_score`` is the eleven with the captain's multiplier, so a
    Triple Captain is already inside it; a Bench Boost's bench is kept beside it
    (``projected_bench_points``) and scores in full that week.
    """

    score = float(week.projected_score)
    if week.chip == "bboost":
        score += float(week.projected_bench_points)
    if not math.isfinite(score):
        raise EntryError("A chip week must score to finite expected points.")
    return score


def _published_chip_points(payload: Mapping[str, object], chip: str) -> float:
    """The chip week's total, re-added from the rows the document itself publishes."""

    own = payload.get("expected_own_points")
    captain = payload.get("captain")
    bench = payload.get("bench")
    if not isinstance(own, float) or not isinstance(captain, dict) or not isinstance(bench, list):
        raise EntryError("A chip document needs its lineup; the plan published none.")
    if chip == "3xc":
        return own + float(str(captain["expected_points"]))
    if chip == "bboost":
        return own + math.fsum(float(str(player["expected_points"])) for player in bench)
    return own


def _rows_on_chip_basis(
    payload: dict[str, object], picks: EntryPicks, projection: Projection, chip: str
) -> None:
    """Restate the move rows and the gain against holding on the chip week's own basis.

    ``build_advice_payload`` measures every row on the eleven with the captain doubled.
    In a Triple Captain or Bench Boost week that is not what the week scores, so a swap
    for a bench player would print as worth nothing in the one week the bench counts.
    The same chain is walked here (the rows in order, each the change once that swap is
    added to the ones above it) with the fifteen valued as the chip week scores it, and
    "holding" is the held fifteen with the same chip played. Where the chain cannot be
    walked every row and the total publish ``null``, as the shared path does.
    """

    moves = payload.get("moves")
    if not isinstance(moves, list):
        return
    lookup = {
        int(str(row["player_id"])): (str(row["position"]), float(str(row["expected_points"])))
        for _, row in projection.table.iterrows()
    }

    def value_of(players: Sequence[int]) -> float | None:
        if any(player not in lookup for player in players):
            return None
        return best_lineup_points_with_chip((lookup[player] for player in players), chip)

    squad = [int(player) for player in picks.squad]
    previous = value_of(squad)
    gains: list[float] | None = [] if previous is not None else None
    for move in moves:
        if gains is None or previous is None:
            break
        player_out = move.get("player_out") if isinstance(move, dict) else None
        player_in = move.get("player_in") if isinstance(move, dict) else None
        if not isinstance(player_out, dict) or not isinstance(player_in, dict):
            gains = None
            break
        out_id, in_id = int(str(player_out["player_id"])), int(str(player_in["player_id"]))
        if out_id not in squad or in_id in squad:
            gains = None
            break
        squad[squad.index(out_id)] = in_id
        value = value_of(squad)
        if value is None:
            gains = None
            break
        gains.append(value - previous)
        previous = value
    for index, move in enumerate(moves):
        if isinstance(move, dict):
            move["expected_points_delta"] = None if gains is None else gains[index]
    payload["expected_gain_vs_hold"] = None if gains is None else math.fsum(gains)


def advise_with_chip(
    request: AdviseEntryRequest,
    *,
    chip: str,
    provider: EntryPicksProvider,
    inputs: RecommendationInputs,
    projection: Projection,
    rules: SeasonRules,
    control: MemberControl | None = None,
) -> ChipAdvice:
    """The one-week pure-points plan with the member's chosen chip played this gameweek.

    The member's own squad is still the only starting point, and the projection does not
    move. The chip is forced, never weighed: the planner is handed exactly that chip for
    exactly this gameweek and decides everything else (transfers, eleven, captain) around
    it. A chip the member does not hold this gameweek is refused before any solve, from
    the same reading of their history the squad page publishes.

    **What is published** is the one-week shape the card already renders, with ``chip``
    naming the chip and every total on the basis the chip week scores on: a Triple
    Captain's ``expected_own_points`` counts the captain three times, a Bench Boost's
    adds the bench, and their move rows and gain against holding are restated on the same
    basis (``_rows_on_chip_basis``), so the rows still add up to the plan's gain and the
    gain to the lineup total. A Wildcard and a Free Hit score as any week does.

    **What stands where a price would** is ``chip_choice.gain_vs_no_chip``: the chip
    week's expected points minus the member's own no-chip control's, both net of the hits
    each pays at the game's charge. It is this gameweek's only and the document says so
    (``CHIP_CHOICE_LIMIT``); ``NO_CHIP_LIMIT`` would be false here and is left off. The
    gain is published as measured, never floored: the planner's objective also weighs the
    bench and its caution margin, which this total does not, so a forced plan can come
    out below the control, and that is named in ``notes``.

    The chip combines with nothing: not the manager's word, not a Top 100 setting, not a
    window and not a rival strategy.
    """

    if request.strategy != COMPUTED_MODE or request.window != COMPUTED_WINDOW:
        raise EntryError("A chosen chip applies to the one-week pure-points plan only.")
    if chip not in CHIP_NAMES:
        raise EntryError(
            f"Chip {chip!r} is not one a member can choose; the game has {CHIP_NAMES!r}."
        )
    picks = _requested_picks(request, request.entry_id, provider=provider, inputs=inputs)
    menu = member_chip_menu(rules, request.gameweek, picks.chips_used)
    if not menu.known:
        raise EntryError(
            f"Entry {picks.entry_id}'s chip history was not captured; no chip can be offered."
        )
    if chip not in menu.held:
        reason = dict(menu.unavailable).get(chip, CHIP_WINDOW_NOT_OPEN)
        raise EntryError(
            f"Entry {picks.entry_id} cannot play {chip!r} in gameweek {request.gameweek}: {reason}."
        )
    solved = _control_for(picks, control, inputs, projection, rules)
    if not solved.plan.has_solution or not solved.plan.weeks:
        raise EntryError("The pure-points control has no solution; nothing can be compared.")
    prices = {
        int(str(row["player_id"])): int(str(row["price_tenths"]))
        for _, row in inputs.players.iterrows()
    }
    held = held_squad_from_picks(picks, current_prices=prices)
    plan, decision, _config = plan_transfers(
        inputs, projection, held, rules, optimization=CHIP_OPTIMIZATION, chip=chip
    )
    if wall_clock_stopped_the_search(plan.solver_status, plan.diagnostics):
        raise SolverExecutionError(
            f"The {chip!r} plan for entry {picks.entry_id} was stopped by the "
            f"{WINDOW_WALL_CEILING_SECONDS}s wall-clock safety cap, not by its deterministic "
            "budget, so it is not the plan a second build would find and may not be published."
        )
    week = plan.weeks[0]
    if week.chip != chip:
        raise EntryError(f"The forced {chip!r} plan came back playing {week.chip!r}.")
    raw_gap = plan.diagnostics.get("absolute_optimality_gap")
    raw_control_gap = solved.plan.diagnostics.get("absolute_optimality_gap")
    payload = build_advice_payload(
        picks,
        inputs,
        projection,
        rules,
        league_id=request.league_id,
        decision=decision,
        solver_status=plan.solver_status.name,
        optimality_gap=float(str(raw_gap)) if raw_gap is not None else None,
        # This path refuses a clock-stopped plan above, so the flag is always false here.
        # It is published anyway: a reader comparing two cards should not have to know
        # which of them carries the guard to know what an absent field means.
        clock_stopped_the_search=wall_clock_stopped_the_search(
            plan.solver_status, plan.diagnostics
        ),
        week=week,
    )
    # The lineup total is published as the chip week scores, and it must be both what the
    # planner counted and what a reader re-adds from the rows beside it.
    chip_points = chip_week_points(week)
    published = _published_chip_points(payload, chip)
    if not math.isclose(published, chip_points, rel_tol=0.0, abs_tol=1e-6):
        raise EntryError(
            f"The {chip!r} week re-adds to {published!r} from its published rows and the "
            f"planner counted {chip_points!r}."
        )
    payload["expected_own_points"] = published
    if chip in _RESCORED_CHIPS:
        _rows_on_chip_basis(payload, picks, projection, chip)
    chip_net = net_expected_points(plan) + (chip_points - float(week.projected_score))
    gain = chip_net - net_expected_points(solved.plan)
    notes: list[str] = []
    if gain < 0.0:
        notes.append(
            f"chip {chip}: the forced plan scores {-gain:.3f} below the no-chip control, "
            "net of hits; published as measured"
        )
    if plan.solver_status.name != "OPTIMAL":
        notes.append(f"chip {chip}: {plan.solver_status.name}, gap {raw_gap}")
    payload["control_solver_status"] = solved.plan.solver_status.name
    payload["control_optimality_gap"] = (
        float(str(raw_control_gap)) if raw_control_gap is not None else None
    )
    limits = payload.get("stated_limits")
    payload["stated_limits"] = [
        *(
            sentence
            for sentence in (limits if isinstance(limits, list) else [])
            if sentence != NO_CHIP_LIMIT
        ),
        CHIP_CHOICE_LIMIT,
        *((FREE_HIT_LIMIT,) if chip == "freehit" else ()),
    ]
    payload["chip_choice"] = {
        "chip": chip,
        "gain_vs_no_chip": gain,
        "basis": CHIP_CHOICE_BASIS,
        "windows_left": dict(menu.windows[chip]),
    }
    return ChipAdvice(chip, payload, tuple(notes))
