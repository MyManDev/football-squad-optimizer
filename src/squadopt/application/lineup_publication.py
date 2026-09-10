"""Serialize a solved lineup with a single deterministic vice/bench completion rule."""

from typing import Any

import pandas as pd

from squadopt.application.entries import EntryError
from squadopt.live.chip_advice import expected_chip_week_points
from squadopt.planning import PlanningWeekResult

_POSITION_ORDER: tuple[str, ...] = ("GK", "DEF", "MID", "FWD")


def advice_player(row: "pd.Series[Any]") -> dict[str, object]:
    name = str(row["name"])
    return {
        "player_id": int(str(row["player_id"])),
        "name": name,
        "short_name": name.rsplit(" ", 1)[-1],
        "position": str(row["position"]),
        "team": str(row["team_id"]),
    }


def _lineup_player(row: "pd.Series[Any]") -> dict[str, object]:
    return {**advice_player(row), "expected_points": float(str(row["expected_points"]))}


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
    expected_own = expected_chip_week_points(week)
    return {
        "expected_own_points": expected_own,
        "captain": _lineup_player(starters[captain_id]),
        "vice_captain": _lineup_player(vice_candidates[0]),
        "starting_xi": [_lineup_player(row) for row in ordered_eleven],
        "bench": [_lineup_player(row) for row in (*goalkeepers, *outfield)],
        "chip": week.chip,
    }
