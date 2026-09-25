"""Season ledger: the permanent record of live decisions and their outcomes.

A live recommendation that is acted on and then forgotten teaches nothing. The
ledger freezes each gameweek's decision at decision time — squad, projections,
provenance, the rendered report — and later attaches the realized outcome, forming
the season's out-of-sample series entry by entry. Entries are immutable and
checksummed like captured snapshots: a recorded decision can be proven to be the
decision that was made, or it cannot support any claim at all.

A mid-season decision carries a ``transfers`` block (`ledger_transfers_v1`): what
moved, what it cost, the bank and free transfers after, the purchase prices the next
week sells at, and the chip played. The opening entry has none; the state a second
deadline starts from is read out of the opening entry's own record.

New decisions also freeze ``vice_captain_player_id``, ``ordered_bench_player_ids``
and ``completion_policy``. These are additive fields within ``season_ledger_v1``:
existing fields keep their meanings, including the original ``bench_player_ids`` order.
Both completion policies place the bench goalkeeper first, choose the best non-captain
starter as vice, and read no realized outcome. They differ in one thing:
``optimizer_projection_order_v1`` orders the outfield bench by decision-time expected
points alone, and ``optimizer_projection_order_v2`` orders it by expected points given
that the player appears, falling back to v1's rule where the projection states no
appearance chance. **The policy is carried, never checked against a list.** A token this
module does not recognise is written and read back unchanged, because the field records
which rule completed a decision and a ledger that refused an unknown one would turn every
later rule into a migration. Older records without these fields remain valid and are never
backfilled on read: absence means the completion was not recorded, not that the original
bench order was the declared substitution order.
Named-eleven outcome scoring is unchanged; recording completion does not apply autosubs.

An outcome states the ``scoring_basis`` that produced its numbers, because the rule is
not recoverable from the number and two numbers on different rules are different
measurements. ``record_outcome`` writes ``named_eleven_no_autosubs``, which is what the
scorer it calls does. Reading refuses a settled outcome that states no basis rather than
supplying one, except where the decision's own shape entails it: see ``_stated_basis``.

Writes are crash-safe. A decision is assembled in a hidden staging directory next to
its final place, verified against its own manifest, and then moved into place with one
rename, so a gameweek directory either exists complete or does not exist at all; a
process that dies mid-write leaves only a staging directory that readers ignore and
the next writer prunes. A rename the operating system refuses only because it still
holds a handle on what was just written is retried briefly; a rename onto a destination
that already exists is not, because that is a refusal rather than a delay. One writer
per gameweek is enforced with an exclusive lock file, so two ticks cannot race the
immutability check. An outcome is written the same
way (temporary file, rename), and a manifest that was not rewritten after the outcome
landed is completed on the next call rather than refused — after the digests it already
records are verified, because completing it is a rewrite and a rewrite over drifted bytes
would bless them.
"""

import contextlib
import hashlib
import json
import logging
import math
import os
import secrets
import shutil
from collections.abc import Callable, Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Final

import pandas as pd

from squadopt.data.atomic import replace_retrying
from squadopt.data.errors import DataError, RenameRefusedError
from squadopt.data.snapshots import CapturedSnapshot
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, live_event_outcomes, live_payload
from squadopt.evaluation.models import EvaluationValidationError, ScoringBasis
from squadopt.evaluation.scoring import complete_optimization_decision
from squadopt.live.errors import LedgerError as LedgerError
from squadopt.live.free_hit import FREE_HIT_CHIP, free_hit_basis_gameweek
from squadopt.live.recommendation import Projection
from squadopt.live.report import Recommendation
from squadopt.live.transfers import (
    FREE_TRANSFERS_AFTER_OPENING,
    LEDGER_TRANSFERS_CONTRACT_VERSION,
    HeldSquad,
)
from squadopt.optimization import OptimizationResult, SolverStatus

SEASON_LEDGER_CONTRACT_VERSION: Final = "season_ledger_v1"
ROLL_MODE: Final = "roll"
"""The ``metadata.mode`` of an entry that records the squad standing still, not a decision."""
LOGGER = logging.getLogger(__name__)
_DECISION_FILE: Final = "decision.json"
_PROJECTIONS_FILE: Final = "projections.csv"
_REPORT_FILE: Final = "report.txt"
_OUTCOME_FILE: Final = "outcome.json"
_MANIFEST_FILE: Final = "manifest.json"
_STAGING_MARKER: Final = ".staging-"
_LOCK_SUFFIX: Final = ".lock"
STALE_STAGING_SECONDS: Final = 3600.0
"""A staging directory older than this belongs to a writer that died; it is pruned."""
STALE_LOCK_SECONDS: Final = 900.0
"""A lock older than this belongs to a writer that died; it is broken, once."""


def _digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _replace_retrying(source: Path, destination: Path) -> None:
    """The shared retried rename, reported in this module's own error type.

    The retry itself lives in ``data.atomic`` because every writer that publishes bytes
    by renaming a sibling needs the same one, and each copy of it was a chance to get the
    policy wrong. What stays here is the translation: callers of the ledger handle
    ``LedgerError``, so a rename this module could not land is one of those, with the
    shared message about how long it waited kept intact.

    A ``PermissionError`` for a destination that already exists is passed through
    untouched. It is not a held handle, and the ledger's existence check under the lock
    has already answered that question before the rename is reached.
    """

    try:
        replace_retrying(source, destination)
    except RenameRefusedError as error:
        raise LedgerError(str(error)) from error


def _write_atomic(path: Path, data: bytes) -> None:
    """Write bytes to ``path`` through a sibling temporary file and one rename.

    The rename is retried on a refusal for the reason ``_replace_retrying`` gives: it
    never refuses an existing ``path`` — a manifest is deliberately rewritten in place,
    and an outcome's immutability is decided by the caller's check under the lock — so
    a ``PermissionError`` here is a held handle and nothing else.
    """

    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}-{secrets.token_hex(4)}")
    try:
        temporary.write_bytes(data)
        _replace_retrying(temporary, path)
    finally:
        with contextlib.suppress(FileNotFoundError):
            temporary.unlink()


def _staging_directory(directory: Path) -> Path:
    return directory.with_name(
        f".{directory.name}{_STAGING_MARKER}{os.getpid()}-{secrets.token_hex(4)}"
    )


def prune_stale_staging(root: Path, season: str, *, older_than_seconds: float | None = None) -> int:
    """Remove staging directories left by writers that died; return how many."""

    limit = STALE_STAGING_SECONDS if older_than_seconds is None else float(older_than_seconds)
    season_directory = Path(root) / season
    if not season_directory.is_dir():
        return 0
    now = datetime.now(UTC).timestamp()
    removed = 0
    for path in season_directory.iterdir():
        if not path.is_dir() or _STAGING_MARKER not in path.name:
            continue
        if now - path.stat().st_mtime < limit:
            continue
        shutil.rmtree(path, ignore_errors=True)
        removed += 1
    return removed


@contextlib.contextmanager
def _gameweek_lock(directory: Path) -> Iterator[None]:
    """Hold the gameweek's exclusive writer lock (a sibling ``.gwNN.lock`` file).

    A second writer is refused while the lock exists; a lock older than
    ``STALE_LOCK_SECONDS`` is treated as abandoned and broken once.
    """

    directory.parent.mkdir(parents=True, exist_ok=True)
    lock_path = directory.with_name(f".{directory.name}{_LOCK_SUFFIX}")
    for attempt in range(2):
        try:
            handle = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            age = datetime.now(UTC).timestamp() - lock_path.stat().st_mtime
            if attempt == 0 and age >= STALE_LOCK_SECONDS:
                with contextlib.suppress(FileNotFoundError):
                    lock_path.unlink()
                continue
            raise LedgerError(
                f"Another writer holds the ledger lock {lock_path} ({age:.0f} s old); "
                "one process records a gameweek at a time."
            ) from None
        break
    else:  # pragma: no cover - the loop returns or raises
        raise LedgerError(f"Could not acquire the ledger lock {lock_path}.")
    try:
        os.write(
            handle,
            f"{os.getpid()} {datetime.now(UTC).isoformat(timespec='seconds')}\n".encode(),
        )
        os.close(handle)
        yield
    finally:
        with contextlib.suppress(FileNotFoundError):
            lock_path.unlink()


def _entry_directory(root: Path, season: str, gameweek: int) -> Path:
    if not isinstance(season, str) or not season.strip():
        raise LedgerError("season must be a non-empty string.")
    if not isinstance(gameweek, int) or isinstance(gameweek, bool) or gameweek < 1:
        raise LedgerError("gameweek must be a positive integer.")
    return Path(root) / season.strip() / f"gw{gameweek:02d}"


def _write_manifest(
    directory: Path, *, contract_version: str = SEASON_LEDGER_CONTRACT_VERSION
) -> None:
    """Re-derive the manifest from every present, individually immutable file.

    ``contract_version`` names the record kind the manifest belongs to; it defaults to
    the season ledger's, and another immutable record built on these primitives states
    its own, so a reader never has to guess which contract the digests were taken under.
    """

    entries = {
        path.name: _digest(path.read_bytes())
        for path in sorted(directory.iterdir())
        if path.name != _MANIFEST_FILE and path.is_file()
    }
    manifest = {
        "contract_version": contract_version,
        "files": entries,
    }
    _write_atomic(
        directory / _MANIFEST_FILE,
        (json.dumps(manifest, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )


def _manifest_files(directory: Path) -> dict[str, str]:
    manifest_path = directory / _MANIFEST_FILE
    if not manifest_path.is_file():
        return {}
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = manifest.get("files")
    return {str(k): str(v) for k, v in files.items()} if isinstance(files, dict) else {}


def _verify_manifest(directory: Path) -> None:
    manifest_path = directory / _MANIFEST_FILE
    if not manifest_path.is_file():
        raise LedgerError(f"Ledger entry {directory} has no manifest.")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    files = manifest.get("files")
    if not isinstance(files, dict):
        raise LedgerError(f"Ledger manifest in {directory} is malformed.")
    for name, expected in files.items():
        path = directory / str(name)
        if not path.is_file():
            raise LedgerError(f"Ledger entry {directory} is missing recorded file {name!r}.")
        if _digest(path.read_bytes()) != expected:
            raise LedgerError(
                f"Ledger file {name!r} in {directory} does not match its recorded "
                "digest; the entry cannot be trusted."
            )


# --- the immutable-write primitives, public ------------------------------------------
#
# The crash-safe write above is not specific to a gameweek decision: assemble in a hidden
# staging directory, verify against a manifest of per-file digests, land with one rename,
# and hold an exclusive lock while doing it. Any other record that must be provable after
# the fact needs exactly these four steps, and a second hand-rolled copy of them would
# drift from this one — a record written by a slightly different rule is a record that
# cannot be compared with this one. They are exported here so another record reuses the
# implementation rather than the idea. The private names stay because this module's own
# call sites read better with them.
digest_bytes = _digest
"""SHA-256 of some bytes, lowercase hex — the digest every manifest here records."""
write_atomic = _write_atomic
"""Write bytes through a sibling temporary file and one rename."""
staging_directory = _staging_directory
"""The hidden sibling a record is assembled in before it lands."""
write_manifest = _write_manifest
"""Re-derive a directory's manifest from the files now in it."""
verify_manifest = _verify_manifest
"""Refuse a directory whose files no longer match their recorded digests."""
record_lock = _gameweek_lock
"""Hold a directory's exclusive writer lock, so two writers cannot race."""


def record_decision(
    root: Path,
    recommendation: Recommendation,
    projection: Projection,
    *,
    report_text: str,
    metadata: Mapping[str, object] | None = None,
) -> Path:
    """Freeze one gameweek's decision. An existing entry is never overwritten."""

    if not isinstance(recommendation, Recommendation):
        raise LedgerError("recommendation must be a Recommendation.")
    if not isinstance(projection, Projection):
        raise LedgerError("projection must be a Projection.")
    if not isinstance(report_text, str) or not report_text.strip():
        raise LedgerError("report_text must be non-empty text.")
    directory = _entry_directory(root, recommendation.season, recommendation.gameweek)
    if directory.exists():
        raise LedgerError(
            f"Ledger entry {directory} already exists; recorded decisions are "
            "immutable. A revised decision needs an explicit, separate record."
        )

    try:
        frozen = complete_optimization_decision(
            OptimizationResult(
                solver_status=SolverStatus[recommendation.solver_status],
                selected_squad=recommendation.squad,
                starting_xi=recommendation.starting_xi,
                bench=recommendation.bench,
                captain=recommendation.captain,
                total_cost_tenths=recommendation.total_cost_tenths,
                projected_score=recommendation.projected_score,
                objective_value=None,
                diagnostics=recommendation.diagnostics,
            )
        )
    except (EvaluationValidationError, KeyError) as error:
        raise LedgerError(
            f"Cannot freeze the decision's vice-captain and bench order: {error}"
        ) from error

    decision = {
        "contract_version": SEASON_LEDGER_CONTRACT_VERSION,
        "snapshot_id": recommendation.snapshot_id,
        "captured_at_utc": recommendation.captured_at_utc,
        "season": recommendation.season,
        "gameweek": recommendation.gameweek,
        "deadline_utc": recommendation.deadline_utc,
        "model_name": recommendation.model_name,
        "model_version": recommendation.model_version,
        "feature_contract_version": recommendation.feature_contract_version,
        "prediction_fingerprint": recommendation.prediction_fingerprint,
        "report_contract_version": recommendation.contract_version,
        "solver_status": recommendation.solver_status,
        "squad_player_ids": [int(value) for value in recommendation.squad["player_id"]],
        "starting_xi_player_ids": [int(value) for value in recommendation.starting_xi["player_id"]],
        "bench_player_ids": [int(value) for value in recommendation.bench["player_id"]],
        "captain_player_id": int(recommendation.captain["player_id"]),
        "vice_captain_player_id": int(str(frozen.vice_captain_id)),
        "ordered_bench_player_ids": [int(str(player)) for player in frozen.bench],
        "completion_policy": frozen.completion_policy,
        "total_cost_tenths": int(recommendation.total_cost_tenths),
        "projected_score": float(recommendation.projected_score),
        "unavailable_player_count": len(projection.unavailable_players),
        "risk_status": str(recommendation.risk.status.value),
        "metadata": dict(metadata or {}),
    }
    if recommendation.transfers is not None:
        decision["transfers"] = recommendation.transfers.as_record()

    def populate(staging: Path) -> None:
        (staging / _DECISION_FILE).write_text(
            json.dumps(decision, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        projection.table.to_csv(staging / _PROJECTIONS_FILE, index=False, lineterminator="\n")
        (staging / _REPORT_FILE).write_text(report_text, encoding="utf-8")

    _land_entry(root, recommendation.season, directory, populate)
    LOGGER.info(
        "ledger.decision.recorded",
        extra={
            "fields": {
                "season": recommendation.season,
                "gameweek": recommendation.gameweek,
                "snapshot_id": recommendation.snapshot_id,
                "directory": directory.as_posix(),
            }
        },
    )
    return directory


def _land_entry(root: Path, season: str, directory: Path, populate: Callable[[Path], None]) -> None:
    """Assemble a new entry in staging and land it with one rename, under the gameweek lock."""

    with _gameweek_lock(directory):
        # Re-check under the lock: another writer may have landed the entry between
        # the caller's check and the lock.
        if directory.exists():
            raise LedgerError(
                f"Ledger entry {directory} already exists; recorded decisions are "
                "immutable. A revised decision needs an explicit, separate record."
            )
        prune_stale_staging(root, season)
        staging = _staging_directory(directory)
        staging.mkdir(parents=True)
        try:
            populate(staging)
            _write_manifest(staging)
            _verify_manifest(staging)
            # One rename: the entry exists complete or not at all. The check above
            # under the lock has already refused an existing entry, so a refusal here
            # is the operating system still holding what was just written.
            _replace_retrying(staging, directory)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise


@dataclass(frozen=True, slots=True)
class _Carried:
    """What the week before hands to a roll: the state the game carried unchanged."""

    squad: tuple[int, ...]
    purchase_prices: dict[int, int]
    bank_tenths: int
    free_transfers: int
    chips_available: list[str] | None


def _player_id_list(
    decision: Mapping[str, object], key: str, *, required: bool = True
) -> list[int] | None:
    """A player-id list as the entry recorded it; ``None`` when an optional one is absent.

    An entry recorded before the bench order and the vice-captain were frozen has neither.
    A roll carries that absence forward as it is: inventing an order the entry never held
    would be a claim, and absent is not zero.
    """

    value = decision.get(key)
    if value is None:
        if required:
            raise LedgerError(f"Ledger decision {key} is missing.")
        return None
    if not isinstance(value, list):
        raise LedgerError(f"Ledger decision {key} is not a list.")
    return [int(str(item)) for item in value]


def _carried_state(previous: "LedgerEntry", *, budget_tenths: int) -> _Carried:
    decision = previous.decision
    squad_ids = decision.get("squad_player_ids")
    if not isinstance(squad_ids, list) or not squad_ids:
        raise LedgerError(
            f"Ledger entry for {previous.season} GW{previous.gameweek} records no squad to carry."
        )
    squad = tuple(int(value) for value in squad_ids)
    block = decision.get("transfers")
    if isinstance(block, Mapping):
        if block.get("chip") == FREE_HIT_CHIP:
            raise LedgerError(
                f"{previous.season} GW{previous.gameweek} played a free hit: the squad it "
                "recorded was temporary and the one the game restored is the entry before "
                "it. A roll carries only what the week before held; decide the next week "
                "from its capture instead."
            )
        purchase = {
            int(player): int(price) for player, price in dict(block["purchase_prices"]).items()
        }
        bank = int(str(block["bank_after_tenths"]))
        free = int(str(block["free_transfers_after"]))
        listed = block.get("chips_available")
        chips = [str(chip) for chip in listed] if isinstance(listed, list) else None
    else:
        purchase = _purchase_prices_from_entry(previous, squad)
        bank = int(budget_tenths) - int(str(decision["total_cost_tenths"]))
        free = FREE_TRANSFERS_AFTER_OPENING
        chips = None
    return _Carried(squad, purchase, bank, free, chips)


def record_roll(
    root: Path,
    season: str,
    gameweek: int,
    *,
    max_free_transfers: int,
    budget_tenths: int,
    recorded_at_utc: str,
    reason: str,
    deadline_utc: str | None = None,
    rules_snapshot_id: str | None = None,
    metadata: Mapping[str, object] | None = None,
) -> Path:
    """Record that the squad stood still through one deadline. An entry is never overwritten.

    A roll is not a decision. It states what the game did with a week nothing was decided
    for: the squad, the picks and the purchase prices carried over unchanged, the bank
    stayed where it was, and one free transfer accrued up to the season's cap. It names
    no capture, no projection and no solver, because there were none, so it claims
    nothing about points. The readers that publish decisions do not see it
    (``load_ledger``); the chain the next decision starts from does
    (``held_squad_from_ledger``).

    It is recorded only from the entry of the week before, so the ledger stays a chain:
    a roll for GW3 needs GW2 recorded, as a decision or as a roll of its own.
    """

    if not isinstance(reason, str) or not reason.strip():
        raise LedgerError("reason must be non-empty text: say why the week was not decided.")
    if not isinstance(recorded_at_utc, str) or not recorded_at_utc.strip():
        raise LedgerError("recorded_at_utc must be non-empty text.")
    if (
        isinstance(max_free_transfers, bool)
        or not isinstance(max_free_transfers, int)
        or max_free_transfers < 1
    ):
        raise LedgerError("max_free_transfers must be a positive integer.")
    if isinstance(budget_tenths, bool) or not isinstance(budget_tenths, int) or budget_tenths < 1:
        raise LedgerError("budget_tenths must be a positive integer.")
    directory = _entry_directory(root, season, gameweek)
    if directory.exists():
        raise LedgerError(
            f"Ledger entry {directory} already exists; recorded decisions are "
            "immutable. A revised decision needs an explicit, separate record."
        )
    if gameweek < 2:
        raise LedgerError(
            "The opening gameweek is decided from its capture, never rolled: there is no "
            "earlier squad to carry."
        )
    if not _entry_directory(root, season, gameweek - 1).is_dir():
        raise LedgerError(
            f"No entry for {season} GW{gameweek - 1}; a roll carries the squad the ledger "
            f"holds for the week before, so record GW{gameweek - 1} first (a decision, or a "
            "roll of its own)."
        )
    previous = load_entry(root, season, gameweek - 1)
    carried = _carried_state(previous, budget_tenths=budget_tenths)
    # The game's own accrual, the same arithmetic ``live.banking`` applies to members:
    # one more free transfer per week not played on a transfer chip, up to the cap.
    free_after = min(int(max_free_transfers), carried.free_transfers + 1)

    # No sell prices and no squad sell value: both need the prices of the week, and no
    # capture of that week exists. Absent is not zero, so the keys are absent.
    transfers: dict[str, object] = {
        "contract_version": LEDGER_TRANSFERS_CONTRACT_VERSION,
        "previous_gameweek": gameweek - 1,
        "transfers_in": [],
        "transfers_out": [],
        "transfer_count": 0,
        "paid_transfer_count": 0,
        "transfer_hit_points": 0.0,
        "free_transfers_before": carried.free_transfers,
        "free_transfers_after": free_after,
        "bank_before_tenths": carried.bank_tenths,
        "bank_after_tenths": carried.bank_tenths,
        "purchase_prices": {
            str(player): int(price) for player, price in sorted(carried.purchase_prices.items())
        },
        "chip": None,
        "max_free_transfers": int(max_free_transfers),
    }
    if carried.chips_available is not None:
        transfers["chips_available"] = list(carried.chips_available)
    before = previous.decision
    decision: dict[str, object] = {
        "contract_version": SEASON_LEDGER_CONTRACT_VERSION,
        "snapshot_id": None,
        "captured_at_utc": None,
        "season": season,
        "gameweek": gameweek,
        "deadline_utc": deadline_utc,
        "model_name": None,
        "model_version": None,
        "feature_contract_version": None,
        "prediction_fingerprint": None,
        "report_contract_version": None,
        "solver_status": None,
        # The game carries last week's picks forward untouched, captaincy included.
        "squad_player_ids": list(carried.squad),
        "starting_xi_player_ids": _player_id_list(before, "starting_xi_player_ids"),
        "bench_player_ids": _player_id_list(before, "bench_player_ids"),
        "captain_player_id": before.get("captain_player_id"),
        "vice_captain_player_id": before.get("vice_captain_player_id"),
        "ordered_bench_player_ids": _player_id_list(
            before, "ordered_bench_player_ids", required=False
        ),
        "completion_policy": before.get("completion_policy"),
        "total_cost_tenths": int(str(before["total_cost_tenths"])),
        "projected_score": None,
        "unavailable_player_count": None,
        "risk_status": None,
        "metadata": {
            **dict(metadata or {}),
            "mode": ROLL_MODE,
            "rolled_from_gameweek": gameweek - 1,
            "recorded_at_utc": recorded_at_utc.strip(),
            "reason": reason.strip(),
            "rules_snapshot_id": rules_snapshot_id,
        },
        "transfers": transfers,
    }
    report = "\n".join(
        [
            f"Season {season}, gameweek {gameweek}: no-transfer roll.",
            f"Recorded {recorded_at_utc.strip()}. Reason: {reason.strip()}",
            f"Deadline: {deadline_utc or 'not stated'}.",
            f"Squad carried unchanged from GW{gameweek - 1}: {len(carried.squad)} players, "
            f"purchase value {sum(carried.purchase_prices.values())} tenths.",
            f"Free transfers: {carried.free_transfers} before, {free_after} after "
            f"(cap {max_free_transfers}). Bank: {carried.bank_tenths} tenths, unchanged.",
            "No capture, no projection, no solver: this entry claims nothing about points.",
            "",
        ]
    )

    def populate(staging: Path) -> None:
        (staging / _DECISION_FILE).write_text(
            json.dumps(decision, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        (staging / _REPORT_FILE).write_text(report, encoding="utf-8")

    _land_entry(root, season, directory, populate)
    LOGGER.info(
        "ledger.roll.recorded",
        extra={
            "fields": {
                "season": season,
                "gameweek": gameweek,
                "rolled_from_gameweek": gameweek - 1,
                "directory": directory.as_posix(),
            }
        },
    )
    return directory


def extract_event_points(snapshot: CapturedSnapshot, *, gameweek: int) -> dict[int, float]:
    """Read realized points for one finished and checked gameweek from a later capture.

    The points come from the capture's own live document for the named week
    (``event-gwNN-live.json``), never from the bootstrap's ``event_points``. Those describe
    whatever event the capture is on, so a capture taken after the next deadline would file
    the following week's points under this week's name, and an outcome can never be
    corrected. A capture that holds no live document for the week is refused; nothing else
    is read in its place.

    The bootstrap still decides whether the week may be read at all: it must be
    ``finished`` **and** ``data_checked`` there, the two flags ``scored_gameweeks`` requires
    of every other settled reader. Bonus lands after the last kick-off, so a total read
    before the check is short by different amounts for different players. The live
    document is read by :func:`live_event_outcomes`, the same reader those records use, and
    player identity is the persistent ``code``, matching the live projection.
    """

    snapshot_id = snapshot.metadata.snapshot_id
    payload = snapshot.payloads.get(BOOTSTRAP_PAYLOAD)
    if payload is None:
        raise LedgerError(f"Snapshot {snapshot_id!r} carries no bootstrap payload.")
    document = json.loads(payload.decode("utf-8"))
    events = document.get("events")
    if not isinstance(events, list):
        raise LedgerError("Bootstrap payload has no events list.")
    event = next(
        (entry for entry in events if isinstance(entry, dict) and entry.get("id") == gameweek),
        None,
    )
    if event is None:
        raise LedgerError(f"The capture publishes no gameweek {gameweek}.")
    if event.get("finished") is not True:
        raise LedgerError(
            f"Gameweek {gameweek} is not finished in this capture; realized points "
            "read now would describe matches still being played."
        )
    checked = event.get("data_checked")
    if checked is not True:
        state = (
            "not yet checked"
            if checked is False
            else f"its data_checked flag is missing or not a boolean ({checked!r})"
        )
        raise LedgerError(
            f"Gameweek {gameweek} is finished but {state} in snapshot {snapshot_id!r}; "
            "bonus may still be landing, so its points are not final. Settle from a capture "
            "taken after the week is checked."
        )
    name = live_payload(gameweek)
    live = snapshot.payloads.get(name)
    if live is None:
        raise LedgerError(
            f"Snapshot {snapshot_id!r} holds no {name}, the live record of gameweek "
            f"{gameweek}. The bootstrap's event_points describe the capture's current event, "
            f"which need not be gameweek {gameweek}, so they are not read instead. Settle "
            "from a capture that holds that week's live document."
        )
    try:
        outcomes = live_event_outcomes(live, payload, gameweek=gameweek)
    except DataError as error:
        raise LedgerError(
            f"Snapshot {snapshot_id!r}: {name} cannot be read as gameweek {gameweek}'s "
            f"outcome. {error}"
        ) from error
    return {
        int(player): float(value)
        for player, value in zip(
            outcomes["player_id"].tolist(), outcomes["total_points"].tolist(), strict=True
        )
    }


def score_named_eleven(decision: Mapping[str, Any], event_points: Mapping[int, float]) -> float:
    """Score the eleven a decision named, under its chip, from one set of player points.

    Starters plus the captain again; a bench boost counts the bench, a triple captain
    counts the captain once more. Automatic substitutions are not applied: this scores the
    eleven that were **named**, which is what the projection was for.

    Public, and separate from ``record_outcome``, because two callers need the identical
    rule. One is the settled outcome below. The other is any provisional score built while
    a gameweek is still being played, which exists precisely to be compared against the
    projection and later against the settled figure -- a second copy of this arithmetic
    would drift, and the comparison is the whole point of having both numbers.

    Scoring is all this does. It reads no ledger and writes nothing, so a provisional
    caller cannot reach the immutable outcome path through it.
    """

    starters = [int(value) for value in decision["starting_xi_player_ids"]]
    bench = [int(value) for value in decision["bench_player_ids"]]
    captain = int(decision["captain_player_id"])
    selected = [int(value) for value in decision["squad_player_ids"]]
    missing = [player for player in {*selected, captain} if player not in event_points]
    if missing:
        raise LedgerError(
            f"Realized points do not cover every selected player; missing {sorted(missing)[:10]!r}."
        )
    chip = _decision_chip(decision)
    score = sum(float(event_points[player]) for player in starters) + float(event_points[captain])
    if chip == "bboost":
        score += sum(float(event_points[player]) for player in bench)
    elif chip == "3xc":
        score += float(event_points[captain])
    return score


def _decision_chip(decision: Mapping[str, Any]) -> object | None:
    transfers = decision.get("transfers")
    return transfers.get("chip") if isinstance(transfers, dict) else None


def _decision_hit_points(decision: Mapping[str, Any]) -> float:
    transfers = decision.get("transfers")
    return float(transfers.get("transfer_hit_points", 0.0)) if isinstance(transfers, dict) else 0.0


def record_outcome(
    root: Path,
    season: str,
    gameweek: int,
    event_points: Mapping[int, float],
    *,
    source_snapshot_id: str,
) -> Path:
    """Attach the realized outcome to an already-frozen decision, exactly once."""

    directory = _entry_directory(root, season, gameweek)
    decision_path = directory / _DECISION_FILE
    if not decision_path.is_file():
        raise LedgerError(
            f"No recorded decision for {season} GW{gameweek}; an outcome without a "
            "frozen decision is not evidence."
        )
    outcome_path = directory / _OUTCOME_FILE
    if outcome_path.exists():
        if _OUTCOME_FILE not in _manifest_files(directory):
            # A writer landed the outcome but died before rewriting the manifest:
            # finish its work instead of refusing forever. Verify first — rewriting the
            # manifest re-derives every digest from the bytes now on disk, so completing
            # it unverified would bless any drift that happened while the entry sat in
            # this state. The files the manifest already records must still match it;
            # outcome.json is not among them, which is what is being completed.
            _verify_manifest(directory)
            with _gameweek_lock(directory):
                _write_manifest(directory)
            return outcome_path
        raise LedgerError(
            f"Outcome for {season} GW{gameweek} is already recorded; outcomes are immutable."
        )
    if not isinstance(source_snapshot_id, str) or not source_snapshot_id.strip():
        raise LedgerError("source_snapshot_id must be non-empty text.")
    _verify_manifest(directory)
    decision = json.loads(decision_path.read_text(encoding="utf-8"))
    if is_roll(decision):
        raise LedgerError(
            f"{season} GW{gameweek} is a roll: the squad stood still and nothing was "
            "projected, so there is no decision to settle. Outcomes attach to decisions."
        )
    selected = [int(value) for value in decision["squad_player_ids"]]
    chip = _decision_chip(decision)
    hit_points = _decision_hit_points(decision)
    realized_xi = score_named_eleven(decision, event_points)
    outcome = {
        "contract_version": SEASON_LEDGER_CONTRACT_VERSION,
        "season": season,
        "gameweek": gameweek,
        "source_snapshot_id": source_snapshot_id.strip(),
        "realized_points_by_player": {
            str(player): float(event_points[player]) for player in sorted(selected)
        },
        "realized_xi_score": realized_xi,
        "transfer_hit_points": hit_points,
        "realized_net_score": realized_xi - hit_points,
        # What produced the two numbers above, recorded beside them because the rule is
        # not recoverable from the numbers themselves. This is a statement of fact about
        # the line that computed them -- ``score_named_eleven`` -- and not a default: a
        # reader is never asked to supply it, and a record that does not carry it is
        # refused by ``load_entry`` rather than assigned one.
        "scoring_basis": str(ScoringBasis.NAMED_ELEVEN_NO_AUTOSUBS),
        "chip": chip,
        "projected_score": float(decision["projected_score"]),
        "projection_error": realized_xi - float(decision["projected_score"]),
    }
    with _gameweek_lock(directory):
        if outcome_path.exists():
            raise LedgerError(
                f"Outcome for {season} GW{gameweek} is already recorded; outcomes are immutable."
            )
        _write_atomic(
            outcome_path,
            (json.dumps(outcome, indent=2, sort_keys=True) + "\n").encode("utf-8"),
        )
        _write_manifest(directory)
    LOGGER.info(
        "ledger.outcome.recorded",
        extra={
            "fields": {
                "season": season,
                "gameweek": gameweek,
                "source_snapshot_id": source_snapshot_id,
                "realized_net_score": realized_xi - hit_points,
            }
        },
    )
    return outcome_path


@dataclass(frozen=True, slots=True)
class LedgerEntry:
    """One verified gameweek entry: the frozen decision and its outcome, if any."""

    season: str
    gameweek: int
    decision: Mapping[str, object]
    outcome: Mapping[str, object] | None
    directory: Path


BASIS_ENTAILED_BY_DECISION: Final = "entailed_by_legacy_decision"
"""``basis_source`` for a basis read off a decision's shape rather than recorded with it."""


def _stated_basis(
    decision: Mapping[str, Any],
    outcome: Mapping[str, Any] | None,
    season: str,
    gameweek: int,
) -> Mapping[str, Any] | None:
    """Refuse an outcome that claims a score without saying what produced it.

    A settled outcome carries a number, and the rule that produced that number cannot be
    recovered from the number. So it has to be written down. An outcome that states no
    basis is refused rather than assigned one, because a default is a claim nobody made.

    One exception, and it is entailed rather than assumed. The official scorer needs a
    frozen bench order and a vice-captain; handed a decision with neither it has nothing
    to complete the eleven with and refuses outright. So for such a decision the named
    eleven is the only rule that could have produced any number at all, and the basis is
    read off the decision's own shape. That reading is stamped with ``basis_source`` so
    the record says the basis was derived and not recorded. A basis-less outcome beside a
    decision that DID freeze a bench order is genuinely ambiguous: either scorer could
    have run, so nothing is entailed and the entry is refused.

    Nothing is written. The stamp exists in memory, on the loaded entry.
    """

    if outcome is None:
        return None
    score = outcome.get("realized_net_score")
    if isinstance(score, bool) or not isinstance(score, int | float):
        # No settled number, so no claim, so no basis is owed.
        return outcome
    if outcome.get("scoring_basis") is not None:
        return outcome
    if (
        decision.get("ordered_bench_player_ids") is None
        and decision.get("vice_captain_player_id") is None
    ):
        return {
            **outcome,
            "scoring_basis": str(ScoringBasis.NAMED_ELEVEN_NO_AUTOSUBS),
            "basis_source": BASIS_ENTAILED_BY_DECISION,
        }
    raise LedgerError(
        f"Outcome for {season} GW{gameweek} records a score of {score} without a "
        "scoring_basis, and its decision froze a bench order or vice-captain, so either "
        "scorer could have produced it. A number whose basis is unknown cannot be "
        "compared with one whose basis is known; record the basis rather than assume it."
    )


def load_entry(root: Path, season: str, gameweek: int) -> LedgerEntry:
    """Load one entry, refusing any file that fails its recorded checksum.

    Also refuses an outcome that states a score without stating the basis that produced
    it; see ``_stated_basis``.
    """

    directory = _entry_directory(root, season, gameweek)
    if not directory.is_dir():
        raise LedgerError(f"No ledger entry at {directory}.")
    _verify_manifest(directory)
    decision = json.loads((directory / _DECISION_FILE).read_text(encoding="utf-8"))
    outcome_path = directory / _OUTCOME_FILE
    outcome = (
        json.loads(outcome_path.read_text(encoding="utf-8")) if outcome_path.is_file() else None
    )
    outcome = _stated_basis(decision, outcome, season, gameweek)
    return LedgerEntry(
        season=season,
        gameweek=gameweek,
        decision=decision,
        outcome=outcome,
        directory=directory,
    )


def load_ledger(root: Path, season: str, *, include_rolls: bool = False) -> tuple[LedgerEntry, ...]:
    """Load every recorded decision of one season in chronological order.

    A roll (``record_roll``) is a record of the squad standing still, not a decision: it
    names no capture and no projection, so every reader that publishes or scores
    decisions would have nothing to publish or score. Those readers keep seeing what
    they saw before rolls existed. The chain the next decision starts from and the
    committed season summary ask for rolls explicitly.
    """

    season_directory = Path(root) / season
    if not season_directory.is_dir():
        return ()
    # Staging directories and lock files are hidden siblings (".gwNN.staging-…",
    # ".gwNN.lock"); only landed entries are named "gwNN".
    gameweeks = sorted(
        int(path.name[2:])
        for path in season_directory.iterdir()
        if path.is_dir() and path.name.startswith("gw") and path.name[2:].isdigit()
    )
    entries = tuple(load_entry(root, season, gameweek) for gameweek in gameweeks)
    if include_rolls:
        return entries
    return tuple(entry for entry in entries if not is_roll(entry.decision))


def _purchase_prices_from_entry(entry: LedgerEntry, squad: tuple[int, ...]) -> dict[int, int]:
    """Purchase prices of a squad recorded before the transfer block existed.

    The opening entry records the roster it projected, price included, so the price a
    player was bought at is the price the entry shows for that player. Read from the
    verified projections file rather than assumed.
    """

    projections = pd.read_csv(entry.directory / _PROJECTIONS_FILE)
    prices = {
        int(player): int(price)
        for player, price in zip(
            projections["player_id"].tolist(), projections["price_tenths"].tolist(), strict=True
        )
    }
    missing = sorted(set(squad) - set(prices))
    if missing:
        raise LedgerError(
            f"Ledger entry for {entry.season} GW{entry.gameweek} records no price for held "
            f"players {missing[:5]!r}."
        )
    return {player: prices[player] for player in squad}


def held_squad_from_ledger(
    root: Path,
    season: str,
    *,
    before_gameweek: int,
    budget_tenths: int,
) -> HeldSquad:
    """Read the state a deadline starts from: the decision recorded for the week before.

    The ledger must hold a decision for exactly the previous gameweek: a decision made
    for a later week from an older squad would ignore whatever the game did with the
    weeks between (free transfers accrue, prices move), and pretending otherwise would
    put a squad the ledger never held into the record. Recording a no-transfer roll for
    a skipped week is the honest way to catch up.
    """

    entries = load_ledger(root, season, include_rolls=True)
    if not entries:
        raise LedgerError(
            f"No decisions recorded for {season}; a mid-season deadline needs the held "
            "squad from the ledger."
        )
    previous = before_gameweek - 1
    matched = [entry for entry in entries if entry.gameweek == previous]
    if not matched:
        held = sorted(entry.gameweek for entry in entries)
        raise LedgerError(
            f"No decision recorded for {season} GW{previous}; the ledger holds "
            f"{held!r}. Record GW{previous} (a no-transfer roll if nothing was done) "
            f"before deciding GW{before_gameweek}."
        )
    entry = matched[0]
    decision = entry.decision
    block = decision.get("transfers")
    free_hit_played = isinstance(block, Mapping) and block.get("chip") == FREE_HIT_CHIP
    if free_hit_played:
        # A free hit's squad was temporary: the squad, bank, and purchase prices held
        # are the ones the free-hit week started from — the entry before it, and the one
        # before that if it was a free-hit week too — while the free transfers carried
        # are the free-hit week's own. The walk back is ``live.free_hit``'s, the same one
        # the member path uses, so the two cannot answer differently.
        assert isinstance(block, Mapping)
        free = int(str(block["free_transfers_after"]))
        by_gameweek: dict[int, LedgerEntry] = {}
        for candidate in entries:
            by_gameweek.setdefault(candidate.gameweek, candidate)

        def was_free_hit(week: int) -> bool:
            recorded = by_gameweek.get(week)
            if recorded is None:
                raise LedgerError(
                    f"GW{previous} was a free-hit week; the squad it started from is GW"
                    f"{week}'s, which the ledger does not hold."
                )
            earlier_block = recorded.decision.get("transfers")
            return isinstance(earlier_block, Mapping) and earlier_block.get("chip") == FREE_HIT_CHIP

        basis = free_hit_basis_gameweek(previous, was_free_hit=was_free_hit)
        if basis is None:
            raise LedgerError(
                f"GW{previous} was a free-hit week with no earlier gameweek to fall back "
                "on; the squad it started from cannot be resolved."
            )
        entry = by_gameweek[basis]
        decision = entry.decision
        block = decision.get("transfers")
    squad_ids = decision["squad_player_ids"]
    if not isinstance(squad_ids, list):
        raise LedgerError("Ledger decision squad_player_ids is not a list.")
    squad = tuple(int(value) for value in squad_ids)
    if isinstance(block, Mapping):
        purchase = {
            int(player): int(price) for player, price in dict(block["purchase_prices"]).items()
        }
        bank = int(str(block["bank_after_tenths"]))
        if not free_hit_played:
            free = int(str(block["free_transfers_after"]))
    else:
        purchase = _purchase_prices_from_entry(entry, squad)
        bank = int(budget_tenths) - int(str(decision["total_cost_tenths"]))
        if not free_hit_played:
            free = FREE_TRANSFERS_AFTER_OPENING
    chips: dict[str, list[int]] = {}
    for earlier in entries:
        if earlier.gameweek > previous:
            continue
        earlier_block = earlier.decision.get("transfers")
        chip = earlier_block.get("chip") if isinstance(earlier_block, Mapping) else None
        if chip is not None:
            chips.setdefault(str(chip), []).append(int(earlier.gameweek))
    return HeldSquad(
        season=season,
        decided_gameweek=previous,
        squad_player_ids=squad,
        purchase_prices=purchase,
        bank_tenths=bank,
        free_transfers=free,
        chips_used={name: tuple(weeks) for name, weeks in chips.items()},
    )


def decision_mode(decision: Mapping[str, object]) -> str | None:
    """The mode a decision was made in: ``live`` before the deadline, ``replay`` from a
    pre-deadline capture afterwards, ``roll`` when the squad stood still and nothing was
    decided; ``None`` on an entry recorded before it was stamped."""

    metadata = decision.get("metadata")
    mode = metadata.get("mode") if isinstance(metadata, Mapping) else None
    return None if mode is None else str(mode)


def is_roll(decision: Mapping[str, object]) -> bool:
    """Whether an entry records the squad standing still rather than a decision."""

    return decision_mode(decision) == ROLL_MODE


def ledger_summary(root: Path, season: str) -> pd.DataFrame:
    """Return one row per recorded gameweek: mode, projected, realized, hits, and the gap."""

    rows: list[dict[str, object]] = []
    for entry in load_ledger(root, season, include_rolls=True):
        realized = float(str(entry.outcome["realized_xi_score"])) if entry.outcome else None
        stated = entry.decision.get("projected_score")
        projected = None if stated is None else float(str(stated))
        transfers = entry.decision.get("transfers")
        block = transfers if isinstance(transfers, Mapping) else {}
        hits = float(str(block.get("transfer_hit_points", 0.0)))
        rows.append(
            {
                "gameweek": entry.gameweek,
                "snapshot_id": entry.decision.get("snapshot_id"),
                "mode": decision_mode(entry.decision),
                "solver_status": entry.decision.get("solver_status"),
                "projected_score": projected,
                "realized_score": realized,
                "projection_error": (
                    (realized - projected)
                    if realized is not None and projected is not None
                    else None
                ),
                "unavailable_players": entry.decision.get("unavailable_player_count"),
                "transfers": int(str(block.get("transfer_count", 0))),
                "transfer_hit_points": hits,
                "realized_net_score": (realized - hits) if realized is not None else None,
                "chip": block.get("chip"),
                "settled": entry.outcome is not None,
            }
        )
    return pd.DataFrame(
        rows,
        columns=[
            "gameweek",
            "snapshot_id",
            "mode",
            "solver_status",
            "projected_score",
            "realized_score",
            "projection_error",
            "unavailable_players",
            "transfers",
            "transfer_hit_points",
            "realized_net_score",
            "chip",
            "settled",
        ],
    )


def _absent(value: object) -> bool:
    """``None`` as recorded, or the NaN pandas turns it into inside a numeric column."""

    return value is None or (isinstance(value, float) and math.isnan(value))


def summary_markdown(root: Path, season: str) -> str:
    """Render the committed season summary; raw entries stay local."""

    table = ledger_summary(root, season)
    lines = [
        f"# Season Ledger {season}",
        "",
        f"- Contract: `{SEASON_LEDGER_CONTRACT_VERSION}`",
        "- One row per recorded decision; raw entries (decision, projections, report, "
        "outcome) live locally under `data/ledger/` with per-file checksums.",
        "- Mode: `live` was decided before its deadline, from a capture that run took; "
        "`replay` was recorded after that deadline, or from a capture the run did not "
        "take but named; `roll` records that the squad stood still through a deadline "
        "nothing was decided for, with no capture, no projection and no solver, the "
        "free transfer carried by the game's own accrual.",
        "",
        "| GW | Snapshot | Mode | Solver | Projected | Realized | Error | Transfers | Hits "
        "| Chip | Net | Unavailable |",
        "| ---: | --- | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: |",
    ]
    for record in table.to_dict(orient="records"):
        realized_value = record["realized_score"]
        error_value = record["projection_error"]
        net_value = record["realized_net_score"]
        projected_value = record["projected_score"]
        unavailable_value = record["unavailable_players"]
        realized = "-" if _absent(realized_value) else f"{float(str(realized_value)):.0f}"
        error = "-" if _absent(error_value) else f"{float(str(error_value)):+.1f}"
        net = "-" if _absent(net_value) else f"{float(str(net_value)):.0f}"
        projected = "-" if _absent(projected_value) else f"{float(str(projected_value)):.1f}"
        unavailable = "-" if _absent(unavailable_value) else f"{int(float(str(unavailable_value)))}"
        snapshot = "-" if _absent(record["snapshot_id"]) else f"`{record['snapshot_id']}`"
        solver = "-" if _absent(record["solver_status"]) else str(record["solver_status"])
        chip = record["chip"] if not _absent(record["chip"]) else "-"
        mode = record["mode"] if not _absent(record["mode"]) else "-"
        lines.append(
            f"| {record['gameweek']} | {snapshot} | {mode} | {solver} "
            f"| {projected} | {realized} | {error} "
            f"| {record['transfers']} | {float(str(record['transfer_hit_points'])):.0f} "
            f"| {chip} | {net} | {unavailable} |"
        )
    settled = table.loc[table["settled"]]
    if not settled.empty:
        lines += [
            "",
            f"Settled gameweeks: {len(settled)}; mean realized "
            f"{settled['realized_score'].astype(float).mean():.1f}; total hits "
            f"{settled['transfer_hit_points'].astype(float).sum():.0f}; net "
            f"{settled['realized_net_score'].astype(float).sum():.0f}; mean projection "
            f"error {settled['projection_error'].astype(float).mean():+.1f}.",
        ]
    lines += [
        "",
        "The ledger records; it never promotes. Every live decision uses the operational control.",
    ]
    return "\n".join(lines) + "\n"
