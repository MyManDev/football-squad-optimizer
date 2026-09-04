"""Read and verify the Phase C component OOF table and decision roster."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Final

import pandas as pd

from squadopt.evaluation.models import EvaluationValidationError

OOF_CONTRACT_VERSION: Final = "phase_c_component_oof_v1"
ROSTER_CONTRACT_VERSION: Final = "phase_c_decision_roster_v1"
LOCKED_HOLDOUT_SEASON: Final = "2025-26"
HANDOFF_KEY: Final = ("season", "target_gameweek", "fold_id", "player_id")
OOF_ARTIFACT_COLUMNS: Final = (
    "contract_version",
    "model_version",
    "feature_contract_version",
    "target_contract_version",
    "dataset_contract_version",
    "season",
    "target_gameweek",
    "decision_timestamp_utc",
    "fold_id",
    "player_id",
    "fixture_count",
    "appearance_target",
    "start_target",
    "minutes_target",
    "points_target",
    "appearance_probability",
    "q_start_given_appearance",
    "start_probability",
    "expected_minutes_if_appearance",
    "raw_expected_points_if_appearance",
    "expected_points_if_appearance",
    "control_expected_points",
    "composition_route",
    "evidence_status",
)
ROSTER_ARTIFACT_COLUMNS: Final = (
    "contract_version",
    "season",
    "target_gameweek",
    "fold_id",
    "player_id",
    "name",
    "team_id",
    "position",
    "price_tenths",
)
_DIGEST = re.compile(r"[0-9a-f]{64}")
_FOLD_ID = re.compile(r"(?P<season>\d{4}-\d{2})-gw(?P<gameweek>\d{2})")


@dataclass(frozen=True, slots=True)
class PhaseCComponentHandoff:
    """Verified component rows, their optimizer roster and source identities."""

    rows: pd.DataFrame
    roster: pd.DataFrame
    table_sha256: str
    roster_sha256: str
    manifest_sha256: str
    repository_commit: str
    model_version: str
    feature_contract_version: str
    target_contract_version: str
    dataset_contract_version: str


def _manifest(path: Path) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise EvaluationValidationError(f"Cannot read Phase C manifest {path}: {error}") from error
    if not isinstance(value, dict):
        raise EvaluationValidationError("Phase C manifest must be a JSON object.")
    return value


def _sha256(path: Path, field: object, label: str) -> str:
    try:
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise EvaluationValidationError(f"Cannot read Phase C {label} {path}: {error}") from error
    if field != digest:
        raise EvaluationValidationError(
            f"Phase C {label} checksum {digest} does not match its manifest."
        )
    return digest


def _file_sha256(path: Path, label: str) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise EvaluationValidationError(f"Cannot read Phase C {label} {path}: {error}") from error


def _schema(
    document: dict[str, object], columns_field: str, dtypes_field: str, expected: tuple[str, ...]
) -> dict[str, str]:
    if document.get(columns_field) != list(expected):
        raise EvaluationValidationError(
            f"Phase C manifest {columns_field} is not the frozen schema."
        )
    raw = document.get(dtypes_field)
    if (
        not isinstance(raw, dict)
        or set(raw) != set(expected)
        or any(not isinstance(value, str) or not value for value in raw.values())
    ):
        raise EvaluationValidationError(f"Phase C manifest {dtypes_field} is incomplete.")
    return {str(column): str(raw[column]) for column in expected}


def _read_csv(path: Path, columns: tuple[str, ...], dtypes: dict[str, str]) -> pd.DataFrame:
    try:
        frame = pd.read_csv(path, dtype=dtypes)
    except (OSError, TypeError, ValueError, pd.errors.ParserError) as error:
        raise EvaluationValidationError(f"Cannot read Phase C CSV {path}: {error}") from error
    if tuple(frame.columns) != columns:
        raise EvaluationValidationError(f"Phase C CSV {path.name!r} does not match its schema.")
    return frame


def _fold_rank(fold_id: object, season_ranks: dict[str, int]) -> tuple[int, int]:
    if not isinstance(fold_id, str):
        raise EvaluationValidationError("Phase C fold ids must be strings.")
    match = _FOLD_ID.fullmatch(fold_id)
    if match is None or match.group("season") not in season_ranks:
        raise EvaluationValidationError(f"Invalid or undeclared Phase C fold id {fold_id!r}.")
    return season_ranks[match.group("season")], int(match.group("gameweek"))


def _validate_chronology(document: dict[str, object], table: pd.DataFrame) -> None:
    seasons = document.get("development_seasons")
    folds = document.get("folds")
    fold_ids = document.get("fold_ids")
    if (
        not isinstance(seasons, list)
        or not seasons
        or any(not isinstance(value, str) or not value for value in seasons)
        or len(seasons) != len(set(seasons))
        or LOCKED_HOLDOUT_SEASON in seasons
    ):
        raise EvaluationValidationError("Phase C development_seasons are invalid.")
    if not isinstance(folds, list) or not isinstance(fold_ids, list):
        raise EvaluationValidationError("Phase C manifest must carry fold records and fold_ids.")
    if len(fold_ids) != len(set(fold_ids)) or document.get("fold_count") != len(fold_ids):
        raise EvaluationValidationError("Phase C manifest fold_ids/count are inconsistent.")
    records = [record for record in folds if isinstance(record, dict)]
    if len(records) != len(folds) or document.get("scored_fold_count") != len(records):
        raise EvaluationValidationError("Phase C scored fold records/count are inconsistent.")
    record_ids = [record.get("fold_id") for record in records]
    table_ids = table["fold_id"].drop_duplicates().tolist()
    if fold_ids != record_ids or set(table_ids) != set(record_ids):
        raise EvaluationValidationError("Phase C table and manifest fold identities differ.")

    ranks = {season: rank for rank, season in enumerate(seasons)}
    for record in records:
        fold_id = record["fold_id"]
        decision_rank = _fold_rank(fold_id, ranks)
        if record.get("season") != fold_id[:7] or record.get("target_gameweek") != decision_rank[1]:
            raise EvaluationValidationError(f"Phase C fold record {fold_id!r} has mismatched keys.")
        training = record.get("training_fold_ids")
        if not isinstance(training, list) or len(training) != len(set(training)):
            raise EvaluationValidationError(f"Phase C fold {fold_id!r} has invalid training ids.")
        if fold_id in training or any(
            _fold_rank(item, ranks) >= decision_rank for item in training
        ):
            raise EvaluationValidationError(
                f"Phase C fold {fold_id!r} is not strictly out of fold."
            )
        cutoff = training[-1] if training else None
        if record.get("training_cutoff_fold_id") != cutoff:
            raise EvaluationValidationError(f"Phase C fold {fold_id!r} has a mismatched cutoff.")
        if (
            record.get("decision_timestamp_utc") is not None
            or record.get("training_cutoff_utc") is not None
        ):
            raise EvaluationValidationError(
                "Archive Phase C folds must not fabricate unavailable decision timestamps."
            )
        if (
            not isinstance(record.get("training_key_digest"), str)
            or _DIGEST.fullmatch(str(record["training_key_digest"])) is None
        ):
            raise EvaluationValidationError(
                f"Phase C fold {fold_id!r} has an invalid training digest."
            )
        rows = table.loc[table["fold_id"].eq(fold_id)]
        if record.get("scored_rows") != len(rows):
            raise EvaluationValidationError(f"Phase C fold {fold_id!r} has a mismatched row count.")
        for field in ("model_version", "feature_contract_version", "target_contract_version"):
            if record.get(field) != document.get(field) or not bool(
                rows[field].eq(record[field]).all()
            ):
                raise EvaluationValidationError(
                    f"Phase C fold {fold_id!r} has inconsistent {field}."
                )


def read_phase_c_component_handoff(
    table_path: Path, roster_path: Path, manifest_path: Path
) -> PhaseCComponentHandoff:
    """Return checksum-, schema- and chronology-verified Phase C component data."""

    table_path, roster_path, manifest_path = map(Path, (table_path, roster_path, manifest_path))
    document = _manifest(manifest_path)
    manifest_digest = _file_sha256(manifest_path, "manifest")
    required = {
        "contract_version",
        "model_version",
        "feature_contract_version",
        "target_contract_version",
        "dataset_contract_version",
        "roster_contract_version",
        "repository_commit",
        "working_tree_dirty",
        "table_file",
        "table_sha256",
        "table_columns",
        "table_column_dtypes",
        "row_count",
        "roster_file",
        "roster_sha256",
        "roster_columns",
        "roster_column_dtypes",
        "roster_row_count",
        "locked_holdout_read",
        "locked_holdout_season",
    }
    missing = sorted(required - document.keys())
    if missing:
        raise EvaluationValidationError(f"Phase C manifest is missing fields {missing!r}.")
    if document["contract_version"] != OOF_CONTRACT_VERSION:
        raise EvaluationValidationError("Phase C OOF contract version is unsupported.")
    if document["roster_contract_version"] != ROSTER_CONTRACT_VERSION:
        raise EvaluationValidationError("Phase C roster contract version is unsupported.")
    if document["working_tree_dirty"] is not False:
        raise EvaluationValidationError("Phase C artifact must come from a clean working tree.")
    if (
        document["locked_holdout_read"] is not False
        or document["locked_holdout_season"] != LOCKED_HOLDOUT_SEASON
    ):
        raise EvaluationValidationError("Phase C artifact does not prove locked-holdout exclusion.")
    if document["table_file"] != table_path.name or document["roster_file"] != roster_path.name:
        raise EvaluationValidationError("Phase C manifest names different artifact files.")
    repository_commit = document["repository_commit"]
    if (
        not isinstance(repository_commit, str)
        or re.fullmatch(r"[0-9a-f]{40}", repository_commit) is None
    ):
        raise EvaluationValidationError("Phase C repository_commit must be a full Git SHA.")

    table_digest = _sha256(table_path, document["table_sha256"], "OOF table")
    roster_digest = _sha256(roster_path, document["roster_sha256"], "roster")
    table = _read_csv(
        table_path,
        OOF_ARTIFACT_COLUMNS,
        _schema(document, "table_columns", "table_column_dtypes", OOF_ARTIFACT_COLUMNS),
    )
    roster = _read_csv(
        roster_path,
        ROSTER_ARTIFACT_COLUMNS,
        _schema(document, "roster_columns", "roster_column_dtypes", ROSTER_ARTIFACT_COLUMNS),
    )
    if document["row_count"] != len(table) or document["roster_row_count"] != len(roster):
        raise EvaluationValidationError("Phase C manifest row counts do not match the CSV files.")
    if (
        table.empty
        or table.duplicated(list(HANDOFF_KEY)).any()
        or roster.duplicated(list(HANDOFF_KEY)).any()
    ):
        raise EvaluationValidationError("Phase C handoff keys must be non-empty and unique.")
    if LOCKED_HOLDOUT_SEASON in set(table["season"]) or LOCKED_HOLDOUT_SEASON in set(
        roster["season"]
    ):
        raise EvaluationValidationError("The locked 2025-26 holdout must not be read.")
    for field in (
        "contract_version",
        "model_version",
        "feature_contract_version",
        "target_contract_version",
        "dataset_contract_version",
    ):
        expected_value = document[field]
        if not isinstance(expected_value, str) or not bool(table[field].eq(expected_value).all()):
            raise EvaluationValidationError(f"Phase C table and manifest disagree on {field}.")
    if not bool(roster["contract_version"].eq(ROSTER_CONTRACT_VERSION).all()):
        raise EvaluationValidationError("Phase C roster rows have the wrong contract version.")
    if not bool(table["decision_timestamp_utc"].isna().all()):
        raise EvaluationValidationError(
            "Archive Phase C rows must not fabricate unavailable decision timestamps."
        )
    if bool(roster[["name", "team_id", "position", "price_tenths"]].isna().any().any()):
        raise EvaluationValidationError("Phase C roster has missing optimizer fields.")
    _validate_chronology(document, table)

    table_keys = (
        table.loc[:, list(HANDOFF_KEY)].sort_values(list(HANDOFF_KEY)).reset_index(drop=True)
    )
    roster_keys = (
        roster.loc[:, list(HANDOFF_KEY)].sort_values(list(HANDOFF_KEY)).reset_index(drop=True)
    )
    if not table_keys.equals(roster_keys):
        raise EvaluationValidationError("Phase C OOF and roster keys do not match exactly.")
    joined = table.merge(
        roster.loc[:, [*HANDOFF_KEY, "position"]],
        on=list(HANDOFF_KEY),
        how="inner",
        validate="one_to_one",
    )
    return PhaseCComponentHandoff(
        rows=joined,
        roster=roster.copy(deep=True),
        table_sha256=table_digest,
        roster_sha256=roster_digest,
        manifest_sha256=manifest_digest,
        repository_commit=repository_commit,
        model_version=str(document["model_version"]),
        feature_contract_version=str(document["feature_contract_version"]),
        target_contract_version=str(document["target_contract_version"]),
        dataset_contract_version=str(document["dataset_contract_version"]),
    )


__all__ = [
    "HANDOFF_KEY",
    "OOF_ARTIFACT_COLUMNS",
    "OOF_CONTRACT_VERSION",
    "ROSTER_ARTIFACT_COLUMNS",
    "ROSTER_CONTRACT_VERSION",
    "PhaseCComponentHandoff",
    "read_phase_c_component_handoff",
]
