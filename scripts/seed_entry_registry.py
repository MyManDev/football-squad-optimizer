"""Seed the entry registry from a captured classic-league standings page.

    python -m scripts.seed_entry_registry --league 352490 --dry-run
    python -m scripts.seed_entry_registry --league 352490
    python -m scripts.seed_entry_registry --league-list config/leagues.json
    python -m scripts.seed_entry_registry --league 352490 --standings-file page1.json

The site's per-entry recommendations are precomputed for the ids in
``data/entries/registry.json`` (#127). Maintaining that list by hand does not scale past a
handful of people, so it is derived from the league everyone is already in: the public
standings page names every member and their entry id.

**Why this is a separate step and not part of the capture.** The capture needs the registry
to know which entry documents to fetch, and the registry comes from the standings page, so
one of the two has to come first. Making the capture do both would put a write to
``data/entries/`` inside the deadline path, where the run sheet's whole point is that
nothing surprising happens. So: seed once, ahead of time, and every later capture reads the
file. On a league whose membership has changed, re-run this before the capture rather than
during it.

That ordering leaves a first-run problem -- no capture holds a standings payload until one
has been taken with the league endpoint wired in. ``--standings-file`` exists for exactly
that: point it at a saved copy of the page and the registry is seeded without a capture.
Like everything else in this repository's data path, this script never fetches; the bytes
are already on disk.

**What is deliberately not written.** The standings page publishes each member's real name
alongside their team name. Only the team name is recorded, as the registry's label. The
registry stays out of git for the same reason the captures do (see ``.gitignore``), but a
file that never holds the personal field cannot leak it either.
"""

import argparse
import sys
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path

from scripts._provenance import REPOSITORY_ROOT, write_json

from squadopt.application.entries import ENTRY_REGISTRY_CONTRACT_VERSION, EntryRegistry
from squadopt.contracts.league_list import LEAGUE_LIST_FILE, LeagueListError, read_league_list
from squadopt.data.errors import DataError
from squadopt.data.snapshots import list_snapshot_ids, read_snapshot
from squadopt.data.sources import FPL_LIVE_SOURCE
from squadopt.data.sources.fpl_live import (
    LeagueStanding,
    fpl_league_standings,
    league_standings_payload,
)

SNAPSHOT_ROOT = REPOSITORY_ROOT / "data" / "snapshots"
REGISTRY_PATH = REPOSITORY_ROOT / "data" / "entries" / "registry.json"


def _standings_bytes(
    *, league_id: int, snapshot_id: str | None, standings_file: Path | None
) -> tuple[bytes, str]:
    """Return the standings payload and a one-line description of where it came from."""

    if standings_file is not None:
        return standings_file.read_bytes(), f"file {standings_file}"

    if snapshot_id is not None:
        chosen = snapshot_id
    else:
        # Only a live capture carries the league standings pages. Several collectors
        # share this root and an identifier begins with its source, so a lexical listing
        # orders by collector before capture time: a `fpl-top100` capture sorts after
        # every `fpl-live` one however old it is, and picking it would fail below on a
        # payload it was never going to hold. Naming a capture outright still reaches
        # every capture held, whatever took it.
        live = list_snapshot_ids(SNAPSHOT_ROOT, source=FPL_LIVE_SOURCE)
        if not live:
            raise DataError(
                f"No {FPL_LIVE_SOURCE} snapshots under {SNAPSHOT_ROOT}. Capture one with "
                "the league endpoint wired in, or pass --standings-file for the first seed."
            )
        chosen = live[-1]
    snapshot = read_snapshot(SNAPSHOT_ROOT, chosen)
    name = league_standings_payload(league_id)
    if name not in snapshot.payloads:
        raise DataError(
            f"Snapshot {chosen} carries no {name}. A capture taken before the league "
            "endpoint was wired in will not have it; pass --standings-file for the first "
            "seed, or name a later snapshot with --snapshot-id."
        )
    return snapshot.payloads[name], f"snapshot {chosen}"


def _printable(value: str) -> str:
    """A team name the console can certainly render, for display only.

    Team names are user-chosen and often carry emoji, which a Windows console codepage
    cannot encode -- printing one raises UnicodeEncodeError and would abort the seed
    before it wrote anything. The registry itself is written as UTF-8 JSON with the name
    intact; only the operator's echo of it is degraded.
    """

    encoding = sys.stdout.encoding or "utf-8"
    return value.encode(encoding, errors="replace").decode(encoding, errors="replace")


def _registry_document(
    members: Sequence[LeagueStanding], *, league_ids: Sequence[int], now: str
) -> dict[str, object]:
    """The registry: every member of every league once, by entry id.

    An entry in two of the site's leagues is one entry with one squad; the first league
    to name it keeps its team name.
    """

    by_id: dict[int, LeagueStanding] = {}
    for member in members:
        by_id.setdefault(member.entry_id, member)
    entries = [
        {"entry_id": member.entry_id, "label": member.entry_name, "registered_at_utc": now}
        for member in sorted(by_id.values(), key=lambda member: member.entry_id)
    ]
    return {
        "contract_version": ENTRY_REGISTRY_CONTRACT_VERSION,
        "seeded_from_league": league_ids[0],
        "seeded_from_leagues": list(league_ids),
        "entries": entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--league",
        type=int,
        action="append",
        help="classic league id; repeat for every league the site serves",
    )
    parser.add_argument(
        "--league-list",
        type=Path,
        help=f"the leagues the site serves ({LEAGUE_LIST_FILE.as_posix()}), instead of --league",
    )
    parser.add_argument("--snapshot-id", help="capture to read (default: the most recent)")
    parser.add_argument(
        "--standings-file", type=Path, help="a saved standings page, for the first seed"
    )
    parser.add_argument("--dry-run", action="store_true", help="report, write nothing")
    arguments = parser.parse_args()
    if arguments.league and arguments.league_list is not None:
        parser.error("--league and --league-list name the leagues two ways; use one")
    try:
        if arguments.league_list is not None:
            league_ids: tuple[int, ...] = read_league_list(arguments.league_list)
        else:
            league_ids = tuple(arguments.league or ())
    except LeagueListError as error:
        parser.error(str(error))
    if not league_ids:
        parser.error("--league (or --league-list) is required")
    if len(set(league_ids)) != len(league_ids):
        parser.error("--league names a league twice")
    if arguments.standings_file is not None and len(league_ids) != 1:
        parser.error("--standings-file is one league's page; name one league with it")

    members: list[LeagueStanding] = []
    try:
        for league_id in league_ids:
            payload, origin = _standings_bytes(
                league_id=league_id,
                snapshot_id=arguments.snapshot_id,
                standings_file=arguments.standings_file,
            )
            standings = fpl_league_standings(payload, league_id=league_id)
            print(f"League    {league_id}  ({origin})")
            print(f"Members   {len(standings)}")
            for member in standings:
                print(f"  {member.rank:>3}  {member.entry_id:>9}  {_printable(member.entry_name)}")
            members.extend(standings)
    except (DataError, OSError) as error:
        print(f"\nThe registry could not be seeded:\n  {error}")
        return 1

    now = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    document = _registry_document(members, league_ids=league_ids, now=now)
    print()
    print("Recording each member's entry id and team name. The page also publishes the")
    print("manager's own name; it is not written.")

    if arguments.dry_run:
        print("\nDry run: nothing written.")
        return 0

    write_json(REGISTRY_PATH, document)
    reread = EntryRegistry.load(REGISTRY_PATH)
    if reread.ids() != tuple(sorted({member.entry_id for member in members})):
        print(f"\nWrote {REGISTRY_PATH} but reading it back did not reproduce the ids.")
        return 1
    print(f"\nWrote {REGISTRY_PATH}")
    print(f"  contract       {ENTRY_REGISTRY_CONTRACT_VERSION}")
    print(f"  entries        {len(reread.entries)} (re-read and verified)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
