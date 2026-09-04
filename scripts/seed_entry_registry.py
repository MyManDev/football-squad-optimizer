"""Seed the entry registry from a captured classic-league standings page.

    python -m scripts.seed_entry_registry --league 352490 --dry-run
    python -m scripts.seed_entry_registry --league 352490
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

from scripts._experiment_cli import REPOSITORY_ROOT, write_json

from squadopt.application.entries import ENTRY_REGISTRY_CONTRACT_VERSION, EntryRegistry
from squadopt.data.errors import DataError
from squadopt.data.snapshots import list_snapshot_ids, read_snapshot
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

    identifiers = list_snapshot_ids(SNAPSHOT_ROOT)
    if not identifiers:
        raise DataError(
            f"No snapshots under {SNAPSHOT_ROOT}. Capture one with the league endpoint "
            "wired in, or pass --standings-file for the first seed."
        )
    chosen = snapshot_id or identifiers[-1]
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
    members: Sequence[LeagueStanding], *, league_id: int, now: str
) -> dict[str, object]:
    entries = [
        {"entry_id": member.entry_id, "label": member.entry_name, "registered_at_utc": now}
        for member in sorted(members, key=lambda member: member.entry_id)
    ]
    return {
        "contract_version": ENTRY_REGISTRY_CONTRACT_VERSION,
        "seeded_from_league": league_id,
        "entries": entries,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--league", type=int, required=True, help="classic league id")
    parser.add_argument("--snapshot-id", help="capture to read (default: the most recent)")
    parser.add_argument(
        "--standings-file", type=Path, help="a saved standings page, for the first seed"
    )
    parser.add_argument("--dry-run", action="store_true", help="report, write nothing")
    arguments = parser.parse_args()

    try:
        payload, origin = _standings_bytes(
            league_id=arguments.league,
            snapshot_id=arguments.snapshot_id,
            standings_file=arguments.standings_file,
        )
        members = fpl_league_standings(payload, league_id=arguments.league)
    except (DataError, OSError) as error:
        print(f"\nThe registry could not be seeded:\n  {error}")
        return 1

    now = datetime.now(UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    document = _registry_document(members, league_id=arguments.league, now=now)

    print(f"League    {arguments.league}  ({origin})")
    print(f"Members   {len(members)}")
    for member in members:
        print(f"  {member.rank:>3}  {member.entry_id:>9}  {_printable(member.entry_name)}")
    print()
    print("Recording each member's entry id and team name. The page also publishes the")
    print("manager's own name; it is not written.")

    if arguments.dry_run:
        print("\nDry run: nothing written.")
        return 0

    write_json(REGISTRY_PATH, document)
    reread = EntryRegistry.load(REGISTRY_PATH)
    if reread.ids() != tuple(sorted(member.entry_id for member in members)):
        print(f"\nWrote {REGISTRY_PATH} but reading it back did not reproduce the ids.")
        return 1
    print(f"\nWrote {REGISTRY_PATH}")
    print(f"  contract       {ENTRY_REGISTRY_CONTRACT_VERSION}")
    print(f"  entries        {len(reread.entries)} (re-read and verified)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
