"""The export and the reader, against each other.

The reader's refusals are tested by damaging a pair the exporter actually wrote, rather than
one assembled here. A hand-built pair can be wrong in the same way the reader is -- both
written from the same misreading of the contract -- and then every test passes while nothing
is checked. A pair that came out of the writer cannot share that mistake.
"""

import json
from collections.abc import Sequence
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from scripts import export_rotation_evidence
from tests.fixtures.synthetic_rotation_capture import (
    CAPTURED_AT,
    DEADLINE,
    DECISION_SOURCE,
    SEASON,
    TARGET_GAMEWEEK,
    bootstrap_payload,
    fixtures_payload,
    roster_entries,
)

from squadopt.data.errors import DataValidationError
from squadopt.data.snapshots import write_snapshot
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD
from squadopt.features.rotation_evidence import CONTRACT_VERSION, ROTATION_EVIDENCE_COLUMNS
from squadopt.features.rotation_evidence_artifact import read_rotation_evidence_artifact

FIXTURE_PATH = Path(__file__).resolve().parents[2] / "data" / "sample" / "club_news_v1.fixture.json"
COMMIT = "0" * 40


@pytest.fixture(name="clean_tree")
def _clean_tree(monkeypatch: pytest.MonkeyPatch) -> None:
    """A committed working tree, so the export's own refusal is not what is under test."""

    monkeypatch.setattr(export_rotation_evidence, "_git_revision", lambda: (COMMIT, False))


def _written_snapshot(root: Path) -> str:
    metadata = write_snapshot(
        root,
        source=DECISION_SOURCE,
        captured_at_utc=CAPTURED_AT,
        payloads={
            BOOTSTRAP_PAYLOAD: bootstrap_payload(),
            FIXTURES_PAYLOAD: fixtures_payload(),
        },
    )
    return metadata.snapshot_id


def _run(tmp_path: Path, *extra: str) -> tuple[int, str, Path]:
    snapshot_root = tmp_path / "snapshots"
    snapshot_id = _written_snapshot(snapshot_root)
    argv: Sequence[str] = [
        "--season",
        SEASON,
        "--target-gameweek",
        str(TARGET_GAMEWEEK),
        "--deadline-utc",
        DEADLINE,
        "--snapshot",
        snapshot_id,
        "--snapshot-root",
        str(snapshot_root),
        "--club-news-fixture",
        str(FIXTURE_PATH),
        "--output-dir",
        str(tmp_path / "out"),
        *extra,
    ]
    code = export_rotation_evidence.main(argv)
    return code, snapshot_id, tmp_path / "out"


def _pair(output_dir: Path) -> tuple[Path, Path]:
    tables = sorted(output_dir.glob("*.csv"))
    assert len(tables) == 1, sorted(path.name for path in output_dir.iterdir())
    return tables[0], tables[0].with_suffix(".manifest.json")


def _rewrite_manifest(manifest_path: Path, **changes: Any) -> None:
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    document.update(changes)
    manifest_path.write_text(
        json.dumps(document, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )


# --- the export -------------------------------------------------------------


def test_the_export_writes_a_readable_pair(tmp_path: Path, clean_tree: None) -> None:
    code, _, output_dir = _run(tmp_path)
    assert code == 0

    table_path, manifest_path = _pair(output_dir)
    table = read_rotation_evidence_artifact(table_path, manifest_path)

    assert tuple(table.columns) == ROTATION_EVIDENCE_COLUMNS
    assert len(table) == len(roster_entries())
    assert table.attrs["repository_commit"] == COMMIT


def test_the_artifact_name_carries_the_contract_the_week_and_the_capture(
    tmp_path: Path, clean_tree: None
) -> None:
    """A rehearsal earlier in the week is a different artifact from the real run."""

    _, snapshot_id, output_dir = _run(tmp_path)
    table_path, _ = _pair(output_dir)

    assert table_path.stem == (
        f"{CONTRACT_VERSION}_{SEASON}_gw{TARGET_GAMEWEEK:02d}_{snapshot_id[-12:]}"
    )


def test_re_running_on_the_same_inputs_is_a_replay_rather_than_a_rewrite(
    tmp_path: Path, clean_tree: None, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _, output_dir = _run(tmp_path)
    assert code == 0
    table_path, manifest_path = _pair(output_dir)
    before = table_path.read_bytes()
    first_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    capsys.readouterr()

    snapshot_root = tmp_path / "snapshots"
    snapshot_id = sorted(path.name for path in snapshot_root.iterdir())[0]
    code = export_rotation_evidence.main(
        [
            "--season",
            SEASON,
            "--target-gameweek",
            str(TARGET_GAMEWEEK),
            "--deadline-utc",
            DEADLINE,
            "--snapshot",
            snapshot_id,
            "--snapshot-root",
            str(snapshot_root),
            "--club-news-fixture",
            str(FIXTURE_PATH),
            "--output-dir",
            str(output_dir),
        ]
    )

    assert code == 0
    assert "replay" in capsys.readouterr().out
    assert table_path.read_bytes() == before
    # The occupant's own timestamp survives: the artifact on disk is the record.
    assert json.loads(manifest_path.read_text(encoding="utf-8")) == first_manifest


def test_a_different_table_under_the_same_name_is_refused(
    tmp_path: Path, clean_tree: None, capsys: pytest.CaptureFixture[str]
) -> None:
    code, _, output_dir = _run(tmp_path)
    assert code == 0
    table_path, _ = _pair(output_dir)
    table_path.write_bytes(b"contract_version\nsomething-else\n")
    capsys.readouterr()

    code, _, _ = _run(tmp_path / "second", "--output-dir", str(output_dir))

    assert code == 1
    assert "never overwritten in place" in capsys.readouterr().out


def test_no_temporary_file_survives_a_refusal(tmp_path: Path, clean_tree: None) -> None:
    code, _, output_dir = _run(tmp_path)
    assert code == 0
    table_path, _ = _pair(output_dir)
    table_path.write_bytes(b"contract_version\nsomething-else\n")

    _run(tmp_path / "second", "--output-dir", str(output_dir))

    assert [path.name for path in output_dir.iterdir() if path.name.startswith(".")] == []


def test_the_export_refuses_a_dirty_working_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The commit it records would not reproduce the bytes, so it does not record one."""

    monkeypatch.setattr(export_rotation_evidence, "_git_revision", lambda: (COMMIT, True))

    code, _, output_dir = _run(tmp_path)

    assert code == 1
    assert "uncommitted changes" in capsys.readouterr().out
    assert not output_dir.exists()


# --- what the reader refuses ------------------------------------------------


@pytest.fixture(name="published")
def _published(tmp_path: Path, clean_tree: None) -> tuple[Path, Path]:
    code, _, output_dir = _run(tmp_path)
    assert code == 0
    return _pair(output_dir)


def test_an_edited_table_is_refused_before_it_is_parsed(
    published: tuple[Path, Path],
) -> None:
    """A parse error would report a malformed column; the real fact is edited bytes."""

    table_path, manifest_path = published
    table_path.write_bytes(table_path.read_bytes().replace(b"never_flagged", b"neveR_flagged"))

    with pytest.raises(DataValidationError, match="not the bytes that were"):
        read_rotation_evidence_artifact(table_path, manifest_path)


def test_a_manifest_missing_a_required_field_is_refused(
    published: tuple[Path, Path],
) -> None:
    table_path, manifest_path = published
    document = json.loads(manifest_path.read_text(encoding="utf-8"))
    del document["roster_size"]
    manifest_path.write_text(json.dumps(document, indent=2, sort_keys=True), encoding="utf-8")

    with pytest.raises(DataValidationError, match="missing required manifest field"):
        read_rotation_evidence_artifact(table_path, manifest_path)


def test_a_row_count_that_is_not_the_roster_size_is_refused(
    published: tuple[Path, Path],
) -> None:
    """The completeness identity. One row per roster player, always."""

    table_path, manifest_path = published
    _rewrite_manifest(manifest_path, roster_size=len(roster_entries()) + 1)

    with pytest.raises(DataValidationError, match="one row per roster player"):
        read_rotation_evidence_artifact(table_path, manifest_path)


def test_a_manifest_that_disagrees_with_a_column_is_refused(
    published: tuple[Path, Path],
) -> None:
    table_path, manifest_path = published
    _rewrite_manifest(manifest_path, season="2019-20")

    with pytest.raises(DataValidationError, match="while the manifest declares"):
        read_rotation_evidence_artifact(table_path, manifest_path)


def _republish(table: pd.DataFrame, table_path: Path, manifest_path: Path) -> None:
    """Write a damaged table back with a manifest whose digest and counts still agree.

    Without this, every mutation below would be caught by the digest check and none of the
    later checks would ever run -- so the tests would pass while measuring one guard.
    """

    payload = table.to_csv(index=False, lineterminator="\n").encode("utf-8")
    table_path.write_bytes(payload)
    import hashlib

    _rewrite_manifest(
        manifest_path,
        table_sha256=hashlib.sha256(payload).hexdigest(),
        row_count=len(table),
    )


def test_a_reordered_column_is_refused(published: tuple[Path, Path]) -> None:
    table_path, manifest_path = published
    table = pd.read_csv(table_path)
    reordered = table[[*ROTATION_EVIDENCE_COLUMNS[1:], ROTATION_EVIDENCE_COLUMNS[0]]]
    _republish(reordered, table_path, manifest_path)

    with pytest.raises(DataValidationError, match="declared order"):
        read_rotation_evidence_artifact(table_path, manifest_path)


def test_a_disposition_outside_the_vocabulary_is_refused(
    published: tuple[Path, Path],
) -> None:
    table_path, manifest_path = published
    table = pd.read_csv(table_path)
    first = table.index[table["rotation_claim_observed"].astype("boolean").fillna(False)][0]
    table.loc[first, "rotation_disposition"] = "probably_starting"
    _republish(table, table_path, manifest_path)

    with pytest.raises(DataValidationError, match="outside its closed vocabulary"):
        read_rotation_evidence_artifact(table_path, manifest_path)


def test_a_disposition_on_a_row_that_observed_nothing_is_refused(
    published: tuple[Path, Path],
) -> None:
    """The absent/zero separator, checked on read as well as written on build."""

    table_path, manifest_path = published
    table = pd.read_csv(table_path)
    unobserved = table.index[~table["rotation_claim_observed"].astype("boolean").fillna(True)][0]
    table.loc[unobserved, "rotation_disposition"] = "no_statement"
    _republish(table, table_path, manifest_path)

    with pytest.raises(DataValidationError, match="disagrees with"):
        read_rotation_evidence_artifact(table_path, manifest_path)


def test_a_missing_observation_flag_is_refused(published: tuple[Path, Path]) -> None:
    table_path, manifest_path = published
    table = pd.read_csv(table_path)
    # Read back, the flag arrives as a plain bool column that cannot hold a missing value --
    # which is itself the property under test. Widened here so the damaged table can exist at
    # all, and the reader is what has to notice it.
    table["rotation_claim_observed"] = table["rotation_claim_observed"].astype("object")
    table.loc[0, "rotation_claim_observed"] = None
    _republish(table, table_path, manifest_path)

    with pytest.raises(DataValidationError, match="collapse the very distinction"):
        read_rotation_evidence_artifact(table_path, manifest_path)


def test_a_capture_that_does_not_predate_the_deadline_is_refused(
    published: tuple[Path, Path],
) -> None:
    table_path, manifest_path = published
    table = pd.read_csv(table_path)
    table["captured_at_utc"] = table["deadline_timestamp_utc"]
    _republish(table, table_path, manifest_path)

    with pytest.raises(DataValidationError, match="strictly earlier"):
        read_rotation_evidence_artifact(table_path, manifest_path)


def test_a_row_claiming_an_input_the_manifest_does_not_declare_is_refused(
    published: tuple[Path, Path],
) -> None:
    """Provenance is per row here, so the manifest carries the union of what rows used."""

    table_path, manifest_path = published
    table = pd.read_csv(table_path)
    table.loc[0, "source_snapshot_ids"] = "some-other-capture-000000000000"
    _republish(table, table_path, manifest_path)

    with pytest.raises(DataValidationError, match="declares"):
        read_rotation_evidence_artifact(table_path, manifest_path)


def test_a_manifest_naming_another_table_is_refused(published: tuple[Path, Path]) -> None:
    table_path, manifest_path = published
    _rewrite_manifest(manifest_path, table_file="somebody_elses_table.csv")

    with pytest.raises(DataValidationError, match="was read beside"):
        read_rotation_evidence_artifact(table_path, manifest_path)


def test_coverage_beyond_what_was_declared_is_refused(published: tuple[Path, Path]) -> None:
    table_path, manifest_path = published
    _rewrite_manifest(manifest_path, clubs_covered=["Arsenal", "Nowhere FC"])

    with pytest.raises(DataValidationError, match="never declared"):
        read_rotation_evidence_artifact(table_path, manifest_path)
