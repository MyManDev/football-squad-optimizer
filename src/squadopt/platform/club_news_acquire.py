"""Acquire one week's club news and name the capture it wrote.

    python -m scripts.capture_club_news --roster-snapshot <id>

The consumption half of this lane has been production code for a while:
``rotation_export`` rebuilds a week from a capture with no network and no model at all. The
acquisition half existed only as a twenty-five line helper inside an integration test, so the
path worked and had no name. This is that helper, promoted, with the things a test does not
need: a registry it did not choose, refusals it has to record, and an id it has to print.

**It runs before the FPL capture, not after.**
:mod:`squadopt.features.rotation_evidence` refuses any week whose club documents carry a fetch
instant at or after the decision capture, because a document read after the decision cannot
have informed it. That is a rule about the order of the week, and this command is the step it
constrains.

**The roster comes from a capture already on disk**, named by ``--roster-snapshot``, rather
than from a fresh call to the platform. The roster is only there so the model can resolve a
short name to a player; fetching one would add a second network target to a command whose
whole reach should be the club hosts the registry names.

**There is no fixture path here.** A run with no key refuses, loudly, from
``club_news_provider``. "We could not ask" and "the fixture said" are different facts, and a
convenience branch in this command would be the one place that quietly merged them.
"""

import argparse
import sys
import time
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

from squadopt.data.claim_identity import roster_from_short_names
from squadopt.data.errors import DataError
from squadopt.data.snapshots import read_snapshot
from squadopt.data.sources.club_news import (
    ClubNewsError,
    ClubNewsProvider,
    RawDocument,
    RosterPlayer,
)
from squadopt.data.sources.club_news_capture import CodedClub, write_club_news_capture
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, short_name_roster
from squadopt.platform.club_news_fetch import (
    ClubSource,
    Opener,
    default_opener,
    fetch_registered_documents,
    load_club_sources,
)
from squadopt.platform.club_news_provider import (
    CodingProviderConfig,
    build_coding_provider,
    code_week_by_club,
)

REPOSITORY_ROOT = Path.cwd()

#: The fetcher's own defaults, named here so `acquire_week` can forward them rather than
#: re-declare what "no opener was given" means.
_default_opener = default_opener


def _utc_instant() -> datetime:
    return datetime.now(UTC)


DEFAULT_REGISTRY: Final = Path("data") / "sources" / "club_news_sources.json"
DEFAULT_SNAPSHOT_ROOT: Final = Path("data") / "snapshots"


@dataclass(frozen=True, slots=True)
class AcquiredWeek:
    """What one acquisition produced, before anything was written.

    The three coverage lists are computed here rather than downstream because this is the
    only moment that knows all of them: the registry says what was declared, the fetch says
    what was read, and the coding says what survived into an answer. Ten minutes later, from
    the payloads alone, a club whose second page was refused is indistinguishable from a club
    that only registered one.
    """

    documents: tuple[RawDocument, ...]
    coded: tuple[CodedClub, ...]
    clubs_declared: tuple[str, ...]
    clubs_covered: tuple[str, ...]
    clubs_partially_covered: tuple[str, ...]
    refused_pages: tuple[tuple[str, str], ...]
    refused_coding: tuple[tuple[str, str], ...]


def _coverage(
    sources: Sequence[ClubSource],
    documents: Sequence[RawDocument],
    coded: Sequence[CodedClub],
) -> tuple[tuple[str, ...], tuple[str, ...], tuple[str, ...]]:
    """Declared, covered, and covered-in-part, as the evidence contract defines them.

    **Covered means read *and* coded.** A club whose pages were read but whose call failed has
    nothing that survives into evidence, and the table would refuse it anyway: provenance is
    per club, and a covered club with no response is a club the manifest cannot describe. It
    is the same rule the contract already states for a club whose every claim lost its
    citation.

    **Partly covered means covered, with at least one registered page unread.** It narrows
    coverage and never replaces it, so every name here is also in the covered list.
    """

    declared = tuple(dict.fromkeys(source.club for source in sources))
    answered = {entry.club for entry in coded}
    read_by_club: dict[str, set[str]] = {}
    for document in documents:
        read_by_club.setdefault(document.club, set()).add(document.requested_url)

    covered = tuple(club for club in declared if club in answered and club in read_by_club)
    registered: dict[str, set[str]] = {}
    for source in sources:
        registered.setdefault(source.club, set()).add(source.url)
    partial = tuple(
        club for club in covered if not registered.get(club, set()) <= read_by_club.get(club, set())
    )
    return declared, covered, partial


def acquire_week(
    *,
    sources: Sequence[ClubSource],
    provider: ClubNewsProvider,
    config: CodingProviderConfig,
    roster: Sequence[RosterPlayer],
    opener: Opener = _default_opener,
    now: Callable[[], datetime] = _utc_instant,
    sleeper: Callable[[float], None] = time.sleep,
    check_robots: bool = True,
) -> AcquiredWeek:
    """Read the registered pages, code them club by club, and report what happened.

    Nothing is written here. The caller decides where a capture goes, and a rehearsal can walk
    this whole function without a store. ``opener`` and ``now`` are the fetcher's own
    parameters, forwarded rather than re-invented, so an offline test drives this exactly as
    it drives the fetch.
    """

    documents, refused_pages = fetch_registered_documents(
        sources, opener=opener, now=now, sleeper=sleeper, check_robots=check_robots
    )
    coded, refused_coding = code_week_by_club(provider, config, documents, roster)
    declared, covered, partial = _coverage(sources, documents, coded)
    return AcquiredWeek(
        documents=documents,
        coded=coded,
        clubs_declared=declared,
        clubs_covered=covered,
        clubs_partially_covered=partial,
        refused_pages=refused_pages,
        refused_coding=refused_coding,
    )


def _parse_arguments(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--roster-snapshot",
        required=True,
        help="a capture already on disk whose bootstrap supplies the short-name roster",
    )
    parser.add_argument("--registry", type=Path, default=REPOSITORY_ROOT / DEFAULT_REGISTRY)
    parser.add_argument(
        "--snapshot-root", type=Path, default=REPOSITORY_ROOT / DEFAULT_SNAPSHOT_ROOT
    )
    parser.add_argument("--dry-run", action="store_true", help="report, write nothing")
    return parser.parse_args(argv)


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def main(
    argv: list[str] | None = None,
    environ: Mapping[str, str] | None = None,
    *,
    opener: Opener = _default_opener,
    now: Callable[[], datetime] = _utc_instant,
    sleeper: Callable[[float], None] = time.sleep,
) -> int:
    """Run one acquisition, or say why it was refused.

    ``opener``, ``now`` and ``sleeper`` are the fetcher's own seams, forwarded so the whole
    command can be rehearsed without a network or a wall clock. Their defaults are the real
    ones, so a production run gets the real ones without being told.
    """

    arguments = _parse_arguments(argv)
    try:
        sources = load_club_sources(arguments.registry)
        roster_snapshot = read_snapshot(arguments.snapshot_root, arguments.roster_snapshot)
        bootstrap = roster_snapshot.payloads.get(BOOTSTRAP_PAYLOAD)
        if bootstrap is None:
            raise DataError(
                f"{arguments.roster_snapshot} carries no {BOOTSTRAP_PAYLOAD!r}, so it cannot "
                "supply the short names a claim is matched against."
            )
        roster = roster_from_short_names(short_name_roster(bootstrap))
        provider, config = build_coding_provider(environ)
        week = acquire_week(
            sources=sources,
            provider=provider,
            config=config,
            roster=roster,
            opener=opener,
            now=now,
            sleeper=sleeper,
        )
    except (ClubNewsError, DataError, OSError, ValueError) as error:
        print(f"Refused: {error}")
        return 1

    print(f"Registry      {len(sources)} pages, {len(week.clubs_declared)} clubs declared")
    print(f"Read          {len(week.documents)} documents")
    print(f"Coded         {len(week.coded)} clubs, provider {config.provider!r}")
    print(f"Covered       {len(week.clubs_covered)} clubs")
    print(f"Partly read   {len(week.clubs_partially_covered)} clubs")
    for club, reason in (*week.refused_pages, *week.refused_coding):
        print(f"  refused     {club}: {reason}")
    if not week.coded:
        print("Nothing was coded, so there is no week to capture.")
        return 1
    if arguments.dry_run:
        print("Dry run: nothing written.")
        return 0

    metadata = write_club_news_capture(
        arguments.snapshot_root,
        documents=week.documents,
        coded=week.coded,
        clubs_declared=week.clubs_declared,
        clubs_covered=week.clubs_covered,
        captured_at_utc=_utc_now(),
        clubs_partially_covered=week.clubs_partially_covered,
    )
    # The id is the point of the command: the weekly runner takes it next.
    print(f"Capture       {metadata.snapshot_id}")
    return 0


if __name__ == "__main__":  # pragma: no cover - exercised through the shim
    sys.exit(main())


__all__ = ["AcquiredWeek", "acquire_week", "main"]
