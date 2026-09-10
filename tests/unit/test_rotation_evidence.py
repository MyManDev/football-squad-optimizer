"""The rotation evidence table, against the committed fixture and a capture that matches it.

Every input here is the real one: the committed club-news fixture's claims, parsed by the
real parser, joined against a synthetic capture whose roster is that fixture's roster. The
join under test is the join that will run in production; only the bytes are ours.
"""

from collections.abc import Sequence
from pathlib import Path

import pandas as pd
import pytest
from tests.fixtures.synthetic_rotation_capture import (
    CAPTURED_BEFORE_THE_DOCUMENTS,
    DEADLINE,
    MIDWEEK_CLUB,
    SEASON,
    TARGET_GAMEWEEK,
    club_names,
    decision_snapshot,
    roster_entries,
)

from squadopt.data.errors import DataSourceError, InvalidValueError
from squadopt.data.sources.club_news import FixtureClubNewsProvider
from squadopt.data.sources.club_news_claims import ParsedClaim, parse_claim_response
from squadopt.features.rotation_evidence import (
    CONTRACT_VERSION,
    FORBIDDEN_COLUMNS,
    ROTATION_EVIDENCE_COLUMNS,
    ClubModelProvenance,
    ModelProvenance,
    build_rotation_evidence_table,
)

FIXTURE_PATH = Path(__file__).resolve().parents[2] / "data" / "sample" / "club_news_v1.fixture.json"

PROMPT_SHA256 = "a" * 64
ARSENAL_RESPONSE_SHA256 = "b" * 64
UNITED_RESPONSE_SHA256 = "c" * 64


def _provenance(response_sha256: str) -> ModelProvenance:
    return ModelProvenance(
        identifier="synthetic-stub",
        version="fixture-1",
        prompt_sha256=PROMPT_SHA256,
        response_sha256=response_sha256,
    )


#: Two clubs, two responses, deliberately different digests. Every test in this module
#: therefore runs against the per-club path rather than a single digest that happens to be
#: right everywhere -- which is how the aliasing this replaced went unnoticed.
MODEL = ClubModelProvenance(
    by_club={
        "Arsenal": _provenance(ARSENAL_RESPONSE_SHA256),
        "Man Utd": _provenance(UNITED_RESPONSE_SHA256),
    }
)
CLUB_NEWS_SNAPSHOT_ID = "club-news-20260912T140500Z-0123456789ab"


@pytest.fixture(name="provider")
def _provider() -> FixtureClubNewsProvider:
    return FixtureClubNewsProvider(FIXTURE_PATH)


@pytest.fixture(name="claims")
def _claims(provider: FixtureClubNewsProvider) -> tuple[ParsedClaim, ...]:
    documents = [provider.fetch(url) for url in provider.urls]
    return parse_claim_response(provider.code(documents, provider.roster()), documents)


def _build(
    provider: FixtureClubNewsProvider,
    claims: Sequence[ParsedClaim],
    **overrides: object,
) -> pd.DataFrame:
    documents = [provider.fetch(url) for url in provider.urls]
    arguments: dict[str, object] = {
        "season": SEASON,
        "target_gameweek": TARGET_GAMEWEEK,
        "deadline_timestamp_utc": DEADLINE,
        "decision_snapshot": decision_snapshot(),
        "claims": claims,
        "documents": documents,
        "clubs_declared": provider.clubs_declared(),
        "clubs_covered": provider.clubs_covered(),
        "model": MODEL,
        "club_news_snapshot_id": CLUB_NEWS_SNAPSHOT_ID,
    }
    arguments.update(overrides)
    return build_rotation_evidence_table(**arguments)  # type: ignore[arg-type]


def _players_of(club: str) -> tuple[int, ...]:
    return tuple(
        int(entry["player_id"]) for entry in roster_entries() if entry["team_name"] == club
    )


@pytest.fixture(name="table")
def _table(provider: FixtureClubNewsProvider, claims: tuple[ParsedClaim, ...]) -> pd.DataFrame:
    return _build(provider, claims)


# --- shape and completeness -------------------------------------------------


def test_the_table_carries_exactly_the_declared_columns_in_order(table: pd.DataFrame) -> None:
    assert tuple(table.columns) == ROTATION_EVIDENCE_COLUMNS
    assert len(ROTATION_EVIDENCE_COLUMNS) == 28


def test_there_is_one_row_per_roster_player_always(table: pd.DataFrame) -> None:
    """The completeness identity, and the honest replacement for an arithmetic one."""

    assert len(table) == len(roster_entries())
    assert table.attrs["roster_size"] == len(roster_entries())
    assert table["player_id"].tolist() == sorted(
        int(entry["player_id"]) for entry in roster_entries()
    )


def test_the_table_carries_no_forbidden_column(table: pd.DataFrame) -> None:
    assert not set(table.columns) & FORBIDDEN_COLUMNS


def test_the_schema_itself_is_checked_against_the_forbidden_set() -> None:
    """Not only a caller's table. The module refuses to import if the schema collides.

    The Phase B export intersects the forbidden set with a table's own columns, which cannot
    fire while the exact-column check runs first -- so it guards a caller and not the
    contract. This one guards the contract, at the moment someone writes a column name.
    """

    assert not frozenset(ROTATION_EVIDENCE_COLUMNS) & FORBIDDEN_COLUMNS
    for name in ("confidence", "p_start", "probability", "news", "quote", "source_url"):
        assert name in FORBIDDEN_COLUMNS


def test_no_column_promises_a_number_about_starting(table: pd.DataFrame) -> None:
    """The one claim field is categorical, and no claim column carries a magnitude.

    Booleans are excluded deliberately rather than by accident: pandas reports a ``boolean``
    column as numeric, and a flag saying whether something was observed is not a number about
    how likely it is. What must not exist is a claim column carrying a quantity -- and the two
    byte offsets are a position in a document, not a quantity about a footballer.
    """

    magnitudes = [
        name
        for name in table.columns
        if name.startswith("rotation_claim")
        and str(table[name].dtype) not in {"boolean", "string"}
        and not name.endswith(("span_start", "span_end"))
    ]

    assert magnitudes == []
    assert table["rotation_disposition"].dtype == "string"
    assert str(table["rotation_claim_span_start"].dtype) == "Int64"


# --- absent is not zero -----------------------------------------------------


def test_the_two_observation_flags_are_never_missing(table: pd.DataFrame) -> None:
    for column in ("rotation_claim_observed", "model_evidence_observed"):
        assert not bool(table[column].isna().any()), column


def test_a_covered_club_that_said_nothing_about_a_player_is_not_an_uncovered_club(
    table: pd.DataFrame,
) -> None:
    """Rice's club was read and did not mention him. That is not the same as never reading it."""

    rice = table.loc[table["player_id"] == 900008].iloc[0]

    assert bool(rice["club_source_covered"]) is True
    assert bool(rice["rotation_claim_observed"]) is False
    assert pd.isna(rice["rotation_disposition"])


def test_a_club_no_document_was_read_for_is_recorded_as_uncovered(
    table: pd.DataFrame, provider: FixtureClubNewsProvider
) -> None:
    uncovered = set(provider.clubs_declared()) - set(provider.clubs_covered())
    assert uncovered, "the fixture is supposed to declare a club it never covered"

    for club in uncovered:
        rows = table.loc[table["player_id"].isin(_players_of(club))]
        assert not rows.empty
        assert not rows["club_source_covered"].any()
        assert not rows["rotation_claim_observed"].any()


def test_the_three_feed_news_states_are_all_distinguished(table: pd.DataFrame) -> None:
    """ "Never flagged" is about the feed; "cleared" is about the player. Not the same fact."""

    states = table.set_index("player_id")["feed_news_state"]

    assert states[900001] == "never_flagged"
    assert states[900002] == "cleared"
    assert states[900003] == "flagged"


def test_a_stated_chance_of_playing_is_kept_and_an_unstated_one_stays_missing(
    table: pd.DataFrame,
) -> None:
    chances = table.set_index("player_id")["feed_chance_of_playing_next_round"]

    assert int(chances[900003]) == 75
    assert pd.isna(chances[900004])


def test_an_empty_scout_risk_list_is_a_zero_and_a_published_one_is_counted(
    table: pd.DataFrame,
) -> None:
    counts = table.set_index("player_id")["feed_scout_risk_count"]

    assert int(counts[900001]) == 1
    assert int(counts[900002]) == 0


# --- the identity join ------------------------------------------------------


def test_an_ambiguous_name_is_attributed_to_neither_candidate(table: pd.DataFrame) -> None:
    """Two Fernandes on one roster. Guessing would put a manager's words on the wrong player."""

    colliding = table.loc[table["player_id"].isin([900012, 900013])]

    assert not colliding["rotation_claim_observed"].any()
    assert colliding["rotation_disposition"].isna().all()
    assert table.attrs["claims_ambiguous"] == 1


def test_a_name_that_matches_nobody_is_counted_and_not_forced_onto_a_player(
    table: pd.DataFrame, claims: tuple[ParsedClaim, ...]
) -> None:
    unresolved = dict(table.attrs["claims_unresolved"])

    assert unresolved.get("no_match") == 1
    assert table.attrs["claims_coded"] == len(claims) - sum(unresolved.values())


def test_the_players_nothing_was_said_about_are_counted(table: pd.DataFrame) -> None:
    not_addressed = int((~table["rotation_claim_observed"].astype("boolean")).sum())

    assert table.attrs["players_not_addressed"] == not_addressed


# --- the citation -----------------------------------------------------------


def test_a_claim_row_carries_a_digest_and_a_span_and_no_words(table: pd.DataFrame) -> None:
    saka = table.loc[table["player_id"] == 900001].iloc[0]

    assert len(str(saka["rotation_claim_source_sha256"])) == 64
    assert int(saka["rotation_claim_span_end"]) > int(saka["rotation_claim_span_start"])


def test_a_row_without_a_claim_carries_no_span(table: pd.DataFrame) -> None:
    rice = table.loc[table["player_id"] == 900008].iloc[0]

    assert pd.isna(rice["rotation_claim_span_start"])
    assert pd.isna(rice["rotation_claim_span_end"])
    assert pd.isna(rice["rotation_claim_source_sha256"])


def test_the_three_dateline_precisions_all_survive_into_the_table(table: pd.DataFrame) -> None:
    precisions = table.set_index("player_id")["rotation_claim_published_precision"]

    assert precisions[900001] == "instant"
    assert precisions[900009] == "day"
    assert precisions[900010] == "unknown"
    assert pd.isna(table.set_index("player_id")["rotation_claim_published_at_utc"][900010])


def test_a_day_dateline_is_not_widened_to_an_instant(table: pd.DataFrame) -> None:
    published = table.set_index("player_id")["rotation_claim_published_at_utc"]

    assert str(published[900009]) == "2026-09-11"


# --- provenance -------------------------------------------------------------


def test_a_row_lists_only_the_captures_it_was_actually_read_from(table: pd.DataFrame) -> None:
    """A capture that contributed nothing to a row is not one of that row's sources."""

    sources = table.set_index("player_id")["source_snapshot_ids"]
    decision_id = decision_snapshot().metadata.snapshot_id

    assert str(sources[900008]) == decision_id
    assert CLUB_NEWS_SNAPSHOT_ID in str(sources[900001])
    assert decision_id in str(sources[900001])


def test_the_manifest_diagnostics_ride_on_attrs(table: pd.DataFrame) -> None:
    for key in (
        "roster_size",
        "roster_snapshot_id",
        "source_snapshot_ids",
        "clubs_declared",
        "clubs_covered",
        "documents_read",
        "document_sha256s",
        "claims_coded",
        "claims_ambiguous",
        "players_not_addressed",
        "model_identifier",
        "model_version",
        "prompt_sha256",
        "response_sha256s",
    ):
        assert key in table.attrs, key


def test_without_a_model_the_model_columns_stay_missing_and_the_flag_stays_false(
    provider: FixtureClubNewsProvider, claims: tuple[ParsedClaim, ...]
) -> None:
    table = _build(provider, claims, model=None)

    assert table["model_identifier"].isna().all()
    assert table["prompt_sha256"].isna().all()
    assert table["model_response_sha256"].isna().all()
    assert not table["model_evidence_observed"].any()
    # Still never NA: "no model was involved" is an observation, not an absence.
    assert not bool(table["model_evidence_observed"].isna().any())


def test_the_two_observation_flags_are_computed_independently(table: pd.DataFrame) -> None:
    """They agree today because the model is the only claim source, and that is worth pinning.

    A later feed-derived disposition would set ``rotation_claim_observed`` without
    ``model_evidence_observed``. If the two had been aliased, the table could not say so.
    """

    assert table["rotation_claim_observed"].equals(table["model_evidence_observed"])


# --- the calendar -----------------------------------------------------------


def test_only_the_club_that_played_midweek_is_flagged(table: pd.DataFrame) -> None:
    midweek = table.loc[table["fixture_context_midweek"].astype("boolean"), "player_id"].tolist()

    assert sorted(midweek) == sorted(_players_of(MIDWEEK_CLUB))


def test_documents_fetched_after_the_capture_refuse_the_whole_week(
    provider: FixtureClubNewsProvider, claims: tuple[ParsedClaim, ...]
) -> None:
    """The half of the ordering constraint no column can express.

    ``timing_verified`` is a fact about a claim: every instant it rests on is earlier than
    the deadline. This is a fact about the *method*. If the club bytes were fetched after the
    capture was taken, whoever fetched them could have looked at the capture first, noticed a
    player who looked wrong, and gone hunting for words about him. That is not partially true
    on some rows, so it refuses the build rather than publishing a table with a caveat.
    """

    late = decision_snapshot(captured_at=CAPTURED_BEFORE_THE_DOCUMENTS)

    with pytest.raises(DataSourceError, match="frozen before the capture"):
        _build(provider, claims, decision_snapshot=late)


def test_the_capture_still_predates_the_deadline_in_that_refusal(
    provider: FixtureClubNewsProvider, claims: tuple[ParsedClaim, ...]
) -> None:
    """So the refusal above is the ordering rule and not the deadline rule wearing its coat."""

    late = decision_snapshot(captured_at=CAPTURED_BEFORE_THE_DOCUMENTS)

    assert late.metadata.captured_at_utc < DEADLINE


def test_a_calendar_that_cannot_answer_refuses_rather_than_saying_no(
    provider: FixtureClubNewsProvider, claims: tuple[ParsedClaim, ...]
) -> None:
    """A False that means "we could not tell" is the failure this whole table avoids."""

    with pytest.raises(DataSourceError, match="could not tell"):
        _build(provider, claims, decision_snapshot=decision_snapshot(kickoff_known=False))


# --- refusals ---------------------------------------------------------------


def test_the_locked_holdout_is_never_built(
    provider: FixtureClubNewsProvider, claims: tuple[ParsedClaim, ...]
) -> None:
    with pytest.raises(DataSourceError, match="locked holdout"):
        _build(provider, claims, season="2025-26")


def test_the_opening_gameweek_has_no_previous_round_to_read(
    provider: FixtureClubNewsProvider, claims: tuple[ParsedClaim, ...]
) -> None:
    with pytest.raises(InvalidValueError, match="at least 2"):
        _build(provider, claims, target_gameweek=1)


def test_coverage_cannot_exceed_what_the_week_declared(
    provider: FixtureClubNewsProvider, claims: tuple[ParsedClaim, ...]
) -> None:
    with pytest.raises(InvalidValueError, match="covered but were never declared"):
        _build(provider, claims, clubs_declared=("Arsenal",), clubs_covered=club_names())


def test_a_capture_missing_a_payload_the_table_reads_is_refused(
    provider: FixtureClubNewsProvider, claims: tuple[ParsedClaim, ...]
) -> None:
    from squadopt.data.snapshots import CapturedSnapshot
    from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD

    complete = decision_snapshot()
    thinner = CapturedSnapshot(
        metadata=complete.metadata,
        payloads={BOOTSTRAP_PAYLOAD: complete.payloads[BOOTSTRAP_PAYLOAD]},
    )

    with pytest.raises(DataSourceError, match="must carry"):
        _build(provider, claims, decision_snapshot=thinner)


def test_the_contract_version_is_stamped_on_every_row(table: pd.DataFrame) -> None:
    assert table["contract_version"].drop_duplicates().tolist() == [CONTRACT_VERSION]


# --- provenance is per club -------------------------------------------------


def test_two_clubs_rows_cite_two_different_responses(table: pd.DataFrame) -> None:
    """The point of the change, stated as a test.

    A model is called once per club, so a row's response digest has to be the digest of
    *that* club's answer. When one digest was written across every row, an Arsenal player's
    disposition carried a citation to bytes that never mentioned him -- and the digest looked
    correct, which is the worst kind of wrong.
    """

    indexed = table.set_index("player_id")["model_response_sha256"]
    arsenal = {indexed[identifier] for identifier in _players_of("Arsenal")}
    united = {indexed[identifier] for identifier in _players_of("Man Utd")}

    assert arsenal - {pd.NA} == {ARSENAL_RESPONSE_SHA256}
    assert united - {pd.NA} == {UNITED_RESPONSE_SHA256}
    assert ARSENAL_RESPONSE_SHA256 != UNITED_RESPONSE_SHA256


def test_the_manifest_lists_every_response_the_week_holds(table: pd.DataFrame) -> None:
    """Sorted, so two runs of the same week produce the same manifest."""

    assert table.attrs["response_sha256s"] == tuple(
        sorted((ARSENAL_RESPONSE_SHA256, UNITED_RESPONSE_SHA256))
    )


def test_the_instrument_stays_single_valued_on_every_row(table: pd.DataFrame) -> None:
    """One question was asked, however many times it was asked.

    ``prompt_sha256`` is a fact about the instrument and must not become per club just
    because the responses did.
    """

    assert set(table["prompt_sha256"].dropna()) == {PROMPT_SHA256}
    assert table.attrs["prompt_sha256"] == PROMPT_SHA256
    assert set(table["model_identifier"].dropna()) == {"synthetic-stub"}


def test_one_response_covering_several_clubs_is_listed_once(
    provider: FixtureClubNewsProvider, claims: tuple[ParsedClaim, ...]
) -> None:
    """The fixture answers once for every club, and that is not two calls.

    A manifest that listed the same digest twice would imply a second call there never was.
    """

    shared = _provenance(ARSENAL_RESPONSE_SHA256)
    table = _build(
        provider,
        claims,
        model=ClubModelProvenance(by_club={"Arsenal": shared, "Man Utd": shared}),
    )

    assert table.attrs["response_sha256s"] == (ARSENAL_RESPONSE_SHA256,)
    assert set(table["model_response_sha256"].dropna()) == {ARSENAL_RESPONSE_SHA256}


def test_a_claim_from_a_club_with_no_response_refuses_the_week(
    provider: FixtureClubNewsProvider, claims: tuple[ParsedClaim, ...]
) -> None:
    """A disposition whose response cannot be named is traceable to no bytes at all.

    Refused rather than written with some other club's digest beside it, which would hand a
    member a citation into a response about different players.
    """

    with pytest.raises(DataSourceError, match="Man Utd"):
        _build(
            provider,
            claims,
            model=ClubModelProvenance(by_club={"Arsenal": _provenance(ARSENAL_RESPONSE_SHA256)}),
        )


def test_every_club_missing_a_response_is_named_at_once(
    provider: FixtureClubNewsProvider, claims: tuple[ParsedClaim, ...]
) -> None:
    """Whoever wired the provenance up wants the whole list, not the first club found."""

    with pytest.raises(DataSourceError) as error:
        _build(
            provider,
            claims,
            model=ClubModelProvenance(by_club={"Everton": _provenance(ARSENAL_RESPONSE_SHA256)}),
        )

    assert "Arsenal" in str(error.value)
    assert "Man Utd" in str(error.value)


def test_a_week_coded_by_two_models_is_refused() -> None:
    """The manifest states one model, so a mixture is not something it can express.

    Same reason the coding call declares no fallback: a week whose claims came from
    somewhere other than the model the manifest names is not a week anyone can check.
    """

    other = ModelProvenance(
        identifier="another-model",
        version="fixture-1",
        prompt_sha256=PROMPT_SHA256,
        response_sha256=UNITED_RESPONSE_SHA256,
    )

    with pytest.raises(InvalidValueError, match="disagree about identifier"):
        ClubModelProvenance(
            by_club={"Arsenal": _provenance(ARSENAL_RESPONSE_SHA256), "Man Utd": other}
        )


def test_a_week_asked_two_different_questions_is_refused() -> None:
    """Two prompts are two measurements, and the manifest digests one."""

    other = ModelProvenance(
        identifier="synthetic-stub",
        version="fixture-1",
        prompt_sha256="d" * 64,
        response_sha256=UNITED_RESPONSE_SHA256,
    )

    with pytest.raises(InvalidValueError, match="disagree about prompt_sha256"):
        ClubModelProvenance(
            by_club={"Arsenal": _provenance(ARSENAL_RESPONSE_SHA256), "Man Utd": other}
        )


def test_a_week_served_by_two_model_versions_is_refused() -> None:
    """A request naming an alias can be served by a snapshot, and two snapshots are a mixture."""

    other = ModelProvenance(
        identifier="synthetic-stub",
        version="fixture-2",
        prompt_sha256=PROMPT_SHA256,
        response_sha256=UNITED_RESPONSE_SHA256,
    )

    with pytest.raises(InvalidValueError, match="disagree about version"):
        ClubModelProvenance(
            by_club={"Arsenal": _provenance(ARSENAL_RESPONSE_SHA256), "Man Utd": other}
        )


def test_provenance_naming_no_club_is_refused() -> None:
    """A week in which no club was coded carries no provenance, not an empty one."""

    with pytest.raises(InvalidValueError, match="at least one club"):
        ClubModelProvenance(by_club={})


def test_a_club_must_be_named() -> None:
    """A blank key cannot be matched against a roster's club, so it is refused on the way in."""

    with pytest.raises(InvalidValueError, match="must be named"):
        ClubModelProvenance(by_club={"  ": _provenance(ARSENAL_RESPONSE_SHA256)})


def test_the_mapping_is_copied_on_construction() -> None:
    """A caller editing its own dict afterwards would be editing a written manifest."""

    supplied = {"Arsenal": _provenance(ARSENAL_RESPONSE_SHA256)}
    model = ClubModelProvenance(by_club=supplied)

    supplied["Man Utd"] = _provenance(UNITED_RESPONSE_SHA256)

    assert set(model.by_club) == {"Arsenal"}
    assert model.response_sha256s == (ARSENAL_RESPONSE_SHA256,)


def test_asking_for_an_uncoded_clubs_response_refuses_rather_than_guessing() -> None:
    """Reached directly, because the table's own check runs before the rows are built."""

    model = ClubModelProvenance(by_club={"Arsenal": _provenance(ARSENAL_RESPONSE_SHA256)})

    with pytest.raises(DataSourceError, match="Everton"):
        model.response_sha256_for("Everton")
