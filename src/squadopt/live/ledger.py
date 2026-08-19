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

Writes are crash-safe. A decision is assembled in a hidden staging directory next to
its final place, verified against its own manifest, and then moved into place with one
rename, so a gameweek directory either exists complete or does not exist at all; a
process that dies mid-write leaves only a staging directory that readers ignore and
the next writer prunes. One writer per gameweek is enforced with an exclusive lock
file, so two ticks cannot race the immutability check. An outcome is written the same
way (temporary file, rename), and a manifest that was not rewritten after the outcome
landed is completed on the next call rather than refused.
"""

import contextlib
import hashlib
import json
import logging
import math
import os
import secrets
import shutil
from collections.abc import Iterator, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pandas as pd

from squadopt.data.snapshots import CapturedSnapshot
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD
from squadopt.live.errors import LedgerError as LedgerError
from squadopt.live.recommendation import Projection
from squadopt.live.report import Recommendation
from squadopt.live.transfers import FREE_TRANSFERS_AFTER_OPENING, HeldSquad

SEASON_LEDGER_CONTRACT_VERSION: Final = "season_ledger_v1"
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


def _write_atomic(path: Path, data: bytes) -> None:
    """Write bytes to ``path`` through a sibling temporary file and one rename."""

    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}-{secrets.token_hex(4)}")
    try:
        temporary.write_bytes(data)
        os.replace(temporary, path)
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


def _write_manifest(directory: Path) -> None:
    """Re-derive the manifest from every present, individually immutable file."""

    entries = {
        path.name: _digest(path.read_bytes())
        for path in sorted(directory.iterdir())
        if path.name != _MANIFEST_FILE and path.is_file()
    }
    manifest = {
        "contract_version": SEASON_LEDGER_CONTRACT_VERSION,
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
        "total_cost_tenths": int(recommendation.total_cost_tenths),
        "projected_score": float(recommendation.projected_score),
        "unavailable_player_count": len(projection.unavailable_players),
        "risk_status": str(recommendation.risk.status.value),
        "metadata": dict(metadata or {}),
    }
    if recommendation.transfers is not None:
        decision["transfers"] = recommendation.transfers.as_record()
    with _gameweek_lock(directory):
        # Re-check under the lock: another writer may have landed the entry between
        # the check above and the lock.
        if directory.exists():
            raise LedgerError(
                f"Ledger entry {directory} already exists; recorded decisions are "
                "immutable. A revised decision needs an explicit, separate record."
            )
        prune_stale_staging(root, recommendation.season)
        staging = _staging_directory(directory)
        staging.mkdir(parents=True)
        try:
            (staging / _DECISION_FILE).write_text(
                json.dumps(decision, indent=2, sort_keys=True) + "\n", encoding="utf-8"
            )
            projection.table.to_csv(staging / _PROJECTIONS_FILE, index=False, lineterminator="\n")
            (staging / _REPORT_FILE).write_text(report_text, encoding="utf-8")
            _write_manifest(staging)
            _verify_manifest(staging)
            # One rename: the entry exists complete or not at all.
            os.replace(staging, directory)
        except BaseException:
            shutil.rmtree(staging, ignore_errors=True)
            raise
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


def extract_event_points(snapshot: CapturedSnapshot, *, gameweek: int) -> dict[int, float]:
    """Read realized points for one finished gameweek from a later capture.

    The raw bootstrap payload is read directly: `event_points` describes the
    capture's current event, so the named gameweek must be marked finished in the
    same capture — otherwise these numbers describe a match still being played.
    Player identity uses the persistent `code`, matching the live projection.
    """

    payload = snapshot.payloads.get(BOOTSTRAP_PAYLOAD)
    if payload is None:
        raise LedgerError(
            f"Snapshot {snapshot.metadata.snapshot_id!r} carries no bootstrap payload."
        )
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
    elements = document.get("elements")
    if not isinstance(elements, list) or not elements:
        raise LedgerError("Bootstrap payload has no elements list.")
    points: dict[int, float] = {}
    for element in elements:
        if not isinstance(element, dict) or "code" not in element:
            raise LedgerError("Bootstrap elements must carry persistent player codes.")
        if "event_points" not in element:
            raise LedgerError(
                "Bootstrap elements carry no event_points; realized outcomes cannot "
                "be read from this capture."
            )
        value = float(element["event_points"])
        if not math.isfinite(value):
            raise LedgerError("event_points must be finite.")
        points[int(element["code"])] = value
    return points


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
            # finish its work instead of refusing forever.
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
    starters = [int(value) for value in decision["starting_xi_player_ids"]]
    bench = [int(value) for value in decision["bench_player_ids"]]
    captain = int(decision["captain_player_id"])
    selected = [int(value) for value in decision["squad_player_ids"]]
    missing = [player for player in {*selected, captain} if player not in event_points]
    if missing:
        raise LedgerError(
            f"Realized points do not cover every selected player; missing {sorted(missing)[:10]!r}."
        )
    transfers = decision.get("transfers")
    chip = transfers.get("chip") if isinstance(transfers, dict) else None
    hit_points = (
        float(transfers.get("transfer_hit_points", 0.0)) if isinstance(transfers, dict) else 0.0
    )
    # Starters plus the captain again; a bench boost counts the bench, a triple captain
    # counts the captain once more. Automatic substitutions are not applied: the ledger
    # scores the eleven that were named, which is what the projection was for.
    realized_xi = sum(float(event_points[player]) for player in starters) + float(
        event_points[captain]
    )
    if chip == "bboost":
        realized_xi += sum(float(event_points[player]) for player in bench)
    elif chip == "3xc":
        realized_xi += float(event_points[captain])
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


def load_entry(root: Path, season: str, gameweek: int) -> LedgerEntry:
    """Load one entry, refusing any file that fails its recorded checksum."""

    directory = _entry_directory(root, season, gameweek)
    if not directory.is_dir():
        raise LedgerError(f"No ledger entry at {directory}.")
    _verify_manifest(directory)
    decision = json.loads((directory / _DECISION_FILE).read_text(encoding="utf-8"))
    outcome_path = directory / _OUTCOME_FILE
    outcome = (
        json.loads(outcome_path.read_text(encoding="utf-8")) if outcome_path.is_file() else None
    )
    return LedgerEntry(
        season=season,
        gameweek=gameweek,
        decision=decision,
        outcome=outcome,
        directory=directory,
    )


def load_ledger(root: Path, season: str) -> tuple[LedgerEntry, ...]:
    """Load every recorded gameweek of one season in chronological order."""

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
    return tuple(load_entry(root, season, gameweek) for gameweek in gameweeks)


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

    entries = load_ledger(root, season)
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
    free_hit_played = isinstance(block, Mapping) and block.get("chip") == "freehit"
    if free_hit_played:
        # A free hit's squad was temporary: the squad, bank, and purchase prices held
        # are the ones the free-hit week started from — the entry before it — while
        # the free transfers carried are the free-hit week's own.
        assert isinstance(block, Mapping)
        free = int(str(block["free_transfers_after"]))
        earlier_entries = [candidate for candidate in entries if candidate.gameweek == previous - 1]
        if not earlier_entries:
            raise LedgerError(
                f"GW{previous} was a free-hit week; the squad it started from is GW"
                f"{previous - 1}'s, which the ledger does not hold."
            )
        entry = earlier_entries[0]
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


def ledger_summary(root: Path, season: str) -> pd.DataFrame:
    """Return one row per recorded gameweek: projected, realized, hits, and the gap."""

    rows: list[dict[str, object]] = []
    for entry in load_ledger(root, season):
        realized = float(str(entry.outcome["realized_xi_score"])) if entry.outcome else None
        projected = float(str(entry.decision["projected_score"]))
        transfers = entry.decision.get("transfers")
        block = transfers if isinstance(transfers, Mapping) else {}
        hits = float(str(block.get("transfer_hit_points", 0.0)))
        rows.append(
            {
                "gameweek": entry.gameweek,
                "snapshot_id": entry.decision["snapshot_id"],
                "solver_status": entry.decision["solver_status"],
                "projected_score": projected,
                "realized_score": realized,
                "projection_error": (realized - projected) if realized is not None else None,
                "unavailable_players": entry.decision["unavailable_player_count"],
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


def summary_markdown(root: Path, season: str) -> str:
    """Render the committed season summary; raw entries stay local."""

    table = ledger_summary(root, season)
    lines = [
        f"# Season Ledger {season}",
        "",
        f"- Contract: `{SEASON_LEDGER_CONTRACT_VERSION}`",
        "- One row per live decision; raw entries (decision, projections, report, "
        "outcome) live locally under `data/ledger/` with per-file checksums.",
        "",
        "| GW | Snapshot | Solver | Projected | Realized | Error | Transfers | Hits | Chip "
        "| Net | Unavailable |",
        "| ---: | --- | --- | ---: | ---: | ---: | ---: | ---: | --- | ---: | ---: |",
    ]
    for record in table.to_dict(orient="records"):
        realized_value = record["realized_score"]
        error_value = record["projection_error"]
        net_value = record["realized_net_score"]
        realized = "-" if realized_value is None else f"{float(str(realized_value)):.0f}"
        error = "-" if error_value is None else f"{float(str(error_value)):+.1f}"
        net = "-" if net_value is None else f"{float(str(net_value)):.0f}"
        chip = record["chip"] if record["chip"] is not None else "-"
        lines.append(
            f"| {record['gameweek']} | `{record['snapshot_id']}` "
            f"| {record['solver_status']} "
            f"| {float(str(record['projected_score'])):.1f} | {realized} | {error} "
            f"| {record['transfers']} | {float(str(record['transfer_hit_points'])):.0f} "
            f"| {chip} | {net} | {record['unavailable_players']} |"
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
