"""Joint chip and transfer advice, separate from the legacy one-week chip switch."""

from squadopt.application.advice import (
    NO_CHIP_LIMIT,
    WINDOW_DETERMINISTIC_UNITS_PER_WEEK,
    WINDOW_LINEARIZATION_LEVEL,
    WINDOW_WALL_CEILING_SECONDS,
    AdviseEntryRequest,
    HorizonBuilder,
    _requested_picks,
    window_payload,
)
from squadopt.application.advice_chips import (
    FREE_HIT_LIMIT,
    _rows_on_chip_basis,
    chip_week_points,
    member_chip_menu,
)
from squadopt.application.advice_variants import _rebased_weeks, weighted_horizon
from squadopt.application.entries import EntryError, EntryPicksProvider, held_squad_from_picks
from squadopt.application.top100_weight import Top100Counts
from squadopt.contracts.preferences import NO_PREFERENCES, DecisionPreferences
from squadopt.live import Projection, RecommendationInputs, SeasonRules
from squadopt.live.chip_strategy import strategy_chip_availability
from squadopt.live.transfers import plan_transfer_horizon
from squadopt.optimization import (
    OptimizationConfig,
    SolverExecutionError,
    wall_clock_stopped_the_search,
)
from squadopt.planning import ChipAvailability
from squadopt.planning.chip_strategy import CHIP_STRATEGY_VERSION


def advise_chip_strategy(
    request: AdviseEntryRequest,
    *,
    chip: str | None,
    top100_weight: int,
    provider: EntryPicksProvider,
    inputs: RecommendationInputs,
    projection: Projection,
    rules: SeasonRules,
    horizon_builder: HorizonBuilder | None,
    counts: Top100Counts | None = None,
    preferences: DecisionPreferences = NO_PREFERENCES,
) -> dict[str, object]:
    if request.strategy != "saf-puan" or horizon_builder is None:
        raise EntryError("Chip strategy requires the pure-points forecast horizon.")
    if top100_weight and counts is None:
        raise EntryError("Chip strategy requires the requested Top100 inputs.")
    picks = _requested_picks(request, request.entry_id, provider=provider, inputs=inputs)
    if chip is not None and not member_chip_menu(rules, request.gameweek, picks.chips_used).known:
        raise EntryError("Chip strategy requires unambiguous captured chip history.")
    dates = tuple(range(request.gameweek, request.gameweek + request.window))
    base = horizon_builder(dates)
    chosen = (
        weighted_horizon(base, counts.counts, top100_weight)
        if counts is not None and top100_weight
        else base
    )
    rights = (
        strategy_chip_availability(rules, dates, picks.chips_used)
        if chip is not None
        else ChipAvailability()
    )
    automatic = chip == "auto"
    if chip is not None and not automatic:
        if request.gameweek not in rights.gameweeks_for(chip):
            raise EntryError("The chosen chip is not held for this gameweek.")
        # A named chip remains an explicit instruction, not permission to spend others.
        rights = ChipAvailability(
            available={chip: frozenset({request.gameweek})},
            forced={request.gameweek: chip},
        )
    held = held_squad_from_picks(
        picks,
        current_prices={
            int(str(row["player_id"])): int(str(row["price_tenths"]))
            for _, row in inputs.players.iterrows()
        },
    )
    plan, _ = plan_transfer_horizon(
        inputs,
        chosen,
        held,
        rules,
        optimization=OptimizationConfig(
            solver_time_limit_seconds=WINDOW_WALL_CEILING_SECONDS,
            solver_deterministic_time_limit=WINDOW_DETERMINISTIC_UNITS_PER_WEEK * request.window,
        ),
        chips=rights,
        chip_strategy=automatic,
        linearization_level=WINDOW_LINEARIZATION_LEVEL,
        preferences=preferences,
    )
    if wall_clock_stopped_the_search(plan.solver_status, plan.diagnostics):
        raise SolverExecutionError("Chip strategy reached its wall-clock safety limit.")
    shown = _rebased_weeks(plan, base)
    payload = window_payload(
        picks,
        projection,
        plan,
        league_id=request.league_id,
        window=request.window,
        weeks=shown,
        optimality_gap_published=False,
    )
    first = shown[0]
    choice = {
        int(str(row["player_id"])): float(str(row["expected_points"]))
        for _, row in chosen.table.loc[chosen.table.gameweek.eq(request.gameweek)].iterrows()
    }
    if top100_weight or first.chip in ("3xc", "bboost"):
        _rows_on_chip_basis(
            payload,
            picks,
            projection,
            first.chip,
            choice_points=choice if top100_weight else None,
            expected_total=chip_week_points(first),
        )
    # No raw-point cost against a paired no-chip control has been measured here.
    payload.pop("expected_points_cost", None)
    payload["expected_own_points"] = chip_week_points(first)
    rows = payload["plan_weeks"]
    assert isinstance(rows, list)
    for row, week in zip(rows, shown, strict=True):
        row["expected_points"] = chip_week_points(week)
    if preferences.active:
        payload["preferences"] = preferences.payload()
        payload["preferences_scope"] = "all_selected_weeks"
    if chip is None:
        if top100_weight:
            payload["selection_top100_weight"] = top100_weight
        return payload
    raw_strategy = plan.diagnostics.get("chip_strategy")
    detail = dict(raw_strategy) if isinstance(raw_strategy, dict) else {}
    strategy_limits = detail.get("limits", [])
    assert isinstance(strategy_limits, list)
    payload["chip_strategy"] = {
        "version": CHIP_STRATEGY_VERSION,
        "mode": "auto" if automatic else "manual",
        "requested_chip": chip,
        "selected_chip": first.chip,
        "top100_weight": top100_weight,
        "objective_gap": plan.diagnostics.get("absolute_optimality_gap"),
        "objective_basis": "selection_utility_with_chip_reserve",
        "experimental": automatic,
        "reservations": detail.get("reservations", []),
        "limits": strategy_limits,
    }
    limits = payload.get("stated_limits")
    payload["stated_limits"] = [
        *[s for s in (limits if isinstance(limits, list) else []) if s != NO_CHIP_LIMIT],
        *strategy_limits,
        "Only the first week's action is current; "
        "later chip dates are revised with the next capture.",
        FREE_HIT_LIMIT,
    ]
    return payload
