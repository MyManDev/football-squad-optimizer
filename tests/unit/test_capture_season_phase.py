"""Tests for the season phase of a capture's cumulative counters.

The counters in an element record -- ``minutes``, ``total_points``, ``starts`` and the
rest -- mean the previous season before the platform resets them and this season
afterwards. Nothing in the payload states which. Both readings are plausible numbers,
so a wrong answer here is invisible downstream, and that is what these tests are for.

Payload builders are borrowed from the adapter's own test module rather than rebuilt,
for the same reason every other borrowed fixture in this suite is: two copies drift.
Their defaults already spell the real window -- opening deadline 17:30Z, first kick-off
19:00Z on 2026-08-21 -- so the boundaries under test are the measured ones.
"""

import pytest
from tests.unit.test_source_fpl_live import (
    _element,
    _fixture,
    _fixtures_payload,
    _payload,
)

from squadopt.data.errors import DataSourceError, DuplicateRecordsError, InvalidValueError
from squadopt.data.sources.fpl_live import (
    SEASON_RELATIVE_ELEMENT_FIELDS,
    CaptureSeasonPhase,
    capture_season_phase,
    in_season_totals,
)

OPENING_DEADLINE = "2026-08-21T17:30:00Z"
FIRST_KICKOFF = "2026-08-21T19:00:00Z"


def _both() -> tuple[bytes, bytes]:
    return _payload(), _fixtures_payload()


# --- the three phases --------------------------------------------------------


@pytest.mark.parametrize(
    ("captured", "expected"),
    [
        ("2026-08-13T20:11:43Z", "prior_season"),
        ("2026-08-20T17:05:25Z", "prior_season"),
        ("2026-08-21T17:29:59Z", "prior_season"),
        ("2026-08-21T17:30:00Z", "unobserved_transition"),
        ("2026-08-21T18:59:59Z", "unobserved_transition"),
        ("2026-08-21T19:00:00Z", "current_season"),
        ("2026-09-04T15:00:00Z", "current_season"),
    ],
)
def test_the_phase_follows_the_capture_instant(captured: str, expected: str) -> None:
    """The two real captures are the first two cases; the rest walk the boundaries."""

    bootstrap, fixtures = _both()

    phase = capture_season_phase(bootstrap, fixtures, captured_at_utc=captured)

    assert phase.phase == expected
    assert phase.opening_deadline_utc == OPENING_DEADLINE
    assert phase.first_kickoff_utc == FIRST_KICKOFF


def test_the_window_between_the_deadline_and_the_first_kickoff_is_not_claimed() -> None:
    """The reset instant was never observed, so that window refuses rather than guesses.

    No capture exists between 17:30Z and 19:00Z, so whether the deadline or the
    kick-off triggers the reset is unmeasured. Claiming either would be an assertion
    about data nobody has.
    """

    bootstrap, fixtures = _both()

    phase = capture_season_phase(bootstrap, fixtures, captured_at_utc="2026-08-21T18:00:00Z")

    assert phase.phase == "unobserved_transition"
    assert not phase.describes_current_season


def test_only_the_current_season_phase_describes_this_season() -> None:
    bootstrap, fixtures = _both()

    for captured, current in (
        ("2026-08-20T17:05:25Z", False),
        ("2026-08-21T18:00:00Z", False),
        ("2026-08-21T19:00:00Z", True),
    ):
        phase = capture_season_phase(bootstrap, fixtures, captured_at_utc=captured)
        assert phase.describes_current_season is current


# --- the guard ---------------------------------------------------------------


@pytest.mark.parametrize("captured", ["2026-08-20T17:05:25Z", "2026-08-21T18:00:00Z"])
def test_a_capture_before_the_reset_has_no_in_season_history(captured: str) -> None:
    """The refusal is the point: those counters are the previous season's."""

    bootstrap, fixtures = _both()

    with pytest.raises(DataSourceError, match="no in-season history"):
        in_season_totals(bootstrap, fixtures, captured_at_utc=captured)


def test_the_refusal_names_the_window_and_what_to_do_about_it() -> None:
    """A caller who hits this needs the instants, not just a rejection."""

    bootstrap, fixtures = _both()

    with pytest.raises(DataSourceError) as error:
        in_season_totals(bootstrap, fixtures, captured_at_utc="2026-08-20T17:05:25Z")

    message = str(error.value)
    assert OPENING_DEADLINE in message
    assert FIRST_KICKOFF in message
    assert "capture after the first kick-off" in message


def test_a_capture_after_the_reset_yields_the_counters() -> None:
    bootstrap, fixtures = _both()

    table = in_season_totals(bootstrap, fixtures, captured_at_utc=FIRST_KICKOFF)

    assert tuple(table.columns) == ("player_id", *SEASON_RELATIVE_ELEMENT_FIELDS)
    assert len(table) == 1
    assert int(table.loc[0, "player_id"]) == 118748
    assert bool(table.notna().all().all())


# --- the shape a consumer joins on ------------------------------------------


def test_identity_is_the_persistent_code_not_the_per_season_id() -> None:
    """A handoff keys on the durable code; the two id spaces must not be confused."""

    bootstrap = _payload([_element(code=222222, id=7)])

    table = in_season_totals(bootstrap, _fixtures_payload(), captured_at_utc=FIRST_KICKOFF)

    assert table["player_id"].tolist() == [222222]


def test_non_player_entries_are_excluded() -> None:
    """Managers are not squad-eligible, on the same grounds player_snapshot uses."""

    bootstrap = _payload([_element(), _element(code=999999, id=99, element_type=5)])

    table = in_season_totals(bootstrap, _fixtures_payload(), captured_at_utc=FIRST_KICKOFF)

    assert table["player_id"].tolist() == [118748]


def test_output_is_sorted_by_player_id_regardless_of_source_order() -> None:
    bootstrap = _payload([_element(code=300000, id=2), _element(code=100000, id=1)])

    table = in_season_totals(bootstrap, _fixtures_payload(), captured_at_utc=FIRST_KICKOFF)

    assert table["player_id"].tolist() == [100000, 300000]


def test_a_repeated_persistent_code_is_rejected() -> None:
    bootstrap = _payload([_element(), _element(id=6)])

    with pytest.raises(DuplicateRecordsError, match="repeats player codes"):
        in_season_totals(bootstrap, _fixtures_payload(), captured_at_utc=FIRST_KICKOFF)


def test_a_payload_with_no_eligible_players_is_an_error_not_an_empty_table() -> None:
    bootstrap = _payload([_element(element_type=5)])

    with pytest.raises(DataSourceError, match="no squad-eligible players"):
        in_season_totals(bootstrap, _fixtures_payload(), captured_at_utc=FIRST_KICKOFF)


# --- a changed payload stops the run ----------------------------------------


@pytest.mark.parametrize("field", list(SEASON_RELATIVE_ELEMENT_FIELDS))
def test_a_renamed_counter_stops_the_run_and_names_itself(field: str) -> None:
    """A dropped counter must fail, not become a column of nulls."""

    record = _element()
    del record[field]

    with pytest.raises(DataSourceError, match=field):
        in_season_totals(_payload([record]), _fixtures_payload(), captured_at_utc=FIRST_KICKOFF)


def test_a_counter_that_is_not_an_integer_is_rejected() -> None:
    bootstrap = _payload([_element(minutes="2700")])

    with pytest.raises(InvalidValueError):
        in_season_totals(bootstrap, _fixtures_payload(), captured_at_utc=FIRST_KICKOFF)


def test_fixtures_without_any_kickoff_cannot_locate_the_reset() -> None:
    """Without a kick-off there is no instant to compare against, so it refuses."""

    fixtures = _fixtures_payload([_fixture(kickoff_time=None)])

    with pytest.raises(DataSourceError, match="publishes no kick-off time"):
        capture_season_phase(_payload(), fixtures, captured_at_utc=FIRST_KICKOFF)


def test_the_earliest_kickoff_is_the_boundary_not_the_first_listed() -> None:
    """Fixture order is the source's business; the reset follows the earliest kick-off."""

    fixtures = _fixtures_payload(
        [
            _fixture(id=2, kickoff_time="2026-08-22T14:00:00Z"),
            _fixture(id=1, kickoff_time=FIRST_KICKOFF),
        ]
    )

    phase = capture_season_phase(_payload(), fixtures, captured_at_utc="2026-08-22T13:00:00Z")

    assert phase.first_kickoff_utc == FIRST_KICKOFF
    assert phase.phase == "current_season"


def test_an_unknown_phase_cannot_be_constructed() -> None:
    """The phase set is closed; a typo must not become a fourth silent state."""

    with pytest.raises(InvalidValueError, match="Unknown capture season phase"):
        CaptureSeasonPhase(
            phase="mid_season",
            captured_at_utc=FIRST_KICKOFF,
            opening_deadline_utc=OPENING_DEADLINE,
            first_kickoff_utc=FIRST_KICKOFF,
        )
