"""Private weekly Benchmark V2 receipts, separate from published decisions."""

import argparse
import hashlib
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from squadopt.data.atomic import document_bytes
from squadopt.data.cohorts import ranked_entries_from_pages, require_pre_deadline_capture
from squadopt.data.errors import DataError, DataSourceError
from squadopt.data.snapshots import (
    CapturedSnapshot,
    SnapshotMetadata,
    read_snapshot,
    write_snapshot,
)
from squadopt.data.sources.fpl_live import (
    BOOTSTRAP_PAYLOAD,
    entry_history_payload,
    entry_picks_payload,
    fpl_league_standings_page,
    gameweek_deadlines,
    league_standings_page_payload,
    live_payload,
    scored_gameweeks,
)
from squadopt.data.timestamps import as_instant
from squadopt.optimization import OptimizationConfig
from squadopt.platform.fpl_capture import BASE_URL, fetch

SEASON = "2026-27"
CONTRACT = "benchmark_v2_capture_v1"
_LIVE_ID = re.compile(r"fpl-[a-z0-9-]+-(\d{8})T\d{6}Z-[0-9a-f]+")


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def read_live_capture(root: Path, identifier: str) -> CapturedSnapshot:
    """Admit live-season ids before opening bytes; never enumerate the store."""
    match = _LIVE_ID.fullmatch(identifier)
    if match is None or not "20260801" <= match.group(1) < "20270801":
        raise DataSourceError("Benchmark capture is outside the live season.")
    snapshot = read_snapshot(root, identifier)
    at = as_instant(snapshot.metadata.captured_at_utc)
    if not as_instant("2026-08-01T00:00:00Z") <= at < as_instant("2027-08-01T00:00:00Z"):
        raise DataSourceError("Benchmark capture is outside the live season.")
    return snapshot


def _deadline(snapshot: CapturedSnapshot, gameweek: int) -> str:
    if type(gameweek) is not int or not 3 <= gameweek <= 38:
        raise DataSourceError("Benchmark V2 starts at gameweek 3.")
    deadlines = {
        item.gameweek: item.deadline_utc
        for item in gameweek_deadlines(snapshot.payloads[BOOTSTRAP_PAYLOAD])
    }
    if gameweek not in deadlines:
        raise DataSourceError("Benchmark capture has no target deadline.")
    return deadlines[gameweek]


def _cohort(snapshot: CapturedSnapshot, gameweek: int, deadline: str) -> tuple[int, ...]:
    if snapshot.metadata.source != "fpl-top100":
        raise DataSourceError("Benchmark needs the original primary Top-100 capture.")
    if as_instant(_deadline(snapshot, gameweek)) != as_instant(deadline):
        raise DataSourceError("Benchmark cohort belongs to another deadline.")
    require_pre_deadline_capture(
        captured_at_utc=snapshot.metadata.captured_at_utc, deadline_timestamp_utc=deadline
    )
    pages = [
        fpl_league_standings_page(
            snapshot.payloads[league_standings_page_payload(314, page)],
            league_id=314,
            expected_page=page,
        )
        for page in (1, 2)
    ]
    return ranked_entries_from_pages(pages, expected_ranks=100)


def freeze_decision(
    root: Path,
    *,
    decision_directory: Path,
    cohort_snapshot_id: str,
    gameweek: int,
    output_root: Path | None = None,
    now: Callable[[], str] = _now,
) -> SnapshotMetadata:
    """Copy an existing primary ledger decision and its exact pool before deadline."""
    decision_bytes = (decision_directory / "decision.json").read_bytes()
    decision = json.loads(decision_bytes)
    if (decision.get("season"), decision.get("gameweek")) != (SEASON, gameweek):
        raise DataSourceError("Benchmark decision belongs to another season or gameweek.")
    source = read_live_capture(root, decision["snapshot_id"])
    if source.metadata.source != "fpl-live":
        raise DataSourceError("Benchmark decision needs a live source capture.")
    deadline = _deadline(source, gameweek)
    if (
        as_instant(decision["deadline_utc"]) != as_instant(deadline)
        or decision["captured_at_utc"] != source.metadata.captured_at_utc
    ):
        raise DataSourceError("Benchmark ledger decision differs from its source capture.")
    require_pre_deadline_capture(
        captured_at_utc=source.metadata.captured_at_utc, deadline_timestamp_utc=deadline
    )
    cohort = read_live_capture(root, cohort_snapshot_id)
    _cohort(cohort, gameweek, deadline)
    for name in (
        "squad_player_ids",
        "starting_xi_player_ids",
        "ordered_bench_player_ids",
        "captain_player_id",
        "vice_captain_player_id",
        "completion_policy",
    ):
        if name not in decision:
            raise DataSourceError("Benchmark decision lacks a frozen scoring input.")
    config = OptimizationConfig()
    binding = {
        "contract_version": CONTRACT,
        "season": SEASON,
        "gameweek": gameweek,
        "cohort_snapshot_id": cohort_snapshot_id,
        "cohort_fingerprint": cohort.metadata.fingerprint,
        "decision_snapshot_id": source.metadata.snapshot_id,
        "decision_fingerprint": source.metadata.fingerprint,
        "system_decision_sha256": hashlib.sha256(decision_bytes).hexdigest(),
        "template_configuration": {
            "budget_tenths": config.budget_tenths,
            "max_players_per_team": config.max_players_per_team,
            "expected_points_scale": config.expected_points_scale,
        },
    }
    started_at = now()
    completed_at = started_at
    require_pre_deadline_capture(captured_at_utc=completed_at, deadline_timestamp_utc=deadline)
    if as_instant(completed_at) < max(
        as_instant(source.metadata.captured_at_utc), as_instant(cohort.metadata.captured_at_utc)
    ):
        raise DataSourceError("Benchmark clock precedes its source captures.")
    destination = output_root or root
    for original in (source, cohort):
        if (destination / original.metadata.snapshot_id).exists():
            existing = read_snapshot(destination, original.metadata.snapshot_id)
            if existing.metadata != original.metadata or existing.payloads != original.payloads:
                raise DataSourceError("Benchmark retained source identity differs.")
        else:
            write_snapshot(
                destination,
                source=original.metadata.source,
                captured_at_utc=original.metadata.captured_at_utc,
                payloads=original.payloads,
            )
    completed_at = now()
    require_pre_deadline_capture(captured_at_utc=completed_at, deadline_timestamp_utc=deadline)
    if as_instant(completed_at) < as_instant(started_at):
        raise DataSourceError("Benchmark freeze clock moved backwards.")
    return write_snapshot(
        destination,
        source="fpl-benchmark-decision",
        captured_at_utc=completed_at,
        payloads={
            BOOTSTRAP_PAYLOAD: source.payloads[BOOTSTRAP_PAYLOAD],
            "system-decision.json": decision_bytes,
            "benchmark.json": document_bytes(binding),
        },
    )


def capture_settled_picks(
    root: Path,
    *,
    freeze_snapshot_id: str,
    fetcher: Callable[[str], bytes] = fetch,
    now: Callable[[], str] = _now,
) -> SnapshotMetadata:
    """Read target-week picks only for the previously frozen 100, after settlement."""
    frozen = read_live_capture(root, freeze_snapshot_id)
    if frozen.metadata.source != "fpl-benchmark-decision":
        raise DataSourceError("Benchmark picks need a decision freeze.")
    binding: dict[str, Any] = json.loads(frozen.payloads["benchmark.json"])
    if binding.get("season") != SEASON or binding.get("contract_version") != CONTRACT:
        raise DataSourceError("Benchmark freeze has another season or contract.")
    gameweek = binding["gameweek"]
    deadline = _deadline(frozen, gameweek)
    require_pre_deadline_capture(
        captured_at_utc=frozen.metadata.captured_at_utc, deadline_timestamp_utc=deadline
    )
    cohort = read_live_capture(root, binding["cohort_snapshot_id"])
    if cohort.metadata.fingerprint != binding["cohort_fingerprint"]:
        raise DataSourceError("Benchmark frozen cohort fingerprint differs.")
    members = _cohort(cohort, gameweek, deadline)
    started_at = now()
    if as_instant(started_at) < as_instant(deadline):
        raise DataSourceError("Benchmark picks cannot be read before the target deadline.")
    bootstrap = fetcher(f"{BASE_URL}/bootstrap-static/")
    observed = {item.gameweek: item.deadline_utc for item in gameweek_deadlines(bootstrap)}
    if (
        gameweek not in scored_gameweeks(bootstrap)
        or gameweek not in observed
        or as_instant(observed[gameweek]) != as_instant(deadline)
    ):
        raise DataSourceError(
            "Benchmark target is not finished and checked at the frozen deadline."
        )
    payloads = {BOOTSTRAP_PAYLOAD: bootstrap}
    unreadable = 0
    for entry in members:
        try:
            picks = fetcher(f"{BASE_URL}/entry/{entry}/event/{gameweek}/picks/")
            history = fetcher(f"{BASE_URL}/entry/{entry}/history/")
        except (DataError, OSError):
            unreadable += 1
            continue
        payloads[entry_picks_payload(entry, gameweek)] = picks
        payloads[entry_history_payload(entry)] = history
    event = fetcher(f"{BASE_URL}/event/{gameweek}/live/")
    completed_at = now()
    if as_instant(completed_at) < as_instant(deadline):
        raise DataSourceError("Benchmark picks completion clock precedes the deadline.")
    if as_instant(completed_at) < as_instant(started_at):
        raise DataSourceError("Benchmark picks clock moved backwards.")
    if (
        not as_instant("2026-08-01T00:00:00Z")
        <= as_instant(completed_at)
        < as_instant("2027-08-01T00:00:00Z")
    ):
        raise DataSourceError("Benchmark picks capture is outside the live season.")
    outcome = write_snapshot(
        root,
        source="fpl-live",
        captured_at_utc=completed_at,
        payloads={BOOTSTRAP_PAYLOAD: bootstrap, live_payload(gameweek): event},
    )
    payloads["benchmark.json"] = document_bytes(
        {
            "contract_version": CONTRACT,
            "season": SEASON,
            "gameweek": gameweek,
            "cohort_snapshot_id": cohort.metadata.snapshot_id,
            "cohort_fingerprint": cohort.metadata.fingerprint,
            "freeze_snapshot_id": frozen.metadata.snapshot_id,
            "freeze_fingerprint": frozen.metadata.fingerprint,
            "outcome_snapshot_id": outcome.snapshot_id,
            "outcome_fingerprint": outcome.fingerprint,
            "members_requested": len(members),
            "members_readable": len(members) - unreadable,
            "members_unreadable": unreadable,
        }
    )
    return write_snapshot(
        root, source="fpl-benchmark-picks", captured_at_utc=completed_at, payloads=payloads
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-root", type=Path, required=True)
    parser.add_argument("--freeze-snapshot", required=True)
    args = parser.parse_args(argv)
    try:
        receipt = capture_settled_picks(args.snapshot_root, freeze_snapshot_id=args.freeze_snapshot)
    except (DataError, OSError, ValueError, KeyError, TypeError):
        print("Benchmark picks capture refused; check the private freeze and settlement inputs.")
        return 1
    print(f"Benchmark picks snapshot: {receipt.snapshot_id}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
