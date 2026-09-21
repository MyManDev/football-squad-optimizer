"""Serialize a solved lineup using the existing deterministic completion rule.

This module also owns the arithmetic behind the one number the card leads with, the
eleven with the captain doubled, so that every figure stated on that basis is produced
by the same code: the plan's own total (``lineup_fields``) and the total a fifteen the
planner did not solve for would be worth (``best_eleven_points``).
"""

from collections.abc import Iterable
from typing import Any, Final

import pandas as pd

from squadopt.application.entries import EntryError
from squadopt.contracts import POSITIONS, Position, order_outfield_bench
from squadopt.optimization import OptimizationConfig
from squadopt.planning import PlanningWeekResult

#: Pitch order for the published eleven and the outfield bench.
_POSITION_ORDER: tuple[Position, ...] = POSITIONS

#: The planner's own defaults, read once rather than restated. ``best_eleven_points``
#: below is the planner with its squad held fixed, so it has to choose an eleven from the
#: same shapes and weigh the bench at the same weight; spelling either of them again here
#: would let the baseline drift away from the plans it is compared against.
_LINEUP_DEFAULTS: Final = OptimizationConfig()


def _legal_shapes() -> tuple[tuple[tuple[Position, int], ...], ...]:
    """Every eleven-man shape the optimizer's position bounds admit, in a fixed order."""

    minimum = _LINEUP_DEFAULTS.starting_position_min
    maximum = _LINEUP_DEFAULTS.starting_position_max
    ranges = [range(minimum[position], maximum[position] + 1) for position in _POSITION_ORDER]
    shapes: list[tuple[tuple[Position, int], ...]] = []

    def walk(index: int, chosen: list[int]) -> None:
        if index == len(_POSITION_ORDER):
            if sum(chosen) == _LINEUP_DEFAULTS.starting_size:
                shapes.append(tuple(zip(_POSITION_ORDER, chosen, strict=True)))
            return
        for count in ranges[index]:
            walk(index + 1, [*chosen, count])

    walk(0, [])
    return tuple(shapes)


#: Built once: the shapes are a function of the configuration, not of any squad.
_LEGAL_SHAPES: Final = _legal_shapes()


def best_eleven_points(squad: Iterable[tuple[str, float]]) -> float | None:
    """What a fifteen is worth on the published basis, the eleven with the captain doubled.

    With the fifteen held fixed the planner has only two decisions left, the shape of the
    eleven and the armband, and both are small enough to settle exactly rather than
    search: within one shape the highest-scoring players of a position maximise the
    eleven's total *and* contain its best player, so that shape's own optimum is read off
    a sort, and there are eight shapes. The shape is then chosen on the planner's own
    objective, the eleven with the captain doubled plus ``bench_weight`` of the bench, so
    this is the planner with its hands tied rather than a second opinion about what a
    fifteen is worth. Ties fall to the first shape in the fixed order above, so two builds
    of one capture return one number.

    What comes back is the published basis alone: the eleven plus the captain's double,
    with the bench's weighted contribution used for the choice and then dropped, exactly
    as ``lineup_fields`` publishes it for a solved week.

    ``None`` when the players handed in hold no legal eleven at all. The caller then has
    no measured number and must publish none: a squad nobody could field is not a squad
    worth zero.
    """

    players = list(squad)
    by_position: dict[str, list[float]] = {str(position): [] for position in _POSITION_ORDER}
    for position, expected_points in players:
        if position in by_position:
            by_position[position].append(float(expected_points))
    for scores in by_position.values():
        scores.sort(reverse=True)
    total = sum(float(expected_points) for _position, expected_points in players)
    best_objective: float | None = None
    best_basis: float | None = None
    for shape in _LEGAL_SHAPES:
        if any(len(by_position[position]) < count for position, count in shape):
            continue
        chosen = [score for position, count in shape for score in by_position[position][:count]]
        if not chosen:
            continue
        basis = sum(chosen) + max(chosen)
        objective = basis + _LINEUP_DEFAULTS.bench_weight * (total - sum(chosen))
        if best_objective is None or objective > best_objective:
            best_objective = objective
            best_basis = basis
    return best_basis


def best_eleven_basis(
    squad: Iterable[
        tuple[str, float, float, bool, bool] | tuple[str, float, float, bool, bool, int]
    ],
) -> float | None:
    """The published basis of the eleven a fifteen would field, chosen on other points.

    Each player is ``(position, choice_points, basis_points, may_start, may_captain)``. The
    shape, the eleven and the armband are chosen exactly as ``best_eleven_points_under``
    chooses them, on ``choice_points``; what comes back is that eleven's total with the
    captain doubled, on ``basis_points``. A plan chosen on points the member asked for
    (the Top 100 influence) is scored this way on the base model's points, so its rows
    and its total describe the eleven it actually fields.

    A player may carry his id as a sixth element. The choice is then made the way the
    solver makes it, so the eleven read here is the eleven the plan fields: on points
    rounded to the solver's thousandths, ties falling to the lowest id. Without ids the
    order handed in breaks ties, as ``best_eleven_points_under`` always did.

    ``None`` when no legal eleven with an eligible captain exists.
    """

    players = []
    for item in squad:
        position, choice, basis, may_start, may_captain = item[:5]
        identity = int(item[5]) if len(item) > 5 else None
        chosen_on = float(choice) if identity is None else round(float(choice) * 1000) / 1000
        players.append(
            (str(position), chosen_on, float(basis), bool(may_start), bool(may_captain), identity)
        )
    total = sum(choice for _position, choice, *_rest in players)
    starters: dict[str, list[tuple[float, float, bool]]] = {
        str(position): [] for position in _POSITION_ORDER
    }
    # Sorted by id first, so the stable sort on points below leaves ties to the lowest id.
    for position, choice, basis, may_start, may_captain, _identity in sorted(
        players, key=lambda row: (row[5] is None, row[5] or 0)
    ):
        if may_start and position in starters:
            starters[position].append((choice, basis, may_captain))
    for rows in starters.values():
        rows.sort(key=lambda row: row[0], reverse=True)
    best_objective: float | None = None
    best_basis: float | None = None
    for shape in _LEGAL_SHAPES:
        if any(len(starters[position]) < count for position, count in shape):
            continue
        for captain_position, _count in shape:
            for captain_index, (captain_choice, captain_basis, eligible) in enumerate(
                starters[captain_position]
            ):
                if not eligible:
                    continue
                chosen: list[float] = []
                stated: list[float] = []
                for position, count in shape:
                    pool = starters[position]
                    if position == captain_position:
                        others = [
                            (choice, basis)
                            for index, (choice, basis, _eligible) in enumerate(pool)
                            if index != captain_index
                        ][: count - 1]
                        if len(others) < count - 1:
                            break
                        chosen.extend([captain_choice, *(choice for choice, _ in others)])
                        stated.extend([captain_basis, *(basis for _, basis in others)])
                    else:
                        chosen.extend(choice for choice, _basis, _eligible in pool[:count])
                        stated.extend(basis for _choice, basis, _eligible in pool[:count])
                else:
                    objective = (
                        sum(chosen)
                        + captain_choice
                        + _LINEUP_DEFAULTS.bench_weight * (total - sum(chosen))
                    )
                    if best_objective is None or objective > best_objective:
                        best_objective = objective
                        best_basis = sum(stated) + captain_basis
    return best_basis


def best_eleven_points_under(
    squad: Iterable[tuple[str, float, bool, bool]],
) -> float | None:
    """``best_eleven_points`` for a fifteen some of whose players may not start or captain.

    Each player is ``(position, expected_points, may_start, may_captain)``. A player who may
    not start is bench-only; one who may not captain may start. Within a shape the eleven
    is no longer a plain sort, because the armband can be worth taking a lower-scoring
    captain-eligible player into the eleven, so every eligible captain is tried: he is put
    in, the rest of his shape is filled from the top of each position among the players
    who may start, and the best objective wins. Ties fall to the first shape and the first
    captain in a fixed order, so two builds of one capture return one number.

    ``None`` when no legal eleven with an eligible captain exists.
    """

    return best_eleven_basis(
        (position, points, points, may_start, may_captain)
        for position, points, may_start, may_captain in squad
    )


def best_lineup_points_with_chip(squad: Iterable[tuple[str, float]], chip: str) -> float | None:
    """What a fifteen is worth in a week the named chip is played.

    A Wildcard and a Free Hit change which fifteen is held and nothing about how it
    scores, so their basis is ``best_eleven_points``. A Triple Captain counts the captain
    three times: the shape is chosen as the planner chooses it under that chip, on the
    eleven with the captain tripled plus ``bench_weight`` of the bench, and what comes
    back is the eleven with the captain tripled. A Bench Boost scores all fifteen, so the
    eleven stops mattering: every legal shape fields each position's best player, the
    armband goes to the best of the fifteen, and the basis is the fifteen's total with
    him counted twice.

    ``None`` when the players hold no legal eleven, as ``best_eleven_points`` answers.
    """

    players = [(str(position), float(points)) for position, points in squad]
    if chip not in {"3xc", "bboost"}:
        return best_eleven_points(players)
    by_position: dict[str, list[float]] = {str(position): [] for position in _POSITION_ORDER}
    for position, expected_points in players:
        if position in by_position:
            by_position[position].append(expected_points)
    for scores in by_position.values():
        scores.sort(reverse=True)
    total = sum(expected_points for _position, expected_points in players)
    best_objective: float | None = None
    best_basis: float | None = None
    for shape in _LEGAL_SHAPES:
        if any(len(by_position[position]) < count for position, count in shape):
            continue
        chosen = [score for position, count in shape for score in by_position[position][:count]]
        if not chosen:
            continue
        if chip == "bboost":
            return total + max(chosen)
        basis = sum(chosen) + 2.0 * max(chosen)
        objective = basis + _LINEUP_DEFAULTS.bench_weight * (total - sum(chosen))
        if best_objective is None or objective > best_objective:
            best_objective = objective
            best_basis = basis
    return best_basis


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
    The planner decides the eleven, the captain and the chip; the vice-captain follows the
    same rule the official scorer applies (highest expected points first, ties by player
    id), and the bench order is **delegated to the function the official scorer calls**,
    :func:`~squadopt.contracts.order_outfield_bench`, with the bench goalkeeper first.
    ``expected_own_points`` is the eleven plus the captain's double: expected points,
    nothing else.

    Delegating rather than sorting here is the point, and the call is not dead work even
    though it returns today's order. A planning week carries no ``appearance_probability``:
    the projection horizon narrows it away, and widening
    ``PROJECTION_HORIZON_COLUMNS``/``PLANNING_HORIZON_COLUMNS`` is a versioned contract
    change with its own question (what an appearance chance means in week three of a
    horizon, where expected points are re-derived from fixture counts). So the shared rule
    meets no chance here, falls back, and produces exactly what a local sort would. What it
    buys is that "what is shown is what would be scored" holds **by construction** rather
    than by two hand-written sorts happening to agree, and that the day the horizon carries
    the column this page follows with no edit here at all.
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
    if len(goalkeepers) != 1:
        raise EntryError("The plan's bench must hold exactly one goalkeeper.")
    outfield_frame = week.bench.loc[week.bench["position"].astype("string") != "GK"]
    outfield = [row for _, row in order_outfield_bench(outfield_frame).iterrows()]
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
