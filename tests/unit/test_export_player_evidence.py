"""The evidence export: contract-checked, deterministic, create-once and identity-free.

Every fixture is synthetic and comes from the evidence tests' reserved blocks (entries
900001+, codes 700001+, placeholder names). The tests assert what the artifact pair must be
for Phase C, not how the writer arrives at it.
"""

import hashlib
import json
import sys
from pathlib import Path

import pandas as pd
import pytest
import tests.unit.test_player_evidence as evidence_tests
from scripts import export_player_evidence as export

from squadopt.data.errors import DataError, DataValidationError
from squadopt.data.snapshots import write_snapshot
from squadopt.features.evidence import CONTRACT_VERSION, EVIDENCE_COLUMNS

COMMIT = "0" * 40
WHEN = "2026-09-02T12:00:00Z"
MANIFEST_KEYS = {
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


def _export(table: pd.DataFrame, directory: Path, name: str = "evidence") -> export.ExportResult:
    return export.write_evidence_artifact(
        table, directory, name, repository_commit=COMMIT, generated_at_utc=WHEN
    )


def _read_manifest(path: Path) -> dict[str, object]:
    document = json.loads(path.read_text(encoding="utf-8"))
    assert isinstance(document, dict)
    return document


def test_a_valid_table_exports_a_csv_and_a_manifest_that_describes_it(tmp_path: Path) -> None:
    table = evidence_tests._build()

    result = _export(table, tmp_path)

    assert result.table_path == tmp_path / "evidence.csv"
    assert result.manifest_path == tmp_path / "evidence.manifest.json"
    manifest = _read_manifest(result.manifest_path)
    assert set(manifest) == MANIFEST_KEYS
    assert manifest["contract_version"] == CONTRACT_VERSION
    assert manifest["artifact_contract_version"] == "player_evidence_export_v1"
    assert manifest["season"] == evidence_tests.SEASON
    assert manifest["target_gameweek"] == evidence_tests.TARGET
    assert manifest["deadline_timestamp_utc"] == evidence_tests.DEADLINE
    assert manifest["row_count"] == len(table)
    assert manifest["cohort_size"] == evidence_tests.COHORT
    assert manifest["elite_members_observed"] == evidence_tests.COHORT
    assert manifest["elite_members_missing_picks"] == 0
    assert manifest["table_file"] == "evidence.csv"
    assert manifest["repository_commit"] == COMMIT
    assert manifest["cohort_snapshot_id"] == table.attrs["cohort_snapshot_id"]
    assert manifest["ownership_snapshot_id"] == table.attrs["ownership_snapshot_id"]
    assert manifest["source_snapshot_ids"] == sorted(
        set(table["source_snapshot_ids"].iloc[0].split(";"))
    )


def test_the_csv_keeps_the_contract_columns_and_writes_missing_as_empty(tmp_path: Path) -> None:
    """A missing count is an empty cell; a real zero is ``0``; a false flag is ``False``."""

    cohort = evidence_tests._cohort_snapshot()
    unobserved = evidence_tests._build(snapshots=[cohort], cohort_snapshot=cohort)
    observed = evidence_tests._build()

    blank = _export(unobserved, tmp_path / "unobserved").table_path.read_text(encoding="utf-8")
    full = _export(observed, tmp_path / "observed").table_path.read_text(encoding="utf-8")

    header = blank.splitlines()[0].split(",")
    assert header == list(EVIDENCE_COLUMNS), "no index column, contract order"
    count = header.index("elite_squad_count_lag1")
    flag = header.index("elite_evidence_observed")
    first = blank.splitlines()[1].split(",")
    assert first[count] == "" and first[flag] == "False"
    unheld = next(
        row.split(",")
        for row in full.splitlines()[1:]
        if row.split(",")[header.index("player_id")] == str(evidence_tests.FIRST_CODE + 19)
    )
    assert unheld[count] == "0" and unheld[flag] == "True"
    assert "\r" not in blank and "\r" not in full


def test_the_aggregate_diagnostics_travel_from_attrs_to_the_manifest(tmp_path: Path) -> None:
    cohort = evidence_tests._cohort_snapshot()
    picks = evidence_tests._snapshot(
        "fpl-elite-picks",
        evidence_tests.BEFORE,
        {
            evidence_tests.entry_picks_payload(
                evidence_tests.FIRST_ENTRY + rank, evidence_tests.TARGET - 1
            ): evidence_tests._picks(elements=[999, *range(2, 16)], captain=2, vice=3)
            for rank in (1, 2)
        },
    )
    table = evidence_tests._build(snapshots=[cohort, picks], cohort_snapshot=cohort)

    manifest = _read_manifest(_export(table, tmp_path).manifest_path)

    assert manifest["elite_members_observed"] == 2
    assert manifest["elite_members_missing_picks"] == evidence_tests.COHORT - 2
    assert manifest["unmapped_picked_elements"] == [999]
    assert set(manifest["source_snapshot_ids"]) == {
        cohort.metadata.snapshot_id,
        picks.metadata.snapshot_id,
    }


def test_the_checksum_is_the_digest_of_the_csv_bytes(tmp_path: Path) -> None:
    result = _export(evidence_tests._build(), tmp_path)

    digest = hashlib.sha256(result.table_path.read_bytes()).hexdigest()
    assert result.table_sha256 == digest
    assert _read_manifest(result.manifest_path)["table_sha256"] == digest


@pytest.mark.parametrize(
    "corruption",
    [
        "contract_version",
        "duplicate_player",
        "missing_attr",
        "two_seasons",
        "empty",
        "extra_column",
    ],
)
def test_a_table_that_breaks_its_contract_is_refused_before_anything_is_written(
    tmp_path: Path, corruption: str
) -> None:
    table = evidence_tests._build()
    attrs = dict(table.attrs)
    if corruption == "contract_version":
        table["contract_version"] = "player_evidence_v0"
    elif corruption == "duplicate_player":
        table = pd.concat([table, table.iloc[[0]]], ignore_index=True)
    elif corruption == "missing_attr":
        attrs.pop("elite_members_missing_picks")
    elif corruption == "two_seasons":
        table.loc[0, "season"] = "2025-26"
    elif corruption == "empty":
        table = table.iloc[0:0]
    elif corruption == "extra_column":
        table["entry_id"] = 900_001
    table.attrs = attrs

    with pytest.raises(DataValidationError):
        _export(table, tmp_path)

    assert list(tmp_path.iterdir()) == []


def test_the_same_table_exports_the_same_bytes_and_the_same_digest(tmp_path: Path) -> None:
    table = evidence_tests._build()

    first = _export(table, tmp_path / "one")
    second = _export(evidence_tests._build(), tmp_path / "two")

    assert first.table_path.read_bytes() == second.table_path.read_bytes()
    assert first.table_sha256 == second.table_sha256
    assert export._canonical(_read_manifest(first.manifest_path)) == export._canonical(
        _read_manifest(second.manifest_path)
    )


def test_an_existing_different_artifact_is_never_overwritten(tmp_path: Path) -> None:
    """Same bytes again is a no-op; different bytes under the same name is a refusal."""

    cohort = evidence_tests._cohort_snapshot()
    observed = evidence_tests._build()
    unobserved = evidence_tests._build(snapshots=[cohort], cohort_snapshot=cohort)

    first = _export(observed, tmp_path)
    original = first.table_path.read_bytes()
    again = _export(observed, tmp_path)
    with pytest.raises(DataError, match="never overwritten"):
        _export(unobserved, tmp_path)

    assert again.table_sha256 == first.table_sha256
    assert first.table_path.read_bytes() == original
    assert not list(tmp_path.glob(".*.tmp-*")), "no temporary file survives"


def test_the_cli_exports_from_the_snapshot_store_and_names_no_identity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    root = tmp_path / "snapshots"
    cohort_id = write_snapshot(
        root,
        source="fpl-top200",
        captured_at_utc=evidence_tests.BEFORE,
        payloads={
            evidence_tests.BOOTSTRAP_PAYLOAD: evidence_tests._bootstrap(),
            evidence_tests.league_standings_page_payload(314, 1): evidence_tests._standings_page(),
        },
    ).snapshot_id
    picks_id = write_snapshot(
        root,
        source="fpl-elite-picks",
        captured_at_utc=evidence_tests.BEFORE,
        payloads=dict(evidence_tests._picks_snapshot(evidence_tests.TARGET - 1).payloads),
    ).snapshot_id
    monkeypatch.setattr(export, "_git_revision", lambda: (COMMIT, False))
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "export_player_evidence",
            "--season",
            evidence_tests.SEASON,
            "--target-gameweek",
            str(evidence_tests.TARGET),
            "--deadline-utc",
            evidence_tests.DEADLINE,
            "--snapshot-root",
            str(root),
            "--cohort-snapshot",
            cohort_id,
            "--snapshot",
            picks_id,
            "--cohort-size",
            "50",
            "--output-dir",
            str(tmp_path / "out"),
        ],
    )

    assert export.main() == 0

    out = capsys.readouterr().out
    written = sorted(path.name for path in (tmp_path / "out").iterdir())
    stem = f"{CONTRACT_VERSION}_{evidence_tests.SEASON}_gw{evidence_tests.TARGET:02d}_top50"
    assert written == [f"{stem}.csv", f"{stem}.manifest.json"]
    identities = ["Placeholder Manager", "Placeholder Squad"] + [
        str(evidence_tests.FIRST_ENTRY + rank) for rank in range(1, evidence_tests.COHORT + 1)
    ]
    for text in (
        out,
        (tmp_path / "out" / f"{stem}.csv").read_text(encoding="utf-8"),
        (tmp_path / "out" / f"{stem}.manifest.json").read_text(encoding="utf-8"),
    ):
        assert not any(identity in text for identity in identities)
    assert "members observed  4" in out and "members missing   46" in out
