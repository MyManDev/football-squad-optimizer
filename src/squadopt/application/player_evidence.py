"""Export one ``player_evidence_v1`` table as the identity-free CSV + manifest Phase C reads.

    python -m scripts.export_player_evidence \\
        --season 2026-27 --target-gameweek 3 --deadline-utc 2026-09-04T17:30:00Z \\
        --cohort-snapshot <fpl-top200-...> --snapshot <fpl-elite-picks-...> \\
        --cohort-size 100 --output-dir artifacts/phase_b

Phase C reads the table and nothing under ``data/snapshots/``. The builder carries some
aggregate diagnostics on ``DataFrame.attrs`` -- which cohort members had no readable picks,
which picked elements had no persistent code -- and a bare CSV would drop them. So the
handoff is a pair: the CSV holds the 27 contract columns in ``player_id`` order, and the
manifest beside it holds the aggregates, the provenance and the CSV's SHA-256.

The table is validated against its own contract before a byte is written, and a missing
diagnostic refuses the export rather than becoming a zero. Writing is create-once: the CSV
goes to a temporary file, its digest is taken from the final bytes, and an existing artifact
with different content is never overwritten. Nothing here is printed or written that names a
manager or an entry.
"""

from __future__ import annotations

import json
import os
import secrets
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Final

import pandas as pd

from squadopt.application.evidence_io import write_json
from squadopt.backtest.export_precision import write_export_table
from squadopt.data.errors import (
    DataError,
    DataValidationError,
    DuplicateRecordsError,
    InvalidValueError,
    MissingColumnsError,
)
from squadopt.data.snapshots import read_snapshot
from squadopt.data.timestamps import as_instant
from squadopt.features.evidence import (
    CONTRACT_VERSION,
    EVIDENCE_COLUMNS,
    build_player_evidence_table,
)
from squadopt.features.evidence_artifact import ARTIFACT_CONTRACT_VERSION
from squadopt.preflight.validator import compute_table_sha256


@dataclass(frozen=True, slots=True)
class PlayerEvidenceRequest:
    season: str
    target_gameweek: int
    deadline_utc: str
    snapshot_root: Path
    cohort_snapshot: str
    snapshots: tuple[str, ...]
    output_dir: Path
    table_name: str
    repository_commit: str
    cohort_size: int = 100


def export_player_evidence(request: PlayerEvidenceRequest) -> ExportResult:
    """Build and verify captured evidence; transport and repository state stay outside."""

    cohort = read_snapshot(request.snapshot_root, request.cohort_snapshot)
    identifiers = tuple(dict.fromkeys((*request.snapshots, request.cohort_snapshot)))
    table = build_player_evidence_table(
        season=request.season,
        target_gameweek=request.target_gameweek,
        deadline_timestamp_utc=request.deadline_utc,
        snapshots=[read_snapshot(request.snapshot_root, identifier) for identifier in identifiers],
        cohort_snapshot=cohort,
        cohort_size=request.cohort_size,
    )
    return write_evidence_artifact(
        table, request.output_dir, request.table_name, repository_commit=request.repository_commit
    )


# Names that would carry an identity or raw text if they ever appeared. The contract's fixed
# column tuple already excludes them; the check exists so a future column cannot slip one in.
_FORBIDDEN_COLUMNS: Final = frozenset(
    {"entry", "entry_id", "entry_name", "player_name", "manager_name", "team_name", "news"}
)


@dataclass(frozen=True, slots=True)
class EvidenceSummary:
    """The aggregate facts of one table -- everything the manifest says about it."""

    season: str
    target_gameweek: int
    deadline_timestamp_utc: str
    row_count: int
    cohort_size: int
    elite_members_observed: int
    elite_members_missing_picks: int
    unmapped_picked_elements: tuple[int, ...]
    cohort_snapshot_id: str
    ownership_snapshot_id: str
    source_snapshot_ids: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ExportResult:
    table_path: Path
    manifest_path: Path
    table_sha256: str
    manifest: Mapping[str, object]
    summary: EvidenceSummary


def _single(table: pd.DataFrame, column: str) -> object:
    """The one value a column carries across every row; anything else is refused."""

    if table[column].isna().any():
        raise InvalidValueError(f"{column} is missing on some rows; the table is not one week.")
    values = table[column].unique()
    if len(values) != 1:
        raise InvalidValueError(
            f"{column} must carry exactly one value across the table, got {len(values)}."
        )
    return values[0]


def _attr(table: pd.DataFrame, key: str) -> object:
    if key not in table.attrs:
        raise DataValidationError(
            f"The table carries no attrs[{key!r}] diagnostic; a missing diagnostic is not "
            "zero, so the export is refused."
        )
    return table.attrs[key]


def validate_evidence_table(table: pd.DataFrame) -> EvidenceSummary:
    """Check the table against its contract and return the aggregates the manifest needs."""

    if not isinstance(table, pd.DataFrame):
        raise DataValidationError("The evidence table must be a pandas DataFrame.")
    if tuple(table.columns) != EVIDENCE_COLUMNS:
        missing = [name for name in EVIDENCE_COLUMNS if name not in table.columns]
        if missing:
            raise MissingColumnsError(f"Evidence table is missing columns {missing!r}.")
        raise DataValidationError(
            "Evidence table columns must be exactly the player_evidence_v1 columns in order."
        )
    forbidden = sorted(set(table.columns) & _FORBIDDEN_COLUMNS)
    if forbidden:
        raise DataValidationError(f"Evidence table carries identity columns {forbidden!r}.")
    if table.empty:
        raise DataValidationError("An empty evidence table is not a handoff.")
    if str(_single(table, "contract_version")) != CONTRACT_VERSION:
        raise DataValidationError(
            f"contract_version must be {CONTRACT_VERSION!r}, got "
            f"{table['contract_version'].unique().tolist()!r}."
        )
    if table["player_id"].dtype.kind != "i":
        raise InvalidValueError("player_id must be the integer persistent code.")
    if not table["player_id"].is_unique:
        raise DuplicateRecordsError("player_id must be unique; a player appears twice.")

    flags = table["timing_verified"]
    if flags.isna().any() or not bool(flags.all()):
        raise DataValidationError("Every row must be timing-verified pre-deadline evidence.")
    deadline = str(_single(table, "deadline_timestamp_utc"))
    captured_at = str(_single(table, "captured_at_utc"))
    if as_instant(captured_at) >= as_instant(deadline):
        raise DataValidationError(
            f"captured_at_utc {captured_at} is not before the deadline {deadline}."
        )

    source_ids = tuple(sorted(set(str(_single(table, "source_snapshot_ids")).split(";"))))
    cohort_id = str(_attr(table, "cohort_snapshot_id"))
    ownership_id = str(_attr(table, "ownership_snapshot_id"))
    for label, snapshot_id in (("cohort", cohort_id), ("ownership", ownership_id)):
        if not snapshot_id.strip():
            raise DataValidationError(f"The {label} snapshot id diagnostic is blank.")
        if snapshot_id not in source_ids:
            raise DataValidationError(
                f"The {label} snapshot {snapshot_id!r} is not among the table's "
                f"source_snapshot_ids {source_ids!r}; provenance disagrees with itself."
            )
    missing_picks = _attr(table, "elite_members_missing_picks")
    if isinstance(missing_picks, bool) or not isinstance(missing_picks, int) or missing_picks < 0:
        raise DataValidationError("attrs['elite_members_missing_picks'] must be a count.")
    raw_unmapped = _attr(table, "unmapped_picked_elements")
    if not isinstance(raw_unmapped, list | tuple) or any(
        isinstance(v, bool) or not isinstance(v, int) for v in raw_unmapped
    ):
        raise DataValidationError("attrs['unmapped_picked_elements'] must be element ids.")

    return EvidenceSummary(
        season=str(_single(table, "season")),
        target_gameweek=int(str(_single(table, "target_gameweek"))),
        deadline_timestamp_utc=deadline,
        row_count=len(table),
        cohort_size=int(str(_single(table, "elite_cohort_size"))),
        elite_members_observed=int(str(_single(table, "elite_members_observed"))),
        elite_members_missing_picks=int(missing_picks),
        unmapped_picked_elements=tuple(int(v) for v in raw_unmapped),
        cohort_snapshot_id=cohort_id,
        ownership_snapshot_id=ownership_id,
        source_snapshot_ids=source_ids,
    )


def _temporary(final: Path) -> Path:
    return final.with_name(f".{final.name}.tmp-{os.getpid()}-{secrets.token_hex(4)}")


def _publish(temporary: Path, final: Path) -> None:
    """Create-once: an identical artifact is kept, a different one is never overwritten."""

    if final.exists():
        if final.read_bytes() == temporary.read_bytes():
            return
        raise DataError(
            f"{final} already exists with different content; an artifact is never "
            "overwritten in place. Choose another name or remove it deliberately."
        )
    os.replace(temporary, final)


def _canonical(manifest: Mapping[str, object]) -> dict[str, object]:
    return {key: value for key, value in manifest.items() if key != "generated_at_utc"}


def write_evidence_artifact(
    table: pd.DataFrame,
    output_dir: Path,
    table_name: str,
    *,
    repository_commit: str,
    generated_at_utc: str | None = None,
) -> ExportResult:
    """Validate, then write ``<table_name>.csv`` and ``<table_name>.manifest.json``.

    The CSV is written to a temporary file first; the digest is taken from the final bytes;
    the manifest is written only after the CSV is in place. Re-running on the same table is
    a no-op that returns the same digest; a different table under the same name is refused.
    """

    summary = validate_evidence_table(table)
    ordered = table.sort_values("player_id", kind="stable").reset_index(drop=True)
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    table_path = output_dir / f"{table_name}.csv"
    manifest_path = output_dir / f"{table_name}.manifest.json"

    temporary = _temporary(table_path)
    try:
        write_export_table(ordered, temporary)
        table_sha256 = compute_table_sha256(temporary)
        _publish(temporary, table_path)
    finally:
        temporary.unlink(missing_ok=True)

    manifest: dict[str, object] = {
        "contract_version": CONTRACT_VERSION,
        "artifact_contract_version": ARTIFACT_CONTRACT_VERSION,
        "season": summary.season,
        "target_gameweek": summary.target_gameweek,
        "deadline_timestamp_utc": summary.deadline_timestamp_utc,
        "generated_at_utc": generated_at_utc or datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "repository_commit": repository_commit,
        "table_file": table_path.name,
        "table_sha256": table_sha256,
        "row_count": summary.row_count,
        "cohort_size": summary.cohort_size,
        "elite_members_observed": summary.elite_members_observed,
        "elite_members_missing_picks": summary.elite_members_missing_picks,
        "unmapped_picked_elements": list(summary.unmapped_picked_elements),
        "cohort_snapshot_id": summary.cohort_snapshot_id,
        "ownership_snapshot_id": summary.ownership_snapshot_id,
        "source_snapshot_ids": list(summary.source_snapshot_ids),
    }
    if manifest_path.exists():
        existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        if not isinstance(existing, dict) or _canonical(existing) != _canonical(manifest):
            raise DataError(
                f"{manifest_path} already exists and describes a different artifact; "
                "refusing to overwrite it."
            )
        # The artifact on disk is the record; its manifest, timestamp included, is returned.
        manifest = existing
    else:
        temporary_manifest = _temporary(manifest_path)
        try:
            write_json(temporary_manifest, manifest)
            os.replace(temporary_manifest, manifest_path)
        finally:
            temporary_manifest.unlink(missing_ok=True)
    return ExportResult(
        table_path=table_path,
        manifest_path=manifest_path,
        table_sha256=table_sha256,
        manifest=manifest,
        summary=summary,
    )
