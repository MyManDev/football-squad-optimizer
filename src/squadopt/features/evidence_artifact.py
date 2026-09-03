"""Read the identity-free Phase B artifact that Phase C consumes."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Final

import pandas as pd

from squadopt.data.errors import DataSourceError, DataValidationError
from squadopt.features.evidence import _EVIDENCE_DTYPES, CONTRACT_VERSION, EVIDENCE_COLUMNS

ARTIFACT_CONTRACT_VERSION: Final = "player_evidence_export_v1"

_REQUIRED_MANIFEST_FIELDS: Final = frozenset(
    {
        "contract_version",
        "artifact_contract_version",
        "season",
        "target_gameweek",
        "deadline_timestamp_utc",
        "generated_at_utc",
        "repository_commit",
        "table_file",
        "table_sha256",
        "row_count",
        "cohort_size",
        "elite_members_observed",
        "elite_members_missing_picks",
        "unmapped_picked_elements",
        "cohort_snapshot_id",
        "ownership_snapshot_id",
        "source_snapshot_ids",
    }
)


def _read_manifest(path: Path) -> dict[str, object]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise DataSourceError(f"Cannot read evidence manifest {path}: {error}") from error
    if not isinstance(document, dict):
        raise DataValidationError("Evidence manifest must be a JSON object.")
    missing = sorted(_REQUIRED_MANIFEST_FIELDS - document.keys())
    if missing:
        raise DataValidationError(f"Evidence manifest is missing required fields {missing!r}.")
    return document


def _single_value(table: pd.DataFrame, column: str) -> object:
    values = table[column].drop_duplicates().tolist()
    if len(values) != 1:
        raise DataValidationError(
            f"Evidence column {column!r} must contain exactly one value; found {values!r}."
        )
    return values[0]


def _validate_manifest_and_table(
    table: pd.DataFrame, manifest: dict[str, object], table_path: Path
) -> tuple[int, ...]:
    if manifest["contract_version"] != CONTRACT_VERSION:
        raise DataValidationError(
            f"Evidence manifest contract_version must be {CONTRACT_VERSION!r}."
        )
    if manifest["artifact_contract_version"] != ARTIFACT_CONTRACT_VERSION:
        raise DataValidationError(
            f"Evidence manifest artifact_contract_version must be {ARTIFACT_CONTRACT_VERSION!r}."
        )
    if manifest["table_file"] != table_path.name:
        raise DataValidationError(
            f"Evidence manifest names table_file {manifest['table_file']!r}, not "
            f"{table_path.name!r}."
        )
    if tuple(table.columns) != EVIDENCE_COLUMNS:
        raise DataValidationError(
            "Evidence CSV columns do not match player_evidence_v1 in its declared order."
        )
    if table.empty:
        raise DataValidationError("Evidence CSV must contain at least one player.")
    if manifest["row_count"] != len(table):
        raise DataValidationError(
            f"Evidence manifest row_count {manifest['row_count']!r} does not match the "
            f"CSV row count {len(table)}."
        )
    if not table["player_id"].is_unique:
        raise DataValidationError("Evidence CSV player_id values must be unique.")
    if not table["player_id"].is_monotonic_increasing:
        raise DataValidationError("Evidence CSV rows must be sorted by player_id.")

    column_to_manifest = {
        "contract_version": "contract_version",
        "season": "season",
        "target_gameweek": "target_gameweek",
        "deadline_timestamp_utc": "deadline_timestamp_utc",
        "elite_cohort_size": "cohort_size",
        "elite_members_observed": "elite_members_observed",
    }
    for column, field in column_to_manifest.items():
        value = _single_value(table, column)
        if value != manifest[field]:
            raise DataValidationError(
                f"Evidence manifest {field} {manifest[field]!r} does not match the CSV "
                f"value {value!r}."
            )

    if table["timing_verified"].isna().any() or not bool(table["timing_verified"].all()):
        raise DataValidationError("Every evidence row must have timing_verified=True.")
    try:
        captured = pd.to_datetime(table["captured_at_utc"], utc=True, errors="raise")
        deadlines = pd.to_datetime(table["deadline_timestamp_utc"], utc=True, errors="raise")
    except (TypeError, ValueError) as error:
        raise DataValidationError(f"Evidence timestamps are invalid: {error}") from error
    if not bool((captured < deadlines).all()):
        raise DataValidationError(
            "Every evidence capture must be strictly earlier than its decision deadline."
        )

    raw_source_ids = manifest["source_snapshot_ids"]
    if not isinstance(raw_source_ids, list) or any(
        not isinstance(value, str) or not value for value in raw_source_ids
    ):
        raise DataValidationError("Evidence manifest source_snapshot_ids must be strings.")
    table_source_ids = tuple(str(_single_value(table, "source_snapshot_ids")).split(";"))
    if tuple(raw_source_ids) != table_source_ids:
        raise DataValidationError(
            "Evidence manifest source_snapshot_ids do not match the CSV provenance."
        )
    for field in ("cohort_snapshot_id", "ownership_snapshot_id"):
        if manifest[field] not in raw_source_ids:
            raise DataValidationError(
                f"Evidence manifest {field} is not among source_snapshot_ids."
            )
    raw_unmapped = manifest["unmapped_picked_elements"]
    if not isinstance(raw_unmapped, list) or any(
        isinstance(value, bool) or not isinstance(value, int) for value in raw_unmapped
    ):
        raise DataValidationError(
            "Evidence manifest unmapped_picked_elements must be integer element ids."
        )
    missing_picks = manifest["elite_members_missing_picks"]
    if isinstance(missing_picks, bool) or not isinstance(missing_picks, int) or missing_picks < 0:
        raise DataValidationError(
            "Evidence manifest elite_members_missing_picks must be a non-negative count."
        )
    return tuple(raw_unmapped)


def read_player_evidence_artifact(table_path: Path, manifest_path: Path) -> pd.DataFrame:
    """Return a contract-checked evidence table with its pandas dtypes restored.

    Phase C reads this artifact pair instead of raw snapshots. A checksum, schema, timing or
    manifest disagreement rejects the pair; ordinary missing evidence remains ``pd.NA``.
    """

    table_path = Path(table_path)
    manifest_path = Path(manifest_path)
    manifest = _read_manifest(manifest_path)
    try:
        table_bytes = table_path.read_bytes()
    except OSError as error:
        raise DataSourceError(f"Cannot read evidence CSV {table_path}: {error}") from error
    digest = hashlib.sha256(table_bytes).hexdigest()
    if manifest["table_sha256"] != digest:
        raise DataValidationError(
            f"Evidence CSV checksum {digest} does not match manifest table_sha256 "
            f"{manifest['table_sha256']!r}."
        )
    try:
        table = pd.read_csv(table_path, dtype=dict(_EVIDENCE_DTYPES))
    except (OSError, TypeError, ValueError, pd.errors.ParserError) as error:
        raise DataValidationError(
            f"Evidence CSV cannot be read under its schema: {error}"
        ) from error

    unmapped_picked_elements = _validate_manifest_and_table(table, manifest, table_path)
    table.attrs.update(
        {
            "artifact_contract_version": manifest["artifact_contract_version"],
            "cohort_snapshot_id": manifest["cohort_snapshot_id"],
            "ownership_snapshot_id": manifest["ownership_snapshot_id"],
            "elite_members_missing_picks": manifest["elite_members_missing_picks"],
            "unmapped_picked_elements": unmapped_picked_elements,
            "generated_at_utc": manifest["generated_at_utc"],
            "repository_commit": manifest["repository_commit"],
            "table_sha256": digest,
        }
    )
    return table
