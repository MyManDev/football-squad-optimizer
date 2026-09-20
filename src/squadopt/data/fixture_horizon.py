"""The next few gameweeks per club, as one capture stated them, blanks included.

The multi-week projection needs to know, for a capture and a first gameweek, how many
matches each club plays in each of the weeks ahead and who those matches are against.
:func:`~squadopt.data.sources.fpl_live.fixture_snapshot` already carries every fact in
that sentence except one, and the missing one is the one a plan goes wrong on.

**A blank week is an absent row.** The fixture table lists matches, so a club with no
match in a gameweek contributes nothing to it, and "this club is idle that week" is
indistinguishable from "this reader did not look at that week" and from "that week is
not in the capture". A consumer that counts rows and treats a missing club as zero has
guessed correctly this time and written the rule that will be wrong the next. This
reader starts from the capture's complete club list and states every club's week,
including the empty ones, which is what makes a blank a fact rather than an absence.

**A gameweek the capture does not publish is not a blank week.** A horizon of five from
gameweek 36 runs past the end of the season, and a reader that answered "every club is
idle in gameweek 39" would be inventing two weeks of rest. The horizon covers the weeks
the capture's own event list publishes and states which ones those were, so a consumer
comparing two horizons can see that one is shorter rather than assume both are five.

## What happens when a fixture is rescheduled between two captures

The platform states a fixture's gameweek in ``event`` and gives a fixture awaiting a new
date ``event: null``. ``fixture_snapshot`` drops those rows, because a club whose match
was postponed genuinely has no fixture that gameweek, and this reader inherits that and
then states the consequence rather than hiding it:
:attr:`FixtureHorizon.unscheduled_count` is carried precisely because a postponed fixture
is one that will come back. **A horizon with unscheduled fixtures outstanding is one
where some club's count can still rise in a gameweek the capture already states.**

Nothing is carried between captures. A later capture *is* the calendar: there is no
merge, no memory of the earlier one, and nothing here re-checks a plan built on an older
one. A reschedule takes one of three shapes, and each is visible only by comparing two
horizons:

1. **Out.** A fixture in the horizon acquires ``event: null``. The club's count for that
   gameweek falls by one and ``unscheduled_count`` rises by one. If the count falls to
   zero the club now has a stated blank where it had a match.
2. **Moved.** A fixture's ``event`` changes from one gameweek to another. One count falls
   and another rises, and if the destination already held a match for that club it is now
   a double.
3. **In.** A previously unscheduled fixture acquires an ``event``. ``unscheduled_count``
   falls and a count rises, possibly into a double, possibly in a gameweek whose deadline
   is already close.

None of the three changes the fixture id, so two horizons can be compared fixture by
fixture. That comparison is deliberately not done here: it is a statement about two
captures, and this reader answers about one.
"""

from collections.abc import Hashable, Mapping
from dataclasses import dataclass
from typing import Final

import pandas as pd

from squadopt.data.errors import InvalidValueError
from squadopt.data.sources.fpl_live import (
    fixture_snapshot,
    gameweek_deadlines,
    team_codes,
    unscheduled_fixture_count,
)

#: The horizon the in-season multi-week projection plans over today.
DEFAULT_HORIZON_WEEKS: Final = 5

FIXTURE_HORIZON_CONTRACT_VERSION: Final = "fixture_horizon_v1"


@dataclass(frozen=True, slots=True)
class HorizonFixture:
    """One match a club plays in one gameweek, as the capture stated it."""

    fixture_id: int
    opponent_team_id: int
    """The opponent's persistent club code, the same identifier as ``team_id``."""
    is_home: bool
    kickoff_utc: str | None
    """``None`` when the capture has no kick-off time, which a fixture can lack while
    still holding a gameweek. Absent is not a time."""
    fixture_difficulty: int | None
    """The platform's own figure for this club, or ``None`` where it publishes none."""
    status: str


@dataclass(frozen=True, slots=True)
class HorizonWeek:
    """One club's one gameweek. An empty ``fixtures`` is a blank, stated."""

    team_id: int
    gameweek: int
    fixtures: tuple[HorizonFixture, ...]

    @property
    def fixture_count(self) -> int:
        """Zero for a blank, one for an ordinary week, two or more for a double."""

        return len(self.fixtures)


@dataclass(frozen=True, slots=True)
class FixtureHorizon:
    """Every club's next few gameweeks from one capture, and what the capture could not say."""

    season: str
    source_snapshot_id: str
    captured_at_utc: str
    gameweeks: tuple[int, ...]
    """The weeks actually covered: the requested range narrowed to what the capture
    publishes, in order. Shorter than asked for near the end of a season."""
    team_ids: tuple[int, ...]
    """Every club the capture declares, sorted. The complete list is the whole point:
    it is what turns a club's absence from a week into a stated blank."""
    unscheduled_count: int
    """Fixtures the capture holds with no gameweek. Each one can still land in this
    horizon, so a non-zero count is a statement that these counts are not final."""
    weeks: tuple[HorizonWeek, ...]
    """One entry per club per covered gameweek, in club then gameweek order."""

    def week(self, team_id: int, gameweek: int) -> HorizonWeek:
        """One club's one week, refusing rather than inventing a week off the horizon."""

        for entry in self.weeks:
            if entry.team_id == team_id and entry.gameweek == gameweek:
                return entry
        raise InvalidValueError(
            f"This horizon covers gameweeks {list(self.gameweeks)!r} for "
            f"{len(self.team_ids)} clubs and holds no club {team_id} in gameweek "
            f"{gameweek}. A week outside a horizon is unknown, not blank."
        )

    @property
    def blanks(self) -> tuple[HorizonWeek, ...]:
        """Every club-week the capture states no match for."""

        return tuple(entry for entry in self.weeks if entry.fixture_count == 0)

    @property
    def doubles(self) -> tuple[HorizonWeek, ...]:
        """Every club-week the capture states more than one match for."""

        return tuple(entry for entry in self.weeks if entry.fixture_count > 1)


def _absent(value: object) -> bool:
    """What the capture did not state, in whichever way pandas spelled it.

    The string columns yield ``pd.NA`` where a value is missing and the nullable integer
    one can yield either that or a ``NaN``. Neither is a value, and both have to leave
    this module as ``None``: a kick-off nobody has set is not the epoch and a difficulty
    the platform publishes none of is not zero.
    """

    return value is None or value is pd.NA or (isinstance(value, float) and value != value)


def _fixture(record: Mapping[Hashable, object]) -> HorizonFixture:
    difficulty = record["fixture_difficulty"]
    kickoff = record["kickoff_time_utc"]
    return HorizonFixture(
        fixture_id=int(str(record["fixture_id"])),
        opponent_team_id=int(str(record["opponent_team_id"])),
        is_home=bool(record["is_home"]),
        kickoff_utc=None if _absent(kickoff) else str(kickoff),
        fixture_difficulty=None if _absent(difficulty) else int(str(difficulty)),
        status=str(record["status"]),
    )


def fixture_horizon(
    fixtures: bytes,
    bootstrap: bytes,
    *,
    season: str,
    snapshot_id: str,
    captured_at_utc: str,
    first_gameweek: int,
    weeks: int = DEFAULT_HORIZON_WEEKS,
) -> FixtureHorizon:
    """Read one capture's calendar for ``weeks`` gameweeks from ``first_gameweek``.

    The arguments are the ones :func:`fixture_snapshot` takes, because this is that
    reader with the capture's club list joined back in; ``season`` is declared and
    checked against the payload there for the same reason it is there.

    ``first_gameweek`` must be one the capture publishes. A horizon starting at a week
    the capture has never heard of is a caller error rather than an empty answer, and an
    empty answer is exactly the shape that gets read as "no fixtures".
    """

    if weeks < 1:
        raise InvalidValueError(f"A horizon covers at least one gameweek, got {weeks}.")
    published = {entry.gameweek for entry in gameweek_deadlines(bootstrap)}
    if first_gameweek not in published:
        raise InvalidValueError(
            f"The capture publishes no gameweek {first_gameweek}; its event list runs "
            f"from {min(published)} to {max(published)}."
        )
    covered = tuple(
        gameweek
        for gameweek in range(first_gameweek, first_gameweek + weeks)
        if gameweek in published
    )

    frame = fixture_snapshot(
        fixtures,
        bootstrap,
        season=season,
        snapshot_id=snapshot_id,
        captured_at_utc=captured_at_utc,
    )
    clubs = tuple(sorted(set(team_codes(bootstrap).values())))
    inside = frame.loc[frame["gameweek"].isin(covered)].sort_values(
        ["kickoff_time_utc", "fixture_id"], kind="stable", na_position="last"
    )
    grouped: dict[tuple[int, int], list[HorizonFixture]] = {}
    for record in inside.to_dict("records"):
        key = (int(str(record["team_id"])), int(str(record["gameweek"])))
        grouped.setdefault(key, []).append(_fixture(record))

    return FixtureHorizon(
        season=str(frame["season"].iloc[0]),
        source_snapshot_id=snapshot_id,
        captured_at_utc=str(frame["captured_at_utc"].iloc[0]),
        gameweeks=covered,
        team_ids=clubs,
        unscheduled_count=unscheduled_fixture_count(fixtures),
        weeks=tuple(
            HorizonWeek(
                team_id=team_id,
                gameweek=gameweek,
                fixtures=tuple(grouped.get((team_id, gameweek), ())),
            )
            for team_id in clubs
            for gameweek in covered
        ),
    )


__all__ = [
    "DEFAULT_HORIZON_WEEKS",
    "FIXTURE_HORIZON_CONTRACT_VERSION",
    "FixtureHorizon",
    "HorizonFixture",
    "HorizonWeek",
    "fixture_horizon",
]
