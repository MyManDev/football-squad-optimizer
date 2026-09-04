"""The public Phase C reader for the Phase B evidence artifact pair."""

import hashlib
import json
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import tests.unit.test_player_evidence as evidence_fixtures
from scripts import export_player_evidence

from squadopt.backtest.export_precision import write_export_table
from squadopt.data.errors import DataValidationError
from squadopt.features.evidence import EVIDENCE_COLUMNS
from squadopt.features.evidence_artifact import read_player_evidence_artifact


def _artifact(tmp_path: Path) -> tuple[Path, Path]:
    table = evidence_fixtures._build()
    table.loc[0, "chance_of_playing_next_round"] = pd.NA
    result = export_player_evidence.write_evidence_artifact(
        table,
        tmp_path,
        "evidence",
        repository_commit="0" * 40,
        generated_at_utc="2026-09-03T07:00:00Z",
    )
    return result.table_path, result.manifest_path


def _manifest(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def _write_manifest(path: Path, manifest: dict[str, Any]) -> None:
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def test_the_public_reader_restores_dtypes_missingness_and_provenance(tmp_path: Path) -> None:
    table_path, manifest_path = _artifact(tmp_path)

    table = read_player_evidence_artifact(table_path, manifest_path)

    assert tuple(table.columns) == EVIDENCE_COLUMNS
    assert str(table["chance_of_playing_next_round"].dtype) == "Int64"
    assert pd.isna(table.loc[0, "chance_of_playing_next_round"])
    assert table.attrs["table_sha256"] == hashlib.sha256(table_path.read_bytes()).hexdigest()
    assert table.attrs["elite_members_missing_picks"] == 0
    assert table.attrs["artifact_contract_version"] == "player_evidence_export_v1"


def test_a_csv_that_does_not_match_its_manifest_is_refused(tmp_path: Path) -> None:
    table_path, manifest_path = _artifact(tmp_path)
    table_path.write_bytes(table_path.read_bytes() + b"\n")

    with pytest.raises(DataValidationError, match="checksum"):
        read_player_evidence_artifact(table_path, manifest_path)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("row_count", 999),
        ("cohort_size", 999),
        ("elite_members_observed", 999),
        ("source_snapshot_ids", ["different-snapshot"]),
    ],
)
def test_manifest_facts_must_match_the_csv(tmp_path: Path, field: str, value: object) -> None:
    table_path, manifest_path = _artifact(tmp_path)
    manifest = _manifest(manifest_path)
    manifest[field] = value
    _write_manifest(manifest_path, manifest)

    with pytest.raises(DataValidationError):
        read_player_evidence_artifact(table_path, manifest_path)


@pytest.mark.parametrize("corruption", ["unverified", "late"])
def test_invalid_timing_is_not_treated_as_missing(tmp_path: Path, corruption: str) -> None:
    table_path, manifest_path = _artifact(tmp_path)
    table = pd.read_csv(table_path)
    if corruption == "unverified":
        table.loc[0, "timing_verified"] = False
    else:
        table.loc[0, "captured_at_utc"] = table.loc[0, "deadline_timestamp_utc"]
    write_export_table(table, table_path)
    manifest = _manifest(manifest_path)
    manifest["table_sha256"] = hashlib.sha256(table_path.read_bytes()).hexdigest()
    _write_manifest(manifest_path, manifest)

    with pytest.raises(DataValidationError):
        read_player_evidence_artifact(table_path, manifest_path)
