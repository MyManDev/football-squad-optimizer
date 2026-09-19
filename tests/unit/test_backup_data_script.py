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


def test_loss_still_protects_new_files_until_explicit_acknowledgement(
    backup: tuple[Path, Path],
) -> None:
    repo, destination = backup
    assert _run(repo, destination).returncode == 0
    original_manifest = next(destination.glob("manifest-*.json"))
    original_bytes = original_manifest.read_bytes()
    (repo / "data/ledger/record.json").unlink()
    for day in (1, 2):
        new = repo / f"data/entries/day{day}.json"
        new.write_text(f"day {day}", encoding="ascii")
        result = _run(repo, destination)
        assert result.returncode == 1 and "MISSING at source: 1 files" in result.stdout
        assert (destination / f"entries/day{day}.json").read_bytes() == new.read_bytes()
        assert list(destination.glob("manifest-*.json")) == [original_manifest]
        assert original_manifest.read_bytes() == original_bytes
    dry_file = repo / "data/entries/dry.json"
    dry_file.write_text("dry", encoding="ascii")
    dry = _run(repo, destination, "-DryRun")
    assert dry.returncode == 1 and "dry run wrote no files or manifest" in dry.stdout
    assert not (destination / "entries/dry.json").exists()
    accepted = _run(repo, destination, "-AcceptMissing")
    assert accepted.returncode == 0 and "ACCEPTED missing at source: 1 files" in accepted.stdout
    assert (destination / "ledger/record.json").read_text() == "ledger"
    assert original_manifest.read_bytes() == original_bytes
    assert len(list(destination.glob("manifest-*.json"))) == 2
    assert _run(repo, destination, "-Verify").returncode == 0
    assert _run(repo, destination).returncode == 0
    assert _run(repo, destination, "-AcceptMissing", "-Verify").returncode == 1
    assert _run(repo, destination, "-AcceptMissing", "-DryRun").returncode == 1


@pytest.mark.parametrize("tree", ["ledger", "advice_records"])
def test_staging_and_lock_land_without_false_loss_even_with_old_manifest(
    backup: tuple[Path, Path], tree: str
) -> None:
    repo, destination = backup
    season = repo / "data" / tree / "2026-27"
    staging = season / ".gw05.staging-123-abcd"
    staging.mkdir(parents=True)
    record = staging / "manifest.json"
    record.write_text("landed record", encoding="ascii")
    lock = season / ".gw05.lock"
    lock.write_text("123", encoding="ascii")
    assert _run(repo, destination).returncode == 0
    manifest_path = next(destination.glob("manifest-*.json"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8-sig"))
    assert len(manifest["files"]) == 5
    assert not (destination / tree / "2026-27").exists()
    # A pre-fix manifest may already contain these transient records.
    for path in (record, lock):
        relative = path.relative_to(repo / "data").as_posix()
        content = path.read_bytes()
        manifest["files"].append(
            dict(
                path=relative,
                destination_path=relative,
                size=len(content),
                sha256=hashlib.sha256(content).hexdigest(),
            )
        )
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    verified = _run(repo, destination, "-Verify")
    assert verified.returncode == 0 and "Ignored transient entries" in verified.stdout
    staging.rename(season / "gw05")
    lock.unlink()
    result = _run(repo, destination)
    assert result.returncode == 0 and "MISSING" not in result.stdout, result.stdout
    assert f"Ignored transient entries in {manifest_path.name}: 2" in result.stdout
    assert (destination / tree / "2026-27/gw05/manifest.json").read_text() == "landed record"
    assert _run(repo, destination, "-Verify").returncode == 0


def test_dot_temporaries_are_reported_but_ordinary_names_are_backed_up(
    backup: tuple[Path, Path],
) -> None:
    repo, destination = backup
    tmp = repo / "data/ledger/2026-27/gw04/.outcome.json.tmp-55-abcd"
    tmp.parent.mkdir(parents=True)
    tmp.write_text("temporary outcome", encoding="ascii")
    retained = repo / "data/handoffs/.retain-fixture"
    retained.mkdir()
    (retained / "record.json").write_text("temporary handoff", encoding="ascii")
    stable_paths = ("snapshots/payloads/lock.json", "advice_records/staging/record.json")
    for relative in stable_paths:
        path = repo / "data" / relative
        path.parent.mkdir(parents=True)
        path.write_text("stable", encoding="ascii")
    result = _run(repo, destination)
    assert result.returncode == 0, result.stdout
    assert "Ignored dot-named source paths: 2" in result.stdout
    assert "TRANSIENT handoffs/.retain-fixture" in result.stdout
    assert "TRANSIENT ledger/2026-27/gw04/.outcome.json.tmp-55-abcd" in result.stdout
    manifest = json.loads(next(destination.glob("manifest-*.json")).read_text())
    assert len(manifest["files"]) == 7
    assert not any(part.startswith(".") for r in manifest["files"] for part in r["path"].split("/"))
    for relative in stable_paths:
        assert (destination / relative).read_text() == "stable"
    tmp.unlink()
    retained.rename(retained.with_name("retained"))
    assert _run(repo, destination).returncode == 0
    assert _run(repo, destination, "-Verify").returncode == 0


def test_transient_output_is_bounded_and_dry_run_writes_nothing(backup: tuple[Path, Path]) -> None:
    repo, destination = backup
    for number in range(25):
        (repo / f"data/handoffs/.handoff-{number:02}").mkdir()
    result = _run(repo, destination, "-DryRun")
    assert result.returncode == 0
    assert "Ignored dot-named source paths: 25" in result.stdout
    assert sum(line.startswith("TRANSIENT ") for line in result.stdout.splitlines()) == 20
    assert list(destination.iterdir()) == []


def test_missing_output_has_total_and_bounded_sample(backup: tuple[Path, Path]) -> None:
    repo, destination = backup
    added = [repo / f"data/entries/sample-{number:02}.json" for number in range(25)]
    for path in added:
        path.write_text("entry", encoding="ascii")
    assert _run(repo, destination).returncode == 0
    for path in added:
        path.unlink()
    result = _run(repo, destination)
    assert result.returncode == 1 and "MISSING at source: 25 files" in result.stdout
    assert sum(line.startswith("entries/sample-") for line in result.stdout.splitlines()) == 20


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
    assert _run(repo, destination).returncode == 1
    assert _run(repo, destination, "-AcceptMissing").returncode == 0
    assert (destination / "entries/added.json").read_text() == "new"
    assert old.is_file()


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
    assert str(link) in result.stdout
    assert not list(destination.glob("manifest-*.json"))
    assert not (destination / "advice_records").exists()
    assert not (destination / "snapshots/record.json").exists()
