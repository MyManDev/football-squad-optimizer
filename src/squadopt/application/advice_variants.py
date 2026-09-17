"""The member menu beyond the one-week pure-points plan: windows and rival strategies, each
with the Top 100 influence.

Three kinds of document, all batch-only (the on-demand request path still answers what
``advice_capabilities`` lists):

- a **pure-points window** (three or five weeks) chosen on Top 100 weighted points;
- a **rival strategy at one week** chosen on Top 100 weighted points;
- a **rival strategy over a window**, at setting 0 or chosen on weighted points.

The rules are the ones the one-week menu already keeps (``advise_with_top100``). The
setting moves the points a plan is *chosen* on and nothing else; every number published is
the base model's; and the price is the base-model difference against the member's own
pure-points plan for the same window at setting 0, floored at zero, with that control's
own bound slack as the ceiling. A window's solves are found rather than proven, so their
price is nearly always read from the ceiling, and the page says "at most".

The Top 100 counts are the previous gameweek's. A window repeats them over its later weeks
exactly as it repeats the first week's projection, and says so; they are read again when
the next gameweek's selections are in.

A rival band is a first-week constraint in a window too: the decided week is held to the
band, at the strictest level one transfer reaches (a window plans one transfer a week),
and the later weeks are planned for points alone, because nothing about the rival's later
squads is known.
"""

import math
from collections.abc import Mapping
from dataclasses import replace
from typing import Final

from squadopt.application.advice import (
    COMPUTED_MODE,
    COMPUTED_WINDOW,
    TOP100_LIMIT,
    AdviseEntryRequest,
    HorizonBuilder,
    MemberControl,
    Top100Advice,
    _advise_against_rival,
    _requested_picks,
    _solve_within_free_transfers,
    solve_window_plan,
    window_horizon,
    window_payload,
)
from squadopt.application.entries import EntryError, EntryPicksProvider, held_squad_from_picks
from squadopt.application.strategies import STRATEGY_CATALOG
from squadopt.application.top100_weight import (
    TOP100_PRICE_BASIS,
    Top100Counts,
    base_points,
    rebased_week,
    validate_top100_weight,
    weighted_projection,
)
from squadopt.live import Projection, RecommendationInputs, SeasonRules
from squadopt.planning import (
    FirstWeekOverlap,
    PlanningWeekResult,
    ProjectionHorizon,
    TransferPlanResult,
)
from squadopt.prediction.elite_evidence import ELITE_COHORT_SIZE

#: What a window chosen under the Top 100 influence assumes about the counts.
TOP100_WINDOW_LIMIT: Final = (
    "The Top 100 counts are the previous gameweek's and are repeated over every week of "
    "the window; they are read again when the next gameweek's selections are in."
)

#: What a rival strategy over a window holds to the band, and what it does not.
RIVAL_WINDOW_LIMIT: Final = (
    "The band against the rival, the overlap and the expected gap are the first week's, "
    "reached with one transfer; the later weeks are planned for points alone, because the "
    "rival's later squads are not known."
)


def weighted_horizon(
    horizon: ProjectionHorizon, counts: Mapping[int, int], weight: int
) -> ProjectionHorizon:
    """``horizon`` with every week's points scaled by the setting and the player's count.

    The same factor in every week, as the window repeats the first week's projection. A
    blank week's zero stays zero.
    """

    weight = validate_top100_weight(weight)
    table = horizon.table.copy(deep=True)
    if weight:
        support = (
            table["player_id"]
            .map(lambda player: counts.get(int(player), 0))
            .astype("float64")
            .div(float(ELITE_COHORT_SIZE))
        )
        table["expected_points"] = table["expected_points"].astype("float64") * (
            1.0 + weight / 100.0 * support
        )
    return replace(horizon, table=table)


def _points_by_week(horizon: ProjectionHorizon) -> dict[int, dict[int, float]]:
    points: dict[int, dict[int, float]] = {}
    for gameweek, player, value in zip(
        horizon.table["gameweek"].tolist(),
        horizon.table["player_id"].tolist(),
        horizon.table["expected_points"].tolist(),
        strict=True,
    ):
        points.setdefault(int(gameweek), {})[int(str(player))] = float(str(value))
    return points


def _rebased_weeks(
    plan: TransferPlanResult, base: ProjectionHorizon
) -> tuple[PlanningWeekResult, ...]:
    by_week = _points_by_week(base)
    return tuple(rebased_week(week, by_week[int(week.gameweek)]) for week in plan.weeks)


def _window_total(weeks: tuple[PlanningWeekResult, ...]) -> float:
    total = math.fsum(
        float(week.projected_score) - float(week.transfer_hit_points) for week in weeks
    )
    if not math.isfinite(total):
        raise EntryError("A window must score to finite base points.")
    return total


def _control_reading(control_payload: Mapping[str, object]) -> tuple[float, float]:
    """The pure-points window's own total and bound slack, read from what it published."""

    rows = control_payload.get("plan_weeks")
    if not isinstance(rows, list) or not rows:
        raise EntryError(
            "The pure-points window publishes no plan weeks; nothing to price against."
        )
    total = math.fsum(
        float(str(row["expected_points"])) - float(str(row["transfer_hit_points"]))
        for row in rows
        if isinstance(row, Mapping)
    )
    if control_payload.get("solver_status") == "OPTIMAL":
        return total, 0.0
    gap = control_payload.get("optimality_gap")
    if gap is None:
        raise EntryError(
            "The pure-points window is unproven and carries no measured bound gap; its "
            "distance from the best plan may not be read as zero."
        )
    return total, max(0.0, float(str(gap)))


def _signature(payload: Mapping[str, object]) -> tuple[object, ...]:
    """What makes two documents the same plan: every week's moves, the eleven, the armband."""

    def ids(players: object) -> tuple[int, ...]:
        return tuple(
            sorted(
                int(str(player["player_id"]))
                for player in (players if isinstance(players, list) else [])
                if isinstance(player, Mapping)
            )
        )

    rows = payload.get("plan_weeks")
    weeks = tuple(
        (ids(row.get("transfers_out")), ids(row.get("transfers_in")))
        for row in (rows if isinstance(rows, list) else [])
        if isinstance(row, Mapping)
    )
    moves = payload.get("moves")
    first = tuple(
        sorted(
            (
                int(str(move["player_out"]["player_id"])),
                int(str(move["player_in"]["player_id"])),
            )
            for move in (moves if isinstance(moves, list) else [])
            if isinstance(move, Mapping)
            and isinstance(move.get("player_out"), Mapping)
            and isinstance(move.get("player_in"), Mapping)
        )
    )
    captain = payload.get("captain")
    return (
        weeks,
        first,
        ids(payload.get("starting_xi")),
        int(str(captain["player_id"])) if isinstance(captain, Mapping) else None,
    )


def _first_week_moves(payload: Mapping[str, object]) -> set[tuple[int, int]]:
    first = _signature(payload)[1]
    return set(first) if isinstance(first, tuple) else set()


def _price(
    payload: dict[str, object],
    *,
    control_payload: Mapping[str, object],
    selected_total: float,
) -> str:
    """Price a window document against the pure-points window; returns an operator note."""

    control_total, slack = _control_reading(control_payload)
    cost = max(control_total, selected_total) - selected_total
    payload["expected_points_cost"] = cost
    payload["expected_points_cost_ceiling"] = max(cost, control_total + slack - selected_total)
    payload["control_solver_status"] = control_payload.get("solver_status")
    payload["control_optimality_gap"] = control_payload.get("optimality_gap")
    if selected_total > control_total:
        return f"price floored at 0, the plan scores {selected_total - control_total:.3f} above"
    return ""


def _top100_block(weight: int, changed: bool, counts: Top100Counts) -> dict[str, object]:
    return {
        "weight": weight,
        "changed": changed,
        "price_basis": TOP100_PRICE_BASIS,
        **counts.source_record(),
    }


def _relabel_moves(
    payload: dict[str, object], reference: Mapping[str, object] | None, *, kept: str
) -> None:
    """A move the setting-0 document also makes keeps its reason; the rest are the setting's."""

    if reference is None:
        return
    shared = _first_week_moves(reference)
    moves = payload.get("moves")
    for move in moves if isinstance(moves, list) else []:
        out, into = move.get("player_out"), move.get("player_in")
        if not isinstance(out, Mapping) or not isinstance(into, Mapping):
            continue
        pair = (int(str(out["player_id"])), int(str(into["player_id"])))
        move["reason_code"] = kept if pair in shared else "top100_preference"


def _limits(payload: dict[str, object], *sentences: str) -> None:
    current = payload.get("stated_limits")
    payload["stated_limits"] = [*(current if isinstance(current, list) else []), *sentences]


def advise_window_with_top100(
    request: AdviseEntryRequest,
    *,
    weight: int,
    counts: Top100Counts,
    provider: EntryPicksProvider,
    inputs: RecommendationInputs,
    projection: Projection,
    rules: SeasonRules,
    horizon_builder: HorizonBuilder | None,
    control_payload: Mapping[str, object],
) -> Top100Advice:
    """A pure-points window chosen on Top 100 weighted points, stated and priced on base ones.

    ``control_payload`` is the member's own pure-points document for the same window at
    setting 0, as published: the price is measured against it and ``changed`` compares
    with it.
    """

    if request.strategy != COMPUTED_MODE or request.window == COMPUTED_WINDOW:
        raise EntryError("This path is the pure-points window under the Top 100 influence.")
    weight = validate_top100_weight(weight)
    if weight == 0:
        raise EntryError("Setting 0 is the published window; it has no document of its own.")
    picks = _requested_picks(request, request.entry_id, provider=provider, inputs=inputs)
    base = window_horizon(inputs, request.window, horizon_builder)
    plan = solve_window_plan(
        picks, inputs, rules, weighted_horizon(base, counts.counts, weight), window=request.window
    )
    weeks = _rebased_weeks(plan, base)
    payload = window_payload(
        picks,
        projection,
        plan,
        league_id=request.league_id,
        window=request.window,
        weeks=weeks,
        optimality_gap_published=False,
        choice_points=base_points(weighted_projection(projection, counts.counts, weight)),
    )
    _limits(payload, TOP100_LIMIT.format(weight=weight), TOP100_WINDOW_LIMIT)
    note = _price(payload, control_payload=control_payload, selected_total=_window_total(weeks))
    _relabel_moves(payload, control_payload, kept="window_value")
    payload["top100"] = _top100_block(
        weight, _signature(payload) != _signature(control_payload), counts
    )
    label = f"Top 100 influence {weight}, {request.window} weeks"
    notes = [f"{label}: {note}"] if note else []
    return Top100Advice(weight, payload, notes=tuple(notes))


def _band(request: AdviseEntryRequest) -> tuple[int | None, int | None, int]:
    strategy = STRATEGY_CATALOG.get(request.strategy)
    if strategy is None:
        raise EntryError(f"Strategy {request.strategy!r} is not in the catalogue.")
    floor = strategy.constraints.overlap_floor
    ceiling = strategy.constraints.overlap_ceiling
    if floor is None and ceiling is None:
        raise EntryError(f"Strategy {request.strategy!r} carries no overlap band.")
    if request.rival_entry_id is None:
        raise EntryError(f"Strategy {request.strategy!r} needs a rival.")
    if request.rival_entry_id == request.entry_id:
        raise EntryError("A member cannot be their own rival.")
    return floor, ceiling, int(request.rival_entry_id)


def advise_rival_with_top100(
    request: AdviseEntryRequest,
    *,
    weight: int,
    counts: Top100Counts,
    provider: EntryPicksProvider,
    inputs: RecommendationInputs,
    projection: Projection,
    rules: SeasonRules,
    control: MemberControl,
    pricing: TransferPlanResult,
    reference_payload: Mapping[str, object],
) -> Top100Advice:
    """A one-week rival strategy chosen on Top 100 weighted points.

    The band, the free-transfer cap and the two candidates are the rival path's own; only
    the points the candidates are solved and compared on carry the setting. The price is
    the strategy and the setting together, in base points, against the same pricing
    control the strategy alone is priced against. ``reference_payload`` is the same
    strategy against the same rival at setting 0.
    """

    if request.window != COMPUTED_WINDOW:
        raise EntryError("This path is the one-week rival strategy under the Top 100 influence.")
    weight = validate_top100_weight(weight)
    if weight == 0:
        raise EntryError("Setting 0 is the published strategy document.")
    floor, ceiling, rival = _band(request)
    payload = _advise_against_rival(
        request,
        rival_entry_id=rival,
        floor=floor,
        ceiling=ceiling,
        provider=provider,
        inputs=inputs,
        projection=projection,
        rules=rules,
        control=control,
        choice=weighted_projection(projection, counts.counts, weight),
        pricing=pricing,
    )
    _limits(payload, TOP100_LIMIT.format(weight=weight))
    _relabel_moves(payload, reference_payload, kept="mode_tradeoff")
    payload["top100"] = _top100_block(
        weight, _signature(payload) != _signature(reference_payload), counts
    )
    return Top100Advice(weight, payload)


def advise_rival_window(
    request: AdviseEntryRequest,
    *,
    weight: int,
    counts: Top100Counts | None,
    provider: EntryPicksProvider,
    inputs: RecommendationInputs,
    projection: Projection,
    rules: SeasonRules,
    horizon_builder: HorizonBuilder | None,
    control_payload: Mapping[str, object],
    reference_payload: Mapping[str, object] | None = None,
) -> Top100Advice:
    """A rival strategy over a three- or five-week window, at setting 0 or under a setting.

    The band holds the decided week only, at the strictest level one transfer reaches,
    found with one-week solves so the window itself is solved once. The price is against
    the member's pure-points window at setting 0 (``control_payload``). Under a setting,
    ``reference_payload`` is this same document at 0.
    """

    if request.window == COMPUTED_WINDOW:
        raise EntryError("This path is the rival strategy over a multi-week window.")
    weight = validate_top100_weight(weight)
    if weight and counts is None:
        raise EntryError("A Top 100 setting needs the week's counts.")
    floor, ceiling, rival = _band(request)
    picks = _requested_picks(request, request.entry_id, provider=provider, inputs=inputs)
    rival_picks = _requested_picks(request, rival, provider=provider, inputs=inputs)
    rival_eleven = frozenset(int(value) for value in rival_picks.starting_xi)
    rival_captain = int(rival_picks.captain)
    expected = base_points(projection)
    missing = sorted({*rival_eleven, rival_captain} - set(expected))
    if rival_captain not in rival_eleven or missing:
        raise EntryError(
            f"Rival entry {rival} cannot be scored from this projection "
            f"(captain outside the eleven, or players missing: {missing[:5]!r})."
        )
    chosen_on = (
        projection
        if not weight or counts is None
        else weighted_projection(projection, counts.counts, weight)
    )
    prices = {
        int(str(row["player_id"])): int(str(row["price_tenths"]))
        for _, row in inputs.players.iterrows()
    }
    held = held_squad_from_picks(picks, current_prices=prices)
    # A window plans one transfer a week, the first week included, so the band is relaxed
    # to what one transfer reaches. The decided week's feasible set is the same in the
    # one-week problem, which answers in seconds what a window solve answers in minutes.
    reached = _solve_within_free_transfers(
        inputs,
        chosen_on,
        held,
        rules,
        rival_eleven=rival_eleven,
        floor=floor,
        ceiling=ceiling,
        transfer_cap=1,
    )
    if reached is None:
        raise EntryError(
            f"The {request.strategy!r} band cannot be reached with one transfer against "
            f"entry {rival}; a window plans one transfer a week."
        )
    applied = reached[2]
    band = FirstWeekOverlap(
        player_ids=rival_eleven,
        minimum=applied if floor is not None else None,
        maximum=applied if floor is None else None,
    )
    base = window_horizon(inputs, request.window, horizon_builder)
    horizon = (
        base if not weight or counts is None else weighted_horizon(base, counts.counts, weight)
    )
    plan = solve_window_plan(
        picks, inputs, rules, horizon, window=request.window, first_week_overlap=band
    )
    weeks = _rebased_weeks(plan, base) if weight else tuple(plan.weeks)
    payload = window_payload(
        picks,
        projection,
        plan,
        league_id=request.league_id,
        window=request.window,
        mode=request.strategy,
        weeks=weeks if weight else None,
        optimality_gap_published=not weight,
        choice_points=base_points(chosen_on) if weight else None,
    )
    _limits(payload, RIVAL_WINDOW_LIMIT)
    note = _price(payload, control_payload=control_payload, selected_total=_window_total(weeks))
    first = weeks[0]
    squad = {int(str(value)) for value in first.selected_squad["player_id"]}
    eleven = [int(str(value)) for value in first.starting_xi["player_id"]]
    captain = int(str(first.captain["player_id"]))
    mine = math.fsum(expected[player] for player in eleven) + expected[captain]
    theirs = (
        math.fsum(expected[player] for player in sorted(rival_eleven)) + expected[rival_captain]
    )
    payload["rival_label"] = f"entry-{rival}"
    payload["rival_entry_id"] = rival
    payload["overlap_count"] = len(squad & rival_eleven)
    payload["transfer_cap"] = 1
    payload["overlap_target"] = floor if floor is not None else ceiling
    payload["overlap_applied"] = applied
    payload["plan_kind"] = "within_free_transfers"
    payload["alternative_plan"] = None
    payload["expected_gap_vs_rival"] = (mine - float(first.transfer_hit_points)) - theirs
    payload["captain_agreement"] = captain == rival_captain
    label = f"{request.strategy} vs {rival}, {request.window} weeks, Top 100 influence {weight}"
    notes = [f"{label}: {note}"] if note else []
    if weight and counts is not None:
        _limits(payload, TOP100_LIMIT.format(weight=weight), TOP100_WINDOW_LIMIT)
        _relabel_moves(payload, reference_payload, kept="mode_tradeoff")
        payload["top100"] = _top100_block(
            weight,
            reference_payload is None or _signature(payload) != _signature(reference_payload),
            counts,
        )
    return Top100Advice(weight, payload, notes=tuple(notes))
