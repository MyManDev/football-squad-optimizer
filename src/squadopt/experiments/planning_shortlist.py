"""Forecast-only candidate reduction; optimality applies only to this subset."""

from collections.abc import Iterable

from squadopt.planning import InitialSquadState, PlanningHorizon


def shortlist_horizon(
    horizon: PlanningHorizon,
    initial: InitialSquadState,
    *,
    required_players: Iterable[object] = (),
    top_per_position: int = 8,
    cheap_per_position: int = 5,
) -> PlanningHorizon:
    """Keep holdings, required IDs, weekly leaders and budget alternatives.

    This is a heuristic restriction, not dominance elimination. Forecasts, prices,
    identity and every selected player's weeks are preserved. No outcomes enter.
    Callers must label any solver proof as restricted to the selected universe.
    """
    for count in (top_per_position, cheap_per_position):
        if isinstance(count, bool) or not isinstance(count, int) or count < 1:
            raise ValueError("Shortlist counts must be positive integers.")
    table = horizon.validated_copy().table
    selected = set(initial.squad_player_ids) | set(required_players)
    if not selected <= set(table.player_id):
        raise ValueError("Held and required players must exist in the horizon.")
    for _, group in table.groupby(["gameweek", "position"], sort=True):
        ranked = group.sort_values(
            ["expected_points", "player_id"], ascending=[False, True], kind="stable"
        )
        cheap = group.sort_values(["buy_price_tenths", "player_id"], kind="stable")
        selected.update(ranked.head(top_per_position).player_id)
        selected.update(cheap.head(cheap_per_position).player_id)
    return PlanningHorizon(table.loc[table.player_id.isin(selected)].copy())
