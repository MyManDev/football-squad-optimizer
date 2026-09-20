"""Bind the pure forecast to one member and the capture the existing product reads.

No solve or file read belongs here. Callers supply only chip gains they already
computed; an absent gain is unknown. A refusal removes the forecast, never the plan.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Any

from squadopt.application.advice_chips import member_chip_menu
from squadopt.application.chip_forecast import (
    MEASURED_RESERVATION,
    MEASURED_THRESHOLD_POLICY,
    PROTOCOL_HOLDING_VALUES,
    ChipForecastError,
    ChipForecastInputs,
    GameweekFixtures,
    HeldChip,
    SquadRow,
    chip_forecast,
)
from squadopt.application.entries import EntryError, EntryPicks
from squadopt.application.fixtures_view import FixturesView, fixtures_view
from squadopt.data.errors import DataError
from squadopt.data.snapshots import CapturedSnapshot
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, team_names
from squadopt.live import Projection, RecommendationInputs, SeasonRules


@dataclass(frozen=True, slots=True)
class ForecastSource:
    snapshot_id: str
    calendar: FixturesView | None
    club_ids_by_name: Mapping[str, int]
    unavailable_reason: str | None = None


def forecast_source(snapshot: CapturedSnapshot) -> ForecastSource:
    """Reuse the published-calendar parser on the already loaded capture."""
    try:
        calendar = fixtures_view(snapshot)
        names = team_names(snapshot.payloads[BOOTSTRAP_PAYLOAD])
        if len(set(names.values())) != len(names):
            raise DataError("Season club names are not unique.")
        return ForecastSource(
            snapshot.metadata.snapshot_id,
            calendar,
            {name: club for club, name in names.items()},
            "calendar_missing" if calendar is None else None,
        )
    except (DataError, KeyError, ValueError):
        return ForecastSource(snapshot.metadata.snapshot_id, None, {}, "calendar_unreadable")


class ForecastUnavailable(ValueError):
    """A stable refusal code, translated by the member card."""


def published_chip_gains(
    payloads: Iterable[tuple[str, Mapping[str, object]]],
) -> dict[str, float | None]:
    """Read computed gains without treating a missing or invalid gain as zero."""
    result: dict[str, float | None] = {}
    for chip, payload in payloads:
        choice = payload.get("chip_choice")
        value = choice.get("gain_vs_no_chip") if isinstance(choice, Mapping) else None
        result[chip] = (
            float(value)
            if isinstance(value, (float, int)) and not isinstance(value, bool)
            else None
        )
    return result


def calendar_counts(
    source: ForecastSource, *, first: int, last: int
) -> tuple[GameweekFixtures, ...]:
    """Expand match rows to complete club counts, including explicit blank zeros.

    The product tests blanks and doubles on these complete maps. The lab's
    season_chain uses sparse rows and its missing-row predicate is not reusable
    here; importing that predicate would also cross the product/lab boundary.
    """
    calendar = source.calendar
    if calendar is None:
        raise ForecastUnavailable(source.unavailable_reason or "calendar_missing")
    if calendar.unscheduled_count != 0:
        raise ForecastUnavailable("fixtures_unscheduled")
    clubs = set(source.club_ids_by_name.values())
    if not clubs:
        raise ForecastUnavailable("club_roster_missing")
    weeks = {week.gameweek: week for week in calendar.gameweeks}
    if len(weeks) != len(calendar.gameweeks):
        raise ForecastUnavailable("calendar_incomplete")
    result = []
    for number in range(first, last + 1):
        if number not in weeks:
            raise ForecastUnavailable("calendar_incomplete")
        # The calendar lists matches, not absent clubs. Start from the COMPLETE
        # season roster: a club missing from a week is an explicit zero.
        counts = dict.fromkeys(clubs, 0)
        seen = set()
        for fixture in weeks[number].fixtures:
            if fixture.fixture_id in seen:
                raise ForecastUnavailable("calendar_incomplete")
            seen.add(fixture.fixture_id)
            for club in (fixture.home.team_id, fixture.away.team_id):
                if club not in counts:
                    raise ForecastUnavailable("club_roster_incomplete")
                counts[club] += 1
        result.append(GameweekFixtures(number, counts))
    return tuple(result)


def member_chip_forecast(
    *,
    league_id: int,
    picks: EntryPicks,
    inputs: RecommendationInputs,
    projection: Projection,
    rules: SeasonRules,
    source: ForecastSource | None,
    gains: Mapping[str, float | None],
) -> dict[str, Any]:
    """One complete reading; never combine gains from another response/capture."""
    week = inputs.deadline.gameweek
    envelope: dict[str, Any] = {
        "season": inputs.season,
        "league_id": league_id,
        "entry_id": picks.entry_id,
        "gameweek": week,
        "source_snapshot_id": inputs.snapshot_id,
        "squad_player_ids": list(picks.squad),
        "bench_player_ids": list(picks.squad[11:]),
        "status": "unavailable",
        "reason": None,
        "forecast": None,
        "calendar_has_structure": None,
        "calendar_range": None,
    }
    try:
        if source is None:
            raise ForecastUnavailable("calendar_missing")
        if (
            source.snapshot_id != inputs.snapshot_id
            or picks.source_snapshot_id != inputs.snapshot_id
            or rules.source_snapshot_id != inputs.snapshot_id
            or picks.season != inputs.season
            or rules.season != inputs.season
            or picks.gameweek + 1 != week
            or (source.calendar is not None and source.calendar.season != inputs.season)
        ):
            raise ForecastUnavailable("capture_mismatch")
        menu = member_chip_menu(rules, week, picks.chips_used)
        if not menu.known:
            raise ForecastUnavailable("chip_history_unknown")
        chips = []
        for name in menu.held:
            active = [
                window
                for window in menu.windows[name].values()
                if window is not None
                and int(str(window["start_event"])) <= week <= int(str(window["stop_event"]))
                and window["state"] == "available"
            ]
            if len(active) != 1:
                raise ForecastUnavailable("chip_window_unreadable")
            window = active[0]
            chips.append(
                HeldChip(
                    name,
                    int(str(window["start_event"])),
                    int(str(window["stop_event"])),
                    gains.get(name),
                )
            )
        calendar = calendar_counts(
            source, first=week, last=max((chip.last_gameweek for chip in chips), default=week)
        )
        players = projection.table.set_index("player_id")
        if not players.index.is_unique:
            raise ForecastUnavailable("forecast_inputs_unreadable")
        bench = {player: n for n, player in enumerate(picks.squad[11:], 1)}
        squad = []
        for player in picks.squad:
            if player not in players.index or player in projection.unprojected_players:
                raise ForecastUnavailable("squad_projection_missing")
            row = players.loc[player]
            club = source.club_ids_by_name.get(str(row["team_id"]))
            if club is None:
                raise ForecastUnavailable("club_roster_incomplete")
            squad.append(
                SquadRow(
                    player,
                    club,
                    str(row["position"]),
                    float(str(row["expected_points"])),
                    bench.get(player),
                    player == picks.captain,
                )
            )
        document = chip_forecast(
            ChipForecastInputs(
                week,
                chips,
                squad,
                calendar,
                PROTOCOL_HOLDING_VALUES,
                MEASURED_THRESHOLD_POLICY,
                MEASURED_RESERVATION,
            )
        )
        later = [item for item in calendar if item.gameweek > week]
        # Raw fixtures omit absent clubs. calendar_counts above inserts every
        # roster club, so these complete maps represent a blank by an explicit
        # zero. The lab's season_chain has the same idea over sparse rows;
        # product cannot import the lab, and must not reuse its missing-row test.
        structure = any(item.clubs_blank or item.clubs_doubling for item in later)
        examined = (
            {"first_gameweek": later[0].gameweek, "last_gameweek": later[-1].gameweek}
            if later
            else None
        )
    except ForecastUnavailable as error:
        envelope["reason"] = str(error)
    except (ChipForecastError, DataError, EntryError, KeyError, TypeError, ValueError):
        envelope["reason"] = "forecast_inputs_unreadable"
    else:
        envelope.update(
            status="available",
            forecast=document,
            calendar_has_structure=structure,
            calendar_range=examined,
        )
    return envelope
