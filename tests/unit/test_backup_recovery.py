"""Backup and restore must prove complete byte sets without overwriting live data."""

import hashlib
import json
from pathlib import Path
from typing import Any

import pytest

from squadopt.platform import backup_recovery as backup


@pytest.fixture
def sources(tmp_path: Path) -> dict[str, Path]:
    roots = {name: tmp_path / name for name in ("snapshots", "ledger", "empty")}
    for root in roots.values():
        root.mkdir()
    (roots["snapshots"] / "capture").mkdir()
    (roots["snapshots"] / "capture" / "bytes.bin").write_bytes(bytes(range(256)))
    (roots["ledger"] / "record.json").write_bytes('{"value":"ş"}\n'.encode())
    return roots


def test_round_trip_preserves_all_bytes_and_empty_roots(
    sources: dict[str, Path], tmp_path: Path
) -> None:
    directory, restored = tmp_path / "backup", tmp_path / "restored"
    receipt = backup.create_backup(sources, directory, writers_stopped=True)
    assert backup.verify_backup(directory, manifest_sha256=receipt.manifest_sha256) == receipt
    assert (
        backup.restore_backup(
            directory, restored, manifest_sha256=receipt.manifest_sha256, writers_stopped=True
        )
        == receipt
    )
    assert receipt.file_count == 2
    assert receipt.total_bytes == 256 + len('{"value":"ş"}\n'.encode())
    assert (restored / "empty").is_dir()
    for name, root in sources.items():
        for file in root.rglob("*"):
            if file.is_file():
                assert (restored / name / file.relative_to(root)).read_bytes() == file.read_bytes()
    raw = (directory / backup.MANIFEST_NAME).read_text(encoding="utf-8")
    assert str(tmp_path) not in raw  # Machine-specific source locations are not restored.


def test_backup_requires_explicit_quiescence(sources: dict[str, Path], tmp_path: Path) -> None:
    with pytest.raises(backup.BackupError, match="Stop every writer"):
        backup.create_backup(sources, tmp_path / "backup", writers_stopped=False)
    assert not (tmp_path / "backup").exists()


@pytest.mark.parametrize("kind", ["contents", "missing", "extra", "manifest", "receipt"])
def test_corruption_is_refused_before_any_restore_write(
    sources: dict[str, Path], tmp_path: Path, kind: str
) -> None:
    directory, restored = tmp_path / "backup", tmp_path / "restored"
    receipt = backup.create_backup(sources, directory, writers_stopped=True)
    digest = receipt.manifest_sha256
    file = directory / "files" / "ledger" / "record.json"
    if kind == "contents":
        file.write_bytes(b"corrupt")
    elif kind == "missing":
        file.unlink()
    elif kind == "extra":
        (file.parent / "unrecorded").write_bytes(b"extra")
    elif kind == "manifest":
        (directory / backup.MANIFEST_NAME).write_bytes(b"{}")
    else:
        digest = "0" * 64
    with pytest.raises(backup.BackupError):
        backup.restore_backup(directory, restored, manifest_sha256=digest, writers_stopped=True)
    assert not restored.exists()
    assert (sources["ledger"] / "record.json").read_text(encoding="utf-8") == '{"value":"ş"}\n'


@pytest.mark.parametrize(
    "location",
    [
        "../escape",
        "/absolute",
        "root/../../escape",
        "C:/escape",
        "ledger/record.json:stream",
        "ledger/CON",
        "ledger\\escape",
    ],
)
def test_even_a_rehashed_malformed_manifest_cannot_escape_target(
    sources: dict[str, Path], tmp_path: Path, location: str
) -> None:
    directory = tmp_path / "backup"
    backup.create_backup(sources, directory, writers_stopped=True)
    path = directory / backup.MANIFEST_NAME
    document = json.loads(path.read_bytes())
    document["files"][0]["path"] = location
    raw = json.dumps(document).encode()
    path.write_bytes(raw)
    with pytest.raises(backup.BackupError):
        backup.restore_backup(
            directory,
            tmp_path / "restored",
            manifest_sha256=hashlib.sha256(raw).hexdigest(),
            writers_stopped=True,
        )
    assert not (tmp_path / "restored").exists()


def test_existing_destination_is_not_overwritten(sources: dict[str, Path], tmp_path: Path) -> None:
    directory = tmp_path / "backup"
    receipt = backup.create_backup(sources, directory, writers_stopped=True)
    target = tmp_path / "restored"
    target.mkdir()
    (target / "keep").write_bytes(b"keep")
    with pytest.raises(backup.BackupError, match="empty"):
        backup.restore_backup(
            directory, target, manifest_sha256=receipt.manifest_sha256, writers_stopped=True
        )
    with pytest.raises(backup.BackupError, match="empty"):
        backup.create_backup(sources, directory, writers_stopped=True)
    assert (target / "keep").read_bytes() == b"keep"
    assert backup.verify_backup(directory, manifest_sha256=receipt.manifest_sha256) == receipt


@pytest.mark.parametrize("case_variant", [False, True])
def test_duplicate_manifest_path_is_rejected_before_restore(
    sources: dict[str, Path], tmp_path: Path, case_variant: bool
) -> None:
    directory = tmp_path / "backup"
    backup.create_backup(sources, directory, writers_stopped=True)
    path = directory / backup.MANIFEST_NAME
    document = json.loads(path.read_bytes())
    duplicate = dict(document["files"][0])
    if case_variant:
        duplicate["path"] = duplicate["path"].upper()
    document["files"].append(duplicate)
    raw = json.dumps(document).encode()
    path.write_bytes(raw)
    with pytest.raises(backup.BackupError, match="duplicate or colliding"):
        backup.restore_backup(
            directory,
            tmp_path / "restored",
            manifest_sha256=hashlib.sha256(raw).hexdigest(),
            writers_stopped=True,
        )
    assert not (tmp_path / "restored").exists()


def test_backup_changes_after_prevalidation_are_refused_during_restore_copy(
    sources: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    directory = tmp_path / "backup"
    receipt = backup.create_backup(sources, directory, writers_stopped=True)
    original = backup._copy

    def tamper_after_verification(source: Path, destination: Path, row: Any) -> None:
        source.write_bytes(source.read_bytes() + b"modified after verification")
        original(source, destination, row)

    monkeypatch.setattr(backup, "_copy", tamper_after_verification)
    with pytest.raises(backup.BackupError, match="changed during copy"):
        backup.restore_backup(
            directory,
            tmp_path / "restored",
            manifest_sha256=receipt.manifest_sha256,
            writers_stopped=True,
        )
    assert (sources["ledger"] / "record.json").read_text(encoding="utf-8") == '{"value":"ş"}\n'


def test_overlapping_roots_or_destination_are_refused(
    sources: dict[str, Path], tmp_path: Path
) -> None:
    with pytest.raises(backup.BackupError, match="overlap"):
        backup.create_backup(sources, sources["ledger"] / "backup", writers_stopped=True)
    with pytest.raises(backup.BackupError, match="overlap"):
        backup.create_backup(
            {"parent": tmp_path, "child": sources["ledger"]},
            tmp_path.parent / "unused",
            writers_stopped=True,
        )


def test_changed_source_never_gets_a_completion_manifest(
    sources: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = backup._copy

    def change(source: Path, destination: Path, row: Any) -> None:
        original(source, destination, row)
        source.write_bytes(source.read_bytes() + b"changed")

    monkeypatch.setattr(backup, "_copy", change)
    directory = tmp_path / "backup"
    with pytest.raises(backup.BackupError, match="changed"):
        backup.create_backup(sources, directory, writers_stopped=True)
    assert not (directory / backup.MANIFEST_NAME).exists()


def test_interrupted_copy_remains_incomplete_and_does_not_overwrite_on_retry(
    sources: dict[str, Path], tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    original = backup._copy
    directory = tmp_path / "backup"
    receipt = backup.create_backup(sources, directory, writers_stopped=True)

    def interrupted(source: Path, destination: Path, row: Any) -> None:
        original(source, destination, row)
        raise OSError("injected interrupted copy")

    monkeypatch.setattr(backup, "_copy", interrupted)
    failed_backup = tmp_path / "failed-backup"
    with pytest.raises(OSError, match="interrupted"):
        backup.create_backup(sources, failed_backup, writers_stopped=True)
    assert not (failed_backup / backup.MANIFEST_NAME).exists()
    target = tmp_path / "restored"
    with pytest.raises(OSError, match="interrupted"):
        backup.restore_backup(
            directory, target, manifest_sha256=receipt.manifest_sha256, writers_stopped=True
        )
    with pytest.raises(backup.BackupError, match="empty"):
        backup.restore_backup(
            directory, target, manifest_sha256=receipt.manifest_sha256, writers_stopped=True
        )
    assert backup.verify_backup(directory, manifest_sha256=receipt.manifest_sha256) == receipt


def test_symlink_source_and_destination_ancestors_are_refused(
    sources: dict[str, Path], tmp_path: Path
) -> None:
    link = tmp_path / "linked"
    try:
        link.symlink_to(sources["ledger"], target_is_directory=True)
    except OSError as error:
        pytest.skip(f"Host does not permit synthetic symlinks: {error}")
    with pytest.raises(backup.BackupError, match="Symlink/reparse"):
        backup.create_backup({"linked": link}, tmp_path / "backup", writers_stopped=True)
    with pytest.raises(backup.BackupError, match="Symlink/reparse"):
        backup.create_backup({"ledger": sources["ledger"]}, link / "backup", writers_stopped=True)


def test_cli_receipt_round_trip_and_nonzero_failure(
    sources: dict[str, Path], tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    destination = tmp_path / "backup"
    assert (
        backup.main(
            [
                "create",
                "--root",
                f"ledger={sources['ledger']}",
                "--destination",
                str(destination),
                "--writers-stopped",
            ]
        )
        == 0
    )
    receipt = json.loads(capsys.readouterr().out)
    assert receipt["status"] == "verified"
    assert (
        backup.main(
            [
                "restore",
                "--backup",
                str(destination),
                "--destination",
                str(tmp_path / "restored"),
                "--manifest-sha256",
                receipt["manifest_sha256"],
                "--writers-stopped",
            ]
        )
        == 0
    )
    capsys.readouterr()
    assert (
        backup.main(
            [
                "verify",
                "--backup",
                str(destination),
                "--manifest-sha256",
                "0" * 64,
            ]
        )
        == 1
    )
    assert json.loads(capsys.readouterr().out)["status"] == "failed"
