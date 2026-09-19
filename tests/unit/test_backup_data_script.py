"""Run the backup only against disposable repositories and destination directories."""

from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
from pathlib import Path

import pytest

POWERSHELL = shutil.which("powershell.exe")
pytestmark = pytest.mark.skipif(
    POWERSHELL is None or shutil.which("git") is None, reason="requires PowerShell 5.1 and Git"
)
SCRIPT = Path(__file__).resolve().parents[2] / "scripts/backup_data.ps1"
TREES = ("snapshots", "ledger", "handoffs", "advice_records", "entries")


def _git(repo: Path, *args: str) -> None:
    subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


@pytest.fixture
def backup(tmp_path: Path) -> tuple[Path, Path]:
    repo = tmp_path / "fixture repo"
    (repo / "scripts").mkdir(parents=True)
    shutil.copyfile(SCRIPT, repo / "scripts/backup_data.ps1")
    _git(repo, "init", "--quiet")
    for tree in (*TREES, "runtime", "raw"):
        folder = repo / "data" / tree
        folder.mkdir(parents=True)
        (folder / "record.json").write_text(tree, encoding="ascii")
    destination = tmp_path / "backup destination"
    destination.mkdir()
    return repo, destination


def _run(repo: Path, destination: Path, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [
            str(POWERSHELL),
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-File",
            str(repo / "scripts/backup_data.ps1"),
            "-Destination",
            str(destination),
            *args,
        ],
        capture_output=True,
        text=True,
        timeout=30,
    )


def test_script_parses_as_ascii_powershell() -> None:
    SCRIPT.read_text(encoding="ascii")
    quoted = str(SCRIPT).replace("'", "''")
    command = (
        "$tokens=$null; $errors=$null; "
        f"$null=[System.Management.Automation.Language.Parser]::ParseFile('{quoted}',"
        "[ref]$tokens,[ref]$errors); if ($errors.Count) {throw ($errors | Out-String)}"
    )
    subprocess.run([str(POWERSHELL), "-NoProfile", "-Command", command], check=True)


def test_dry_run_then_additive_backup_and_verify(backup: tuple[Path, Path]) -> None:
    repo, destination = backup
    before = {
        p.relative_to(repo): (p.read_bytes(), p.stat().st_mtime_ns)
        for p in (repo / "data").rglob("*")
        if p.is_file()
    }
    dry = _run(repo, destination, "-DryRun")
    assert dry.returncode == 0, dry.stderr
    assert f"Copy total: {sum(len(tree) for tree in TREES)} bytes" in dry.stdout
    assert list(destination.iterdir()) == []
    result = _run(repo, destination)
    assert result.returncode == 0, result.stderr
    assert not (destination / "runtime").exists() and not (destination / "raw").exists()
    manifest = json.loads(max(destination.glob("manifest-*.json")).read_text(encoding="utf-8-sig"))
    assert len(manifest["files"]) == 5
    for record in manifest["files"]:
        content = (repo / "data" / record["path"]).read_bytes()
        assert record["sha256"].lower() == hashlib.sha256(content).hexdigest()
        assert record["size"] == len(content)
    assert [r["path"] for r in manifest["files"]] == sorted(r["path"] for r in manifest["files"])
    repeat = _run(repo, destination)
    assert repeat.returncode == 0 and "Copy total: 0 bytes" in repeat.stdout
    assert len(list(destination.glob("manifest-*.json"))) == 2
    assert _run(repo, destination, "-Verify").returncode == 0
    for path, (content, modified) in before.items():
        assert (repo / path).read_bytes() == content
        assert (repo / path).stat().st_mtime_ns == modified


def test_conflict_preserves_both_and_manifest_guides_restore(backup: tuple[Path, Path]) -> None:
    repo, destination = backup
    assert _run(repo, destination).returncode == 0
    source = repo / "data/snapshots/record.json"
    source.write_text("new capture", encoding="ascii")
    result = _run(repo, destination)
    assert result.returncode == 1 and "CONFLICT snapshots/record.json" in result.stdout
    assert (destination / "snapshots/record.json").read_text() == "snapshots"
    variants = list((destination / "snapshots").glob("*.conflict-*"))
    assert len(variants) == 1 and variants[0].read_text() == "new capture"
    repeat = _run(repo, destination)
    assert repeat.returncode == 0 and "Copy total: 0 bytes" in repeat.stdout
    assert list((destination / "snapshots").glob("*.conflict-*")) == variants
    assert _run(repo, destination, "-Verify").returncode == 0
    source.write_text("damaged", encoding="ascii")
    assert _run(repo, destination, "-Verify").returncode != 0
    shutil.copyfile(variants[0], source)
    assert _run(repo, destination, "-Verify").returncode == 0


@pytest.mark.parametrize("side", ["source", "destination", "new-source", "missing-source"])
def test_verify_refuses_missing_changed_or_unrecorded_files(
    backup: tuple[Path, Path], side: str
) -> None:
    repo, destination = backup
    assert _run(repo, destination).returncode == 0
    path = (destination if side == "destination" else repo / "data") / "ledger/record.json"
    if side == "missing-source":
        path.unlink()
    else:
        if side == "new-source":
            path = path.with_name("new.json")
        path.write_text("LEDGER", encoding="ascii")  # Same size: exercises the hash, not size.
    result = _run(repo, destination, "-Verify")
    assert result.returncode != 0 and "ledger/" in result.stdout


def test_destination_boundaries_and_no_manifest(backup: tuple[Path, Path], tmp_path: Path) -> None:
    repo, destination = backup
    for forbidden in (repo, repo / "data", tmp_path / "absent"):
        assert _run(repo, forbidden, "-DryRun").returncode != 0
    assert _run(repo, destination, "-Verify").returncode != 0
    _git(repo, "add", "scripts")
    _git(
        repo,
        "-c",
        "user.name=Fixture",
        "-c",
        "user.email=fixture@example.test",
        "commit",
        "--quiet",
        "-m",
        "fixture",
    )
    linked = tmp_path / "linked"
    _git(repo, "worktree", "add", "--detach", str(linked))
    assert _run(repo, linked, "-DryRun").returncode != 0
    assert not (linked / "snapshots").exists()


def test_reparse_destination_cannot_bypass_boundary(
    backup: tuple[Path, Path], tmp_path: Path
) -> None:
    repo, _ = backup
    link = tmp_path / "alias"
    command = "New-Item -ItemType Junction -Path '{}' -Target '{}' | Out-Null".format(
        str(link).replace("'", "''"), str(repo).replace("'", "''")
    )
    subprocess.run([str(POWERSHELL), "-NoProfile", "-Command", command], check=True)
    assert _run(repo, link, "-DryRun").returncode != 0


def test_source_loss_does_not_replace_last_good_manifest(backup: tuple[Path, Path]) -> None:
    repo, destination = backup
    assert _run(repo, destination).returncode == 0
    before = {
        p.relative_to(destination): p.read_bytes() for p in destination.rglob("*") if p.is_file()
    }
    for tree in TREES:
        (repo / "data" / tree / "record.json").unlink()
    result = _run(repo, destination)
    assert result.returncode == 1 and "MISSING at source: 5 files" in result.stdout
    assert before == {
        p.relative_to(destination): p.read_bytes() for p in destination.rglob("*") if p.is_file()
    }
    for tree in TREES:
        shutil.copyfile(destination / tree / "record.json", repo / "data" / tree / "record.json")
    assert _run(repo, destination, "-Verify").returncode == 0


def test_verify_selected_manifest_and_reject_escape(backup: tuple[Path, Path]) -> None:
    repo, destination = backup
    assert _run(repo, destination).returncode == 0
    old = next(destination.glob("manifest-*.json"))
    added = repo / "data/entries/added.json"
    added.write_text("new", encoding="ascii")
    assert _run(repo, destination).returncode == 0
    added.unlink()  # Restored source matches the older recovery point.
    assert _run(repo, destination, "-Verify").returncode == 1
    assert _run(repo, destination, "-Verify", "-Manifest", old.name).returncode == 0
    assert _run(repo, destination, "-Verify", "-Manifest", "../" + old.name).returncode == 1
    assert _run(repo, destination, "-Manifest", old.name).returncode == 1


def test_utf8_filename_survives_manifest_verification(backup: tuple[Path, Path]) -> None:
    repo, destination = backup
    (repo / "data/entries/\u00e7a\u011fr\u0131.json").write_text("member", encoding="ascii")
    assert _run(repo, destination).returncode == 0
    result = _run(repo, destination, "-Verify")
    assert result.returncode == 0, result.stdout


@pytest.mark.parametrize("side", ["source", "destination"])
def test_tree_junction_is_refused_before_any_copy(backup: tuple[Path, Path], side: str) -> None:
    repo, destination = backup
    root = repo / "data" if side == "source" else destination
    link = root / "snapshots/sneaky"
    link.parent.mkdir(exist_ok=True)
    command = "New-Item -ItemType Junction -Path '{}' -Target '{}' | Out-Null".format(
        str(link).replace("'", "''"), str(repo / "data/runtime").replace("'", "''")
    )
    subprocess.run([str(POWERSHELL), "-NoProfile", "-Command", command], check=True)
    result = _run(repo, destination)
    assert result.returncode == 1 and "reparse point" in result.stdout
    assert not list(destination.glob("manifest-*.json"))
    assert not (destination / "advice_records").exists()
    assert not (destination / "snapshots/record.json").exists()
