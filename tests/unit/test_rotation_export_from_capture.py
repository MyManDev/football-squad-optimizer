"""Evidence built from a durable capture, on the same path the fixture takes.

This is the integration R07 asks for, and its point is narrow: the capture path and the
fixture path are one production path with different bytes. Everything after
``_club_news_inputs`` -- locating, parsing, the identity join, the table, the manifest --
does not know which source it was handed, so a run from a real week's capture exercises
exactly the code the offline tests exercise.

Two things are asserted rather than described. The claims are identical between the two
sources, because they are the same week's words either way; and the provenance columns are
**not**, because they record different facts -- which question was asked, and which bytes
answered. A test that demanded both be equal would be demanding that the capture forget
where it came from.

Nothing here reaches a network or calls a model. The capture is written to a temporary
directory and read back through the store.
"""

import hashlib
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
    bootstrap_payload,
    fixtures_payload,
    roster_entries,
)

from squadopt.application.rotation_export import (
    RotationExportRequest,
    _inputs_from_capture,
    export_rotation_evidence,
)
from squadopt.data.errors import DataError, DataSourceError, InvalidValueError
from squadopt.data.snapshots import read_snapshot, write_snapshot
from squadopt.data.sources.club_news import (
    ClaimResponse,
    ClubNewsError,
    FixtureClubNewsProvider,
    RawDocument,
)
from squadopt.data.sources.club_news_capture import CodedClub, write_club_news_capture
from squadopt.data.sources.club_news_coding import (
    LEGACY_ROTATION_CLAIM_CODING_CONTRACT_VERSION,
    CodingFixture,
    coding_prompt_sha256,
)
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD

SAMPLE = Path(__file__).resolve().parents[2] / "data" / "sample"
FIXTURE = SAMPLE / "club_news_v1.fixture.json"
CODING_FIXTURE = SAMPLE / "club_news_coding_v1.fixture.json"
COMMIT = "0" * 40
NEWS_CAPTURED_AT = "2026-09-12T14:30:00Z"

CLAIM_COLUMNS = (
    "player_id",
    "rotation_claim_observed",
    "rotation_disposition",
    "rotation_claim_source_sha256",
    "rotation_claim_span_start",
    "rotation_claim_span_end",
    "rotation_claim_speaker",
    "club_source_covered",
)


def _decision(root: Path) -> str:
    metadata = write_snapshot(
        root,
        source=DECISION_SOURCE,
        captured_at_utc=CAPTURED_AT,
        payloads={BOOTSTRAP_PAYLOAD: bootstrap_payload(), FIXTURES_PAYLOAD: fixtures_payload()},
    )
    return metadata.snapshot_id


def _documents() -> tuple[RawDocument, ...]:
    provider = FixtureClubNewsProvider(FIXTURE)
    return tuple(provider.fetch(url) for url in provider.urls)


def _coded(clubs: tuple[str, ...] | None = None) -> tuple[CodedClub, ...]:
    response = CodingFixture(CODING_FIXTURE).response()
    covered = clubs if clubs is not None else FixtureClubNewsProvider(FIXTURE).clubs_covered()
    return tuple(
        CodedClub(
            club=club,
            response=response,
            prompt_contract_version=LEGACY_ROTATION_CLAIM_CODING_CONTRACT_VERSION,
            prompt_sha256=coding_prompt_sha256(
                contract_version=LEGACY_ROTATION_CLAIM_CODING_CONTRACT_VERSION
            ),
        )
        for club in covered
    )


def _news_capture(
    root: Path,
    *,
    documents: tuple[RawDocument, ...] | None = None,
    coded: tuple[CodedClub, ...] | None = None,
    captured_at: str = NEWS_CAPTURED_AT,
) -> str:
    provider = FixtureClubNewsProvider(FIXTURE)
    metadata = write_club_news_capture(
        root,
        documents=_documents() if documents is None else documents,
        coded=_coded() if coded is None else coded,
        clubs_declared=provider.clubs_declared(),
        clubs_covered=provider.clubs_covered(),
        captured_at_utc=captured_at,
    )
    return metadata.snapshot_id


def _export(
    tmp_path: Path, *, from_capture: bool, output: str = "out", **overrides: object
) -> pd.DataFrame:
    root = tmp_path / "snapshots"
    decision = _decision(root)
    news = _news_capture(root, **overrides) if from_capture else None  # type: ignore[arg-type]
    request = RotationExportRequest(
        SEASON,
        TARGET_GAMEWEEK,
        DEADLINE,
        decision,
        root,
        None if from_capture else FIXTURE,
        tmp_path / output,
        club_news_snapshot=news,
        table_name="table",
    )
    export_rotation_evidence(request, repository_commit=COMMIT)
    return pd.read_csv(tmp_path / output / "table.csv")


def _players_of(club: str) -> tuple[int, ...]:
    return tuple(
        int(entry["player_id"]) for entry in roster_entries() if entry["team_name"] == club
    )


# --- one path, two sources --------------------------------------------------


def test_the_capture_and_the_fixture_produce_the_same_claims(tmp_path: Path) -> None:
    """The same week's words either way, so every claim column has to agree.

    This is what makes the capture path production rather than a parallel implementation:
    the fixture's canned response is in the parser's format, the capture holds the coding
    format and is located on the way through, and the claims come out identical.
    """

    from_fixture = _export(tmp_path / "a", from_capture=False)
    from_capture = _export(tmp_path / "b", from_capture=True)

    assert from_capture[list(CLAIM_COLUMNS)].equals(from_fixture[list(CLAIM_COLUMNS)])


def test_the_two_sources_do_not_pretend_to_share_a_provenance(tmp_path: Path) -> None:
    """They record different facts, and a test demanding equality would demand a lie.

    The fixture path stamps a placeholder prompt digest, because no prompt produced its
    canned answer. The capture path carries the frozen prompt's real digest and hashes the
    stored response bytes. Same claims, different questions behind them.
    """

    from_fixture = _export(tmp_path / "a", from_capture=False)
    from_capture = _export(tmp_path / "b", from_capture=True)

    assert set(from_capture["prompt_sha256"].dropna()) == {
        coding_prompt_sha256(contract_version=LEGACY_ROTATION_CLAIM_CODING_CONTRACT_VERSION)
    }
    assert set(from_fixture["prompt_sha256"].dropna()) != set(
        from_capture["prompt_sha256"].dropna()
    )


def test_the_response_digest_is_taken_over_the_stored_bytes(tmp_path: Path) -> None:
    """Not over a re-serialisation, so the row points at what the capture actually holds."""

    expected = hashlib.sha256(
        CodingFixture(CODING_FIXTURE).response().text.encode("utf-8")
    ).hexdigest()

    table = _export(tmp_path, from_capture=True)

    assert set(table["model_response_sha256"].dropna()) == {expected}


def test_two_exports_from_one_capture_agree(tmp_path: Path) -> None:
    """Offline determinism, measured. No network and no model on either run."""

    first = _export(tmp_path / "a", from_capture=True)
    second = _export(tmp_path / "b", from_capture=True)

    assert first.equals(second)


def test_a_club_read_but_silent_is_still_covered(tmp_path: Path) -> None:
    """The distinction the capture's index exists to carry, surviving to the rows."""

    table = _export(tmp_path, from_capture=True).set_index("player_id")

    everton = _players_of("Everton")
    assert everton, "the fixture declares a club it never covered"
    assert not table.loc[list(everton), "club_source_covered"].any()
    assert table.loc[list(_players_of("Arsenal")), "club_source_covered"].all()


# --- per club, from the capture --------------------------------------------


def _response_for(club: str) -> ClaimResponse:
    """One club's coding response, carrying only that club's claims and documents.

    This is the shape a real week has: the model is called once per club and each answer
    speaks about one squad. Split out of the committed coding fixture rather than written
    by hand, so the claims stay the ones the fixture pair already agrees on.
    """

    document = json.loads(CodingFixture(CODING_FIXTURE).response().text)
    claims = [claim for claim in document["claims"] if claim["team_name"] == club]
    cited = {claim["source_url"] for claim in claims}
    text = (
        json.dumps(
            {
                "contract_version": document["contract_version"],
                "documents": [entry for entry in document["documents"] if entry["url"] in cited],
                "claims": claims,
            },
            indent=2,
            sort_keys=True,
            ensure_ascii=False,
        )
        + "\n"
    )
    return ClaimResponse(text=text, model_identifier="synthetic-stub", model_version="fixture-1")


def test_each_club_cites_its_own_response(tmp_path: Path) -> None:
    """A week called once per club puts a different digest in each club's rows.

    The fixture answers once for every club, so this builds what a real week produces and
    the failure it guards against is concrete: one digest across every row would give an
    Arsenal player a citation into United's response, and the digest would verify.

    Two responses that both coded the same player would be refused instead, and that is
    also right -- one player, one disposition, and no rule anywhere for choosing between
    two answers about him.
    """

    coded = tuple(
        CodedClub(
            club=club,
            response=_response_for(club),
            prompt_contract_version=LEGACY_ROTATION_CLAIM_CODING_CONTRACT_VERSION,
            prompt_sha256=coding_prompt_sha256(
                contract_version=LEGACY_ROTATION_CLAIM_CODING_CONTRACT_VERSION
            ),
        )
        for club in ("Arsenal", "Man Utd")
    )

    table = _export(tmp_path, from_capture=True, coded=coded).set_index("player_id")

    digests = {
        club: set(table.loc[list(_players_of(club)), "model_response_sha256"].dropna())
        for club in ("Arsenal", "Man Utd")
    }
    assert len(digests["Arsenal"]) == 1
    assert len(digests["Man Utd"]) == 1
    assert digests["Arsenal"] != digests["Man Utd"]


def test_the_manifest_lists_every_response_the_capture_held(tmp_path: Path) -> None:
    """Two calls, two digests, and the manifest says so rather than naming one."""

    coded = tuple(
        CodedClub(
            club=club,
            response=_response_for(club),
            prompt_contract_version=LEGACY_ROTATION_CLAIM_CODING_CONTRACT_VERSION,
            prompt_sha256=coding_prompt_sha256(
                contract_version=LEGACY_ROTATION_CLAIM_CODING_CONTRACT_VERSION
            ),
        )
        for club in ("Arsenal", "Man Utd")
    )
    root = tmp_path / "snapshots"
    decision = _decision(root)
    news = _news_capture(root, coded=coded)
    request = RotationExportRequest(
        SEASON,
        TARGET_GAMEWEEK,
        DEADLINE,
        decision,
        root,
        None,
        tmp_path / "out",
        club_news_snapshot=news,
        table_name="table",
    )

    export_rotation_evidence(request, repository_commit=COMMIT)

    manifest = json.loads((tmp_path / "out" / "table.manifest.json").read_text(encoding="utf-8"))
    assert len(manifest["response_sha256s"]) == 2
    assert manifest["response_sha256s"] == sorted(manifest["response_sha256s"])


def test_a_claim_on_a_club_with_no_recorded_response_costs_only_that_claim(
    tmp_path: Path,
) -> None:
    """An Arsenal response cannot borrow United's held documents or discard Arsenal's claims."""
    table = _export(tmp_path, from_capture=True, coded=_coded(("Arsenal",))).set_index("player_id")
    assert table.loc[list(_players_of("Arsenal")), "rotation_claim_observed"].any()
    united = table.loc[list(_players_of("Man Utd"))]
    assert not united.rotation_claim_observed.any()
    assert not united.rotation_claim_unresolved.any()
    assert united.model_response_sha256.isna().all()


# --- the refusals -----------------------------------------------------------


def test_naming_both_sources_is_refused(tmp_path: Path) -> None:
    """Which source produced the evidence may not be settled by a precedence rule."""

    with pytest.raises(InvalidValueError, match="exactly one club-news source"):
        RotationExportRequest(
            SEASON,
            TARGET_GAMEWEEK,
            DEADLINE,
            "fpl-live-20260912T150000Z-abcdef123456",
            tmp_path,
            FIXTURE,
            tmp_path / "out",
            club_news_snapshot="club-news-20260912T143000Z-abcdef123456",
        )


def test_naming_neither_source_is_refused(tmp_path: Path) -> None:
    """A week with no claims and no way to say why is not an export."""

    with pytest.raises(InvalidValueError, match="exactly one club-news source"):
        RotationExportRequest(
            SEASON,
            TARGET_GAMEWEEK,
            DEADLINE,
            "fpl-live-20260912T150000Z-abcdef123456",
            tmp_path,
            None,
            tmp_path / "out",
        )


def test_a_capture_with_no_response_is_refused(tmp_path: Path) -> None:
    """Read and never asked about is a state, and it is not an empty set of claims."""

    root = tmp_path / "snapshots"
    decision = _decision(root)
    provider = FixtureClubNewsProvider(FIXTURE)
    metadata = write_club_news_capture(
        root,
        documents=_documents(),
        coded=(),
        clubs_declared=provider.clubs_declared(),
        clubs_covered=provider.clubs_covered(),
        captured_at_utc=NEWS_CAPTURED_AT,
    )
    request = RotationExportRequest(
        SEASON,
        TARGET_GAMEWEEK,
        DEADLINE,
        decision,
        root,
        None,
        tmp_path / "out",
        club_news_snapshot=metadata.snapshot_id,
        table_name="table",
    )

    with pytest.raises(DataError, match="no model response"):
        export_rotation_evidence(request, repository_commit=COMMIT)


def test_documents_fetched_after_the_decision_capture_refuse_the_week(tmp_path: Path) -> None:
    """R07's deadline case: the chain is frozen before the decision, or it is not evidence.

    A document read after the capture the week was decided from could not have informed
    that decision, and recording it as though it had would be a claim about knowledge
    nobody had.
    """

    late = tuple(
        RawDocument(
            club=document.club,
            requested_url=document.requested_url,
            final_url=document.final_url,
            http_status=document.http_status,
            content_type=document.content_type,
            byte_length=document.byte_length,
            fetched_at_utc="2026-09-12T16:00:00Z",
            content=document.content,
            readable=document.readable,
            last_modified_utc=document.last_modified_utc,
        )
        for document in _documents()
    )

    with pytest.raises(DataSourceError, match="frozen before the capture"):
        _export(tmp_path, from_capture=True, documents=late)


# --- one bad citation costs one claim ---------------------------------------


def _response_with_a_broken_quote(player: str) -> ClaimResponse:
    """The committed coding response with one player's quote tidied into nonsense.

    Tidied rather than mangled, because that is the realistic failure: a model that rewrites
    a dash or drops a comma has not copied the document, and its quote will not locate.
    """

    fixture = json.loads(CodingFixture(CODING_FIXTURE).response().text)
    for claim in fixture["claims"]:
        if claim["player_name"] == player:
            claim["quote"] = claim["quote"].replace(" ", " even ", 1)
            break
    else:  # pragma: no cover - the fixture is expected to name him
        raise AssertionError(f"The coding fixture carries no claim about {player!r}.")
    return ClaimResponse(
        text=json.dumps(fixture, ensure_ascii=False),
        model_identifier="synthetic-stub",
        model_version="fixture-1",
    )


def _broken_export(tmp_path: Path, player: str) -> pd.DataFrame:
    response = _response_with_a_broken_quote(player)
    covered = FixtureClubNewsProvider(FIXTURE).clubs_covered()
    coded = tuple(
        CodedClub(
            club=club,
            response=response,
            prompt_contract_version=LEGACY_ROTATION_CLAIM_CODING_CONTRACT_VERSION,
            prompt_sha256=coding_prompt_sha256(
                contract_version=LEGACY_ROTATION_CLAIM_CODING_CONTRACT_VERSION
            ),
        )
        for club in covered
    )
    return _export(tmp_path, from_capture=True, coded=coded)


def _claimed_player() -> tuple[str, int]:
    """One player the committed response makes a claim about, with his roster id."""

    fixture = json.loads(CodingFixture(CODING_FIXTURE).response().text)
    name = str(fixture["claims"][0]["player_name"])
    team = str(fixture["claims"][0]["team_name"])
    for entry in roster_entries():
        if entry["web_name"] == name and entry["team_name"] == team:
            return name, int(entry["player_id"])
    raise AssertionError(f"The roster carries no {name!r} of {team!r}.")


def test_one_unlocatable_quote_no_longer_costs_the_whole_week(tmp_path: Path) -> None:
    """The failure this change is about: the week used to produce no table at all.

    `locate_claim_response` raises on the first quote that will not locate and the exporter
    did not catch it, so one unverifiable citation out of many discarded every verified one --
    on a deadline, with nothing to show for the pages that were read.
    """

    name, _ = _claimed_player()
    whole = _export(tmp_path / "whole", from_capture=True)

    damaged = _broken_export(tmp_path / "damaged", name)

    assert len(damaged) == len(whole), "every roster player still gets a row"
    surviving = damaged["rotation_claim_observed"].sum()
    assert surviving == whole["rotation_claim_observed"].sum() - 1


def test_the_dropped_claim_is_a_source_error_and_not_a_silence(tmp_path: Path) -> None:
    """The whole point of the new column.

    Without it this player reads as "his club was read and said nothing about him", which is
    false twice over: something was said, and what failed was our ability to stand behind the
    quote. He must carry no disposition either -- an unverifiable citation does not get to
    contribute a disposition by another route.
    """

    name, player_id = _claimed_player()

    damaged = _broken_export(tmp_path, name)

    row = damaged.set_index("player_id").loc[player_id]
    assert bool(row["rotation_claim_unresolved"]) is True
    assert bool(row["rotation_claim_observed"]) is False
    assert pd.isna(row["rotation_disposition"])
    assert pd.isna(row["rotation_claim_span_start"])


def test_every_other_player_is_untouched_by_one_bad_citation(tmp_path: Path) -> None:
    """A source error is about one claim, so it must not mark anybody else."""

    name, player_id = _claimed_player()

    damaged = _broken_export(tmp_path, name)

    others = damaged[damaged["player_id"] != player_id]
    assert not others["rotation_claim_unresolved"].any()


def test_the_unresolved_flag_is_never_missing(tmp_path: Path) -> None:
    """Never NA, like `rotation_claim_observed`: absent and False are different facts."""

    table = _export(tmp_path, from_capture=True)

    assert table["rotation_claim_unresolved"].notna().all()
    assert not table["rotation_claim_unresolved"].any()


def test_a_format_breach_still_refuses_the_whole_response(tmp_path: Path) -> None:
    """The reporting sibling drops citations, not shapes.

    A claim missing a required field cannot be reported -- there is no identity to name -- and
    a response shaped like that is a broken answer rather than one bad quote, so it refuses
    the week exactly as it did before.
    """

    fixture = json.loads(CodingFixture(CODING_FIXTURE).response().text)
    del fixture["claims"][0]["disposition"]
    response = ClaimResponse(
        text=json.dumps(fixture, ensure_ascii=False),
        model_identifier="synthetic-stub",
        model_version="fixture-1",
    )
    coded = tuple(
        CodedClub(
            club=club,
            response=response,
            prompt_contract_version=LEGACY_ROTATION_CLAIM_CODING_CONTRACT_VERSION,
            prompt_sha256=coding_prompt_sha256(
                contract_version=LEGACY_ROTATION_CLAIM_CODING_CONTRACT_VERSION
            ),
        )
        for club in FixtureClubNewsProvider(FIXTURE).clubs_covered()
    )

    with pytest.raises(ClubNewsError, match="missing required field"):
        _export(tmp_path, from_capture=True, coded=coded)


def test_one_claim_the_parser_refuses_costs_that_claim_and_not_the_week(tmp_path: Path) -> None:
    """The same rule one step later: the quote locates, and the parser refuses the claim.

    A label the response's contract does not have is refused for that claim. Before, it
    refused the whole response, and every club it coded lost its week of evidence.
    """

    name, player_id = _claimed_player()
    fixture = json.loads(CodingFixture(CODING_FIXTURE).response().text)
    (claim,) = (entry for entry in fixture["claims"] if entry["player_name"] == name)
    claim["disposition"] = "stated_full_match_unavailable"
    response = ClaimResponse(
        text=json.dumps(fixture, ensure_ascii=False),
        model_identifier="synthetic-stub",
        model_version="fixture-1",
    )
    coded = tuple(
        CodedClub(
            club=club,
            response=response,
            prompt_contract_version=LEGACY_ROTATION_CLAIM_CODING_CONTRACT_VERSION,
            prompt_sha256=coding_prompt_sha256(
                contract_version=LEGACY_ROTATION_CLAIM_CODING_CONTRACT_VERSION
            ),
        )
        for club in FixtureClubNewsProvider(FIXTURE).clubs_covered()
    )

    whole = _export(tmp_path / "whole", from_capture=True).set_index("player_id")
    damaged = _export(tmp_path / "damaged", from_capture=True, coded=coded).set_index("player_id")

    row = damaged.loc[player_id]
    assert bool(row["rotation_claim_unresolved"]) is True
    assert bool(row["rotation_claim_observed"]) is False
    assert pd.isna(row["rotation_disposition"])
    columns = [*CLAIM_COLUMNS[1:-1], "rotation_claim_unresolved"]
    pd.testing.assert_frame_equal(
        damaged.drop(index=player_id)[columns], whole.drop(index=player_id)[columns]
    )


@pytest.mark.parametrize("field", ["paraphrase", "speaker"])
def test_one_claim_with_an_empty_text_field_costs_that_claim_and_not_the_week(
    tmp_path: Path, field: str
) -> None:
    """The locator's rule for an empty text field: the claim still names its player, club and
    page, so it is set aside and recorded, as a quote that will not locate is. Before, it
    refused the whole response, and every club it coded lost its week of evidence.
    """

    name, player_id = _claimed_player()
    fixture = json.loads(CodingFixture(CODING_FIXTURE).response().text)
    (claim,) = (entry for entry in fixture["claims"] if entry["player_name"] == name)
    claim[field] = ""
    response = ClaimResponse(
        text=json.dumps(fixture, ensure_ascii=False),
        model_identifier="synthetic-stub",
        model_version="fixture-1",
    )
    coded = tuple(
        CodedClub(
            club=club,
            response=response,
            prompt_contract_version=LEGACY_ROTATION_CLAIM_CODING_CONTRACT_VERSION,
            prompt_sha256=coding_prompt_sha256(
                contract_version=LEGACY_ROTATION_CLAIM_CODING_CONTRACT_VERSION
            ),
        )
        for club in FixtureClubNewsProvider(FIXTURE).clubs_covered()
    )

    whole = _export(tmp_path / "whole", from_capture=True).set_index("player_id")
    damaged = _export(tmp_path / "damaged", from_capture=True, coded=coded).set_index("player_id")

    row = damaged.loc[player_id]
    assert bool(row["rotation_claim_unresolved"]) is True
    assert bool(row["rotation_claim_observed"]) is False
    assert pd.isna(row["rotation_disposition"])
    columns = [*CLAIM_COLUMNS[1:-1], "rotation_claim_unresolved"]
    pd.testing.assert_frame_equal(
        damaged.drop(index=player_id)[columns], whole.drop(index=player_id)[columns]
    )


def _one_call_per_club(damage: dict[str, object] | None = None) -> tuple[CodedClub, ...]:
    """Arsenal and Man Utd each answered by their own call, Arsenal's optionally damaged."""

    responses = {club: json.loads(_response_for(club).text) for club in ("Arsenal", "Man Utd")}
    if damage is not None:
        responses["Arsenal"].update(damage)
    return tuple(
        CodedClub(
            club=club,
            response=ClaimResponse(
                text=json.dumps(responses[club], ensure_ascii=False),
                model_identifier="synthetic-stub",
                model_version="fixture-1",
            ),
            prompt_contract_version=LEGACY_ROTATION_CLAIM_CODING_CONTRACT_VERSION,
            prompt_sha256=coding_prompt_sha256(
                contract_version=LEGACY_ROTATION_CLAIM_CODING_CONTRACT_VERSION
            ),
        )
        for club in ("Arsenal", "Man Utd")
    )


def _summary(tmp_path: Path, coded: tuple[CodedClub, ...]) -> tuple[Any, pd.DataFrame, Any]:
    root = tmp_path / "snapshots"
    decision = _decision(root)
    news = _news_capture(root, coded=coded)
    summary = export_rotation_evidence(
        RotationExportRequest(
            SEASON,
            TARGET_GAMEWEEK,
            DEADLINE,
            decision,
            root,
            None,
            tmp_path / "out",
            club_news_snapshot=news,
            table_name="table",
        ),
        repository_commit=COMMIT,
    )
    table = pd.read_csv(tmp_path / "out" / "table.csv").set_index("player_id")
    manifest = json.loads((tmp_path / "out" / "table.manifest.json").read_text(encoding="utf-8"))
    return summary, table, manifest


def test_one_club_answer_the_reader_refuses_costs_that_club_and_not_the_week(
    tmp_path: Path,
) -> None:
    """Two claims about one player refuse the response; with a call per club that is one club.

    The parser has no rule for choosing between two answers about a player, so it refuses
    the response they came in. That used to end the export, and United's readable answer
    was lost with Arsenal's. Now Arsenal leaves the covered list, United's rows are exactly
    what they are in a clean week, and the refusal is returned with its reason.
    """

    clean_summary, clean, _ = _summary(tmp_path / "clean", _one_call_per_club())
    arsenal = json.loads(_response_for("Arsenal").text)
    twice = [*arsenal["claims"], dict(arsenal["claims"][0])]

    summary, table, manifest = _summary(tmp_path / "damaged", _one_call_per_club({"claims": twice}))

    assert clean_summary["responses_refused"] == []
    (refusal,) = summary["responses_refused"]
    assert refusal["clubs"] == ["Arsenal"]
    assert "twice" in refusal["reason"]
    assert manifest["clubs_covered"] == ["Man Utd"]
    assert "Arsenal" in manifest["clubs_declared"]
    arsenal_rows = table.loc[list(_players_of("Arsenal"))]
    assert not arsenal_rows.club_source_covered.any()
    assert not arsenal_rows.rotation_claim_observed.any()
    united = list(_players_of("Man Utd"))
    # Everything a claim puts in a row, and the coverage flags. The capture's own id is in
    # other columns and differs between the two weeks by construction.
    columns = [*CLAIM_COLUMNS[1:-1], "rotation_claim_unresolved", "club_source_covered"]
    pd.testing.assert_frame_equal(table.loc[united, columns], clean.loc[united, columns])
    assert table.loc[united, "rotation_claim_observed"].any()


def test_a_week_whose_every_answer_is_refused_is_still_refused(tmp_path: Path) -> None:
    """With nothing left to narrow, the reader's own refusal is raised as it was."""

    arsenal = json.loads(_response_for("Arsenal").text)
    twice = [*arsenal["claims"], dict(arsenal["claims"][0])]
    (only_arsenal, _united) = _one_call_per_club({"claims": twice})

    with pytest.raises(ClubNewsError, match="twice"):
        _summary(tmp_path, (only_arsenal,))


def test_a_club_whose_every_claim_lost_its_citation_is_no_longer_covered(
    tmp_path: Path,
) -> None:
    """Nothing that club said survives into evidence, so calling it covered would assert
    that its page was read into the table when none of it was.

    Distinct from a club that was read and genuinely said nothing: that one has no claims
    either way and stays covered, which is the difference the coverage list carries.
    """

    fixture = json.loads(CodingFixture(CODING_FIXTURE).response().text)
    club = str(fixture["claims"][0]["team_name"])
    for claim in fixture["claims"]:
        if claim["team_name"] == club:
            claim["quote"] = claim["quote"].replace(" ", " even ", 1)
    response = ClaimResponse(
        text=json.dumps(fixture, ensure_ascii=False),
        model_identifier="synthetic-stub",
        model_version="fixture-1",
    )
    coded = tuple(
        CodedClub(
            club=name,
            response=response,
            prompt_contract_version=LEGACY_ROTATION_CLAIM_CODING_CONTRACT_VERSION,
            prompt_sha256=coding_prompt_sha256(
                contract_version=LEGACY_ROTATION_CLAIM_CODING_CONTRACT_VERSION
            ),
        )
        for name in FixtureClubNewsProvider(FIXTURE).clubs_covered()
    )

    table = _export(tmp_path, from_capture=True, coded=coded).set_index("player_id")

    for player_id in _players_of(club):
        assert bool(table.loc[player_id, "club_source_covered"]) is False

    # Which of the club's players carry a source error is the identity seam's answer, not
    # this test's: the fixture writes "Martinez" where the roster spells "Martínez", and
    # re-deriving that here would be a second copy of the resolver that could disagree with
    # the first. What must hold is that the flag lands inside this club and nowhere else.
    flagged = set(table.index[table["rotation_claim_unresolved"].fillna(False)])
    assert flagged, "the club's claims all failed, so somebody must be flagged"
    assert flagged <= set(_players_of(club))


def _coded_responses(responses: dict[str, dict]) -> tuple[CodedClub, ...]:
    return tuple(
        replace(
            entry,
            response=ClaimResponse(
                text=json.dumps(responses[entry.club], ensure_ascii=False),
                model_identifier="synthetic-stub",
                model_version="fixture-1",
            ),
        )
        for entry in _coded()
    )


def test_opponent_unlocatable_mention_cannot_remove_a_quiet_clubs_coverage(tmp_path: Path):
    responses = {club: json.loads(_response_for(club).text) for club in ("Arsenal", "Man Utd")}
    mention = dict(responses["Man Utd"]["claims"][0])
    mention["source_url"] = responses["Arsenal"]["claims"][0]["source_url"]
    mention["quote"] = "This opponent quote does not occur in the held document."
    responses["Arsenal"]["claims"].append(mention)
    responses["Man Utd"]["claims"] = []

    table = _export(tmp_path, from_capture=True, coded=_coded_responses(responses)).set_index(
        "player_id"
    )
    united = table.loc[list(_players_of("Man Utd"))]
    assert united.club_source_covered.all()
    assert not united.rotation_claim_observed.any()
    assert not united.rotation_claim_unresolved.any()
    assert table.loc[list(_players_of("Arsenal")), "rotation_claim_observed"].any()
    manifest = json.loads((tmp_path / "out" / "table.manifest.json").read_text(encoding="utf-8"))
    assert "Man Utd" in manifest["clubs_covered"]


@pytest.mark.parametrize("quiet", [False, True])
def test_per_club_response_cannot_borrow_another_calls_real_citation(tmp_path: Path, quiet):
    responses = {club: json.loads(_response_for(club).text) for club in ("Arsenal", "Man Utd")}
    borrowed = dict(responses["Man Utd"]["claims"][0])
    borrowed["disposition"] = "stated_expected_absent"
    if quiet:
        responses["Man Utd"]["claims"] = []
    baseline = _export(
        tmp_path / "baseline", from_capture=True, coded=_coded_responses(responses)
    ).set_index("player_id")
    # The copied URL, quote and dateline are all genuine held United evidence; only the
    # producing response is wrong. They must never acquire United's unrelated response hash.
    responses["Arsenal"]["claims"].append(borrowed)
    responses["Arsenal"]["documents"].extend(responses["Man Utd"]["documents"])
    coded = _coded_responses(responses)
    table = _export(tmp_path / "borrowed", from_capture=True, coded=coded).set_index("player_id")
    columns = [*CLAIM_COLUMNS[1:], "rotation_claim_unresolved"]
    pd.testing.assert_frame_equal(table[columns], baseline[columns])
    united = table.loc[list(_players_of("Man Utd"))]
    assert united.club_source_covered.all()
    if quiet:
        assert united.model_response_sha256.isna().all()
    else:
        own = next(entry for entry in coded if entry.club == "Man Utd")
        expected = hashlib.sha256(own.response.text.encode("utf-8")).hexdigest()
        assert set(united.model_response_sha256.dropna()) == {expected}


@pytest.mark.parametrize("citation", ["unknown", "foreign"])
@pytest.mark.parametrize("response_club", ["Arsenal", "Man Utd"])
def test_bad_citation_diagnostics_follow_the_responding_club(
    tmp_path: Path, citation: str, response_club: str
) -> None:
    responses = {club: json.loads(_response_for(club).text) for club in ("Arsenal", "Man Utd")}
    mention = dict(responses["Arsenal"]["claims"][0])
    mention["source_url"] = (
        "https://example.invalid/not-fetched"
        if citation == "unknown"
        else responses["Man Utd"]["claims"][0]["source_url"]
    )
    mention["quote"] = "This quote does not occur in any held document."
    for response in responses.values():
        response["claims"] = []
    responses[response_club]["claims"] = [mention]

    table = _export(tmp_path, from_capture=True, coded=_coded_responses(responses)).set_index(
        "player_id"
    )
    own_response = response_club == "Arsenal"
    arsenal = table.loc[list(_players_of("Arsenal"))]
    united = table.loc[list(_players_of("Man Utd"))]
    assert int(arsenal.rotation_claim_unresolved.sum()) == int(own_response)
    assert arsenal.club_source_covered.eq(not own_response).all()
    assert united.club_source_covered.all()
    assert not united.rotation_claim_unresolved.any()
    assert not table.rotation_claim_observed.any()
    assert table.rotation_disposition.isna().all()
    manifest = json.loads((tmp_path / "out" / "table.manifest.json").read_text(encoding="utf-8"))
    assert ("Arsenal" in manifest["clubs_covered"]) is not own_response
    assert "Man Utd" in manifest["clubs_covered"]


def test_response_binding_preserves_the_actual_failed_citation(tmp_path: Path) -> None:
    responses = {club: json.loads(_response_for(club).text) for club in ("Arsenal", "Man Utd")}
    claim = responses["Arsenal"]["claims"][0]
    unknown_url = "https://example.invalid/actual-failed-url"
    claim["source_url"] = unknown_url
    responses["Arsenal"]["claims"] = [claim]
    snapshot_id = _news_capture(tmp_path, coded=_coded_responses(responses))

    inputs = _inputs_from_capture(read_snapshot(tmp_path, snapshot_id))

    (dropped,) = inputs.unverifiable
    assert dropped.source_url == unknown_url
    assert unknown_url in dropped.why
    assert "not among the fetched documents" in dropped.why
    assert inputs.unverifiable_response_clubs == {dropped: frozenset({"Arsenal"})}
