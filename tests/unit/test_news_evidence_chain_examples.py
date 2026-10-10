"""Worked examples of the club-news evidence chain, one test per rule a claim must pass.

Each case builds a real capture, export and table offline and reads it back the way the
advice service does. Nothing reaches a network or calls a model.

The cases follow the chain in order: where the publication date comes from, which wordings
bind a player, which match a statement is about, why a statement is refused, what a wrong
citation costs, whose response may speak about whom, and what replayed legacy coding is
allowed to assert.
"""

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from tests.fixtures.synthetic_rotation_capture import (
    CAPTURED_AT,
    DEADLINE,
    DECISION_SOURCE,
    SEASON,
    TARGET_GAMEWEEK,
    TARGET_KICKOFF,
    bootstrap_payload,
    fixtures_payload,
    roster_entries,
)
from tests.unit.test_club_news_coding_versions import _document, _response
from tests.unit.test_news_attestation_chain import _pair, _rewrite
from tests.unit.test_rotation_export_from_capture import (
    CLAIM_COLUMNS,
    _coded_responses,
    _export,
    _players_of,
    _response_for,
)

from squadopt.application.football_context import manager_word_attestation_reason
from squadopt.application.manager_words import ManagerWord, load_manager_words
from squadopt.application.rotation_export import (
    RotationExportRequest,
    _inputs_from_capture,
    export_rotation_evidence,
)
from squadopt.data.errors import DataValidationError
from squadopt.data.snapshots import read_snapshot, write_snapshot
from squadopt.data.sources.club_news import ClaimResponse, RawDocument
from squadopt.data.sources.club_news_capture import CodedClub, write_club_news_capture
from squadopt.data.sources.club_news_coding import (
    ROTATION_CLAIM_CODING_CONTRACT_VERSION,
    coding_prompt_sha256,
)
from squadopt.data.sources.club_news_scope import verified_fixture_scope
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD
from squadopt.features.rotation_evidence_artifact import read_rotation_evidence_artifact

ABSENCE = "Saka will miss the next Premier League match."
#: The instant the held document states for itself (see ``_document``).
SOURCE_DATE = "2026-09-12T13:00:00Z"
#: The address no document was fetched from.
UNKNOWN_URL = "https://example.invalid/not-fetched"
#: Arsenal's league fixture of the target gameweek in the synthetic calendar.
TARGET_FIXTURE_ID = 401


# --- helpers ----------------------------------------------------------------


def _stating(published_at: str, precision: str = "instant") -> ClaimResponse:
    """The model's answer about ``ABSENCE``, declaring this publication date for the page."""

    response = _response(quote=ABSENCE, label="stated_expected_absent")
    answer = json.loads(response.text)
    answer["documents"][0].update(
        {"published_at_utc": published_at, "published_precision": precision}
    )
    return replace(response, text=json.dumps(answer))


def _published(instant: str) -> RawDocument:
    """The held page saying ``ABSENCE``, with its own dateline moved to ``instant``."""

    document = _document(ABSENCE)
    assert SOURCE_DATE.encode() in document.content
    content = document.content.replace(SOURCE_DATE.encode(), instant.encode())
    return replace(document, content=content, readable=content, byte_length=len(content))


def _chain(
    tmp_path: Path,
    *,
    document: RawDocument | None = None,
    response: ClaimResponse | None = None,
    bootstrap: bytes | None = None,
    fixtures: list[dict[str, Any]] | None = None,
) -> tuple[Path, Path, Path]:
    """A real capture, export and table for the cases ``_pair`` cannot express.

    ``_pair`` fixes the model's stated date, the page's own dateline, the bootstrap and the
    fixtures the calendar already holds. This builds the same chain with any of those four
    replaced, and returns what ``_pair`` returns.
    """

    version = ROTATION_CLAIM_CODING_CONTRACT_VERSION
    root = tmp_path / "snapshots"
    decision = write_snapshot(
        root,
        source=DECISION_SOURCE,
        captured_at_utc=CAPTURED_AT,
        payloads={
            BOOTSTRAP_PAYLOAD: bootstrap_payload() if bootstrap is None else bootstrap,
            FIXTURES_PAYLOAD: fixtures_payload()
            if fixtures is None
            else json.dumps(fixtures).encode(),
        },
    ).snapshot_id
    news = write_club_news_capture(
        root,
        documents=(_document(ABSENCE) if document is None else document,),
        coded=(
            CodedClub(
                "Arsenal",
                _stating(SOURCE_DATE) if response is None else response,
                version,
                coding_prompt_sha256(contract_version=version),
            ),
        ),
        clubs_declared=("Arsenal",),
        clubs_covered=("Arsenal",),
        captured_at_utc="2026-09-12T14:30:00Z",
    )
    result = export_rotation_evidence(
        RotationExportRequest(
            SEASON,
            TARGET_GAMEWEEK,
            DEADLINE,
            decision,
            root,
            None,
            tmp_path / "out",
            club_news_snapshot=news.snapshot_id,
            table_name="table",
        ),
        repository_commit="0" * 40,
    )
    return result["table_path"], result["manifest_path"], root / news.snapshot_id


def _observed(table_path: Path, manifest_path: Path) -> Any:
    """The one row of the checked table that carries a claim."""

    table = read_rotation_evidence_artifact(table_path, manifest_path)
    (index,) = table.index[table.rotation_claim_observed]
    return table.loc[index]


def _word(table_path: Path, source: Path) -> ManagerWord:
    """The one statement the reader makes of the table and its held source."""

    (word,) = load_manager_words(table_path, club_news_source=source).words
    return word


def _forge(table_path: Path, manifest_path: Path, **values: object) -> None:
    """Rewrite columns of the claimed row and give the manifest the new table digest."""

    def change(frame: pd.DataFrame) -> None:
        for column, value in values.items():
            frame.loc[frame.rotation_claim_observed, column] = value

    _rewrite(table_path, manifest_path, change)


def _scope_as_built_and_as_read(
    table_path: Path, manifest_path: Path, source: Path, *, expected: bool
) -> ManagerWord:
    """Assert the table's scope flag, then the reader's own answer about the same claim.

    Where the table says no, its flag is first rewritten to yes: the reader has to rebuild
    the calendar from the decision capture, not repeat what the table says.
    """

    assert bool(_observed(table_path, manifest_path).rotation_claim_scope_verified) is expected
    if not expected:
        _forge(table_path, manifest_path, rotation_claim_scope_verified=True)
    word = _word(table_path, source)
    assert word.scope_verified is expected
    return word


def _arsenal_fixture(event: int | None, kickoff: str | None) -> dict[str, Any]:
    """One more Arsenal league fixture, in ``event`` (``None`` is not yet assigned)."""

    teams = {team["name"]: team["id"] for team in json.loads(bootstrap_payload())["teams"]}
    return {
        **json.loads(fixtures_payload())[0],
        "id": 9999,
        "event": event,
        "team_h": teams["Arsenal"],
        "team_a": teams["Fulham"],
        "kickoff_time": kickoff,
        "finished": False,
    }


def _with_fixture(
    tmp_path: Path, event: int | None, kickoff: str | None
) -> tuple[Path, Path, Path]:
    """The default chain with one more Arsenal fixture in the captured calendar."""

    extra = _arsenal_fixture(event, kickoff)
    if event is None or event <= TARGET_GAMEWEEK:
        return _pair(tmp_path, extra_fixture=extra)
    # The committed bootstrap publishes no gameweek after the target, and the export refuses
    # a fixture in a gameweek the bootstrap does not publish. So a later gameweek needs a
    # bootstrap that declares it.
    bootstrap = json.loads(bootstrap_payload())
    bootstrap["events"].append(
        {"id": event, "deadline_time": "2026-09-19T17:30:00Z", "finished": False}
    )
    return _chain(
        tmp_path,
        bootstrap=json.dumps(bootstrap).encode(),
        fixtures=[*json.loads(fixtures_payload()), extra],
    )


def _player_id(name: str, club: str) -> int:
    (entry,) = (
        entry
        for entry in roster_entries()
        if entry["web_name"] == name and entry["team_name"] == club
    )
    return int(entry["player_id"])


def _club_responses() -> dict[str, dict[str, Any]]:
    """Arsenal's and Man Utd's coding answers, one call per club, ready to be edited."""

    return {club: json.loads(_response_for(club).text) for club in ("Arsenal", "Man Utd")}


def _claim_about(response: dict[str, Any], name: str) -> dict[str, Any]:
    (claim,) = (entry for entry in response["claims"] if entry["player_name"] == name)
    return claim


# --- A: the publication date is the source's, not the model's ----------------


@pytest.mark.parametrize(
    ("stated", "precision", "agrees"),
    [
        (SOURCE_DATE, "instant", True),
        ("2026-09-12T12:00:00Z", "instant", False),
        ("2026-09-12", "day", False),
    ],
)
def test_the_table_carries_the_source_date_whatever_the_model_states(
    tmp_path: Path, stated: str, precision: str, agrees: bool
) -> None:
    """A model that states another date than the page must not move the date or keep a role.

    If this failed, either the model's own instant would be stored as an observed source
    fact, or a statement whose date the model got wrong would still constrain a player.
    """

    table_path, manifest_path, source = _chain(tmp_path, response=_stating(stated, precision))

    row = _observed(table_path, manifest_path)
    assert row.rotation_claim_published_at_utc == SOURCE_DATE
    assert row.rotation_claim_published_precision == "instant"
    assert bool(row.rotation_claim_publication_verified) is agrees

    word = _word(table_path, source)
    assert word.words == ABSENCE
    assert word.published_at_utc == SOURCE_DATE
    # The wording and the calendar are sound in all three cases: only the date decides.
    assert word.scope_verified
    assert word.publication_verified is agrees
    assert word.role == ("not_starting" if agrees else None)
    assert manager_word_attestation_reason(word) == (None if agrees else "publication_unverified")


@pytest.mark.parametrize(
    "forged",
    [
        {"rotation_claim_published_at_utc": "2026-09-12T12:00:00Z"},
        {
            "rotation_claim_published_at_utc": "2026-09-12",
            "rotation_claim_published_precision": "day",
        },
    ],
    ids=["another_instant", "day_precision"],
)
def test_a_publication_date_forged_after_export_is_not_reported_verified(
    tmp_path: Path, forged: dict[str, str]
) -> None:
    """The reader compares the table's date with the held page, not with the table's flag.

    If this failed, editing one cell of a published table (and its digest) would change
    when a statement is said to have been published while it still read as verified.
    """

    table_path, manifest_path, source = _pair(tmp_path)
    assert _word(table_path, source).role == "not_starting"

    _forge(table_path, manifest_path, **forged)

    # The table still claims it, and the artifact check alone cannot tell.
    assert bool(_observed(table_path, manifest_path).rotation_claim_publication_verified)
    word = _word(table_path, source)
    assert word.published_at_utc == forged["rotation_claim_published_at_utc"]
    assert not word.publication_verified
    assert word.role is None


# --- B: which absence wordings bind the named player -------------------------


@pytest.mark.parametrize(
    ("quote", "accepted"),
    [
        ("Saka will miss the next Premier League match.", True),
        ("Saka is ruled out for the next Premier League match.", True),
        ("Saka has been ruled out of the next Premier League match.", True),
        ("Saka won't feature in the next Premier League match.", True),
        ("Saka will not travel to the next Premier League match.", True),
        ("Saka is unavailable for the upcoming league game.", True),
        ("Saka misses the next Premier League match.", True),
        ("Saka is sidelined for the next Premier League match.", True),
        ("Saka will play no part in the next Premier League match.", True),
        ("Saka is not available for the next Premier League match.", True),
        ("Saka will miss the next Premier League fixture.", True),
        # The tense and contraction forms the rule already reads for its other predicates.
        ("Saka has been sidelined for the next Premier League match.", True),
        ("Saka will be sidelined for the next Premier League match.", True),
        ("Saka isn't available for the next Premier League match.", True),
        # Natural wordings the finite rule does not read. They stay readable and unapplied.
        ("Saka will sit out the next Premier League match.", False),
        ("Saka will miss Saturday's Premier League match.", False),
        ("Bukayo Saka will miss the next Premier League match.", False),
    ],
)
def test_an_absence_wording_binds_the_named_player_only_where_the_rule_reads_it(
    tmp_path: Path, quote: str, accepted: bool
) -> None:
    """Each wording is pinned as the scope rule reads it, from the page to the member's plan.

    If an accepted wording failed, a plain statement of absence would stop constraining the
    player. If an unaccepted one failed, the rule has widened and should be reviewed.
    """

    assert (
        verified_fixture_scope(quote.encode(), "stated_expected_absent", player_name="Saka")[1]
        is accepted
    )

    table_path, manifest_path, source = _pair(tmp_path, quote=quote)

    assert bool(_observed(table_path, manifest_path).rotation_claim_scope_verified) is accepted
    word = _word(table_path, source)
    assert word.player_id == _player_id("Saka", "Arsenal")
    assert word.words == quote and word.publication_verified
    assert word.scope_verified is accepted
    assert word.role == ("not_starting" if accepted else None)


# --- C: a full-match limit binds only the player it names --------------------


@pytest.mark.parametrize(
    ("quote", "names_the_claimed_player"),
    [
        ("Saka cannot complete the full upcoming league match.", True),
        ("Timber cannot complete the full upcoming league match.", False),
    ],
)
def test_a_full_match_limit_binds_only_the_player_it_names(
    tmp_path: Path, quote: str, names_the_claimed_player: bool
) -> None:
    """A sentence about Timber must not limit Saka's minutes because the model said Saka.

    If this failed, a full-match restriction would be applied to whichever player the model
    attached the sentence to. The label carries no first-week role for either player: its
    consumer is the football minute gate, which asks ``manager_word_attestation_reason``.
    """

    table_path, manifest_path, source = _pair(
        tmp_path, quote=quote, disposition="stated_full_match_unavailable"
    )

    row = _observed(table_path, manifest_path)
    assert row.player_id == _player_id("Saka", "Arsenal")
    assert bool(row.rotation_claim_scope_verified) is names_the_claimed_player
    if not names_the_claimed_player:
        # Claiming the scope in the table does not help: the reader reads the quote again.
        _forge(
            table_path,
            manifest_path,
            rotation_claim_fixture_scope="upcoming_premier_league",
            rotation_claim_scope_verified=True,
        )

    word = _word(table_path, source)
    assert word.words == quote and word.publication_verified
    assert word.scope_verified is names_the_claimed_player
    assert word.role is None
    assert manager_word_attestation_reason(word) == (
        None if names_the_claimed_player else "upcoming_league_scope_unverified"
    )


# --- D: the statement is about the club's next league match ------------------


@pytest.mark.parametrize(
    ("instant", "scope"),
    [
        # After the decision capture (15:00): nobody deciding could have read it.
        ("2026-09-12T15:30:00Z", False),
        # At the capture instant exactly. The scope rule admits it, and the role is still
        # withheld because the page claims a publication later than its own fetch (14:00).
        ("2026-09-12T15:00:00Z", True),
    ],
    ids=["after_the_capture", "at_the_capture"],
)
def test_a_source_published_at_or_after_the_decision_capture_constrains_nobody(
    tmp_path: Path, instant: str, scope: bool
) -> None:
    """A page dated after the decision was captured cannot have informed that decision.

    If this failed, a statement published too late for the week would still take a player
    out of a member's eleven.
    """

    table_path, manifest_path, source = _chain(
        tmp_path, document=_published(instant), response=_stating(instant)
    )

    word = _scope_as_built_and_as_read(table_path, manifest_path, source, expected=scope)

    # The model and the page agree on the date; what is wrong is where the date falls.
    assert word.published_at_utc == instant and word.publication_verified
    assert word.role is None


@pytest.mark.parametrize(
    ("kickoff", "expected"),
    [
        ("2026-09-12T14:30:00Z", False),
        (CAPTURED_AT, False),
        ("2026-09-12T15:00:01Z", True),
    ],
    ids=["before_the_capture", "at_the_capture", "one_second_after"],
)
def test_a_target_match_that_kicked_off_by_the_capture_is_not_the_next_match(
    tmp_path: Path, kickoff: str, expected: bool
) -> None:
    """The target match must still be ahead when the decision is captured.

    If this failed, "the next league match" would be bound to a match already under way or
    played, and the statement would constrain a week it does not describe.
    """

    fixtures = json.loads(fixtures_payload())
    (target,) = (fixture for fixture in fixtures if fixture["id"] == TARGET_FIXTURE_ID)
    assert target["event"] == TARGET_GAMEWEEK
    target["kickoff_time"] = kickoff

    table_path, manifest_path, source = _chain(tmp_path, fixtures=fixtures)

    word = _scope_as_built_and_as_read(table_path, manifest_path, source, expected=expected)
    assert word.role == ("not_starting" if expected else None)


@pytest.mark.parametrize(
    ("kickoff", "expected"),
    [
        # Between the capture and the target kickoff (19:00).
        ("2026-09-12T18:00:00Z", False),
        # Between the publication (13:00) and the capture.
        ("2026-09-12T14:00:00Z", False),
        # Already played when the page was published: the target is still the next match.
        ("2026-09-12T12:00:00Z", True),
        # A later gameweek with no kickoff yet is taken to follow the target.
        (None, True),
    ],
    ids=["after_the_capture", "before_the_capture", "before_publication", "undated"],
)
def test_a_later_gameweek_fixture_dated_before_the_target_unbinds_the_statement(
    tmp_path: Path, kickoff: str | None, expected: bool
) -> None:
    """A match of a later gameweek played first is the next match, whatever its number.

    If this failed, the statement would be applied to the target gameweek while the club's
    next match after publication was a different one.
    """

    table_path, manifest_path, source = _with_fixture(tmp_path, TARGET_GAMEWEEK + 1, kickoff)

    word = _scope_as_built_and_as_read(table_path, manifest_path, source, expected=expected)
    assert word.role == ("not_starting" if expected else None)


@pytest.mark.parametrize(
    "event",
    [None, TARGET_GAMEWEEK, TARGET_GAMEWEEK + 1],
    ids=["unassigned", "same_gameweek", "later_gameweek"],
)
def test_two_fixtures_sharing_the_first_kickoff_leave_the_statement_unbound(
    tmp_path: Path, event: int | None
) -> None:
    """With two matches at the first kickoff there is no single next match to bind to.

    If this failed, one of the two would be chosen silently and the statement applied to
    a match the source never singled out.
    """

    table_path, manifest_path, source = _with_fixture(tmp_path, event, TARGET_KICKOFF)

    word = _scope_as_built_and_as_read(table_path, manifest_path, source, expected=False)
    assert word.role is None


# --- E: why a statement is refused -------------------------------------------


@pytest.mark.parametrize(
    ("quote", "label"),
    [
        # Two different competitions, one label.
        ("Saka will miss the cup match.", "other_competition"),
        ("Saka will miss the national team game.", "other_competition"),
        ("Saka missed the previous league match.", "past"),
        # The present tense reads neither a past league fixture nor another competition.
        ("Saka misses the last Premier League fixture.", "past"),
        ("Saka misses the cup match.", "other_competition"),
        # A conditional shares its label with a wrong subject, a mixed reference and a
        # wording about the right match that the rule does not read.
        (
            "Saka will only feature in the next Premier League match if he passes a late test.",
            "ambiguous",
        ),
        ("Timber will miss the next Premier League match.", "ambiguous"),
        ("Saka will miss the next Premier League match after the cup match.", "ambiguous"),
        ("Saka will sit out the next Premier League match.", "ambiguous"),
        # No fixture at all shares its label with a fixture named in words outside the rule.
        ("Saka will not travel.", "unspecified"),
        ("Saka will miss Saturday's Premier League match.", "unspecified"),
    ],
    ids=[
        "cup",
        "national_team",
        "past_league_match",
        "past_league_fixture",
        "cup_in_the_present_tense",
        "conditional",
        "another_player",
        "league_and_cup_together",
        "unread_wording",
        "no_fixture",
        "fixture_named_by_day",
    ],
)
def test_a_refused_statement_carries_the_exact_reason_label(quote: str, label: str) -> None:
    """The label is what a reader of the record is told about why a statement was refused.

    If this failed, a refusal would be filed under another reason, or would stop being a
    refusal.
    """

    assert verified_fixture_scope(quote.encode(), "stated_expected_absent", player_name="Saka") == (
        label,
        False,
    )


@pytest.mark.parametrize(
    ("quote", "label"),
    [
        ("Saka will miss the cup match.", "other_competition"),
        ("Saka missed the previous league match.", "past"),
        ("Saka will not travel.", "unspecified"),
    ],
)
def test_the_table_records_ambiguous_when_the_model_declared_another_scope(
    tmp_path: Path, quote: str, label: str
) -> None:
    """The stored label is the rule's own only where the model declared the same one.

    If this failed, the table would carry a scope label that neither the rule nor the model
    stands behind alone. Here the model declared the upcoming league match for every quote.
    """

    assert verified_fixture_scope(quote.encode(), "stated_expected_absent", player_name="Saka") == (
        label,
        False,
    )

    table_path, manifest_path, _ = _pair(tmp_path, quote=quote)

    row = _observed(table_path, manifest_path)
    assert row.rotation_claim_fixture_scope == "ambiguous"
    assert not bool(row.rotation_claim_scope_verified)


# --- F: a genuine quote under a wrong address --------------------------------


@pytest.mark.parametrize(
    ("club", "name", "address"),
    [
        ("Arsenal", "Saka", "unknown"),
        ("Arsenal", "Saka", "another_club_page"),
        ("Man Utd", "Dalot", "own_club_other_page"),
    ],
)
def test_a_genuine_quote_under_a_wrong_address_is_a_failed_claim_and_not_a_silence(
    tmp_path: Path, club: str, name: str, address: str
) -> None:
    """The quote exists, but not where the claim says, so the claim fails and is recorded.

    A silent player is one whose club was read, with no claim and no failed claim. If this
    failed, a statement we could not stand behind would read as the club saying nothing
    about him, or would be accepted from a page it was never on.
    """

    responses = _club_responses()
    baseline = _export(
        tmp_path / "right", from_capture=True, coded=_coded_responses(responses)
    ).set_index("player_id")
    claim = _claim_about(responses[club], name)
    united_press = _claim_about(responses["Man Utd"], "Mount")["source_url"]
    wrong = UNKNOWN_URL if address == "unknown" else united_press
    assert claim["source_url"] != wrong
    claim["source_url"] = wrong

    damaged = _export(
        tmp_path / "wrong", from_capture=True, coded=_coded_responses(responses)
    ).set_index("player_id")

    player = _player_id(name, club)
    # Under its right address the same quote stands, so the address is all that changed.
    assert bool(baseline.loc[player, "rotation_claim_observed"])
    row = damaged.loc[player]
    assert bool(row["rotation_claim_unresolved"]) is True
    assert bool(row["rotation_claim_observed"]) is False
    assert pd.isna(row["rotation_disposition"])
    assert pd.isna(row["rotation_claim_span_start"])
    # The club's other statements survive, so the club is still covered, and nobody else's
    # row moved.
    assert bool(row["club_source_covered"]) is True
    columns = [*CLAIM_COLUMNS[1:], "rotation_claim_unresolved"]
    pd.testing.assert_frame_equal(
        damaged.drop(index=player)[columns], baseline.drop(index=player)[columns]
    )
    manifest = json.loads(
        (tmp_path / "wrong" / "out" / "table.manifest.json").read_text(encoding="utf-8")
    )
    assert club in manifest["clubs_covered"]


def test_a_club_whose_only_claim_cites_a_wrong_address_is_not_read_as_silent(
    tmp_path: Path,
) -> None:
    """Nothing the club said survives, so the club leaves the covered list.

    If this failed, every Arsenal player would read as "his club was read and said nothing
    about him" in a week where its one statement was lost to a bad citation.
    """

    responses = _club_responses()
    claim = _claim_about(responses["Arsenal"], "Saka")
    claim["source_url"] = UNKNOWN_URL
    responses["Arsenal"]["claims"] = [claim]

    table = _export(tmp_path, from_capture=True, coded=_coded_responses(responses)).set_index(
        "player_id"
    )

    arsenal = table.loc[list(_players_of("Arsenal"))]
    assert not arsenal.club_source_covered.any()
    assert not arsenal.rotation_claim_observed.any()
    flagged = set(arsenal.index[arsenal.rotation_claim_unresolved])
    assert flagged == {_player_id("Saka", "Arsenal")}
    united = table.loc[list(_players_of("Man Utd"))]
    assert united.club_source_covered.all()
    assert united.rotation_claim_observed.any()
    manifest = json.loads((tmp_path / "out" / "table.manifest.json").read_text(encoding="utf-8"))
    assert manifest["clubs_covered"] == ["Man Utd"]


# --- G: a rival's response cannot speak for another club ---------------------


def test_a_rival_response_cannot_change_another_clubs_player(tmp_path: Path) -> None:
    """Arsenal's answer, citing Arsenal's own page, says a Man Utd player is absent.

    If this failed, one club's page could contradict another club about its own player,
    and Mount's row would lose his club's statement or gain Arsenal's.
    """

    responses = _club_responses()
    baseline = _export(
        tmp_path / "own", from_capture=True, coded=_coded_responses(responses)
    ).set_index("player_id")
    own = _claim_about(responses["Man Utd"], "Mount")
    rival = {
        **_claim_about(responses["Arsenal"], "Havertz"),
        "player_name": "Mount",
        "team_name": "Man Utd",
    }
    assert rival["disposition"] != own["disposition"]
    assert rival["source_url"] != own["source_url"]
    responses["Arsenal"]["claims"].append(rival)

    table = _export(
        tmp_path / "rival", from_capture=True, coded=_coded_responses(responses)
    ).set_index("player_id")

    # The rival claim is not lost on the way: its quote locates on Arsenal's page and the
    # parser keeps it, so it is the table builder that turns it away.
    root = tmp_path / "rival" / "snapshots"
    (news,) = root.glob("club-news-*")
    inputs = _inputs_from_capture(read_snapshot(root, news.name))
    about_mount = {
        (claim.source_url, claim.disposition)
        for claim in inputs.claims
        if claim.player_name == "Mount"
    }
    assert about_mount == {
        (own["source_url"], own["disposition"]),
        (rival["source_url"], rival["disposition"]),
    }
    assert inputs.unverifiable == ()

    mount = _player_id("Mount", "Man Utd")
    assert table.loc[mount, "rotation_disposition"] == own["disposition"]
    assert not bool(table.loc[mount, "rotation_claim_unresolved"])
    # Every column of every Man Utd row, apart from the one that names the news capture,
    # whose bytes differ between the two weeks by construction.
    united = list(_players_of("Man Utd"))
    by_construction = ["source_snapshot_ids"]
    pd.testing.assert_frame_equal(
        table.loc[united].drop(columns=by_construction),
        baseline.loc[united].drop(columns=by_construction),
    )
    columns = [*CLAIM_COLUMNS[1:], "rotation_claim_unresolved"]
    pd.testing.assert_frame_equal(table[columns], baseline[columns])


# --- H: replayed legacy coding asserts nothing new ---------------------------


@pytest.mark.parametrize("version", ["rotation_claim_coding_v1", "rotation_claim_coding_v2"])
def test_legacy_coded_evidence_reads_without_assurance(tmp_path: Path, version: str) -> None:
    """Coding made before scope and publication were checked gains neither on replay.

    If this failed, an old response replayed through the current code would constrain a
    player on checks that were never part of its contract.
    """

    table_path, manifest_path, source = _pair(tmp_path, version=version)

    row = _observed(table_path, manifest_path)
    assert row.rotation_claim_fixture_scope == "unspecified"
    assert not bool(row.rotation_claim_scope_verified)
    assert not bool(row.rotation_claim_publication_verified)
    assert pd.isna(row.rotation_claim_publication_source)

    words = load_manager_words(table_path, club_news_source=source)
    (word,) = words.words
    assert word.words == ABSENCE
    assert not word.scope_verified and not word.publication_verified
    assert word.role is None
    assert words.exclusion() is None
    assert manager_word_attestation_reason(word) == "publication_unverified"

    # Turning the two flags on afterwards is refused with the whole table: a legacy row
    # carries no scope label and no publication source for them to rest on.
    _forge(
        table_path,
        manifest_path,
        rotation_claim_scope_verified=True,
        rotation_claim_publication_verified=True,
    )
    with pytest.raises(DataValidationError):
        load_manager_words(table_path, club_news_source=source)
