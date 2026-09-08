"""Tests for the identity join: what it resolves, and what it refuses to guess at.

Driven partly by the committed club-news fixture, which is where the hard cases were
declared: a bare surname two players in one club share, a name matching nobody, and a short
name carrying a diacritic. Nothing here reaches a network.
"""

import json
from typing import Any

import pandas as pd
import pytest
from scripts.generate_club_news_fixture import FIXTURE_FILE

from squadopt.data.claim_identity import (
    MATCH_BASES,
    UNRESOLVED_REASONS,
    ResolvedClaim,
    UnresolvedClaim,
    claim_surname,
    normalise_claim_name,
    resolve_claim_player,
    roster_from_short_names,
)
from squadopt.data.errors import DataSourceError, DataValidationError, InvalidValueError
from squadopt.data.sources.club_news import FixtureClubNewsProvider, RosterPlayer
from squadopt.data.sources.fpl_live import SHORT_NAME_COLUMNS, short_name_roster

ARSENAL = "Arsenal"
UNITED = "Man Utd"


@pytest.fixture(name="roster")
def _roster() -> tuple[RosterPlayer, ...]:
    return FixtureClubNewsProvider(FIXTURE_FILE).roster()


def _player(player_id: int, web_name: str, team_name: str = ARSENAL) -> RosterPlayer:
    return RosterPlayer(player_id=player_id, web_name=web_name, team_name=team_name)


# --- folding ----------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Saka", "saka"),
        ("  SAKA  ", "saka"),
        ("Bukayo   Saka", "bukayo saka"),
        # The dot separates parts rather than being stripped, or the surname would be lost.
        ("B.Fernandes", "b fernandes"),
        ("O'Reilly", "o reilly"),
        ("Alexander-Arnold", "alexander arnold"),
    ],
)
def test_folding_settles_case_spacing_and_punctuation(value: str, expected: str) -> None:
    assert normalise_claim_name(value) == expected


def test_a_combining_mark_is_dropped() -> None:
    assert normalise_claim_name("Mart\u00ednez") == "martinez"
    assert normalise_claim_name("\u00c5s") == "as"


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        # A stroke or a ligature is one code point with no mark to drop, so decomposition
        # alone leaves it intact. These are the ones the closed table reaches.
        ("\u00d8degaard", "odegaard"),
        ("Sch\u00e4r", "schar"),
        ("\u00c6bischer", "aebischer"),
        ("Wei\u00df", "weiss"),
        ("\u0141ukasz", "lukasz"),
        ("Sigur\u00f0sson", "sigurdsson"),
    ],
)
def test_an_undecomposable_letter_folds_through_the_closed_table(value: str, expected: str) -> None:
    assert normalise_claim_name(value) == expected


def test_a_letter_outside_the_table_is_left_alone_rather_than_guessed_at() -> None:
    """Refusing loses a claim; a wrong fold names the wrong player."""

    assert normalise_claim_name("\u0416ivkovic") == "\u0436ivkovic"


def test_a_composed_and_a_decomposed_spelling_fold_to_one_key() -> None:
    """One page writes NFC and another NFD; the same player must not become two."""

    composed = "Martínez"
    decomposed = "Martínez"

    assert composed != decomposed
    assert normalise_claim_name(composed) == normalise_claim_name(decomposed)


def test_folding_an_empty_name_gives_an_empty_key() -> None:
    assert normalise_claim_name("   ") == ""


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Saka", "saka"),
        ("Bukayo Saka", "saka"),
        ("B.Fernandes", "fernandes"),
        ("A.Fernandes", "fernandes"),
        ("", ""),
    ],
)
def test_the_surname_is_the_last_part_however_it_is_separated(value: str, expected: str) -> None:
    assert claim_surname(value) == expected


# --- resolving --------------------------------------------------------------


def test_an_exact_short_name_resolves(roster: tuple[RosterPlayer, ...]) -> None:
    result = resolve_claim_player("Saka", ARSENAL, roster)

    assert result == ResolvedClaim(player_id=900001, matched_on="web_name")


def test_a_full_name_resolves_through_its_surname(roster: tuple[RosterPlayer, ...]) -> None:
    """A club page writes the full name; the payload publishes the short one."""

    result = resolve_claim_player("Bukayo Saka", ARSENAL, roster)

    assert result == ResolvedClaim(player_id=900001, matched_on="surname")


def test_a_claim_that_drops_a_diacritic_still_resolves(roster: tuple[RosterPlayer, ...]) -> None:
    """Without folding a real capture would silently lose the player."""

    result = resolve_claim_player("Martinez", ARSENAL, roster)

    assert isinstance(result, ResolvedClaim)
    assert result.matched_on == "web_name"


def test_the_club_narrows_the_search_before_the_name_is_looked_at() -> None:
    """The same short name in two clubs is two players, and the fetch is per club."""

    roster = (_player(1, "Smith", ARSENAL), _player(2, "Smith", UNITED))

    assert resolve_claim_player("Smith", ARSENAL, roster) == ResolvedClaim(1, "web_name")
    assert resolve_claim_player("Smith", UNITED, roster) == ResolvedClaim(2, "web_name")


def test_the_club_is_matched_by_the_same_folding_as_the_name() -> None:
    roster = (_player(1, "Saka", "Arsenal"),)

    assert resolve_claim_player("Saka", "  ARSENAL ", roster) == ResolvedClaim(1, "web_name")


def test_a_unique_surname_inside_one_club_is_the_same_person_not_a_likelier_one() -> None:
    roster = (_player(1, "B.Fernandes", UNITED), _player(2, "Mount", UNITED))

    assert resolve_claim_player("Fernandes", UNITED, roster) == ResolvedClaim(1, "surname")


# --- refusing ---------------------------------------------------------------


def test_a_surname_two_players_in_one_club_share_refuses(
    roster: tuple[RosterPlayer, ...],
) -> None:
    """The case the fixture exists to carry: refuse, never pick the more famous one."""

    result = resolve_claim_player("Fernandes", UNITED, roster)

    assert result == UnresolvedClaim(reason="ambiguous", candidates=(900012, 900013))


def test_a_name_matching_nobody_refuses(roster: tuple[RosterPlayer, ...]) -> None:
    result = resolve_claim_player("Ghost Player", ARSENAL, roster)

    assert result == UnresolvedClaim(reason="no_match")


def test_a_club_the_roster_does_not_carry_is_its_own_reason(
    roster: tuple[RosterPlayer, ...],
) -> None:
    """Never asked about that club is not asked-and-found-nobody."""

    result = resolve_claim_player("Kudus", "Tottenham", roster)

    assert result == UnresolvedClaim(reason="unknown_team")


def test_an_empty_name_refuses_rather_than_matching_the_first_player(
    roster: tuple[RosterPlayer, ...],
) -> None:
    assert resolve_claim_player("   ", ARSENAL, roster) == UnresolvedClaim(reason="no_match")


def test_two_players_sharing_a_short_name_in_one_club_refuse() -> None:
    """Ambiguity at the first tier, not only the second."""

    roster = (_player(1, "Smith"), _player(2, "Smith"))

    assert resolve_claim_player("Smith", ARSENAL, roster) == UnresolvedClaim(
        reason="ambiguous", candidates=(1, 2)
    )


def test_the_three_reasons_are_distinct_and_declared(roster: tuple[RosterPlayer, ...]) -> None:
    """None of them may stand in for another: they answer different questions."""

    reasons = {
        resolve_claim_player(name, team, roster).reason  # type: ignore[union-attr]
        for name, team in (
            ("Kudus", "Tottenham"),
            ("Ghost Player", ARSENAL),
            ("Fernandes", UNITED),
        )
    }

    assert reasons == set(UNRESOLVED_REASONS)


def test_an_unresolved_claim_cannot_claim_a_reason_it_does_not_have() -> None:
    with pytest.raises(ValueError, match="reason must be one of"):
        UnresolvedClaim(reason="probably_saka")


def test_only_an_ambiguous_claim_may_name_candidates() -> None:
    with pytest.raises(ValueError, match="Only an ambiguous claim"):
        UnresolvedClaim(reason="no_match", candidates=(1,))


def test_an_ambiguous_claim_with_one_candidate_would_be_a_resolution() -> None:
    with pytest.raises(ValueError, match="at least two candidates"):
        UnresolvedClaim(reason="ambiguous", candidates=(1,))


def test_a_resolution_declares_which_tier_matched() -> None:
    with pytest.raises(ValueError, match="matched_on must be one of"):
        ResolvedClaim(player_id=1, matched_on="vibes")

    assert set(MATCH_BASES) == {"web_name", "surname"}


# --- the roster the join runs against ---------------------------------------


def _bootstrap_element(
    code: int, web_name: str, *, team: int = 1, **overrides: Any
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "code": code,
        "id": code,
        "first_name": "Given",
        "second_name": "Name",
        "web_name": web_name,
        "team": team,
        "element_type": 3,
        "now_cost": 55,
    }
    record.update(overrides)
    return record


def _bootstrap(elements: list[dict[str, Any]]) -> bytes:
    return json.dumps(
        {
            "teams": [
                {"id": 1, "code": 3, "name": "Arsenal", "short_name": "ARS"},
                {"id": 14, "code": 14, "name": "Man Utd", "short_name": "MUN"},
            ],
            "elements": elements,
        }
    ).encode("utf-8")


def test_the_short_name_roster_reads_the_form_a_claim_uses() -> None:
    """`player_snapshot` joins first and second name; a press conference does not."""

    frame = short_name_roster(_bootstrap([_bootstrap_element(118748, "Saka")]))

    assert tuple(frame.columns) == SHORT_NAME_COLUMNS
    assert frame["web_name"].tolist() == ["Saka"]
    assert frame["player_id"].tolist() == [118748]
    assert frame["team_name"].tolist() == ["Arsenal"]


def test_a_payload_without_web_name_stops_the_run_and_names_the_field() -> None:
    record = _bootstrap_element(1, "Saka")
    del record["web_name"]

    with pytest.raises(DataSourceError, match="web_name"):
        short_name_roster(_bootstrap([record]))


def test_an_empty_web_name_is_rejected() -> None:
    with pytest.raises(InvalidValueError, match="empty web_name"):
        short_name_roster(_bootstrap([_bootstrap_element(1, "   ")]))


def test_a_player_on_an_undeclared_team_cannot_be_resolved_within_it() -> None:
    with pytest.raises(InvalidValueError, match="does not declare"):
        short_name_roster(_bootstrap([_bootstrap_element(1, "Saka", team=99)]))


def test_non_players_are_excluded_from_the_short_name_roster() -> None:
    frame = short_name_roster(
        _bootstrap(
            [
                _bootstrap_element(1, "Saka"),
                _bootstrap_element(2, "Arteta", element_type=5),
            ]
        )
    )

    assert frame["player_id"].tolist() == [1]


def test_a_roster_with_no_eligible_players_is_an_error_not_an_empty_table() -> None:
    with pytest.raises(DataSourceError, match="no roster"):
        short_name_roster(_bootstrap([_bootstrap_element(1, "Arteta", element_type=5)]))


def test_the_bridge_turns_the_table_into_the_seams_shape() -> None:
    frame = short_name_roster(
        _bootstrap([_bootstrap_element(1, "Saka"), _bootstrap_element(2, "Mount", team=14)])
    )

    roster = roster_from_short_names(frame)

    assert roster == (
        RosterPlayer(player_id=1, web_name="Saka", team_name="Arsenal"),
        RosterPlayer(player_id=2, web_name="Mount", team_name="Man Utd"),
    )


def test_the_bridge_refuses_a_table_of_the_wrong_shape() -> None:
    with pytest.raises(DataValidationError, match="missing columns"):
        roster_from_short_names(pd.DataFrame({"player_id": [1]}))


def test_a_claim_resolves_against_a_roster_read_from_a_capture() -> None:
    """The whole point of the bridge: the join runs on real bytes, not only the fixture."""

    roster = roster_from_short_names(
        short_name_roster(
            _bootstrap(
                [
                    _bootstrap_element(118748, "Saka"),
                    _bootstrap_element(200001, "B.Fernandes", team=14),
                    _bootstrap_element(200002, "A.Fernandes", team=14),
                ]
            )
        )
    )

    assert resolve_claim_player("Bukayo Saka", "Arsenal", roster) == ResolvedClaim(
        player_id=118748, matched_on="surname"
    )
    assert resolve_claim_player("Fernandes", "Man Utd", roster) == UnresolvedClaim(
        reason="ambiguous", candidates=(200001, 200002)
    )
