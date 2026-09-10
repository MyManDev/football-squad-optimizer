"""Installed, transport-neutral rotation evidence export."""

import hashlib
import os
import secrets
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pandas as pd

from squadopt.backtest.export_precision import EXPORT_LINE_TERMINATOR
from squadopt.data.errors import DataError, InvalidValueError
from squadopt.data.snapshots import CapturedSnapshot, read_snapshot
from squadopt.data.sources.club_news import (
    FixtureClubNewsProvider,
    RawDocument,
)
from squadopt.data.sources.club_news_capture import CodedClub, read_club_news_capture
from squadopt.data.sources.club_news_claims import ParsedClaim, parse_claim_response
from squadopt.data.sources.club_news_coding import locate_claim_response
from squadopt.experiments.shadow_report import write_document_once
from squadopt.features.rotation_evidence import (
    CONTRACT_VERSION,
    ClubModelProvenance,
    ModelProvenance,
    build_rotation_evidence_table,
)
from squadopt.features.rotation_evidence_artifact import ARTIFACT_CONTRACT_VERSION

_NAME_DIGEST_CHARACTERS: Final = 12


@dataclass(frozen=True, slots=True)
class RotationExportRequest:
    """One export, and exactly one club-news source.

    ``club_news_fixture`` and ``club_news_snapshot`` are alternatives, and exactly one must
    be given. The fixture stands in for a source and is what the offline tests use; the
    snapshot is a durable club-news capture, read from the same store as the decision
    capture. Refusing both is not pedantry: "which source produced this evidence" is the
    first question anyone asks of a row, and a precedence rule would answer it silently.
    """

    season: str
    target_gameweek: int
    deadline_utc: str
    snapshot: str
    snapshot_root: Path
    club_news_fixture: Path | None
    output_dir: Path
    club_news_snapshot: str | None = None
    table_name: str | None = None

    def __post_init__(self) -> None:
        if (self.club_news_fixture is None) == (self.club_news_snapshot is None):
            raise InvalidValueError(
                "Name exactly one club-news source: a fixture path or a capture id. Both "
                "would leave which one produced the evidence to a precedence rule, and "
                "neither leaves the week with no claims and no way to say why."
            )


def export_rotation_evidence(
    request: RotationExportRequest, *, repository_commit: str
) -> Mapping[str, object]:
    return _export(request, repository_commit=repository_commit)


@dataclass(frozen=True, slots=True)
class _ClubNewsInputs:
    """Everything the table needs from the club-news side of the week."""

    documents: tuple[RawDocument, ...]
    claims: tuple[ParsedClaim, ...]
    model: ClubModelProvenance
    clubs_declared: tuple[str, ...]
    clubs_covered: tuple[str, ...]


def _club_news_inputs(request: RotationExportRequest) -> _ClubNewsInputs:
    """Read the documents, claims and model provenance from whichever source was named.

    **The one construction site**, and now with two sources behind it rather than one. Both
    are pure: neither reaches a network nor calls a model. That is the whole shape of the
    integration -- the network adapter writes a capture in ``platform``, and this layer reads
    the capture. ``application`` therefore never imports ``platform``, and the import
    contract enforces it rather than a comment asking for it.

    Everything after this function -- locating, parsing, identity, the table, the manifest --
    is one path regardless of which source was used, so a fixture run and a capture run are
    the same production path with different bytes.
    """

    if request.club_news_snapshot is not None:
        return _inputs_from_capture(
            read_snapshot(request.snapshot_root, request.club_news_snapshot)
        )
    if request.club_news_fixture is None:  # pragma: no cover - __post_init__ refuses this
        raise InvalidValueError("No club-news source was named.")
    return _inputs_from_fixture(request.club_news_fixture)


def _inputs_from_capture(snapshot: CapturedSnapshot) -> _ClubNewsInputs:
    """Rebuild a week's club-news inputs from a durable capture.

    No network and no model: the documents and the raw responses come off the disk, the
    quotes are located against those same bytes, and the claims are parsed from the located
    result. Running this twice over one capture produces the same claims and the same table
    digest, which is what makes a decision defensible after the fact.

    **Responses are de-duplicated by their text before parsing.** One response can cover
    several clubs -- the fixture answers once for all of them -- and parsing the same
    response once per club would produce the same claim twice and refuse the week for a
    duplication this function created. The provenance mapping still has an entry per club,
    because that is a statement about which response coded which club and not about how
    many distinct answers there were.
    """

    documents, coded, clubs_declared, clubs_covered = read_club_news_capture(snapshot)
    if not coded:
        raise DataError(
            f"{snapshot.metadata.snapshot_id} carries documents but no model response, so "
            "no claim can be read from it. A capture with nothing coded is a week that was "
            "read and not asked about."
        )

    claims: list[ParsedClaim] = []
    for text in dict.fromkeys(entry.response.text for entry in coded):
        response = next(entry.response for entry in coded if entry.response.text == text)
        claims.extend(parse_claim_response(locate_claim_response(response, documents), documents))

    return _ClubNewsInputs(
        documents=documents,
        claims=tuple(claims),
        model=_provenance_from_capture(coded),
        clubs_declared=clubs_declared,
        clubs_covered=clubs_covered,
    )


def _provenance_from_capture(coded: Sequence[CodedClub]) -> ClubModelProvenance:
    """One provenance record per club, every field read from the capture.

    Nothing here is derived from a convention or a default. The response digest is taken
    over the stored bytes, the prompt digest is the one the capture recorded beside them, and
    the requested and serving model identities are the two the response itself carries. A
    week whose clubs disagree about any of the three is refused by
    :class:`ClubModelProvenance`, not smoothed over here.
    """

    return ClubModelProvenance(
        by_club={
            entry.club: ModelProvenance(
                identifier=entry.response.model_identifier,
                version=entry.response.model_version,
                prompt_sha256=entry.prompt_sha256,
                response_sha256=hashlib.sha256(entry.response.text.encode("utf-8")).hexdigest(),
            )
            for entry in coded
        }
    )


def _inputs_from_fixture(fixture_path: Path) -> _ClubNewsInputs:
    """Read the same inputs from the committed synthetic fixture.

    Kept, and not as a courtesy: every offline test of the evidence path runs through here,
    and the fixture is the specification of the hard cases a live source cannot be relied on
    to contain.
    """

    provider = FixtureClubNewsProvider(fixture_path)
    documents = tuple(provider.fetch(url) for url in provider.urls)

    response = provider.code(documents, provider.roster())
    claims = parse_claim_response(response, documents)
    covered = provider.clubs_covered()
    provenance = ModelProvenance(
        identifier=response.model_identifier,
        version=response.model_version,
        # A6's prompt is a versioned constant, but it is not the question *this* response was
        # produced from: the fixture serves a canned answer that no prompt ever asked for.
        # Stamping it with `coding_prompt_sha256()` would claim the frozen prompt produced it,
        # which is a stronger and falser statement than a placeholder that says so plainly.
        prompt_sha256=hashlib.sha256(b"fixture-provider-has-no-prompt").hexdigest(),
        response_sha256=hashlib.sha256(response.text.encode("utf-8")).hexdigest(),
    )
    # Every covered club maps to this one response, which is what actually happened: the
    # fixture answers once for all of them, and saying so is not the same as pretending
    # there was a call per club. A real provider called per club builds this mapping from
    # its own responses and the digests then differ -- which is the case the table is now
    # able to record.
    model = ClubModelProvenance(by_club={club: provenance for club in covered})
    return _ClubNewsInputs(
        documents=documents,
        claims=claims,
        model=model,
        clubs_declared=provider.clubs_declared(),
        clubs_covered=covered,
    )


def _artifact_name(*, season: str, target_gameweek: int, distinguishing_snapshot: str) -> str:
    """The stem, built so a rehearsal is a different artifact from the real run.

    The digest is the capture the *claims* came from, because that is what a second run
    within one week actually changes. While the fixture stands in for a live source the
    claims are fixed, so the decision capture is what varies and is used instead; either
    way the manifest records both, so which one named the file is never a guess.
    """

    return (
        f"{CONTRACT_VERSION}_{season}_gw{target_gameweek:02d}"
        f"_{distinguishing_snapshot[-_NAME_DIGEST_CHARACTERS:]}"
    )


def _publish_once(payload: bytes, destination: Path) -> str:
    """Create a file exactly once, atomically, and say which of two happened.

    Deliberately not a copy of ``export_player_evidence._publish``, which tests for an
    existing file and then renames over it: between those two steps a concurrent writer can
    publish, and the rename destroys its bytes without a word. Here the bytes are completed
    and fsynced in a sibling temporary and published with a no-overwrite hard link, so the
    loser of a race compares its own bytes with the winner's and reports a replay when they
    agree. The Phase B export is frozen and not this lane's to change; the third table
    writer that needs this should share one helper rather than grow a third copy.
    """

    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f".{destination.name}.tmp-{os.getpid()}-{secrets.token_hex(8)}"
    )
    try:
        with temporary.open("xb") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        try:
            os.link(temporary, destination)
        except FileExistsError:
            if destination.read_bytes() == payload:
                return "replay"
            raise DataError(
                f"{destination} already exists with different content; an artifact is never "
                "overwritten in place. Choose another name or remove it deliberately."
            ) from None
        return "written"
    finally:
        temporary.unlink(missing_ok=True)


def _table_bytes(table: pd.DataFrame) -> bytes:
    """The exact bytes the digest is taken over.

    The terminator is the project's own constant rather than pandas' platform default, so the
    digest identifies the table and not the operating system that wrote it.
    """

    return table.to_csv(index=False, lineterminator=EXPORT_LINE_TERMINATOR).encode("utf-8")


def _manifest(
    table: pd.DataFrame,
    *,
    season: str,
    target_gameweek: int,
    deadline_timestamp_utc: str,
    table_file: str,
    table_sha256: str,
    repository_commit: str,
    generated_at_utc: str,
) -> dict[str, object]:
    attrs = table.attrs
    return {
        "contract_version": CONTRACT_VERSION,
        "artifact_contract_version": ARTIFACT_CONTRACT_VERSION,
        "season": season,
        "target_gameweek": target_gameweek,
        "deadline_timestamp_utc": deadline_timestamp_utc,
        "generated_at_utc": generated_at_utc,
        "repository_commit": repository_commit,
        "table_file": table_file,
        "table_sha256": table_sha256,
        "row_count": len(table),
        "roster_size": attrs["roster_size"],
        "roster_snapshot_id": attrs["roster_snapshot_id"],
        "source_snapshot_ids": list(attrs["source_snapshot_ids"]),
        "clubs_declared": list(attrs["clubs_declared"]),
        "clubs_covered": list(attrs["clubs_covered"]),
        "documents_read": attrs["documents_read"],
        "document_sha256s": list(attrs["document_sha256s"]),
        "model_identifier": attrs["model_identifier"],
        "model_version": attrs["model_version"],
        "prompt_sha256": attrs["prompt_sha256"],
        "response_sha256s": list(attrs["response_sha256s"]),
        "claims_coded": attrs["claims_coded"],
        "claims_ambiguous": attrs["claims_ambiguous"],
        "players_not_addressed": attrs["players_not_addressed"],
    }


def _decision_snapshot(root: Path, snapshot_id: str) -> CapturedSnapshot:
    return read_snapshot(root, snapshot_id)


def _export(arguments: RotationExportRequest, *, repository_commit: str) -> Mapping[str, object]:
    decision = _decision_snapshot(arguments.snapshot_root, arguments.snapshot)
    club_news = _club_news_inputs(arguments)
    table = build_rotation_evidence_table(
        season=arguments.season,
        target_gameweek=arguments.target_gameweek,
        deadline_timestamp_utc=arguments.deadline_utc,
        decision_snapshot=decision,
        claims=club_news.claims,
        documents=club_news.documents,
        clubs_declared=club_news.clubs_declared,
        clubs_covered=club_news.clubs_covered,
        model=club_news.model,
        club_news_snapshot_id=arguments.club_news_snapshot,
    )
    name = arguments.table_name or _artifact_name(
        season=arguments.season,
        target_gameweek=arguments.target_gameweek,
        distinguishing_snapshot=arguments.club_news_snapshot or decision.metadata.snapshot_id,
    )
    table_path = arguments.output_dir / f"{name}.csv"
    manifest_path = arguments.output_dir / f"{name}.manifest.json"

    payload = _table_bytes(table)
    # The digest comes from the bytes that will be published, taken before publishing them,
    # so a replay and a first write record the same value for the same table.
    table_sha256 = hashlib.sha256(payload).hexdigest()
    table_outcome = _publish_once(payload, table_path)
    manifest = _manifest(
        table,
        season=arguments.season,
        target_gameweek=arguments.target_gameweek,
        deadline_timestamp_utc=arguments.deadline_utc,
        table_file=table_path.name,
        table_sha256=table_sha256,
        repository_commit=repository_commit,
        generated_at_utc=datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    manifest_outcome = write_document_once(manifest, manifest_path)
    return {
        "table_path": table_path,
        "manifest_path": manifest_path,
        "table_sha256": table_sha256,
        "table_outcome": table_outcome,
        "manifest_outcome": manifest_outcome,
        "rows": len(table),
        "claims_coded": manifest["claims_coded"],
        "players_not_addressed": manifest["players_not_addressed"],
    }
