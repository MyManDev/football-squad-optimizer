"""Compatibility rotation export command."""

import argparse
import sys
from collections.abc import Sequence
from pathlib import Path
from typing import Final

from scripts._experiment_cli import REPOSITORY_ROOT, _git_revision

from squadopt.application.rotation_export import (
    _NAME_DIGEST_CHARACTERS as _NAME_DIGEST_CHARACTERS,
)
from squadopt.application.rotation_export import (
    _artifact_name as _artifact_name,
)
from squadopt.application.rotation_export import (
    _club_news_inputs as _club_news_inputs,
)
from squadopt.application.rotation_export import (
    _ClubNewsInputs as _ClubNewsInputs,
)
from squadopt.application.rotation_export import (
    _decision_snapshot as _decision_snapshot,
)
from squadopt.application.rotation_export import (
    _export as _export,
)
from squadopt.application.rotation_export import (
    _manifest as _manifest,
)
from squadopt.application.rotation_export import (
    _publish_once as _publish_once,
)
from squadopt.application.rotation_export import (
    _table_bytes as _table_bytes,
)
from squadopt.data.errors import DataError
from squadopt.data.sources.club_news import (
    ClubNewsError,
)
from squadopt.experiments.shadow_report import ShadowReportError

DEFAULT_SNAPSHOT_ROOT: Final = REPOSITORY_ROOT / "data" / "snapshots"


DEFAULT_OUTPUT_DIR: Final = REPOSITORY_ROOT / "artifacts" / "rotation"


DEFAULT_CLUB_NEWS_FIXTURE: Final = REPOSITORY_ROOT / "data" / "sample" / "club_news_v1.fixture.json"


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
        default=None,
        help=(
            "the committed synthetic fixture standing in for a real club-news source; "
            f"defaults to {DEFAULT_CLUB_NEWS_FIXTURE} unless --club-news-snapshot is given"
        ),
    )
    parser.add_argument(
        "--club-news-snapshot",
        default=None,
        help=(
            "the club-news capture the claims are read from, recorded per row and used to "
            "name the artifact; omit to read the fixture instead"
        ),
    )
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--table-name", default=None, help="file stem; defaults to the contract")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_arguments(argv)
    # The fixture default is applied here rather than by argparse, so that naming a capture
    # does not silently arrive alongside a fixture nobody asked for. Every invocation that
    # worked before this flag existed still works: omitting both reads the fixture, and
    # naming both is the one case that refuses.
    if arguments.club_news_snapshot is None and arguments.club_news_fixture is None:
        arguments.club_news_fixture = DEFAULT_CLUB_NEWS_FIXTURE
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
