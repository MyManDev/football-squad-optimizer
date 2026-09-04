"""Write the site's league tree from a capture that read the registered entries.

    python -m scripts.build_league_site --league 352490 --out web/public
    python -m scripts.build_league_site --league 352490 --snapshot-id <id> --dry-run

The capture must have been taken with ``--entries`` so it holds each registered member's
three public documents plus the league standings page; ``scripts.seed_entry_registry``
writes the registry that names them. This shell reads those payloads, hands them to
``build_league_views`` through the ``EntryPicksProvider`` seam, and writes
``<out>/data/league/**``.

What it does not do is decide anything of ours: no ledger is read, no decision recorded.
A member's advice is computed from that member's own squad and the shared projection, and
the invariance test in ``tests/unit/test_league_views.py`` pins that as fact rather than
as intention.

Nothing personal is committed. The registry and the captures stay local (``.gitignore``
excludes ``data/entries/`` and ``data/snapshots/``); what this writes under ``web/public``
is the public post-deadline picture the league's own standings page already shows.
"""

import argparse
import json
import sys
from collections.abc import Mapping, Sequence
from pathlib import Path

from squadopt.application.entries import EntryPicks, EntryRegistry
from squadopt.application.league_views import (
    MemberStanding,
    build_league_views,
)
from squadopt.application.mode_selection import build_mode_paths
from squadopt.data.errors import DataError
from squadopt.data.snapshots import read_snapshot
from squadopt.data.sources.fpl_live import (
    EntryGameweekPoints,
    fpl_entry_history_points,
    fpl_entry_picks,
    fpl_league_standings,
    scored_gameweeks,
)
from squadopt.data.sources.vaastav import build_panel
from squadopt.live import (
    load_residual_history,
    project,
    read_inputs,
    read_projection_handoff,
    read_season_rules,
)
from squadopt.live.recommendation import infer_season


def _element_to_code(payloads: object) -> dict[int, int]:
    """Map the capture's per-season element ids onto the codes everything else uses."""

    document = json.loads(payloads["bootstrap-static.json"].decode("utf-8"))  # type: ignore[index]
    elements = document.get("elements")
    if not isinstance(elements, list):
        raise DataError("The capture's bootstrap payload carries no elements list.")
    return {
        int(element["id"]): int(element["code"])
        for element in elements
        if isinstance(element, dict) and "id" in element and "code" in element
    }


def member_points(
    payloads: Mapping[str, bytes], entry_ids: Sequence[int], *, gameweek: int
) -> dict[int, EntryGameweekPoints]:
    """Each member's score for one gameweek, from that member's own history.

    A member whose history the capture does not hold, or who has no row for this week, is
    **omitted** rather than recorded as zero: the caller publishes null for them, which
    says the capture does not prove their score. Omission is the honest answer and a zero
    would be a claim.
    """

    scores: dict[int, EntryGameweekPoints] = {}
    for entry_id in entry_ids:
        payload = payloads.get(f"entry-{entry_id}-history.json")
        if payload is None:
            continue
        for week in fpl_entry_history_points(payload, entry_id=entry_id):
            if week.gameweek == gameweek:
                scores[entry_id] = week
                break
    return scores


def last_scored_gameweek(bootstrap: bytes, *, before: int) -> int | None:
    """The most recent week whose points are final, earlier than the week being built.

    ``None`` while no week has been both finished and checked — before the opening
    deadline, and during the hours after the last whistle when bonus has not landed.
    """

    scored = [week for week in scored_gameweeks(bootstrap) if week < before]
    return max(scored) if scored else None


SNAPSHOT_ROOT = Path("data/snapshots")
ARCHIVE_ROOT = Path("data/raw/vaastav-fpl")
REGISTRY_PATH = Path("data/entries/registry.json")


class _CapturePicks:
    """Serves each member's picks from the capture's own payloads.

    One translation happens here and it is load-bearing: the entry endpoints name players
    by **element** id, which is a per-season number, while everything downstream of a
    capture — the projection, the prices, the ledger — names them by **code**, the
    identifier that survives a transfer window. Handing element ids to a consumer that
    means codes does not fail loudly; it silently fails to find any of the squad, which
    is exactly how this surfaced (fifteen members, "no current price", zero rendered).
    """

    def __init__(self, snapshot: object, snapshot_id: str) -> None:
        self._payloads = getattr(snapshot, "payloads", {})
        self._snapshot_id = snapshot_id
        self._code_by_element = _element_to_code(self._payloads)

    def _code(self, element: int) -> int:
        code = self._code_by_element.get(int(element))
        if code is None:
            raise DataError(
                f"The capture's bootstrap does not name element {element}, so the squad "
                "cannot be resolved to the ids the projection uses."
            )
        return code

    def picks(self, entry_id: int, season: str, gameweek: int) -> EntryPicks:
        picks_name = f"entry-{entry_id}-picks-gw{gameweek:02d}.json"
        history_name = f"entry-{entry_id}-history.json"
        for name in (picks_name, history_name):
            if name not in self._payloads:
                raise DataError(f"The capture holds no {name}; re-capture with --entries.")
        record = fpl_entry_picks(
            self._payloads[picks_name],
            self._payloads[history_name],
            entry_id=entry_id,
            season=season,
            gameweek=gameweek,
            source_snapshot_id=self._snapshot_id,
        )
        # The data record and the application type are twins by design: same field names,
        # no translation table, so a drift on either side is a type error rather than a
        # silently wrong squad.
        return EntryPicks(
            entry_id=record.entry_id,
            season=record.season,
            gameweek=record.gameweek,
            squad=tuple(self._code(player) for player in record.squad),
            starting_xi=tuple(self._code(player) for player in record.starting_xi),
            captain=self._code(record.captain),
            vice_captain=self._code(record.vice_captain),
            bank_tenths=record.bank_tenths,
            free_transfers=record.free_transfers,
            free_transfers_known=record.free_transfers_known,
            chips_used=record.chips_used,
            purchase_prices={
                self._code(player): price for player, price in record.purchase_prices.items()
            },
            purchase_prices_known=record.purchase_prices_known,
            source_snapshot_id=record.source_snapshot_id,
        )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--league", type=int, required=True)
    parser.add_argument("--snapshot-id", help="default: the most recent capture")
    parser.add_argument("--out", default="web/public")
    parser.add_argument("--season")
    parser.add_argument("--archive-root", default=str(ARCHIVE_ROOT))
    parser.add_argument("--registry", default=str(REGISTRY_PATH))
    parser.add_argument(
        "--in-season-projection",
        type=Path,
        help="projection handoff for this capture and gameweek; required from GW2 on, "
        "the same file the decision reads (projection_handoff_v1)",
    )
    parser.add_argument(
        "--mode-residuals",
        type=Path,
        help="residual export (csv/parquet beside its manifest) to build one-week scenario "
        "paths from; turns on the competitive play modes. When given, a history that "
        "cannot honestly support paths fails the run rather than silently downgrading.",
    )
    parser.add_argument("--dry-run", action="store_true", help="report, write nothing")
    arguments = parser.parse_args()

    try:
        from scripts.recommend_current_squad import resolve_snapshot_id

        snapshot_id = resolve_snapshot_id(arguments.snapshot_id)
        snapshot = read_snapshot(SNAPSHOT_ROOT, snapshot_id)
        season = arguments.season or infer_season(snapshot)
        inputs = read_inputs(snapshot, season=season, gameweek=None)
        registry = EntryRegistry.load(Path(arguments.registry))
        if not registry.entries:
            raise DataError(
                f"No registered entries in {arguments.registry}; seed it first with "
                "`python -m scripts.seed_entry_registry --league <id>`."
            )

        standings_name = f"league-{arguments.league}-standings.json"
        payloads = getattr(snapshot, "payloads", {})
        standings: dict[int, MemberStanding] = {}
        league_name = f"League {arguments.league}"
        registered = [int(entry.entry_id) for entry in registry.entries]
        scored = last_scored_gameweek(
            payloads["bootstrap-static.json"], before=int(inputs.deadline.gameweek)
        )
        scores = member_points(payloads, registered, gameweek=scored) if scored is not None else {}
        if standings_name in payloads:
            rows = fpl_league_standings(payloads[standings_name], league_id=arguments.league)
            standings = {
                row.entry_id: MemberStanding(
                    entry_id=row.entry_id,
                    team_name=row.entry_name,
                    manager_name=row.player_name,
                    rank=row.rank,
                    gameweek_points=(
                        scores[row.entry_id].points if row.entry_id in scores else None
                    ),
                    total_points=(
                        scores[row.entry_id].total_points if row.entry_id in scores else None
                    ),
                )
                for row in rows
            }
        scored_note = (
            f"points for {len(scores)} of {len(registered)} from gameweek {scored}"
            if scored is not None
            else "no scored gameweek yet, so no points are published"
        )
        print(
            f"capture {snapshot_id}: {len(registry.entries)} registered, "
            f"{len(standings)} in the standings, targeting {season} "
            f"gameweek {inputs.deadline.gameweek}; {scored_note}"
        )
        if arguments.dry_run:
            print("Dry run: nothing written.")
            return 0

        panel = build_panel(Path(arguments.archive_root))
        # Members' advice uses the same projection our own decision uses; from GW2 on that
        # is the produced handoff, and the live path refuses one built from another
        # capture — so the league tree and the decision cannot silently disagree.
        in_season = (
            read_projection_handoff(arguments.in_season_projection)
            if arguments.in_season_projection
            else None
        )
        projection = project(inputs, panel, in_season=in_season)
        mode_paths = None
        if arguments.mode_residuals:
            history = load_residual_history(arguments.mode_residuals)
            mode_paths = build_mode_paths(
                projection,
                history,
                season=season,
                gameweek=int(inputs.deadline.gameweek),
            )
            print(
                f"mode paths: {mode_paths.config.scenario_count} scenarios for gameweek "
                f"{inputs.deadline.gameweek} from {history.source_id}"
            )
        out_dir = Path(arguments.out) / "data" / "league"
        report = build_league_views(
            _CapturePicks(snapshot, snapshot_id),
            registry.entries,
            inputs,
            projection,
            read_season_rules(snapshot, season=season),
            league_id=arguments.league,
            league_name=league_name,
            out_dir=out_dir,
            standings=standings,
            scored_gameweek=scored,
            mode_paths=mode_paths,
        )
        print(f"Rendered {report.rendered_count} of {len(report.members)} members into {out_dir}")
        for member in report.members:
            if not member.rendered:
                print(f"  not rendered  {member.entry_id}  {member.reason}")
        return 0
    except (DataError, OSError, ValueError) as error:
        print(f"build_league_site failed:\n  {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
