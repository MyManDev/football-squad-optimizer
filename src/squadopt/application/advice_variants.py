"""The member menu beyond the one-week pure-points plan: windows and rival strategies, each
with the Top 100 influence.

Three kinds of document. The batch publishes them against the default rival only; a
request reaches each of them, against any rival, through ``advice_menu.advise_menu_entry``:

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

import copy
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
    _setting_rows,
    _solve_within_free_transfers,
    solve_window_plan,
    unproven_bench_allowance,
    window_horizon,
    window_payload,
    window_stated_limits,
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


def _players(payload: Mapping[str, object], key: str) -> list[Mapping[str, object]]:
    rows = payload.get(key)
    return [row for row in rows if isinstance(row, Mapping)] if isinstance(rows, list) else []


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


def _control_bench_bound(control_payload: Mapping[str, object], base: ProjectionHorizon) -> float:
    """No less than the bench points the pure-points window carries, from what it published.

    The payload names the first week's fifteen and every week's transfers, so each week's
    fifteen is known; its eleven is not, beyond the first. A week's bench is the fifteen
    less the eleven, and the eleven scores its published total less the captain's double,
    who is at most the fifteen's best player: so the fifteen's points, less that total,
    plus the best player's, is never below the bench. A bound, used only to keep an
    unproven ceiling honest.
    """

    by_week = _points_by_week(base)
    squad = {
        int(str(player["player_id"]))
        for key in ("starting_xi", "bench")
        for player in _players(control_payload, key)
    }
    bound = 0.0
    rows = control_payload.get("plan_weeks")
    for index, row in enumerate(rows if isinstance(rows, list) else []):
        if index:
            squad -= {int(str(p["player_id"])) for p in row.get("transfers_out", [])}
            squad |= {int(str(p["player_id"])) for p in row.get("transfers_in", [])}
        points = by_week.get(int(str(row["gameweek"])), {})
        held = [points.get(player, 0.0) for player in squad]
        if held:
            bound += max(0.0, math.fsum(held) - float(str(row["expected_points"])) + max(held))
    return bound


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
    # A later week can differ in its eleven or armband alone (a double gameweek under a
    # setting), and only its total shows it, so the total is part of what a week is.
    weeks = tuple(
        (
            ids(row.get("transfers_out")),
            ids(row.get("transfers_in")),
            round(float(str(row.get("expected_points", 0.0))), 6),
        )
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
    base: ProjectionHorizon,
) -> str:
    """Price a window document against the pure-points window; returns an operator note."""

    control_total, slack = _control_reading(control_payload)
    allowance = unproven_bench_allowance(slack, _control_bench_bound(control_payload, base))
    cost = max(control_total, selected_total) - selected_total
    payload["expected_points_cost"] = cost
    payload["expected_points_cost_ceiling"] = max(
        cost, control_total + slack + allowance - selected_total
    )
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

    if reference is not None:
        shared = _first_week_moves(reference)
        moves = payload.get("moves")
        for move in moves if isinstance(moves, list) else []:
            out, into = move.get("player_out"), move.get("player_in")
            if not isinstance(out, Mapping) or not isinstance(into, Mapping):
                continue
            pair = (int(str(out["player_id"])), int(str(into["player_id"])))
            move["reason_code"] = kept if pair in shared else "top100_preference"
    _setting_rows(payload)


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
    note = _price(
        payload, control_payload=control_payload, selected_total=_window_total(weeks), base=base
    )
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


def band_level_with_one_transfer(
    request: AdviseEntryRequest,
    *,
    provider: EntryPicksProvider,
    inputs: RecommendationInputs,
    projection: Projection,
    rules: SeasonRules,
) -> int:
    """The strictest level of the strategy's band one transfer reaches against the rival.

    The band constrains which fifteen is held and carries no points, so the level depends
    on the member, the rival and the strategy only: not on the window, and not on a Top 100
    setting. A caller rendering a member's whole menu finds it once.
    """

    floor, ceiling, rival = _band(request)
    picks = _requested_picks(request, request.entry_id, provider=provider, inputs=inputs)
    rival_picks = _requested_picks(request, rival, provider=provider, inputs=inputs)
    prices = {
        int(str(row["player_id"])): int(str(row["price_tenths"]))
        for _, row in inputs.players.iterrows()
    }
    # A window plans one transfer a week, the first week included, so the band is relaxed
    # to what one transfer reaches. The decided week's feasible set is the same in the
    # one-week problem, which answers in seconds what a window solve answers in minutes.
    reached = _solve_within_free_transfers(
        inputs,
        projection,
        held_squad_from_picks(picks, current_prices=prices),
        rules,
        rival_eleven=frozenset(int(value) for value in rival_picks.starting_xi),
        floor=floor,
        ceiling=ceiling,
        transfer_cap=1,
    )
    if reached is None:
        raise EntryError(
            f"The {request.strategy!r} band cannot be reached with one transfer against "
            f"entry {rival}; a window plans one transfer a week."
        )
    return reached[2]


def _fifteen(payload: Mapping[str, object]) -> set[int]:
    return {
        int(str(player["player_id"]))
        for key in ("starting_xi", "bench")
        for player in _players(payload, key)
    }


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
    applied_level: int | None = None,
    pure_payload: Mapping[str, object] | None = None,
) -> Top100Advice:
    """A rival strategy over a three- or five-week window, at setting 0 or under a setting.

    The band holds the decided week only, at the strictest level one transfer reaches
    (``band_level_with_one_transfer``; ``applied_level`` hands in one already found). The
    price is against the member's pure-points window at setting 0 (``control_payload``).
    Under a setting, ``reference_payload`` is this same document at 0.

    ``pure_payload`` is the pure-points window at this same setting. When its first week
    already holds the band it is the banded plan too, exactly as the manager's word reads
    whether it binds off the control: the best plan without the band, holding the band, is
    a best plan with it. It is then restated as the strategy's document and no window is
    solved again. It is used only when it holds the band; otherwise the window is solved.
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
    applied = (
        applied_level
        if applied_level is not None
        else band_level_with_one_transfer(
            request, provider=provider, inputs=inputs, projection=projection, rules=rules
        )
    )
    base = window_horizon(inputs, request.window, horizon_builder)
    holds = pure_payload is not None and (
        len(_fifteen(pure_payload) & rival_eleven) >= applied
        if floor is not None
        else len(_fifteen(pure_payload) & rival_eleven) <= applied
    )
    if pure_payload is not None and holds:
        payload = copy.deepcopy(dict(pure_payload))
        payload["mode"] = request.strategy
        moves = payload.get("moves")
        for move in moves if isinstance(moves, list) else []:
            if move.get("reason_code") == "window_value":
                move["reason_code"] = "mode_tradeoff"
        payload["stated_limits"] = window_stated_limits(projection)
        payload.pop("top100", None)
        rows = payload.get("plan_weeks")
        selected_total = math.fsum(
            float(str(row["expected_points"])) - float(str(row["transfer_hit_points"]))
            for row in (rows if isinstance(rows, list) else [])
        )
    else:
        chosen_on = (
            projection
            if not weight or counts is None
            else weighted_projection(projection, counts.counts, weight)
        )
        band = FirstWeekOverlap(
            player_ids=rival_eleven,
            minimum=applied if floor is not None else None,
            maximum=applied if floor is None else None,
        )
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
        selected_total = _window_total(weeks)
    _limits(payload, RIVAL_WINDOW_LIMIT)
    note = _price(
        payload, control_payload=control_payload, selected_total=selected_total, base=base
    )
    eleven = sorted(int(str(player["player_id"])) for player in _players(payload, "starting_xi"))
    captain_row = payload.get("captain")
    if len(eleven) != 11 or not isinstance(captain_row, Mapping):
        raise EntryError("The window's first week publishes no eleven to compare with the rival.")
    captain = int(str(captain_row["player_id"]))
    mine = math.fsum(expected[player] for player in eleven) + expected[captain]
    theirs = (
        math.fsum(expected[player] for player in sorted(rival_eleven)) + expected[rival_captain]
    )
    payload["rival_label"] = f"entry-{rival}"
    payload["rival_entry_id"] = rival
    payload["overlap_count"] = len(_fifteen(payload) & rival_eleven)
    payload["transfer_cap"] = 1
    payload["overlap_target"] = floor if floor is not None else ceiling
    payload["overlap_applied"] = applied
    payload["plan_kind"] = "within_free_transfers"
    payload["alternative_plan"] = None
    payload["expected_gap_vs_rival"] = (
        mine - float(str(payload.get("transfer_hit_points", 0.0)))
    ) - theirs
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
