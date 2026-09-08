"""A synthetic decision capture that agrees with the committed club-news fixture.

The rotation evidence table joins three things: the club-news fixture's claims, the decision
capture's roster and feed, and the captured calendar. Testing it needs a capture whose roster
is exactly the fixture's roster -- same persistent codes, same clubs -- or the join under test
is measuring a mismatch rather than the rule.

So this builds one, from the fixture's own roster rather than from a second list of names. If
someone adds a player to the club-news fixture, this capture grows with it and nothing here
has to be remembered.

The calendar is arranged so the midweek reading has both answers in it: one club kicked off
inside the four days before the deadline and the others did not. That is the only way a test
can tell a working flag from a constant.
"""

import json
from typing import Any, Final

from squadopt.data.snapshots import (
    SNAPSHOT_SCHEMA_VERSION,
    CapturedSnapshot,
    SnapshotMetadata,
    build_snapshot_id,
    payload_checksum,
    snapshot_fingerprint,
)
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD
from tests.fixtures.synthetic_club_news import make_club_news_fixture

SEASON: Final = "2026-27"
TARGET_GAMEWEEK: Final = 4
#: The GW4 deadline the club-news fixture's documents were published ahead of.
DEADLINE: Final = "2026-09-12T17:30:00Z"
#: After the documents were fetched (14:05) and before the deadline, as a real capture is.
CAPTURED_AT: Final = "2026-09-12T15:00:00Z"
#: Earlier than the club documents' own fetch instant, so the claim chain would not have been
#: frozen before the decision. The one state the builder refuses on method rather than data.
CAPTURED_BEFORE_THE_DOCUMENTS: Final = "2026-09-12T13:00:00Z"

#: Inside the four days before the deadline, so this club's players read as midweek.
MIDWEEK_KICKOFF: Final = "2026-09-09T19:00:00Z"
#: The previous weekend: earlier than the window, so these players do not.
WEEKEND_KICKOFF: Final = "2026-09-05T14:00:00Z"
#: This gameweek's own kickoff, after the deadline and therefore outside the window.
TARGET_KICKOFF: Final = "2026-09-12T19:00:00Z"

#: The club whose fixture falls in the window.
MIDWEEK_CLUB: Final = "Man Utd"
#: A club with no players on this roster, so the midweek fixture marks exactly one roster
#: club rather than both sides of it. A real capture is full of these.
OPPONENT_CLUB: Final = "Fulham"

_POSITION_BY_INDEX: Final[tuple[int, ...]] = (1, 2, 3, 4)


def roster_entries() -> tuple[dict[str, Any], ...]:
    """The club-news fixture's roster, which this capture must reproduce exactly."""

    entries = make_club_news_fixture()["roster"]
    return tuple(dict(entry) for entry in entries)


def club_names() -> tuple[str, ...]:
    """Every club on that roster, in a stable order."""

    return tuple(sorted({str(entry["team_name"]) for entry in roster_entries()}))


def _team_ids() -> dict[str, int]:
    """Per-season team ids for every club in the capture, roster clubs and the opponent alike.

    Deliberately not the persistent codes: the payload keys clubs by an id assigned per
    season, and the table under test has to translate between the two.
    """

    return {name: position + 1 for position, name in enumerate((*club_names(), OPPONENT_CLUB))}


def _element(index: int, entry: dict[str, Any], team_id: int) -> dict[str, Any]:
    """One element record carrying every field the readers on this path require.

    The three news states are spread deliberately across the roster: most players have never
    been flagged, one carries an emptied note with its stamp still on it, and one is flagged
    now. A capture in which every player looks the same cannot tell a three-state reading
    from a constant.
    """

    name = str(entry["web_name"])
    stamped = index in (1, 2)
    return {
        "code": int(entry["player_id"]),
        "id": index + 1,
        "first_name": name.split(".")[0] if "." in name else "Synthetic",
        "second_name": name,
        "web_name": name,
        "team": team_id,
        "element_type": _POSITION_BY_INDEX[index % len(_POSITION_BY_INDEX)],
        "now_cost": 50 + index,
        "status": "d" if index == 2 else "a",
        "chance_of_playing_next_round": 75 if index == 2 else (None if index == 3 else 100),
        # index 1: flagged once and since cleared -- empty text, stamp kept.
        # index 2: flagged now -- text and stamp.
        "news": "Knock, assessed daily." if index == 2 else "",
        "news_added": "2026-09-10T09:00:00Z" if stamped else None,
        "scout_risks": [{"type": "rotation"}] if index == 0 else [],
        "scout_news_link": "https://example.invalid/scout" if index == 0 else None,
    }


def bootstrap_payload() -> bytes:
    """The captured bootstrap: teams, the roster's elements, and the season's deadlines."""

    team_id_by_name = _team_ids()
    elements = [
        _element(index, entry, team_id_by_name[str(entry["team_name"])])
        for index, entry in enumerate(roster_entries())
    ]
    document: dict[str, Any] = {
        "teams": [
            # The persistent code is deliberately not the per-season id: handing one where
            # the other is meant matches nothing rather than raising, and the table under
            # test translates between them.
            {"id": identifier, "name": name, "code": 700 + identifier}
            for name, identifier in team_id_by_name.items()
        ],
        "elements": elements,
        "events": [
            {"id": 1, "deadline_time": "2026-08-14T17:30:00Z", "finished": True},
            {"id": 2, "deadline_time": "2026-08-22T17:30:00Z", "finished": True},
            {"id": 3, "deadline_time": "2026-09-05T17:30:00Z", "finished": True},
            {"id": TARGET_GAMEWEEK, "deadline_time": DEADLINE, "finished": False},
        ],
    }
    return json.dumps(document).encode("utf-8")


def fixtures_payload(*, kickoff_known: bool = True) -> bytes:
    """The captured calendar.

    ``kickoff_known=False`` drops the kickoff time from one fixture in the window, which is
    the state the midweek reading must refuse rather than answer.
    """

    team_id_by_name = _team_ids()
    midweek = team_id_by_name[MIDWEEK_CLUB]
    opponent = team_id_by_name[OPPONENT_CLUB]
    weekend = sorted(
        identifier
        for name, identifier in team_id_by_name.items()
        if name not in (MIDWEEK_CLUB, OPPONENT_CLUB)
    )

    def fixture(
        fixture_id: int, gameweek: int, home: int, away: int, kickoff: str | None
    ) -> dict[str, Any]:
        return {
            "id": fixture_id,
            "event": gameweek,
            "team_h": home,
            "team_a": away,
            "team_h_difficulty": 3,
            "team_a_difficulty": 3,
            "kickoff_time": kickoff,
            "finished": gameweek < TARGET_GAMEWEEK,
            "provisional_start_time": False,
        }

    records = [
        # The previous round. The midweek club played inside the window against a club with
        # no players on this roster, so exactly one roster club is marked; the others played
        # at the weekend, before the window opens.
        fixture(301, TARGET_GAMEWEEK - 1, midweek, opponent, MIDWEEK_KICKOFF),
        fixture(
            302,
            TARGET_GAMEWEEK - 1,
            weekend[0],
            weekend[1],
            WEEKEND_KICKOFF if kickoff_known else None,
        ),
        # This round, after the deadline and therefore outside the window.
        fixture(401, TARGET_GAMEWEEK, weekend[0], midweek, TARGET_KICKOFF),
        fixture(402, TARGET_GAMEWEEK, weekend[1], opponent, TARGET_KICKOFF),
    ]
    return json.dumps(records).encode("utf-8")


#: The source name a live capture is written under.
DECISION_SOURCE: Final = "fpl-live"


def decision_snapshot(
    *, kickoff_known: bool = True, captured_at: str = CAPTURED_AT
) -> CapturedSnapshot:
    """The capture as the store would hand it back, id and fingerprint included.

    Built through the store's own fingerprint and id functions rather than with a made-up
    identifier, so the provenance a row records has the shape a real one does -- the
    artifact name is derived from the last twelve characters of it.

    ``captured_at`` moves the capture instant. Passing one earlier than ``FETCHED_AT`` is how
    a test reaches the state where the club documents were fetched after the decision was
    captured, which the builder refuses.
    """

    payloads = {
        BOOTSTRAP_PAYLOAD: bootstrap_payload(),
        FIXTURES_PAYLOAD: fixtures_payload(kickoff_known=kickoff_known),
    }
    checksums = {name: payload_checksum(content) for name, content in payloads.items()}
    fingerprint = snapshot_fingerprint(
        source=DECISION_SOURCE,
        captured_at_utc=captured_at,
        schema_version=SNAPSHOT_SCHEMA_VERSION,
        checksums=checksums,
    )
    return CapturedSnapshot(
        metadata=SnapshotMetadata(
            snapshot_id=build_snapshot_id(
                source=DECISION_SOURCE,
                captured_at_utc=captured_at,
                fingerprint=fingerprint,
            ),
            source=DECISION_SOURCE,
            captured_at_utc=captured_at,
            schema_version=SNAPSHOT_SCHEMA_VERSION,
            checksums=checksums,
            fingerprint=fingerprint,
        ),
        payloads=payloads,
    )
