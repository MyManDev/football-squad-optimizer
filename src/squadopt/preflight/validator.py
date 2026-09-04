"""Checks that decide whether a residual-export artifact may enter a measurement run.

Every check appends a named :class:`PreflightFinding` instead of raising, so one run
reports every contract violation at once. Only unusable inputs (a missing file, a
manifest that is not a mapping) raise :class:`PreflightError`, because nothing about
such inputs can be examined.
"""

import hashlib
from collections.abc import Mapping
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np
import pandas as pd

from squadopt.data.errors import format_examples
from squadopt.preflight.models import (
    ALLOWED_POSITIONS,
    COMMIT_PATTERN,
    MANIFEST_IDENTITY_FIELDS,
    MANIFEST_REQUIRED_FIELDS,
    REALIZED_POINTS_TOLERANCE,
    RESIDUAL_EXPORT_COLUMNS,
    RESIDUAL_EXPORT_CONTRACT_VERSION,
    RESIDUAL_IDENTITY_TOLERANCE,
    SHA256_PATTERN,
    PreflightError,
    PreflightExpectations,
    PreflightFinding,
    PreflightReport,
)

_KEY_COLUMNS = ("fold_id", "player_id")
_SORT_COLUMNS = ("season", "gameweek", "player_id")


def compute_table_sha256(path: Path) -> str:
    """Return the lowercase SHA-256 of the exact file bytes named by the manifest."""

    if not path.is_file():
        raise PreflightError(f"Residual table file does not exist: {path}.")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _finding(check: str, passed: bool, detail: str) -> PreflightFinding:
    return PreflightFinding(check=check, passed=passed, detail=detail)


def _is_utc_timestamp(value: str) -> bool:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return False
    return parsed.utcoffset() == timedelta(0)


def check_residual_manifest(manifest: Mapping[str, object]) -> tuple[PreflightFinding, ...]:
    """Check one manifest against the residual-export contract's required fields."""

    if not isinstance(manifest, Mapping):
        raise PreflightError("manifest must be a mapping.")
    findings: list[PreflightFinding] = []

    missing = [name for name in MANIFEST_REQUIRED_FIELDS if name not in manifest]
    findings.append(
        _finding(
            "manifest_fields_present",
            not missing,
            "All required manifest fields are present."
            if not missing
            else f"Missing required manifest fields: {format_examples(missing)}.",
        )
    )

    if "contract_version" in manifest:
        version = manifest["contract_version"]
        findings.append(
            _finding(
                "manifest_contract_version",
                version == RESIDUAL_EXPORT_CONTRACT_VERSION,
                f"contract_version is {version!r}; expected {RESIDUAL_EXPORT_CONTRACT_VERSION!r}."
                if version != RESIDUAL_EXPORT_CONTRACT_VERSION
                else f"contract_version is {RESIDUAL_EXPORT_CONTRACT_VERSION!r}.",
            )
        )

    invalid_text = [
        name
        for name in MANIFEST_IDENTITY_FIELDS
        if name in manifest
        and (not isinstance(manifest[name], str) or not str(manifest[name]).strip())
    ]
    findings.append(
        _finding(
            "manifest_identity_text",
            not invalid_text,
            "Identity fields are non-empty text."
            if not invalid_text
            else f"Identity fields must be non-empty text: {format_examples(invalid_text)}.",
        )
    )

    if "development_seasons" in manifest:
        seasons = manifest["development_seasons"]
        valid = (
            isinstance(seasons, list | tuple)
            and bool(seasons)
            and all(isinstance(season, str) and season.strip() for season in seasons)
            and len({str(season).strip() for season in seasons}) == len(seasons)
        )
        findings.append(
            _finding(
                "manifest_development_seasons",
                valid,
                "development_seasons is a unique list of non-empty season names."
                if valid
                else f"development_seasons is invalid: {seasons!r}.",
            )
        )

    invalid_counts = [
        name
        for name in ("fold_count", "row_count")
        if name in manifest
        and (
            isinstance(manifest[name], bool)
            or not isinstance(manifest[name], int)
            or int(str(manifest[name])) < 1
        )
    ]
    findings.append(
        _finding(
            "manifest_population_counts",
            not invalid_counts,
            "fold_count and row_count are positive integers."
            if not invalid_counts
            else f"Counts must be positive integers: {format_examples(invalid_counts)}.",
        )
    )

    if "repository_commit" in manifest:
        commit = manifest["repository_commit"]
        valid = isinstance(commit, str) and bool(COMMIT_PATTERN.match(commit))
        findings.append(
            _finding(
                "manifest_repository_commit",
                valid,
                "repository_commit is a 40-character lowercase hex commit."
                if valid
                else f"repository_commit is not a full lowercase commit hash: {commit!r}.",
            )
        )

    if "table_sha256" in manifest:
        digest = manifest["table_sha256"]
        valid = isinstance(digest, str) and bool(SHA256_PATTERN.match(digest))
        findings.append(
            _finding(
                "manifest_table_sha256_format",
                valid,
                "table_sha256 is a 64-character lowercase hex digest."
                if valid
                else f"table_sha256 is not a lowercase SHA-256 digest: {digest!r}.",
            )
        )

    if "created_at_utc" in manifest:
        stamp = manifest["created_at_utc"]
        valid = isinstance(stamp, str) and _is_utc_timestamp(stamp)
        findings.append(
            _finding(
                "manifest_created_at_utc",
                valid,
                "created_at_utc is an explicit UTC timestamp."
                if valid
                else f"created_at_utc is not an explicit UTC timestamp: {stamp!r}.",
            )
        )

    if "opening_gameweeks_included" in manifest:
        flag = manifest["opening_gameweeks_included"]
        findings.append(
            _finding(
                "manifest_opening_flag_type",
                isinstance(flag, bool),
                "opening_gameweeks_included is a boolean."
                if isinstance(flag, bool)
                else f"opening_gameweeks_included must be a boolean, got {flag!r}.",
            )
        )

    return tuple(findings)


def _player_id_kinds(values: pd.Series) -> set[str]:
    kinds: set[str] = set()
    for value in values:
        if isinstance(value, bool):
            kinds.add("bool")
        elif isinstance(value, int | np.integer):
            kinds.add("int")
        elif isinstance(value, str):
            kinds.add("str")
        else:
            kinds.add(type(value).__name__)
    return kinds


def check_residual_table(table: pd.DataFrame) -> tuple[PreflightFinding, ...]:
    """Check one residual table against the row-level residual-export contract.

    Column and emptiness violations short-circuit the value checks: a table with the
    wrong shape cannot be examined row-by-row, and reporting derived failures for
    every downstream rule would bury the actual defect.
    """

    if not isinstance(table, pd.DataFrame):
        raise PreflightError("table must be a pandas DataFrame.")
    findings: list[PreflightFinding] = []

    columns = tuple(str(column) for column in table.columns)
    if columns != RESIDUAL_EXPORT_COLUMNS:
        findings.append(
            _finding(
                "table_columns",
                False,
                f"Columns are {list(columns)!r}; the contract requires exactly "
                f"{list(RESIDUAL_EXPORT_COLUMNS)!r} in order.",
            )
        )
        return tuple(findings)
    findings.append(_finding("table_columns", True, "Columns match the contract order exactly."))

    if table.empty:
        findings.append(_finding("table_row_population", False, "Table contains no rows."))
        return tuple(findings)
    findings.append(_finding("table_row_population", True, f"Table contains {len(table)} rows."))

    duplicated = int(table.duplicated(subset=list(_KEY_COLUMNS)).sum())
    findings.append(
        _finding(
            "table_key_uniqueness",
            duplicated == 0,
            "One row per (fold_id, player_id)."
            if duplicated == 0
            else f"{duplicated} rows repeat a (fold_id, player_id) key.",
        )
    )

    gameweeks = table["gameweek"]
    if not pd.api.types.is_integer_dtype(gameweeks):
        findings.append(
            _finding(
                "table_fold_id_format",
                False,
                f"gameweek must be an integer column, got dtype {gameweeks.dtype}.",
            )
        )
    else:
        expected_fold = (
            table["season"].astype(str) + "-gw" + gameweeks.astype("int64").map("{:02d}".format)
        )
        mismatched = table.loc[
            (table["fold_id"].astype(str) != expected_fold) | (gameweeks < 1), "fold_id"
        ]
        findings.append(
            _finding(
                "table_fold_id_format",
                mismatched.empty,
                "fold_id equals '<season>-gwNN' and matches season/gameweek on every row."
                if mismatched.empty
                else "fold_id disagrees with season/gameweek: "
                f"{format_examples(mismatched.unique().tolist())}.",
            )
        )

    kinds = _player_id_kinds(table["player_id"])
    stable_ids = kinds in ({"int"}, {"str"})
    findings.append(
        _finding(
            "table_player_id_representation",
            stable_ids,
            f"player_id uses one stable representation ({next(iter(kinds))})."
            if stable_ids
            else f"player_id mixes representations: {sorted(kinds)!r}.",
        )
    )

    team_ids = table["team_id"]
    bad_teams = int((team_ids.isna() | (team_ids.astype(str).str.strip() == "")).sum())
    positions = table["position"]
    bad_positions = positions.loc[~positions.isin(sorted(ALLOWED_POSITIONS))]
    identity_ok = bad_teams == 0 and bad_positions.empty
    findings.append(
        _finding(
            "table_identity_values",
            identity_ok,
            "team_id and position carry valid identities on every row."
            if identity_ok
            else f"{bad_teams} rows lack a team_id; invalid positions: "
            f"{format_examples(bad_positions.unique().tolist())}.",
        )
    )

    numeric_ok = True
    for name in ("predicted_points", "realized_points", "residual"):
        if not pd.api.types.is_numeric_dtype(table[name]):
            numeric_ok = False
            findings.append(
                _finding(
                    f"table_{name}",
                    False,
                    f"{name} must be numeric, got dtype {table[name].dtype}.",
                )
            )
    if numeric_ok:
        predicted = table["predicted_points"].astype("float64")
        bad_predicted = int((~np.isfinite(predicted) | (predicted < 0.0)).sum())
        findings.append(
            _finding(
                "table_predicted_points",
                bad_predicted == 0,
                "Predicted points are finite and non-negative."
                if bad_predicted == 0
                else f"{bad_predicted} predicted points are non-finite or negative.",
            )
        )
        realized = table["realized_points"].astype("float64")
        residual = table["residual"].astype("float64")
        bad_finite = int((~np.isfinite(realized) | (~np.isfinite(residual))).sum())
        findings.append(
            _finding(
                "table_realized_points",
                bad_finite == 0,
                "Realized points and residuals are finite."
                if bad_finite == 0
                else f"{bad_finite} rows carry non-finite realized points or residuals.",
            )
        )
        if bad_finite == 0:
            drift = (residual - (realized - predicted)).abs()
            broken = int((drift > RESIDUAL_IDENTITY_TOLERANCE).sum())
            findings.append(
                _finding(
                    "table_residual_identity",
                    broken == 0,
                    "residual equals realized_points - predicted_points within tolerance."
                    if broken == 0
                    else f"{broken} rows violate residual = realized - predicted.",
                )
            )

    if stable_ids:
        ordered = table.sort_values(list(_SORT_COLUMNS), kind="stable", ignore_index=True)
        sorted_ok = table.reset_index(drop=True).equals(ordered)
        findings.append(
            _finding(
                "table_sort_order",
                sorted_ok,
                "Rows are sorted by season, gameweek, then player_id."
                if sorted_ok
                else "Rows are not sorted by season, gameweek, then player_id.",
            )
        )

    return tuple(findings)


def check_table_matches_manifest(
    table: pd.DataFrame,
    manifest: Mapping[str, object],
    *,
    table_sha256: str | None = None,
) -> tuple[PreflightFinding, ...]:
    """Check that a manifest describes the table it accompanies.

    ``table_sha256`` is the digest of the exact file bytes the table was read from.
    When it is ``None`` (an in-memory table with no file), no checksum finding is
    produced; the CLI always supplies it.
    """

    if not isinstance(table, pd.DataFrame):
        raise PreflightError("table must be a pandas DataFrame.")
    if not isinstance(manifest, Mapping):
        raise PreflightError("manifest must be a mapping.")
    findings: list[PreflightFinding] = []
    has_columns = tuple(str(column) for column in table.columns) == RESIDUAL_EXPORT_COLUMNS

    declared_rows = manifest.get("row_count")
    if isinstance(declared_rows, int) and not isinstance(declared_rows, bool):
        findings.append(
            _finding(
                "manifest_row_count_matches_table",
                declared_rows == len(table),
                f"Manifest row_count {declared_rows} matches the table."
                if declared_rows == len(table)
                else f"Manifest declares {declared_rows} rows; the table has {len(table)}.",
            )
        )

    if has_columns:
        observed_folds = int(table["fold_id"].nunique())
        declared_folds = manifest.get("fold_count")
        if isinstance(declared_folds, int) and not isinstance(declared_folds, bool):
            findings.append(
                _finding(
                    "manifest_fold_count_matches_table",
                    declared_folds == observed_folds,
                    f"Manifest fold_count {declared_folds} matches the table."
                    if declared_folds == observed_folds
                    else f"Manifest declares {declared_folds} folds; "
                    f"the table has {observed_folds}.",
                )
            )

        declared_seasons = manifest.get("development_seasons")
        if isinstance(declared_seasons, list | tuple):
            observed_seasons = sorted({str(value) for value in table["season"]})
            expected_seasons = sorted(str(season) for season in declared_seasons)
            findings.append(
                _finding(
                    "manifest_seasons_match_table",
                    expected_seasons == observed_seasons,
                    "Manifest development_seasons match the table's seasons."
                    if expected_seasons == observed_seasons
                    else f"Manifest names seasons {expected_seasons!r}; "
                    f"the table contains {observed_seasons!r}.",
                )
            )

        opening_flag = manifest.get("opening_gameweeks_included")
        if isinstance(opening_flag, bool) and pd.api.types.is_integer_dtype(table["gameweek"]):
            has_opening_rows = bool((table["gameweek"] == 1).any())
            consistent = opening_flag == has_opening_rows
            findings.append(
                _finding(
                    "manifest_opening_flag_matches_table",
                    consistent,
                    "opening_gameweeks_included agrees with the table's gameweeks."
                    if consistent
                    else (
                        "Manifest claims opening folds but the table has no GW1 rows."
                        if opening_flag
                        else "Table contains GW1 rows the manifest does not declare "
                        "as opening evidence."
                    ),
                )
            )

    if table_sha256 is not None:
        declared_digest = manifest.get("table_sha256")
        matches = isinstance(declared_digest, str) and declared_digest == table_sha256
        findings.append(
            _finding(
                "table_checksum_matches_manifest",
                matches,
                "Table bytes match the manifest's SHA-256 digest."
                if matches
                else "Table bytes do not match the manifest's SHA-256 digest; "
                "the file is not the one the manifest describes.",
            )
        )

    return tuple(findings)


def check_manifest_expectations(
    manifest: Mapping[str, object],
    expectations: PreflightExpectations,
) -> tuple[PreflightFinding, ...]:
    """Check a manifest against externally agreed facts about the handoff."""

    if not isinstance(manifest, Mapping):
        raise PreflightError("manifest must be a mapping.")
    if not isinstance(expectations, PreflightExpectations):
        raise PreflightError("expectations must be a PreflightExpectations.")
    findings: list[PreflightFinding] = []

    scalar_checks: tuple[tuple[str, str, object], ...] = (
        ("expected_fold_count", "fold_count", expectations.fold_count),
        ("expected_row_count", "row_count", expectations.row_count),
        ("expected_objective", "evaluation_objective", expectations.evaluation_objective),
        ("expected_repository_commit", "repository_commit", expectations.repository_commit),
        ("expected_dataset_snapshot", "dataset_snapshot_id", expectations.dataset_snapshot_id),
        (
            "expected_opening_flag",
            "opening_gameweeks_included",
            expectations.opening_gameweeks_included,
        ),
    )
    for check, field_name, expected in scalar_checks:
        if expected is None:
            continue
        observed = manifest.get(field_name)
        findings.append(
            _finding(
                check,
                observed == expected,
                f"Manifest {field_name} matches the expected {expected!r}."
                if observed == expected
                else f"Manifest {field_name} is {observed!r}; the handoff agreed on {expected!r}.",
            )
        )

    if expectations.development_seasons is not None:
        declared = manifest.get("development_seasons")
        observed_seasons = (
            tuple(sorted(str(season) for season in declared))
            if isinstance(declared, list | tuple)
            else None
        )
        matches = observed_seasons == expectations.development_seasons
        findings.append(
            _finding(
                "expected_seasons",
                matches,
                "Manifest development_seasons match the agreed seasons."
                if matches
                else f"Manifest names seasons {observed_seasons!r}; the handoff agreed "
                f"on {expectations.development_seasons!r}.",
            )
        )

    return tuple(findings)


def run_residual_export_preflight(
    table: pd.DataFrame,
    manifest: Mapping[str, object],
    *,
    table_sha256: str | None = None,
    expectations: PreflightExpectations | None = None,
    artifact_label: str = "residual_export",
) -> PreflightReport:
    """Run every single-artifact check and return one complete report."""

    findings = (
        *check_residual_manifest(manifest),
        *check_residual_table(table),
        *check_table_matches_manifest(table, manifest, table_sha256=table_sha256),
    )
    if expectations is not None:
        findings = (*findings, *check_manifest_expectations(manifest, expectations))
    return PreflightReport(artifact_label=artifact_label, findings=findings)


def check_export_pair(
    reference_table: pd.DataFrame,
    reference_manifest: Mapping[str, object],
    candidate_table: pd.DataFrame,
    candidate_manifest: Mapping[str, object],
) -> tuple[PreflightFinding, ...]:
    """Check the pairing rule between one reference and one candidate export.

    Rows are never intersected: a key present on one side only is a failure, because
    silently dropping unmatched players would change both the prediction-error
    population and the optimizer decision being compared.
    """

    for frame in (reference_table, candidate_table):
        if not isinstance(frame, pd.DataFrame):
            raise PreflightError("tables must be pandas DataFrames.")
    for document in (reference_manifest, candidate_manifest):
        if not isinstance(document, Mapping):
            raise PreflightError("manifests must be mappings.")
    findings: list[PreflightFinding] = []

    reference_label = reference_manifest.get("candidate_label")
    candidate_label = candidate_manifest.get("candidate_label")
    findings.append(
        _finding(
            "pair_labels_differ",
            reference_label != candidate_label,
            f"Reference {reference_label!r} and candidate {candidate_label!r} "
            "name different regimes."
            if reference_label != candidate_label
            else f"Both exports carry the same candidate_label {reference_label!r}.",
        )
    )

    shared_fields = (
        ("pair_development_seasons", "development_seasons"),
        ("pair_evaluation_objective", "evaluation_objective"),
        ("pair_dataset_snapshot", "dataset_snapshot_id"),
        ("pair_repository_commit", "repository_commit"),
        ("pair_opening_flag", "opening_gameweeks_included"),
    )
    for check, field_name in shared_fields:
        reference_value = reference_manifest.get(field_name)
        candidate_value = candidate_manifest.get(field_name)
        if isinstance(reference_value, list | tuple) and isinstance(candidate_value, list | tuple):
            reference_value = tuple(sorted(str(item) for item in reference_value))
            candidate_value = tuple(sorted(str(item) for item in candidate_value))
        matches = reference_value == candidate_value
        findings.append(
            _finding(
                check,
                matches,
                f"Both manifests agree on {field_name}."
                if matches
                else f"{field_name} differs: reference {reference_value!r} vs "
                f"candidate {candidate_value!r}.",
            )
        )

    for frame in (reference_table, candidate_table):
        if tuple(str(column) for column in frame.columns) != RESIDUAL_EXPORT_COLUMNS:
            findings.append(
                _finding(
                    "pair_row_keys",
                    False,
                    "Row-level pairing was not evaluated because at least one table "
                    "does not carry the contract columns.",
                )
            )
            return tuple(findings)

    reference_folds = set(reference_table["fold_id"].astype(str))
    candidate_folds = set(candidate_table["fold_id"].astype(str))
    findings.append(
        _finding(
            "pair_fold_policy",
            reference_folds == candidate_folds,
            f"Both exports cover the same {len(reference_folds)} folds."
            if reference_folds == candidate_folds
            else "Fold policies differ: reference-only folds "
            f"{format_examples(sorted(reference_folds - candidate_folds))}; candidate-only "
            f"folds {format_examples(sorted(candidate_folds - reference_folds))}.",
        )
    )

    key_columns = list(_KEY_COLUMNS)
    merged = reference_table.merge(
        candidate_table,
        on=key_columns,
        how="outer",
        suffixes=("_reference", "_candidate"),
        indicator=True,
    )
    reference_only = int((merged["_merge"] == "left_only").sum())
    candidate_only = int((merged["_merge"] == "right_only").sum())
    keys_match = reference_only == 0 and candidate_only == 0
    findings.append(
        _finding(
            "pair_row_keys",
            keys_match,
            f"All {len(merged)} (fold_id, player_id) keys are present in both exports."
            if keys_match
            else f"{reference_only} keys exist only in the reference and "
            f"{candidate_only} only in the candidate; rows are never intersected silently.",
        )
    )

    matched = merged.loc[merged["_merge"] == "both"]
    if not matched.empty:
        realized_reference = matched["realized_points_reference"].astype("float64")
        realized_candidate = matched["realized_points_candidate"].astype("float64")
        realized_drift = int(
            ((realized_reference - realized_candidate).abs() > REALIZED_POINTS_TOLERANCE).sum()
        )
        findings.append(
            _finding(
                "pair_realized_points",
                realized_drift == 0,
                "Matched rows carry identical realized points."
                if realized_drift == 0
                else f"{realized_drift} matched rows disagree on realized points; the two "
                "exports cannot describe the same outcomes.",
            )
        )
        reference_teams = matched["team_id_reference"].astype(str)
        candidate_teams = matched["team_id_candidate"].astype(str)
        identity_drift = int(
            (
                (reference_teams != candidate_teams)
                | (matched["position_reference"] != matched["position_candidate"])
            ).sum()
        )
        findings.append(
            _finding(
                "pair_row_identity",
                identity_drift == 0,
                "Matched rows agree on team and position identity."
                if identity_drift == 0
                else f"{identity_drift} matched rows disagree on team or position identity.",
            )
        )

    return tuple(findings)


def run_export_pair_preflight(
    reference_table: pd.DataFrame,
    reference_manifest: Mapping[str, object],
    candidate_table: pd.DataFrame,
    candidate_manifest: Mapping[str, object],
    *,
    artifact_label: str = "residual_export_pair",
) -> PreflightReport:
    """Run every pairing check and return one complete report."""

    findings = check_export_pair(
        reference_table,
        reference_manifest,
        candidate_table,
        candidate_manifest,
    )
    return PreflightReport(artifact_label=artifact_label, findings=findings)
