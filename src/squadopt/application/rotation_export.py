"""Installed, transport-neutral rotation evidence export."""

import hashlib
import os
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pandas as pd

from squadopt.backtest.export_precision import EXPORT_LINE_TERMINATOR
from squadopt.data.errors import DataError
from squadopt.data.snapshots import CapturedSnapshot, read_snapshot
from squadopt.data.sources.club_news import (
    FixtureClubNewsProvider,
    RawDocument,
)
from squadopt.data.sources.club_news_claims import ParsedClaim, parse_claim_response
from squadopt.experiments.shadow_report import write_document_once
from squadopt.features.rotation_evidence import (
    CONTRACT_VERSION,
    ModelProvenance,
    build_rotation_evidence_table,
)
from squadopt.features.rotation_evidence_artifact import ARTIFACT_CONTRACT_VERSION

_NAME_DIGEST_CHARACTERS: Final = 12


@dataclass(frozen=True, slots=True)
class RotationExportRequest:
    season: str
    target_gameweek: int
    deadline_utc: str
    snapshot: str
    snapshot_root: Path
    club_news_fixture: Path
    output_dir: Path
    club_news_snapshot: str | None = None
    table_name: str | None = None


def export_rotation_evidence(
    request: RotationExportRequest, *, repository_commit: str
) -> Mapping[str, object]:
    return _export(request, repository_commit=repository_commit)


@dataclass(frozen=True, slots=True)
class _ClubNewsInputs:
    """Everything the table needs from the club-news side of the week."""

    documents: tuple[RawDocument, ...]
    claims: tuple[ParsedClaim, ...]
    model: ModelProvenance
    clubs_declared: tuple[str, ...]
    clubs_covered: tuple[str, ...]


def _club_news_inputs(fixture_path: Path) -> _ClubNewsInputs:
    """Read the documents, claims and model provenance from the club-news source.

    **The one construction site.** A real provider replaces the two lines that build and
    query it; everything after them -- parsing, identity, the table, the manifest -- is
    already the production path and no test of it moves.
    """

    provider = FixtureClubNewsProvider(fixture_path)
    documents = tuple(provider.fetch(url) for url in provider.urls)

    response = provider.code(documents, provider.roster())
    claims = parse_claim_response(response, documents)
    model = ModelProvenance(
        identifier=response.model_identifier,
        version=response.model_version,
        # The prompt is a versioned constant in the repository from A6 onward. Until a real
        # call exists there is no prompt, so the stub's own response stands in for both
        # digests rather than a zeroed placeholder pretending to be one.
        prompt_sha256=hashlib.sha256(b"fixture-provider-has-no-prompt").hexdigest(),
        response_sha256=hashlib.sha256(response.text.encode("utf-8")).hexdigest(),
    )
    return _ClubNewsInputs(
        documents=documents,
        claims=claims,
        model=model,
        clubs_declared=provider.clubs_declared(),
        clubs_covered=provider.clubs_covered(),
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
    club_news = _club_news_inputs(arguments.club_news_fixture)
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
