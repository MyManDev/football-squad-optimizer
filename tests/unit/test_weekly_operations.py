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


def _git(cwd: Path, *arguments: str) -> str:
    completed = subprocess.run(
        [
            "git",
            "-c",
            "user.name=Synthetic",
            "-c",
            "user.email=synthetic@example.invalid",
            *arguments,
        ],
        cwd=cwd,
        check=True,
        capture_output=True,
        text=True,
    )
    return completed.stdout.strip()


def _git_checkout(tmp_path: Path) -> tuple[Path, weekly.WeeklyPaths, list[str]]:
    """A clean Git checkout holding the synthetic world, and the arguments that run it."""

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
    (checkout / "source.py").write_text("unchanged")
    public = checkout / "web/public/data/members.json"
    public.parent.mkdir(parents=True)
    public.write_text("previous publication")
    _git(checkout, "init", "-q")
    _git(checkout, "add", ".")
    _git(checkout, "commit", "-qm", "fixture")
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
    ]
    return checkout, paths, args


def _origin_develop_behind_head(checkout: Path) -> str:
    """Publish HEAD as ``origin/develop``, then commit once more so HEAD is ahead of it."""

    origin = checkout.parent / "origin.git"
    _git(checkout, "init", "-q", "--bare", str(origin))
    _git(checkout, "remote", "add", "origin", str(origin))
    _git(checkout, "push", "-q", "origin", "HEAD:refs/heads/develop")
    (checkout / "source.py").write_text("committed here, not yet on develop")
    _git(checkout, "commit", "-qam", "unmerged")
    return _git(checkout, "rev-parse", "origin/develop")


def test_default_preview_can_resume_in_clean_git_checkout_but_source_drift_cannot(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    checkout, paths, base = _git_checkout(tmp_path)
    source = checkout / "source.py"
    public = checkout / "web/public/data/members.json"
    args = [*base, "--run-id", "git-resume"]
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


def test_a_publish_off_the_fresh_origin_develop_refuses_in_preflight(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The publication base is checked before a capture or a solve is spent on a run that
    the publish stage would refuse hours later; the refusal names the recovery."""

    checkout, paths, args = _git_checkout(tmp_path)
    base = _origin_develop_behind_head(checkout)
    head = _git(checkout, "rev-parse", "HEAD")
    assert base != head

    assert weekly.main([*args, "--publish", "--run-id", "off-develop"]) == 1

    stderr = capsys.readouterr().err
    assert "run_week stopped:" in stderr
    assert "origin/develop" in stderr and base[:12] in stderr and head[:12] in stderr
    assert "start a new run" in stderr
    doc = json.loads((paths.journal / "off-develop/run.json").read_bytes())
    assert doc["stages"][0]["name"] == "preflight" and doc["stages"][0]["status"] == "failed"
    assert all(stage["status"] == "pending" for stage in doc["stages"][1:])
    assert not (checkout / ".codex-tmp").exists()


def test_the_publish_stage_checks_the_base_again_before_touching_git(tmp_path: Path) -> None:
    """The backstop: develop can move during the run, so the last stage checks once more,
    before any worktree or branch exists, and names the same recovery."""

    from squadopt.platform.weekly_publish import PublishError, PublishNames, publish

    checkout, _, _ = _git_checkout(tmp_path)
    _origin_develop_behind_head(checkout)
    head = _git(checkout, "rev-parse", "HEAD")

    with pytest.raises(PublishError, match="origin/develop") as refusal:
        publish(
            PublishNames("2026-27", 2, "decision"),
            force_branch=False,
            dry_run=True,
            workspace=checkout,
            expected_commit=head,
        )
    assert "start a new run" in str(refusal.value)
    assert not (checkout / ".codex-tmp").exists()


def test_a_settled_outcome_refusal_is_stated_at_the_run_boundary(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """The stage's own refusal reaches the operator as a stated refusal with exit 1, not as
    an uncaught traceback, and the journal shows where the run stopped."""

    from squadopt.application.settled_outcomes import SettledOutcomeExportError

    _, paths, args = _git_checkout(tmp_path)

    def refuse(request):
        raise SettledOutcomeExportError("synthetic: manifest describes a different artifact")

    monkeypatch.setattr(weekly, "export_settled_outcomes", refuse)
    assert weekly.main([*args, "--run-id", "settled-refusal"]) == 1

    stderr = capsys.readouterr().err
    assert "run_week stopped: synthetic: manifest describes a different artifact" in stderr
    doc = json.loads((paths.journal / "settled-refusal/run.json").read_bytes())
    statuses = {stage["name"]: stage["status"] for stage in doc["stages"]}
    assert statuses["preflight"] == "completed" and statuses["capture"] == "completed"
    assert statuses["settled_outcomes"] == "failed"
    assert statuses["handoff"] == "pending" and statuses["league"] == "pending"


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
