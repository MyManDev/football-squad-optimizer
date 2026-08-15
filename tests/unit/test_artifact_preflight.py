"""Contract tests for the residual-export artifact preflight.

Every table here is synthetic and hand-built. The negative cases are the point: the
preflight exists so that a corrupted, mislabeled, or mispaired handoff artifact is
rejected with a named reason before any measurement run consumes it.
"""

import json
import sys
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
import scripts.run_artifact_preflight as preflight_cli

from squadopt.preflight import (
    PREFLIGHT_CONTRACT_VERSION,
    RESIDUAL_EXPORT_COLUMNS,
    PreflightError,
    PreflightExpectations,
    PreflightReport,
    compute_table_sha256,
    preflight_report_to_dict,
    preflight_report_to_markdown,
    run_export_pair_preflight,
    run_residual_export_preflight,
)

SEASON = "2025-26"
COMMIT = "a" * 40
SNAPSHOT = "archive@test-pin"


def _table(**overrides: Any) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for gameweek in (2, 3):
        for player_id, team_id, position, predicted in (
            (101, "Alpha", "MID", 4.0),
            (202, "Beta", "FWD", 5.5),
        ):
            realized = predicted + (0.5 if gameweek == 2 else -1.0)
            rows.append(
                {
                    "fold_id": f"{SEASON}-gw{gameweek:02d}",
                    "season": SEASON,
                    "gameweek": gameweek,
                    "player_id": player_id,
                    "team_id": team_id,
                    "position": position,
                    "predicted_points": predicted,
                    "realized_points": realized,
                    "residual": realized - predicted,
                }
            )
    frame = pd.DataFrame(rows, columns=list(RESIDUAL_EXPORT_COLUMNS))
    for column, values in overrides.items():
        frame[column] = values
    return frame


def _manifest(table: pd.DataFrame, **overrides: Any) -> dict[str, object]:
    document: dict[str, object] = {
        "contract_version": "oos_residual_export_v1",
        "candidate_label": "calendar_blind_baseline",
        "model_name": "control-model",
        "model_version": "1.0.0",
        "feature_contract_version": "form_window_v1",
        "training_contract_version": "training_v1",
        "evaluation_objective": "single_gameweek_realized_squad_points_v1",
        "development_seasons": sorted({str(season) for season in table["season"]}),
        "opening_gameweeks_included": bool((table["gameweek"] == 1).any()),
        "fold_count": int(table["fold_id"].nunique()),
        "row_count": len(table),
        "repository_commit": COMMIT,
        "dataset_snapshot_id": SNAPSHOT,
        "table_sha256": "0" * 64,
        "created_at_utc": "2026-08-15T00:00:00Z",
    }
    document.update(overrides)
    return document


def _failed_checks(report: PreflightReport) -> tuple[str, ...]:
    return tuple(finding.check for finding in report.failures)


# --- accepting a valid handoff ----------------------------------------------


def test_a_contract_conforming_export_passes_every_check() -> None:
    table = _table()

    report = run_residual_export_preflight(table, _manifest(table))

    assert report.passed
    assert report.contract_version == PREFLIGHT_CONTRACT_VERSION
    assert report.failures == ()


def test_matching_file_bytes_satisfy_the_checksum_rule(tmp_path: Path) -> None:
    table = _table()
    destination = tmp_path / "export.csv"
    table.to_csv(destination, index=False)
    digest = compute_table_sha256(destination)

    report = run_residual_export_preflight(
        pd.read_csv(destination),
        _manifest(table, table_sha256=digest),
        table_sha256=digest,
    )

    assert report.passed


def test_agreed_expectations_are_confirmed_against_the_manifest() -> None:
    table = _table()

    report = run_residual_export_preflight(
        table,
        _manifest(table),
        expectations=PreflightExpectations(
            fold_count=2,
            row_count=4,
            development_seasons=(SEASON,),
            evaluation_objective="single_gameweek_realized_squad_points_v1",
            repository_commit=COMMIT,
            dataset_snapshot_id=SNAPSHOT,
            opening_gameweeks_included=False,
        ),
    )

    assert report.passed
    assert "expected_fold_count" in {finding.check for finding in report.findings}


# --- rejecting a corrupted or mislabeled artifact ---------------------------


def test_corrupted_file_bytes_fail_the_checksum_check(tmp_path: Path) -> None:
    table = _table()
    destination = tmp_path / "export.csv"
    table.to_csv(destination, index=False)
    manifest = _manifest(table, table_sha256=compute_table_sha256(destination))
    destination.write_bytes(destination.read_bytes() + b"tampered")

    report = run_residual_export_preflight(
        pd.read_csv(destination),
        manifest,
        table_sha256=compute_table_sha256(destination),
    )

    assert "table_checksum_matches_manifest" in _failed_checks(report)


def test_a_missing_manifest_field_is_named() -> None:
    table = _table()
    manifest = _manifest(table)
    del manifest["dataset_snapshot_id"]

    report = run_residual_export_preflight(table, manifest)

    assert "manifest_fields_present" in _failed_checks(report)
    assert any("dataset_snapshot_id" in finding.detail for finding in report.failures)


def test_a_foreign_contract_version_is_rejected() -> None:
    table = _table()

    report = run_residual_export_preflight(
        table, _manifest(table, contract_version="oos_residual_export_v2")
    )

    assert "manifest_contract_version" in _failed_checks(report)


def test_an_abbreviated_repository_commit_is_rejected() -> None:
    table = _table()

    report = run_residual_export_preflight(table, _manifest(table, repository_commit="a0cee7b"))

    assert "manifest_repository_commit" in _failed_checks(report)


def test_a_timestamp_without_an_explicit_utc_offset_is_rejected() -> None:
    table = _table()

    report = run_residual_export_preflight(
        table, _manifest(table, created_at_utc="2026-08-15T00:00:00")
    )

    assert "manifest_created_at_utc" in _failed_checks(report)


def test_declared_fold_and_row_counts_must_describe_the_table() -> None:
    table = _table()

    report = run_residual_export_preflight(
        table, _manifest(table, fold_count=147, row_count=101447)
    )

    failed = _failed_checks(report)
    assert "manifest_fold_count_matches_table" in failed
    assert "manifest_row_count_matches_table" in failed


def test_declared_seasons_must_describe_the_table() -> None:
    table = _table()

    report = run_residual_export_preflight(
        table, _manifest(table, development_seasons=["2021-22", "2022-23"])
    )

    assert "manifest_seasons_match_table" in _failed_checks(report)


def test_a_gw2_export_cannot_be_relabeled_as_opening_evidence() -> None:
    """The opening flag is evidence, not a convenience flag."""

    table = _table()

    report = run_residual_export_preflight(table, _manifest(table, opening_gameweeks_included=True))

    assert "manifest_opening_flag_matches_table" in _failed_checks(report)


def test_undeclared_gw1_rows_are_reported() -> None:
    table = _table(gameweek=[1, 1, 3, 3])
    table["fold_id"] = [f"{SEASON}-gw{int(gameweek):02d}" for gameweek in table["gameweek"]]

    report = run_residual_export_preflight(
        table, _manifest(table, opening_gameweeks_included=False)
    )

    assert "manifest_opening_flag_matches_table" in _failed_checks(report)


# --- rejecting a malformed table --------------------------------------------


def test_reordered_columns_are_rejected_before_row_checks() -> None:
    table = _table().loc[:, list(reversed(RESIDUAL_EXPORT_COLUMNS))]

    report = run_residual_export_preflight(table, _manifest(_table()))

    assert "table_columns" in _failed_checks(report)
    assert "table_key_uniqueness" not in {finding.check for finding in report.findings}


def test_a_repeated_fold_player_key_is_rejected() -> None:
    table = _table(player_id=[101, 101, 202, 202])
    table.loc[1, "player_id"] = 101

    report = run_residual_export_preflight(table, _manifest(table))

    assert "table_key_uniqueness" in _failed_checks(report)


def test_a_fold_id_that_disagrees_with_season_and_gameweek_is_rejected() -> None:
    table = _table()
    table.loc[0, "fold_id"] = f"{SEASON}-gw09"

    report = run_residual_export_preflight(table, _manifest(table))

    assert "table_fold_id_format" in _failed_checks(report)


def test_mixed_player_id_representations_are_rejected() -> None:
    table = _table(player_id=[101, "202", 303, "404"])

    report = run_residual_export_preflight(table, _manifest(table))

    assert "table_player_id_representation" in _failed_checks(report)


def test_a_negative_predicted_point_is_rejected() -> None:
    table = _table()
    table.loc[0, "predicted_points"] = -0.5

    report = run_residual_export_preflight(table, _manifest(table))

    assert "table_predicted_points" in _failed_checks(report)


def test_a_non_finite_realized_point_is_rejected() -> None:
    table = _table()
    table.loc[0, "realized_points"] = float("nan")

    report = run_residual_export_preflight(table, _manifest(table))

    assert "table_realized_points" in _failed_checks(report)


def test_a_broken_residual_identity_is_rejected() -> None:
    table = _table()
    table.loc[0, "residual"] = 99.0

    report = run_residual_export_preflight(table, _manifest(table))

    assert "table_residual_identity" in _failed_checks(report)


def test_an_unsorted_export_is_rejected() -> None:
    table = _table().iloc[::-1].reset_index(drop=True)

    report = run_residual_export_preflight(table, _manifest(table))

    assert "table_sort_order" in _failed_checks(report)


def test_an_unknown_position_is_rejected() -> None:
    table = _table()
    table.loc[0, "position"] = "STRIKER"

    report = run_residual_export_preflight(table, _manifest(table))

    assert "table_identity_values" in _failed_checks(report)


def test_disagreeing_expectations_are_reported() -> None:
    table = _table()

    report = run_residual_export_preflight(
        table,
        _manifest(table),
        expectations=PreflightExpectations(fold_count=147, repository_commit="b" * 40),
    )

    failed = _failed_checks(report)
    assert "expected_fold_count" in failed
    assert "expected_repository_commit" in failed


# --- the pairing rule -------------------------------------------------------


def _pair() -> tuple[pd.DataFrame, dict[str, object], pd.DataFrame, dict[str, object]]:
    reference = _table()
    candidate = _table()
    candidate["predicted_points"] = candidate["predicted_points"] + 0.25
    candidate["residual"] = candidate["realized_points"] - candidate["predicted_points"]
    reference_manifest = _manifest(reference, candidate_label="calendar_blind_baseline")
    candidate_manifest = _manifest(
        candidate,
        candidate_label="calendar_aware_candidate",
        model_name="candidate-model",
        model_version="2.0.0",
    )
    return reference, reference_manifest, candidate, candidate_manifest


def test_a_matched_pair_with_shared_outcomes_passes() -> None:
    reference, reference_manifest, candidate, candidate_manifest = _pair()

    report = run_export_pair_preflight(reference, reference_manifest, candidate, candidate_manifest)

    assert report.passed


def test_two_exports_with_the_same_label_cannot_form_a_pair() -> None:
    reference, reference_manifest, candidate, candidate_manifest = _pair()
    candidate_manifest["candidate_label"] = reference_manifest["candidate_label"]

    report = run_export_pair_preflight(reference, reference_manifest, candidate, candidate_manifest)

    assert "pair_labels_differ" in _failed_checks(report)


def test_exports_from_different_commits_cannot_form_a_pair() -> None:
    reference, reference_manifest, candidate, candidate_manifest = _pair()
    candidate_manifest["repository_commit"] = "b" * 40

    report = run_export_pair_preflight(reference, reference_manifest, candidate, candidate_manifest)

    assert "pair_repository_commit" in _failed_checks(report)


def test_a_missing_fold_is_a_fold_policy_failure_not_an_intersection() -> None:
    reference, reference_manifest, candidate, candidate_manifest = _pair()
    candidate = candidate.loc[candidate["gameweek"] != 3].reset_index(drop=True)

    report = run_export_pair_preflight(reference, reference_manifest, candidate, candidate_manifest)

    failed = _failed_checks(report)
    assert "pair_fold_policy" in failed
    assert "pair_row_keys" in failed


def test_a_missing_player_row_is_reported_from_both_sides() -> None:
    reference, reference_manifest, candidate, candidate_manifest = _pair()
    candidate = candidate.drop(index=0).reset_index(drop=True)

    report = run_export_pair_preflight(reference, reference_manifest, candidate, candidate_manifest)

    assert "pair_row_keys" in _failed_checks(report)


def test_disagreeing_realized_points_break_the_pair() -> None:
    """Two exports that disagree on outcomes cannot describe the same folds."""

    reference, reference_manifest, candidate, candidate_manifest = _pair()
    candidate.loc[0, "realized_points"] = 99.0
    candidate.loc[0, "residual"] = 99.0 - float(candidate.loc[0, "predicted_points"])

    report = run_export_pair_preflight(reference, reference_manifest, candidate, candidate_manifest)

    assert "pair_realized_points" in _failed_checks(report)


def test_disagreeing_team_identity_breaks_the_pair() -> None:
    reference, reference_manifest, candidate, candidate_manifest = _pair()
    candidate.loc[0, "team_id"] = "Gamma"

    report = run_export_pair_preflight(reference, reference_manifest, candidate, candidate_manifest)

    assert "pair_row_identity" in _failed_checks(report)


def test_disagreeing_dataset_snapshots_break_the_pair() -> None:
    reference, reference_manifest, candidate, candidate_manifest = _pair()
    candidate_manifest["dataset_snapshot_id"] = "archive@other-pin"

    report = run_export_pair_preflight(reference, reference_manifest, candidate, candidate_manifest)

    assert "pair_dataset_snapshot" in _failed_checks(report)


# --- the report and its serializations --------------------------------------


def test_the_report_names_every_check_it_ran() -> None:
    table = _table()

    report = run_residual_export_preflight(table, _manifest(table))
    document = preflight_report_to_dict(report)
    markdown = preflight_report_to_markdown(report)

    assert document["passed"] is True
    assert document["contract_version"] == PREFLIGHT_CONTRACT_VERSION
    findings = document["findings"]
    assert isinstance(findings, list)
    assert {entry["check"] for entry in findings if isinstance(entry, dict)} == {
        finding.check for finding in report.findings
    }
    assert "PASSED" in markdown
    assert "table_residual_identity" in markdown


def test_a_report_without_findings_is_invalid() -> None:
    with pytest.raises(PreflightError, match="non-empty tuple"):
        PreflightReport(artifact_label="empty", findings=())


def test_unusable_inputs_raise_instead_of_reporting() -> None:
    with pytest.raises(PreflightError, match="DataFrame"):
        run_residual_export_preflight("not a table", _manifest(_table()))  # type: ignore[arg-type]


# --- the command-line gate --------------------------------------------------


def _write_export(
    directory: Path, name: str, table: pd.DataFrame, **overrides: Any
) -> tuple[Path, Path]:
    table_path = directory / f"{name}.csv"
    table.to_csv(table_path, index=False)
    manifest = _manifest(table, table_sha256=compute_table_sha256(table_path), **overrides)
    manifest_path = directory / f"{name}.manifest.json"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    return table_path, manifest_path


def _run_cli(monkeypatch: pytest.MonkeyPatch, *args: str) -> int:
    monkeypatch.setattr(sys, "argv", ["run_artifact_preflight", *args])
    return preflight_cli.main()


def test_the_cli_accepts_a_valid_pair_and_writes_its_record(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    reference, _, candidate, _ = _pair()
    reference_table, reference_manifest = _write_export(tmp_path, "reference", reference)
    candidate_table, candidate_manifest = _write_export(
        tmp_path,
        "candidate",
        candidate,
        candidate_label="calendar_aware_candidate",
        model_name="candidate-model",
    )
    record = tmp_path / "preflight.json"

    exit_code = _run_cli(
        monkeypatch,
        "--table",
        str(candidate_table),
        "--manifest",
        str(candidate_manifest),
        "--reference-table",
        str(reference_table),
        "--reference-manifest",
        str(reference_manifest),
        "--expect-fold-count",
        "2",
        "--json-output",
        str(record),
    )

    assert exit_code == 0
    document = json.loads(record.read_text(encoding="utf-8"))
    assert document["passed"] is True
    assert len(document["reports"]) == 3


def test_the_cli_fails_a_tampered_table(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    table = _table()
    table_path, manifest_path = _write_export(tmp_path, "export", table)
    table_path.write_bytes(table_path.read_bytes() + b"\n")

    exit_code = _run_cli(monkeypatch, "--table", str(table_path), "--manifest", str(manifest_path))

    assert exit_code == 1


def test_the_cli_refuses_half_a_reference_pair(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    table = _table()
    table_path, manifest_path = _write_export(tmp_path, "export", table)

    exit_code = _run_cli(
        monkeypatch,
        "--table",
        str(table_path),
        "--manifest",
        str(manifest_path),
        "--reference-table",
        str(table_path),
    )

    assert exit_code == 2


def test_the_cli_reports_a_missing_file_as_an_error(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    exit_code = _run_cli(
        monkeypatch,
        "--table",
        str(tmp_path / "missing.csv"),
        "--manifest",
        str(tmp_path / "missing.json"),
    )

    assert exit_code == 1
