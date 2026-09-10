"""Weekly service composition keeps provenance, preflight and preview semantics."""

import json
import shutil
import subprocess
from dataclasses import replace
from pathlib import Path
from types import SimpleNamespace

import pytest
from tests.unit.test_publication_services import publication_world

from squadopt.application.weekly_plan import WeekError, WeeklyRequest, rotation_artifact
from squadopt.platform import weekly_operations as weekly
from squadopt.platform.weekly_journal import WeeklyJournalError, inspect_run


def world(tmp_path: Path, *, rotation: bool = False) -> weekly.WeeklyOperations:
    publication = publication_world(tmp_path)
    snapshots = tmp_path / "weekly-snapshots"
    shutil.copytree(
        publication.snapshot_root / publication.snapshot_id, snapshots / publication.snapshot_id
    )
    paths = replace(
        weekly.WeeklyPaths.under(tmp_path),
        snapshots=snapshots,
        archive=publication.archive_root,
        registry=publication.registry_path,
        handoffs=tmp_path / "published-handoffs",
        out=publication.out_dir,
    )
    request = WeeklyRequest(
        "2026-27",
        2,
        publication.league_id,
        snapshot_id=publication.snapshot_id,
        skip_top100=True,
        rotation=rotation,
        workers=1,
    )
    return weekly.WeeklyOperations(
        request,
        paths,
        run_id="synthetic",
        repository_commit="b" * 40,
        handoff=publication.handoff_path,
    )


def test_real_weekly_services_complete_and_resume_without_rebuilding(tmp_path: Path) -> None:
    operation = world(tmp_path)
    receipt = operation.execute()
    doc = json.loads(receipt.read_bytes())
    assert doc["status"] == "completed"
    names = [stage["name"] for stage in doc["stages"]]
    assert names == [
        "preflight",
        "capture",
        "settled_outcomes",
        "handoff",
        "league",
        "site",
        "scoreboard",
    ]
    settled = doc["stages"][2]["value"]
    assert settled["gameweeks_exported"] == [] and settled["skipped"]
    assert not operation.paths.records.exists()
    members = json.loads((operation.paths.out / "data/league/members.json").read_bytes())
    assert members["payload"]["gameweek"] == 2 and members["payload"]["season"] == "2026-27"
    entry = json.loads((operation.paths.out / "data/league/entries/101.json").read_bytes())
    assert entry["payload"]["source_snapshot_id"] == operation.request.snapshot_id
    before = weekly.fingerprint_paths([operation.paths.out])
    resumed = weekly.WeeklyOperations(
        operation.request,
        operation.paths,
        run_id="synthetic",
        repository_commit="b" * 40,
        resume=True,
        handoff=operation.supplied_handoff,
    )
    resumed.execute()
    assert weekly.fingerprint_paths([operation.paths.out]) == before
    assert inspect_run(operation.paths.journal, "synthetic")["status"] == "completed"
    # A mutable alias changed by another writer is not accepted just because the run succeeded.
    alias = operation.paths.handoffs / "2026-27-gw02.json"
    alias.write_bytes(alias.read_bytes() + b" ")
    assert inspect_run(operation.paths.journal, "synthetic")["status"] == "invalid_artifacts"
    with pytest.raises(WeeklyJournalError, match="changed"):
        resumed.execute()


def test_wrong_capture_handoff_is_rejected_before_alias_write(tmp_path: Path) -> None:
    operation = world(tmp_path)
    operation.values["capture"] = {"snapshot_id": "other-capture"}
    with pytest.raises(WeekError, match="exact capture"):
        operation._handoff()
    assert not operation.paths.handoffs.exists()


def test_default_preview_can_resume_in_clean_git_checkout_but_source_drift_cannot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    publication = publication_world(tmp_path / "fixtures")
    checkout = tmp_path / "checkout"
    checkout.mkdir()
    paths = weekly.WeeklyPaths.under(checkout)
    shutil.copytree(
        publication.snapshot_root / publication.snapshot_id,
        paths.snapshots / publication.snapshot_id,
    )
    shutil.copytree(publication.archive_root, paths.archive)
    paths.registry.parent.mkdir(parents=True)
    shutil.copyfile(publication.registry_path, paths.registry)
    handoff = checkout / "data/prebuilt.json"
    shutil.copyfile(publication.handoff_path, handoff)
    (checkout / ".gitignore").write_text("data/\nartifacts/\n")
    source = checkout / "source.py"
    source.write_text("unchanged")
    public = checkout / "web/public/data/members.json"
    public.parent.mkdir(parents=True)
    public.write_text("previous publication")
    for command in (
        ["init", "-q"],
        ["add", "."],
        [
            "-c",
            "user.name=Synthetic",
            "-c",
            "user.email=synthetic@example.invalid",
            "commit",
            "-qm",
            "fixture",
        ],
    ):
        subprocess.run(["git", *command], cwd=checkout, check=True, capture_output=True)
    args = [
        "--workspace",
        str(checkout),
        "--season",
        "2026-27",
        "--gameweek",
        "2",
        "--league",
        "352490",
        "--snapshot-id",
        publication.snapshot_id,
        "--skip-top100",
        "--workers",
        "1",
        "--handoff",
        str(handoff),
        "--run-id",
        "git-resume",
    ]
    actual_scoreboard = weekly.publish_scoreboard

    def interrupt(request):
        raise OSError("synthetic interruption after preview member/site build")

    monkeypatch.setattr(weekly, "publish_scoreboard", interrupt)
    assert weekly.main(args) == 1
    assert inspect_run(paths.journal, "git-resume")["status"] == "failed"
    assert public.read_text() == "previous publication"
    monkeypatch.setattr(weekly, "publish_scoreboard", actual_scoreboard)
    assert weekly.main([*args, "--resume"]) == 0
    assert (paths.journal / "git-resume/preview/data/league/members.json").is_file()
    source.write_text("unrelated source edit")
    assert weekly.main([*args, "--resume"]) == 1


def test_prebuilt_handoff_cannot_claim_fresh_top100_composition(tmp_path: Path) -> None:
    operation = world(tmp_path)
    request = replace(
        operation.request, skip_top100=False, cohort_snapshot="cohort", elite_snapshot="elite"
    )
    with pytest.raises(WeekError, match="does not apply new evidence"):
        weekly.WeeklyOperations(
            request,
            operation.paths,
            run_id="bad",
            repository_commit="b" * 40,
            handoff=operation.supplied_handoff,
        )


@pytest.mark.parametrize("existing", [False, True])
def test_rotation_export_is_capture_pinned_and_existing_pair_is_validated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, existing: bool
) -> None:
    operation = world(tmp_path)
    operation.run.directory.mkdir(parents=True)
    operation.values["capture"] = {
        "snapshot_id": operation.request.snapshot_id,
        "deadline_utc": "2026-08-28T17:30:00Z",
    }
    table, manifest = rotation_artifact(
        operation.paths.rotation, "2026-27", 2, operation.request.snapshot_id or ""
    )
    calls = []

    def export(request, *, repository_commit):
        calls.append(request)
        assert repository_commit == "b" * 40
        table.parent.mkdir(parents=True, exist_ok=True)
        table.write_text("table")
        manifest.write_text("manifest")
        return {}

    if existing:
        export(None, repository_commit="b" * 40)
        calls.clear()
    checked = []
    monkeypatch.setattr(weekly, "export_rotation_evidence", export)
    monkeypatch.setattr(
        weekly, "read_rotation_evidence_artifact", lambda *args: checked.append(args)
    )
    result = operation._rotation()
    assert checked == [(table, manifest)]
    assert result.value["table"] == str(table)
    assert len(calls) == (0 if existing else 1)
    if calls:
        assert calls[0].snapshot == operation.request.snapshot_id
        assert calls[0].deadline_utc == "2026-08-28T17:30:00Z"


def test_missing_reused_rotation_refuses_before_capture_or_export(tmp_path: Path) -> None:
    operation = world(tmp_path, rotation=True)
    with pytest.raises(WeekError, match="already on disk"):
        operation.execute()
    doc = json.loads(operation.run.path.read_bytes())
    assert doc["stages"][0]["status"] == "failed"
    assert all(stage["status"] == "pending" for stage in doc["stages"][1:])


def test_preview_and_publish_record_destination_are_explicit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    operation = world(tmp_path)
    operation.values["capture"] = {"snapshot_id": operation.request.snapshot_id}
    operation.values["handoff"] = {"path": str(operation.supplied_handoff)}
    calls = []

    def publish(request, **kwargs):
        calls.append(request)
        return SimpleNamespace(output_paths=(), snapshot_id=request.snapshot_id, gameweek=2)

    monkeypatch.setattr(weekly, "publish_league", publish)
    operation._league()
    operation._league(tmp_path / "publication", record=True)
    assert calls[0].record_root is None
    assert calls[1].record_root == operation.paths.records
    assert calls[1].out_dir == tmp_path / "publication"
    assert "rotation" not in operation.stages


@pytest.mark.parametrize(
    "options",
    [
        [],
        ["--decide", "--chip", "bboost", "--rotation", "--publish"],
        ["--snapshot-id", "capture", "--skip-top100", "--projection", "component-only"],
    ],
)
def test_legacy_and_installed_dry_run_flags_match_without_writing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str], options: list[str]
) -> None:
    from scripts import run_week as legacy

    args = [
        "--workspace",
        str(tmp_path),
        "--season",
        "2026-27",
        "--gameweek",
        "4",
        "--league",
        "352490",
        "--dry-run",
        *options,
    ]
    assert weekly.main(args) == 0
    installed = capsys.readouterr().out
    assert legacy.main(args) == 0
    assert capsys.readouterr().out == installed
    assert list(tmp_path.iterdir()) == []
