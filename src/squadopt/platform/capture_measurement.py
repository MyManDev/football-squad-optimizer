"""Offline availability calibration and a paired late-capture audit.

No output changes a projection or writes into the capture archive. Rates belong to
research output only; member publication consumes neither this document nor its text.
"""

import argparse
import json
from collections import defaultdict
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from squadopt.data.errors import DataError
from squadopt.data.snapshots import CapturedSnapshot, list_snapshot_ids, read_snapshot
from squadopt.data.sources.fpl_live import (
    BOOTSTRAP_PAYLOAD,
    FPL_LIVE_SOURCE,
    gameweek_deadlines,
    live_event_outcomes,
    live_payload,
    scored_gameweeks,
)
from squadopt.data.timestamps import as_instant
from squadopt.live import infer_season
from squadopt.live.ledger import write_atomic

AVAILABILITY_FIELDS = ("status", "chance_of_playing_next_round", "news", "news_added")


def _players(snapshot: CapturedSnapshot) -> dict[int, Mapping[str, Any]]:
    document = json.loads(snapshot.payloads[BOOTSTRAP_PAYLOAD])
    result: dict[int, Mapping[str, Any]] = {}
    for player in document["elements"]:
        code = int(player["code"])
        if code in result:
            raise DataError("Capture contains duplicate persistent player codes.")
        result[code] = player
    return result


def compare_captures(
    early: CapturedSnapshot, late: CapturedSnapshot, *, gameweek: int
) -> dict[str, object]:
    """Count changed fields only among matched players; missing and zero differ."""
    if infer_season(early) != infer_season(late):
        raise DataError("Late-capture comparison needs the same season.")
    deadlines = [
        next(
            (
                row
                for row in gameweek_deadlines(item.payloads[BOOTSTRAP_PAYLOAD])
                if row.gameweek == gameweek
            ),
            None,
        )
        for item in (early, late)
    ]
    if any(row is None for row in deadlines):
        raise DataError("Both captures must name the target deadline.")
    first, second = deadlines
    assert first is not None and second is not None
    if as_instant(first.deadline_utc) != as_instant(second.deadline_utc):
        raise DataError("The target deadline changed between captures.")
    early_at = as_instant(early.metadata.captured_at_utc)
    late_at = as_instant(late.metadata.captured_at_utc)
    deadline = as_instant(second.deadline_utc)
    if not early_at < late_at < deadline:
        raise DataError("Need early capture < late capture < deadline.")
    if (deadline - late_at).total_seconds() > 24 * 3600:
        raise DataError("Late capture must be inside the final 24 hours.")
    before, after = _players(early), _players(late)
    matched = sorted(before.keys() & after.keys())
    return {
        "contract_version": "late_capture_audit_v1",
        "season": infer_season(early),
        "gameweek": gameweek,
        "early_snapshot_id": early.metadata.snapshot_id,
        "late_snapshot_id": late.metadata.snapshot_id,
        "deadline_utc": second.deadline_utc,
        "hours_between": (late_at - early_at).total_seconds() / 3600,
        "hours_before_deadline": (deadline - late_at).total_seconds() / 3600,
        "matched_players": len(matched),
        "added_players": len(after.keys() - before.keys()),
        "removed_players": len(before.keys() - after.keys()),
        "changed": {
            field: sum(before[player].get(field) != after[player].get(field) for player in matched)
            for field in AVAILABILITY_FIELDS
        },
        "changed_players": sum(
            any(
                before[player].get(field) != after[player].get(field)
                for field in AVAILABILITY_FIELDS
            )
            for player in matched
        ),
        "decision_effect": "not_measured",
    }


def availability_calibration(
    snapshots: Sequence[CapturedSnapshot], *, season: str
) -> dict[str, object]:
    """Every pre-deadline capture against its next deadline's checked event-live.

    Rows remain separate per capture so repeated snapshots never masquerade as
    independent player-weeks. Unknown feed values receive their own bucket.
    """
    captures = sorted(
        (item for item in snapshots if infer_season(item) == season),
        key=lambda item: (as_instant(item.metadata.captured_at_utc), item.metadata.snapshot_id),
    )
    rows: list[dict[str, object]] = []
    skipped: list[dict[str, object]] = []
    for capture in captures:
        deadline = next(
            (
                row
                for row in gameweek_deadlines(capture.payloads[BOOTSTRAP_PAYLOAD])
                if as_instant(row.deadline_utc) > as_instant(capture.metadata.captured_at_utc)
            ),
            None,
        )
        if deadline is None:
            continue
        settled = next(
            (
                item
                for item in reversed(captures)
                if as_instant(item.metadata.captured_at_utc) > as_instant(deadline.deadline_utc)
                and deadline.gameweek in scored_gameweeks(item.payloads[BOOTSTRAP_PAYLOAD])
                and live_payload(deadline.gameweek) in item.payloads
            ),
            None,
        )
        if settled is None:
            skipped.append(
                {
                    "snapshot_id": capture.metadata.snapshot_id,
                    "gameweek": deadline.gameweek,
                    "reason": "no_checked_event_live",
                }
            )
            continue
        outcomes = live_event_outcomes(
            settled.payloads[live_payload(deadline.gameweek)],
            settled.payloads[BOOTSTRAP_PAYLOAD],
            gameweek=deadline.gameweek,
        )
        actual = outcomes.set_index("player_id")["minutes"].to_dict()
        buckets: dict[tuple[str | None, int | None, bool], list[bool]] = defaultdict(list)
        missing = 0
        for code, player in _players(capture).items():
            if code not in actual:
                missing += 1
                continue
            chance = player.get("chance_of_playing_next_round")
            if chance is not None and (
                isinstance(chance, bool) or chance not in (0, 25, 50, 75, 100)
            ):
                raise DataError("Unexpected official chance-of-playing bucket.")
            key = (player.get("status"), chance, bool(player.get("news_added")))
            buckets[key].append(actual[code] > 0)
        for (status, chance, news_present), values in sorted(
            buckets.items(), key=lambda item: str(item[0])
        ):
            rows.append(
                {
                    "snapshot_id": capture.metadata.snapshot_id,
                    "outcome_snapshot_id": settled.metadata.snapshot_id,
                    "gameweek": deadline.gameweek,
                    "status": status,
                    "chance_of_playing_next_round": chance,
                    "news_added_present": news_present,
                    "players": len(values),
                    "appearances": sum(values),
                    "appearance_rate": sum(values) / len(values),
                    "unmatched_players_in_capture": missing,
                }
            )
    return {
        "contract_version": "availability_calibration_v1",
        "season": season,
        "unit": "player_capture",
        "rows": rows,
        "skipped": skipped,
    }


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-root", type=Path, required=True)
    parser.add_argument("--season", required=True)
    parser.add_argument("--early-snapshot")
    parser.add_argument("--late-snapshot")
    parser.add_argument("--gameweek", type=int)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.early_snapshot or args.late_snapshot:
        if not (args.early_snapshot and args.late_snapshot and args.gameweek):
            parser.error("Late audit needs both snapshot IDs and --gameweek.")
        early = read_snapshot(args.snapshot_root, args.early_snapshot)
        late = read_snapshot(args.snapshot_root, args.late_snapshot)
        if infer_season(early) != args.season:
            parser.error("The requested season does not match the captures.")
        result = compare_captures(early, late, gameweek=args.gameweek)
    else:
        result = availability_calibration(
            tuple(
                read_snapshot(args.snapshot_root, name)
                for name in list_snapshot_ids(args.snapshot_root, source=FPL_LIVE_SOURCE)
            ),
            season=args.season,
        )
    args.out.parent.mkdir(parents=True, exist_ok=True)
    write_atomic(
        args.out,
        (json.dumps(result, indent=2, sort_keys=True, allow_nan=False) + "\n").encode("utf-8"),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
