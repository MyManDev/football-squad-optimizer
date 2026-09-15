"""Score an actual personal plan in the unchanged base model, before publication."""

from collections.abc import Mapping, Sequence
from typing import Any

import pandas as pd

from squadopt.planning.models import PlanningWeekResult


def base_model_values(
    weeks: Sequence[PlanningWeekResult],
    table: pd.DataFrame,
    diagnostics: Mapping[str, Any],
) -> dict[str, object]:
    """Internal pricing inputs; the worker removes these before serving the answer.

    The uplift is a player-specific multiplier in every horizon week. Undo that
    multiplier on the *chosen* XI and captain, without choosing a new lineup. The
    ceiling relaxes budget, positions, team limits and transfers, so it remains safe
    even when either solve is FEASIBLE or its objective values bench players.
    """
    ratios = diagnostics.get("top100_base_point_ratios")
    if ratios is None:
        return {}
    net, ceiling = 0.0, 0.0
    for week in weeks:
        if week.chip is not None:
            raise ValueError("Personal price accounting requires the member no-chip policy.")
        net += sum(
            float(str(row.expected_points)) * ratios[int(str(row.player_id))]
            for row in week.starting_xi.itertuples()
        )
        captain = week.captain
        net += float(str(captain["expected_points"])) * ratios[int(str(captain["player_id"]))]
        net -= week.transfer_hit_points
        rows = table.loc[table["gameweek"] == week.gameweek] if "gameweek" in table else table
        points = (rows["expected_points"] * rows["player_id"].map(ratios)).sort_values(
            ascending=False
        )
        ceiling += float(points.head(11).sum() + points.iloc[0])
    return {"_top100_base_net": net, "_top100_base_ceiling": max(net, ceiling)}
