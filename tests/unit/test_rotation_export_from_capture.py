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
from pathlib import Path

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
    export_rotation_evidence,
)
from squadopt.data.errors import DataError, DataSourceError, InvalidValueError
from squadopt.data.snapshots import write_snapshot
from squadopt.data.sources.club_news import (
    ClaimResponse,
    FixtureClubNewsProvider,
    RawDocument,
)
from squadopt.data.sources.club_news_capture import CodedClub, write_club_news_capture
from squadopt.data.sources.club_news_coding import (
    ROTATION_CLAIM_CODING_CONTRACT_VERSION,
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
            prompt_contract_version=ROTATION_CLAIM_CODING_CONTRACT_VERSION,
            prompt_sha256=coding_prompt_sha256(),
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

    assert set(from_capture["prompt_sha256"].dropna()) == {coding_prompt_sha256()}
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
            prompt_contract_version=ROTATION_CLAIM_CODING_CONTRACT_VERSION,
            prompt_sha256=coding_prompt_sha256(),
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
            prompt_contract_version=ROTATION_CLAIM_CODING_CONTRACT_VERSION,
            prompt_sha256=coding_prompt_sha256(),
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


def test_a_claim_on_a_club_with_no_recorded_response_refuses_the_week(tmp_path: Path) -> None:
    """R07's wrong club/player case, from the capture side.

    The capture codes Arsenal only, while the response it stores places claims on Man Utd
    players too. A disposition whose response cannot be named is traceable to no bytes, so
    the week refuses rather than borrowing Arsenal's digest for a United player.
    """

    with pytest.raises(DataSourceError, match="Man Utd"):
        _export(tmp_path, from_capture=True, coded=_coded(("Arsenal",)))


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
