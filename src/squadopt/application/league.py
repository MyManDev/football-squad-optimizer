"""The league view: our season against everyone else playing the same game.

Two things the capture already publishes make the comparison possible, and neither has
been used before: each gameweek's ``average_entry_score`` and ``highest_score`` (the
game's own summary of every manager's week), and each player's ``selected_by_percent``
(how much of the field owns him). Put beside the ledger they answer the two questions a
reader actually has — *are we better than the average manager*, and *how much of this
squad is the template everyone else also owns*.

What this module refuses to do is invent the answer. A gameweek the game has not scored
yet has no average, so the row says so; a season with no settled gameweek has no verdict,
and the view carries ``None`` rather than a zero that reads like evidence.
"""

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from squadopt.application.views import LedgerView, PlayerView, _View
from squadopt.data.snapshots import CapturedSnapshot
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD

DIFFERENTIAL_OWNERSHIP_PERCENT = 10.0
"""At or below this ownership a starter is a differential: most of the field does not have him."""


class LeagueError(ValueError):
    """The capture could not answer a league question."""


@dataclass(frozen=True, slots=True)
class LeagueWeekView(_View):
    """One gameweek, us against the game's own summary of everyone."""

    gameweek: int
    deadline_utc: str
    finished: bool
    average_entry_score: float | None
    """The game's average across every entry; None until the gameweek is scored."""
    highest_score: float | None
    our_projected_score: float | None
    our_realized_score: float | None
    our_realized_net_score: float | None
    difference_to_average: float | None
    """Our realized net minus the average; None until both exist."""


@dataclass(frozen=True, slots=True)
class OwnershipView(_View):
    """How much of our squad the rest of the field also owns."""

    gameweek: int
    squad: tuple[PlayerView, ...]
    ownership_percent: Mapping[str, float]
    """Player id (as a string) -> selected_by_percent at capture time."""
    mean_starter_ownership: float
    """The unweighted mean over the starting eleven; the captain is not counted twice."""
    effective_ownership: float
    """Starters plus the captain again: what the field is exposed to, as we are."""
    differentials: tuple[int, ...]
    """Starters at or below the differential threshold."""
    differential_threshold_percent: float
    most_owned_starter: int | None
    least_owned_starter: int | None


@dataclass(frozen=True, slots=True)
class LeagueView(_View):
    """The league page's payload: the season week by week, and this week's ownership."""

    season: str
    source_snapshot_id: str
    captured_at_utc: str
    weeks: tuple[LeagueWeekView, ...]
    scored_gameweeks: int
    our_total_realized_net_score: float | None
    league_total_average_score: float | None
    total_difference_to_average: float | None
    """Sum over the gameweeks where both exist; the only league claim this view makes."""
    ownership: OwnershipView | None
    verdict: str
    """One sentence a reader can quote, written from what is actually known."""


def _bootstrap(snapshot: CapturedSnapshot) -> dict[str, object]:
    payload = snapshot.payloads.get(BOOTSTRAP_PAYLOAD)
    if payload is None:
        raise LeagueError(f"Snapshot {snapshot.metadata.snapshot_id!r} carries no bootstrap.")
    document = json.loads(payload.decode("utf-8"))
    if not isinstance(document, dict):
        raise LeagueError("The bootstrap payload is not an object.")
    return document


def _events(document: Mapping[str, object]) -> list[Mapping[str, object]]:
    events = document.get("events")
    if not isinstance(events, list):
        raise LeagueError("The bootstrap payload carries no events.")
    return [event for event in events if isinstance(event, Mapping)]


def _optional_number(value: object) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, int | float):
        return float(value)
    try:
        return float(str(value))
    except ValueError:
        return None


def ownership_by_player(snapshot: CapturedSnapshot) -> dict[int, float]:
    """``selected_by_percent`` per player, keyed the way this project identifies players.

    The platform's ``code`` is the persistent identifier the canonical schema uses as
    ``player_id``; ``id`` is the per-season element number, which changes between seasons
    and is not what a ledger entry names.
    """

    elements = _bootstrap(snapshot).get("elements")
    if not isinstance(elements, list):
        raise LeagueError("The bootstrap payload carries no elements.")
    owned: dict[int, float] = {}
    for element in elements:
        if not isinstance(element, Mapping):
            continue
        percent = _optional_number(element.get("selected_by_percent"))
        identifier = element.get("code", element.get("id"))
        if percent is not None and identifier is not None:
            owned[int(str(identifier))] = percent
    return owned


def ownership_view(
    snapshot: CapturedSnapshot,
    *,
    gameweek: int,
    starters: Sequence[PlayerView],
    bench: Sequence[PlayerView],
    captain_player_id: int,
) -> OwnershipView:
    """Our squad's exposure to what everyone else owns, from one capture."""

    owned = ownership_by_player(snapshot)
    squad = tuple(starters) + tuple(bench)
    percents = {
        str(player.player_id): owned[player.player_id]
        for player in squad
        if player.player_id in owned
    }
    known = [player for player in starters if player.player_id in owned]
    starter_percents = [owned[player.player_id] for player in known]
    mean_starter = sum(starter_percents) / len(starter_percents) if starter_percents else 0.0
    captain_percent = owned.get(int(captain_player_id), 0.0)  # unowned reads as zero exposure
    effective = sum(starter_percents) + captain_percent
    differentials = tuple(
        player.player_id
        for player in known
        if owned[player.player_id] <= DIFFERENTIAL_OWNERSHIP_PERCENT
    )
    ranked = sorted(known, key=lambda player: owned[player.player_id])
    return OwnershipView(
        gameweek=int(gameweek),
        squad=squad,
        ownership_percent=percents,
        mean_starter_ownership=mean_starter,
        effective_ownership=effective,
        differentials=differentials,
        differential_threshold_percent=DIFFERENTIAL_OWNERSHIP_PERCENT,
        most_owned_starter=ranked[-1].player_id if ranked else None,
        least_owned_starter=ranked[0].player_id if ranked else None,
    )


def _verdict(scored: int, difference: float | None, ownership: OwnershipView | None) -> str:
    if scored == 0 or difference is None:
        return (
            "No gameweek has been scored yet, so there is nothing to compare: the game "
            "publishes an average only once a gameweek finishes."
        )
    weeks = "gameweek" if scored == 1 else "gameweeks"
    standing = f"{difference:+.0f} points against the game's average over {scored} scored {weeks}"
    caveat = (
        " — one gameweek is noise, not evidence"
        if scored < 5
        else " — still fewer weeks than a season's variation needs"
        if scored < 20
        else ""
    )
    template = (
        ""
        if ownership is None
        else f"; the starting eleven averages {ownership.mean_starter_ownership:.0f}% ownership"
    )
    return standing + caveat + template + "."


def league_view(
    snapshot: CapturedSnapshot,
    ledger: LedgerView,
    *,
    ownership: OwnershipView | None = None,
) -> LeagueView:
    """Our season beside the game's own weekly summary, from one capture and the ledger."""

    document = _bootstrap(snapshot)
    rows = {row.gameweek: row for row in ledger.rows}
    weeks: list[LeagueWeekView] = []
    total_ours = 0.0
    total_average = 0.0
    scored = 0
    for event in _events(document):
        gameweek = int(str(event["id"]))
        finished = bool(event.get("finished"))
        average = _optional_number(event.get("average_entry_score")) if finished else None
        highest = _optional_number(event.get("highest_score")) if finished else None
        row = rows.get(gameweek)
        ours = row.realized_net_score if row is not None else None
        difference = None if average is None or ours is None else ours - average
        if difference is not None:
            total_ours += ours or 0.0
            total_average += average or 0.0
            scored += 1
        weeks.append(
            LeagueWeekView(
                gameweek=gameweek,
                deadline_utc=str(event.get("deadline_time", "")),
                finished=finished,
                average_entry_score=average,
                highest_score=highest,
                our_projected_score=None if row is None else row.projected_score,
                our_realized_score=None if row is None else row.realized_score,
                our_realized_net_score=ours,
                difference_to_average=difference,
            )
        )
    difference_total = None if scored == 0 else total_ours - total_average
    return LeagueView(
        season=ledger.season,
        source_snapshot_id=snapshot.metadata.snapshot_id,
        captured_at_utc=snapshot.metadata.captured_at_utc,
        weeks=tuple(weeks),
        scored_gameweeks=scored,
        our_total_realized_net_score=None if scored == 0 else total_ours,
        league_total_average_score=None if scored == 0 else total_average,
        total_difference_to_average=difference_total,
        ownership=ownership,
        verdict=_verdict(scored, difference_total, ownership),
    )


__all__ = [
    "DIFFERENTIAL_OWNERSHIP_PERCENT",
    "LeagueError",
    "LeagueView",
    "LeagueWeekView",
    "OwnershipView",
    "league_view",
    "ownership_by_player",
    "ownership_view",
]
