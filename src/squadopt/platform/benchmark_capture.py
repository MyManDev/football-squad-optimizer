"""Private weekly Benchmark V2 receipts, separate from published decisions."""

import argparse
import contextlib
import hashlib
import io
import json
import re
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.error import HTTPError

from squadopt.data.atomic import document_bytes, write_document_once
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
    next_open_deadline,
    scored_gameweeks,
)
from squadopt.data.timestamps import as_instant
from squadopt.live.ledger import LedgerError, verify_manifest
from squadopt.optimization import OptimizationConfig
from squadopt.platform._queue_lock import QueueFileLock
from squadopt.platform.fpl_capture import BASE_URL, fetch

SEASON = "2026-27"
CONTRACT = "benchmark_v2_capture_v1"
_LIVE_ID = re.compile(r"fpl-[a-z0-9-]+-(\d{8})T\d{6}Z-[0-9a-f]+")


class BenchmarkCaptureRefused(DataSourceError):
    def __init__(self, reason: str, message: str) -> None:
        super().__init__(message)
        self.reason = reason


def refusal_code(error: Exception) -> str:
    if isinstance(error, BenchmarkCaptureRefused):
        return error.reason
    if isinstance(error, LedgerError):
        return "invalid_decision"
    if isinstance(error, OSError):
        return "transport_failure"
    return "invalid_input"


def freeze_claim_path(root: Path, gameweek: int) -> Path:
    if type(gameweek) is not int or not 3 <= gameweek <= 38:
        raise BenchmarkCaptureRefused("invalid_gameweek", "Benchmark V2 starts at gameweek 3.")
    return root / "claims" / f"freeze-{SEASON}-gw{gameweek:02d}.json"


def picks_claim_path(root: Path, freeze_snapshot_id: str) -> Path:
    if _LIVE_ID.fullmatch(freeze_snapshot_id) is None:
        raise BenchmarkCaptureRefused("missing_freeze", "Benchmark picks need a live freeze id.")
    return root / "claims" / f"picks-{freeze_snapshot_id}.json"


def _claimed(root: Path, path: Path) -> SnapshotMetadata | None:
    if not path.is_file():
        return None
    claim = json.loads(path.read_bytes())
    snapshot = read_live_capture(root, claim["snapshot_id"])
    if snapshot.metadata.fingerprint != claim["fingerprint"]:
        raise BenchmarkCaptureRefused("provenance_mismatch", "Benchmark claim fingerprint differs.")
    return snapshot.metadata


def _claim(root: Path, path: Path, receipt: SnapshotMetadata) -> SnapshotMetadata:
    # Lock only the short metadata transaction, never the network collection.
    with QueueFileLock(root / "claims/.claims.lock").hold():
        existing = _claimed(root, path)
        if existing is not None:
            return existing
        write_document_once(
            {"snapshot_id": receipt.snapshot_id, "fingerprint": receipt.fingerprint}, path
        )
        return receipt


def _predeadline(captured_at: str, deadline: str) -> None:
    try:
        require_pre_deadline_capture(captured_at_utc=captured_at, deadline_timestamp_utc=deadline)
    except DataError as error:
        raise BenchmarkCaptureRefused("late", str(error)) from error


def _http_status(error: Exception) -> int | None:
    current: BaseException | None = error
    while current is not None:
        if isinstance(current, HTTPError):
            return int(current.code)
        current = current.__cause__
    return None


def _private_fetch(url: str) -> bytes:
    # The shared fetcher prints retry URLs; these contain private cohort entry ids.
    with contextlib.redirect_stdout(io.StringIO()):
        return fetch(url)


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def read_live_capture(root: Path, identifier: str) -> CapturedSnapshot:
    """Admit live-season ids before opening bytes; never enumerate the store."""
    match = _LIVE_ID.fullmatch(identifier)
    if match is None or not "20260801" <= match.group(1) < "20270801":
        raise BenchmarkCaptureRefused(
            "outside_live_season", "Benchmark capture is outside the live season."
        )
    snapshot = read_snapshot(root, identifier)
    at = as_instant(snapshot.metadata.captured_at_utc)
    if not as_instant("2026-08-01T00:00:00Z") <= at < as_instant("2027-08-01T00:00:00Z"):
        raise BenchmarkCaptureRefused(
            "outside_live_season", "Benchmark capture is outside the live season."
        )
    return snapshot


def _deadline(snapshot: CapturedSnapshot, gameweek: int) -> str:
    if type(gameweek) is not int or not 3 <= gameweek <= 38:
        raise BenchmarkCaptureRefused("invalid_gameweek", "Benchmark V2 starts at gameweek 3.")
    deadlines = {
        item.gameweek: item.deadline_utc
        for item in gameweek_deadlines(snapshot.payloads[BOOTSTRAP_PAYLOAD])
    }
    if gameweek not in deadlines:
        raise BenchmarkCaptureRefused(
            "deadline_mismatch", "Benchmark capture has no target deadline."
        )
    return deadlines[gameweek]


def _cohort(snapshot: CapturedSnapshot, gameweek: int, deadline: str) -> tuple[int, ...]:
    if snapshot.metadata.source != "fpl-top100":
        raise BenchmarkCaptureRefused(
            "no_cohort", "Benchmark needs the original primary Top-100 capture."
        )
    if as_instant(_deadline(snapshot, gameweek)) != as_instant(deadline):
        raise BenchmarkCaptureRefused(
            "deadline_mismatch", "Benchmark cohort belongs to another deadline."
        )
    _predeadline(snapshot.metadata.captured_at_utc, deadline)
    opened = next_open_deadline(
        gameweek_deadlines(snapshot.payloads[BOOTSTRAP_PAYLOAD]),
        as_of_utc=snapshot.metadata.captured_at_utc,
    )
    if opened.gameweek != gameweek:
        raise BenchmarkCaptureRefused(
            "deadline_mismatch", "Benchmark cohort was open for another gameweek."
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
    destination = output_root or root
    claim_path = freeze_claim_path(destination, gameweek)
    existing_claim = _claimed(destination, claim_path)
    if existing_claim is not None:
        return existing_claim
    if not (decision_directory / "decision.json").is_file():
        raise BenchmarkCaptureRefused("missing_decision", "Benchmark needs a recorded decision.")
    verify_manifest(decision_directory)
    decision_bytes = (decision_directory / "decision.json").read_bytes()
    manifest = json.loads((decision_directory / "manifest.json").read_bytes())
    if manifest["files"].get("decision.json") != hashlib.sha256(decision_bytes).hexdigest():
        raise BenchmarkCaptureRefused(
            "invalid_decision", "Benchmark decision digest differs from its manifest."
        )
    decision = json.loads(decision_bytes)
    if (decision.get("season"), decision.get("gameweek")) != (SEASON, gameweek):
        raise BenchmarkCaptureRefused(
            "not_a_decision", "Benchmark decision belongs to another season or gameweek."
        )
    if not isinstance(decision.get("snapshot_id"), str):
        raise BenchmarkCaptureRefused("not_a_decision", "Benchmark needs a captured decision.")
    source = read_live_capture(root, decision["snapshot_id"])
    if source.metadata.source != "fpl-live":
        raise BenchmarkCaptureRefused(
            "not_a_decision", "Benchmark decision needs a live source capture."
        )
    deadline = _deadline(source, gameweek)
    if (
        as_instant(decision["deadline_utc"]) != as_instant(deadline)
        or decision["captured_at_utc"] != source.metadata.captured_at_utc
    ):
        raise BenchmarkCaptureRefused(
            "deadline_mismatch", "Benchmark ledger decision differs from its source capture."
        )
    _predeadline(source.metadata.captured_at_utc, deadline)
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
            raise BenchmarkCaptureRefused(
                "not_a_decision", "Benchmark decision lacks a frozen scoring input."
            )
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
    _predeadline(completed_at, deadline)
    if as_instant(completed_at) < max(
        as_instant(source.metadata.captured_at_utc), as_instant(cohort.metadata.captured_at_utc)
    ):
        raise BenchmarkCaptureRefused(
            "clock_before_capture", "Benchmark clock precedes its source captures."
        )
    for original in (source, cohort):
        if (destination / original.metadata.snapshot_id).exists():
            existing = read_snapshot(destination, original.metadata.snapshot_id)
            if existing.metadata != original.metadata or existing.payloads != original.payloads:
                raise BenchmarkCaptureRefused(
                    "provenance_mismatch", "Benchmark retained source identity differs."
                )
        else:
            write_snapshot(
                destination,
                source=original.metadata.source,
                captured_at_utc=original.metadata.captured_at_utc,
                payloads=original.payloads,
            )
    completed_at = now()
    _predeadline(completed_at, deadline)
    if as_instant(completed_at) < as_instant(started_at):
        raise BenchmarkCaptureRefused(
            "clock_moved_backwards", "Benchmark freeze clock moved backwards."
        )
    receipt = write_snapshot(
        destination,
        source="fpl-benchmark-decision",
        captured_at_utc=completed_at,
        payloads={
            BOOTSTRAP_PAYLOAD: source.payloads[BOOTSTRAP_PAYLOAD],
            "system-decision.json": decision_bytes,
            "benchmark.json": document_bytes(binding),
        },
    )
    return _claim(destination, claim_path, receipt)


def capture_settled_picks(
    root: Path,
    *,
    freeze_snapshot_id: str,
    fetcher: Callable[[str], bytes] = _private_fetch,
    now: Callable[[], str] = _now,
) -> SnapshotMetadata:
    """Read target-week picks only for the previously frozen 100, after settlement."""
    claim_path = picks_claim_path(root, freeze_snapshot_id)
    existing_claim = _claimed(root, claim_path)
    if existing_claim is not None:
        return existing_claim
    if not (root / freeze_snapshot_id).is_dir():
        raise BenchmarkCaptureRefused("missing_freeze", "Benchmark freeze does not exist.")
    frozen = read_live_capture(root, freeze_snapshot_id)
    if frozen.metadata.source != "fpl-benchmark-decision":
        raise BenchmarkCaptureRefused("missing_freeze", "Benchmark picks need a decision freeze.")
    binding: dict[str, Any] = json.loads(frozen.payloads["benchmark.json"])
    if binding.get("season") != SEASON or binding.get("contract_version") != CONTRACT:
        raise BenchmarkCaptureRefused(
            "invalid_freeze", "Benchmark freeze has another season or contract."
        )
    gameweek = binding["gameweek"]
    deadline = _deadline(frozen, gameweek)
    _predeadline(frozen.metadata.captured_at_utc, deadline)
    binding_claim = _claimed(root, freeze_claim_path(root, gameweek))
    if binding_claim != frozen.metadata:
        raise BenchmarkCaptureRefused("invalid_freeze", "Benchmark freeze is not the claimed week.")
    cohort = read_live_capture(root, binding["cohort_snapshot_id"])
    if cohort.metadata.fingerprint != binding["cohort_fingerprint"]:
        raise BenchmarkCaptureRefused(
            "provenance_mismatch", "Benchmark frozen cohort fingerprint differs."
        )
    members = _cohort(cohort, gameweek, deadline)
    started_at = now()
    if as_instant(started_at) < as_instant(deadline):
        raise BenchmarkCaptureRefused(
            "not_settled", "Benchmark picks cannot be read before the target deadline."
        )
    bootstrap = fetcher(f"{BASE_URL}/bootstrap-static/")
    observed = {item.gameweek: item.deadline_utc for item in gameweek_deadlines(bootstrap)}
    if (
        gameweek not in scored_gameweeks(bootstrap)
        or gameweek not in observed
        or as_instant(observed[gameweek]) != as_instant(deadline)
    ):
        raise BenchmarkCaptureRefused(
            "not_settled", "Benchmark target is not finished and checked at the frozen deadline."
        )
    payloads = {BOOTSTRAP_PAYLOAD: bootstrap}
    unreadable = 0
    failure_counts: dict[str, int] = {}
    for entry in members:
        try:
            picks = fetcher(f"{BASE_URL}/entry/{entry}/event/{gameweek}/picks/")
            history = fetcher(f"{BASE_URL}/entry/{entry}/history/")
        except (DataError, OSError) as error:
            if _http_status(error) != 404:
                raise BenchmarkCaptureRefused(
                    "transport_failure", "Benchmark collection has an unresolved read failure."
                ) from error
            unreadable += 1
            failure_counts["http_404"] = failure_counts.get("http_404", 0) + 1
            continue
        payloads[entry_picks_payload(entry, gameweek)] = picks
        payloads[entry_history_payload(entry)] = history
    event = fetcher(f"{BASE_URL}/event/{gameweek}/live/")
    completed_at = now()
    if as_instant(completed_at) < as_instant(deadline):
        raise BenchmarkCaptureRefused(
            "late", "Benchmark picks completion clock precedes the deadline."
        )
    if as_instant(completed_at) < as_instant(started_at):
        raise BenchmarkCaptureRefused(
            "clock_moved_backwards", "Benchmark picks clock moved backwards."
        )
    if (
        not as_instant("2026-08-01T00:00:00Z")
        <= as_instant(completed_at)
        < as_instant("2027-08-01T00:00:00Z")
    ):
        raise BenchmarkCaptureRefused(
            "outside_live_season", "Benchmark picks capture is outside the live season."
        )
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
            "failure_counts": failure_counts,
        }
    )
    receipt = write_snapshot(
        root, source="fpl-benchmark-picks", captured_at_utc=completed_at, payloads=payloads
    )
    return _claim(root, claim_path, receipt)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--snapshot-root", type=Path, required=True)
    parser.add_argument("--freeze-snapshot", required=True)
    args = parser.parse_args(argv)
    try:
        receipt = capture_settled_picks(args.snapshot_root, freeze_snapshot_id=args.freeze_snapshot)
    except (DataError, OSError, ValueError, KeyError, TypeError) as error:
        print(f"Benchmark picks capture refused: {refusal_code(error)}")
        return 1
    binding = json.loads(
        read_live_capture(args.snapshot_root, receipt.snapshot_id).payloads["benchmark.json"]
    )
    print(
        f"Benchmark picks snapshot: {receipt.snapshot_id}; "
        f"readable={binding['members_readable']}; unreadable={binding['members_unreadable']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
