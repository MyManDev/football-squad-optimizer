r"""Export one week's ``rotation_evidence_v1`` pair, exactly once.

    python -m scripts.export_rotation_evidence \
        --season 2026-27 \
        --target-gameweek 4 \
        --deadline-utc 2026-09-12T17:30:00Z \
        --snapshot <fpl-live capture id> \
        --club-news-fixture data/sample/club_news_v1.fixture.json

Writes ``<name>.csv`` and ``<name>.manifest.json``: the table one row per roster player, and
the manifest that makes it checkable without trusting whoever wrote it. The export refuses a
dirty working tree, because the commit it records would otherwise not reproduce the bytes.

The claims come from a :class:`ClubNewsProvider`. Today the only one is the committed
synthetic fixture, and the provider is constructed in one function on purpose: connecting a
real source changes that function and nothing else in this file.
"""

import argparse
import hashlib
import os
import secrets
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pandas as pd
from scripts._experiment_cli import REPOSITORY_ROOT, _git_revision

from squadopt.backtest.export_precision import EXPORT_LINE_TERMINATOR
from squadopt.data.errors import DataError
from squadopt.data.snapshots import CapturedSnapshot, read_snapshot
from squadopt.data.sources.club_news import (
    ClubNewsError,
    FixtureClubNewsProvider,
    RawDocument,
)
from squadopt.data.sources.club_news_claims import ParsedClaim, parse_claim_response
from squadopt.experiments.shadow_report import ShadowReportError, write_document_once
from squadopt.features.rotation_evidence import (
    CONTRACT_VERSION,
    ModelProvenance,
    build_rotation_evidence_table,
)
from squadopt.features.rotation_evidence_artifact import ARTIFACT_CONTRACT_VERSION

DEFAULT_SNAPSHOT_ROOT: Final = REPOSITORY_ROOT / "data" / "snapshots"
DEFAULT_OUTPUT_DIR: Final = REPOSITORY_ROOT / "artifacts" / "rotation"
DEFAULT_CLUB_NEWS_FIXTURE: Final = REPOSITORY_ROOT / "data" / "sample" / "club_news_v1.fixture.json"

#: How many characters of a capture's fingerprint go into the artifact name. The same twelve
#: the snapshot id itself carries, so the two can be read against each other by eye.
_NAME_DIGEST_CHARACTERS: Final = 12


def _parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--season", required=True)
    parser.add_argument("--target-gameweek", type=int, required=True)
    parser.add_argument("--deadline-utc", required=True)
    parser.add_argument("--snapshot", required=True, help="the decision capture's id")
    parser.add_argument("--snapshot-root", type=Path, default=DEFAULT_SNAPSHOT_ROOT)
    parser.add_argument(
        "--club-news-fixture",
        type=Path,
        default=DEFAULT_CLUB_NEWS_FIXTURE,
        help="the committed synthetic fixture standing in for a real club-news source",
    )
    parser.add_argument(
        "--club-news-snapshot",
        default=None,
        help=(
            "the capture the claims were read from, recorded per row and used to name the "
            "artifact; omit while the fixture stands in for it"
        ),
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--table-name", default=None, help="file stem; defaults to the contract")
    return parser.parse_args(argv)


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


def _export(arguments: argparse.Namespace, *, repository_commit: str) -> Mapping[str, object]:
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


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_arguments(argv)
    revision, dirty = _git_revision()
    if dirty:
        print(
            "Refused: the working tree has uncommitted changes, so the artifact could not be "
            "reproduced from the commit it would record; commit or stash them first."
        )
        return 1
    try:
        result = _export(arguments, repository_commit=revision)
    except (ClubNewsError, DataError, ShadowReportError, OSError, ValueError) as error:
        print(f"Refused: {error}")
        return 1

    print(f"Rows          {result['rows']}")
    print(f"Claims coded  {result['claims_coded']}")
    print(f"Not addressed {result['players_not_addressed']}")
    print(f"Digest        {result['table_sha256']}")
    print(f"Wrote         {result['table_path']} ({result['table_outcome']})")
    print(f"              {result['manifest_path']} ({result['manifest_outcome']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
